import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.extract import save_patient, validate  # noqa: E402
from ehr.record import record_events  # noqa: E402
from ehr.review import apply_review, sign_note  # noqa: E402
from tests.test_reason import patient as reason_patient  # noqa: E402,F401

NOTE_TEXT = ("S: Skipping metformin most days because of the stomach upset. Taking ibuprofen 400 mg most days since around May.\n"
             "O: BP 154/94 sitting.\n"
             "A/P:\n1. Type 2 diabetes. Switch metformin to extended-release 1000 mg daily with dinner. Repeat A1c in 3 months.\n"
             "2. Hypertension. Stop ibuprofen. Start lisinopril 10 mg daily. Home BP log, goal under 140/90 in 4 weeks.\n")
NOTE = {"id": "note_0009", "patient_id": "pt_t", "encounter_id": None, "time": "2026-09-15T09:40:00-04:00", "author": "Dr. Chen", "text": NOTE_TEXT}

RAW = {
    "observations": [{"quote": "BP 154/94", "loinc": "8480-6", "value": 154, "unit": "mm[Hg]", "date": None, "problem_refs": ["prob_htn"], "confidence": 0.95}],
    "findings": [{"quote": "Skipping metformin most days because of the stomach upset.", "summary": "Metformin non-adherence, GI upset", "problem_refs": ["prob_ckd"], "confidence": 0.9}],
    "problems": [],
    "medications": [{"ref": "m1", "quote": "Taking ibuprofen 400 mg most days since around May.", "name": "Ibuprofen OTC", "dose": "400 mg", "route": "PO", "frequency": "most days",
                     "start": "2026-05-01", "end": "2026-09-15", "existing_med_id": None, "change": "new", "treats_problem_refs": [], "confidence": 0.9}],
    "suspected_causes": [{"quote": "Stop ibuprofen.", "cause_ref": "m1", "effect_ref": "prob_htn", "rationale": "NSAID and blood pressure", "confidence": 0.8}],
    "plans": [
        {"quote": "Switch metformin to extended-release 1000 mg daily with dinner.", "kind": "therapeutic", "text": "Switch metformin to extended-release 1000 mg daily", "problem_refs": ["prob_ckd"], "confidence": 0.9},
        {"quote": "Repeat A1c in 3 months.", "kind": "monitoring", "text": "Repeat A1c in 3 months", "problem_refs": ["prob_ckd"], "confidence": 0.9},
        {"quote": "Start lisinopril 10 mg daily.", "kind": "therapeutic", "text": "Start lisinopril 10 mg daily", "problem_refs": ["prob_htn"], "confidence": 0.9},
        {"quote": "Home BP log, goal under 140/90 in 4 weeks.", "kind": "monitoring", "text": "Home BP log, goal under 140/90 in 4 weeks", "problem_refs": ["prob_htn"], "confidence": 0.85},
        {"quote": "not in the note", "kind": "referral", "text": "PT", "problem_refs": ["prob_htn"], "confidence": 0.5},
        {"quote": "Stop ibuprofen.", "kind": "therapeutic", "text": "Stop ibuprofen", "problem_refs": ["nope"], "confidence": 0.9},
    ],
}


def test_plan_items_are_extracted_with_quotes_and_problems(reason_patient):
    batch = validate(reason_patient, NOTE, RAW, "x")
    plans = batch["proposed"]["plans"]
    assert [(p["kind"], p["text"], p["problem_id"]) for p in plans] == [
        ("therapeutic", "Switch metformin to extended-release 1000 mg daily", "prob_ckd"),
        ("monitoring", "Repeat A1c in 3 months", "prob_ckd"),
        ("therapeutic", "Start lisinopril 10 mg daily", "prob_htn"),
        ("monitoring", "Home BP log, goal under 140/90 in 4 weeks", "prob_htn"),
    ]
    assert all(p["status"] == "proposed" and p["provenance"]["note_id"] == "note_0009" and p["provenance"]["quote"] in NOTE_TEXT for p in plans)
    assert plans[0]["id"].startswith("plan_")
    reasons = [r["reason"] for r in batch["rejected"] if r["kind"] == "plan"]
    assert any("verbatim" in r for r in reasons) and any("no resolvable problem" in r for r in reasons)


def test_signing_the_note_commits_it_and_the_record_reads_it_back(reason_patient, tmp_path):
    data_dir = tmp_path / "patients"
    data_dir.mkdir()
    p = copy.deepcopy(reason_patient)
    p["notes"].append(NOTE)
    save_patient(p, data_dir)
    batch = validate(p, NOTE, RAW, "x")
    q = tmp_path / "proposed" / "pt_t"
    q.mkdir(parents=True)
    (q / "note_0009.json").write_text(json.dumps(batch))
    # the clinician rejects one plan item first, then signs the note
    apply_review("pt_t", "note_0009", reject=[batch["proposed"]["plans"][3]["id"]], reason_code="not_relevant", reason="she has no cuff at home", data_dir=data_dir)
    r = sign_note("pt_t", "note_0009", data_dir=data_dir)
    chart = json.loads((data_dir / "pt_t.json").read_text())
    note = next(n for n in chart["notes"] if n["id"] == "note_0009")
    assert note["status"] == "signed" and note["review"]["by"] == "Dr. Chen" and r["signed_at"] == note["review"]["at"]
    assert [pl["text"] for pl in chart["plans"]] == ["Switch metformin to extended-release 1000 mg daily", "Repeat A1c in 3 months", "Start lisinopril 10 mg daily"]
    assert any(m["name"] == "Ibuprofen OTC" for m in chart["medications"])
    kinds = [e["kind"] for e in record_events(chart, tmp_path / "proposed", note_id="note_0009")]
    assert kinds[0] == "note.received" and kinds[-1] == "note.signed"
    assert {"observation.recorded", "medication.course_opened", "edge.asserted", "plan.set", "proposal.rejected"} <= set(kinds)
    rejected = next(e for e in record_events(chart, tmp_path / "proposed", note_id="note_0009") if e["kind"] == "proposal.rejected")
    assert "she has no cuff at home" in rejected["text"]
    # a note that was never read has no queue: signing it is an error, not a silent no-op
    import pytest
    with pytest.raises(FileNotFoundError):
        sign_note("pt_t", "note_0007", data_dir=data_dir)
