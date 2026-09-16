import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.draft import run_draft, sign_draft  # noqa: E402
from ehr.extract import run_extraction  # noqa: E402
from ehr.review import apply_review, sign_note  # noqa: E402


def _visit(tmp_path: Path) -> Path:
    """A scratch copy of the golden data, taken through the note's review and signature."""
    data = tmp_path / "data"
    shutil.copytree(ROOT / "data" / "patients", data / "patients")
    (data / "proposed" / "pt_002").mkdir(parents=True)
    for f in (ROOT / "data" / "proposed" / "pt_002").glob("*.raw.json"):
        shutil.copy(f, data / "proposed" / "pt_002" / f.name)
    run_extraction("pt_002", ROOT / "data" / "notes" / "note_demo_102.json", replay=data / "proposed" / "pt_002" / "note_demo_102.raw.json", data_dir=data / "patients")
    apply_review("pt_002", "note_demo_102", reject=["lnk_demo_102_20"], reason="Non-adherence is the cause, not the drug.", reason_code="disagree", data_dir=data / "patients")
    sign_note("pt_002", "note_demo_102", data_dir=data / "patients")
    return data / "patients"


def test_visit_note_compiles_from_the_encounter_and_signs_into_documents(tmp_path):
    d = _visit(tmp_path)
    batch = run_draft("pt_002", "enc_c002", data_dir=d)
    doc = batch["proposed"]["documents"][0]
    heads = [s["heading"] for s in doc["sections"]]
    assert heads[0] == "Subjective" and doc["sections"][0]["source"] == "transcript" and doc["sections"][0]["cites"] == ["note_demo_102"]
    assert "Assessment · Essential hypertension" in heads and "Plan · Essential hypertension" in heads
    htn = next(s for s in doc["sections"] if s["heading"] == "Assessment · Essential hypertension")
    assert "suspected cause" in htn["text"] and "lnk_demo_102_18" in htn["cites"]
    dm = next(s for s in doc["sections"] if s["heading"] == "Assessment · Diabetes mellitus type 2")
    assert "rejected: Non-adherence is the cause, not the drug." in dm["text"] and "lnk_demo_102_20" in dm["cites"]
    assert set(doc["problems_addressed"]) >= {"prob_0007", "prob_0009"}
    # every review made at this visit carries the encounter
    chart = json.loads((d / "pt_002.json").read_text())
    assert all(pl["review"]["encounter_id"] == "enc_c002" for pl in chart["plans"])
    # the clinician edits a section and signs; the edit is kept, the citations are kept, the document is on the chart
    edited = [{"heading": s["heading"], "text": ("Adherence, not the drug. " + s["text"]) if s["heading"].startswith("Assessment · Diabetes") else s["text"]} for s in doc["sections"]]
    out = sign_draft("pt_002", "enc_c002", edited, data_dir=d)
    chart = json.loads((d / "pt_002.json").read_text())
    signed = next(x for x in chart["documents"] if x["id"] == out["document_id"])
    dm2 = next(s for s in signed["sections"] if s["heading"] == "Assessment · Diabetes mellitus type 2")
    assert dm2["text"].startswith("Adherence, not the drug.") and dm2.get("edited") and dm2["cites"] == dm["cites"]
    assert signed["status"] == "accepted" and signed["review"]["encounter_id"] == "enc_c002"
    # a signed draft is not recompiled over
    assert run_draft("pt_002", "enc_c002", data_dir=d)["proposed"]["documents"][0]["status"] == "accepted"


def test_clinician_intent_is_signed_at_once_and_reaches_the_visit_note(tmp_path):
    from ehr.intent import run_intent
    d = _visit(tmp_path)
    out = run_intent("pt_002", "prob_0007", "monitoring", "Home BP log, review in two weeks", data_dir=d)
    ref = run_intent("pt_002", "prob_0007", "referral", "Nutrition counselling", data_dir=d)
    stop = run_intent("pt_002", "prob_0007", "therapeutic", "Stop hydrochlorothiazide", course_id="med_hydrochlorothiazide", change="stop", data_dir=d)
    chart = json.loads((d / "pt_002.json").read_text())
    plan = next(p for p in chart["plans"] if p["id"] == out["plan_id"])
    assert plan["status"] == "accepted" and plan["provenance"]["source"] == "clinician" and plan["review"]["encounter_id"] == "enc_c002"
    assert any(o["kind"] == "referral" and o["provenance"].get("from_plan") == ref["plan_id"] for o in chart["orders"])
    hctz = next(m for m in chart["medications"] if m["id"] == "med_hydrochlorothiazide")
    assert hctz["segments"][-1]["end"] == "2026-09-15" and stop["effective"] == "2026-09-15"  # the visit day, not today
    doc = run_draft("pt_002", "enc_c002", data_dir=d)["proposed"]["documents"][0]
    htn_plan = next(s for s in doc["sections"] if s["heading"] == "Plan · Essential hypertension")
    assert "Home BP log, review in two weeks" in htn_plan["text"] and "Nutrition counselling" in htn_plan["text"]
    assert "Hydrochlorothiazide 25 mg stopped" in htn_plan["text"] or "hydrochlorothiazide" in htn_plan["text"].lower()
    assert out["plan_id"] in htn_plan["cites"] and "med_hydrochlorothiazide" in htn_plan["cites"]
