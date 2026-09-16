from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ehr.draft import draft_note, run_draft, sign_draft
from ehr.draft_updates import read_draft, save_draft, preview_updates, incorporate_updates
from ehr.extract import save_patient
from ehr.intent import add_intent, run_intent
from ehr.trend import load_patient


@pytest.fixture
def chart():
    return {
        "patient": {"id": "pt_dest", "name": "Test", "dob": "1970-01-01", "sex": "F"},
        "encounters": [{"id": "enc_test", "time": "2026-01-10T09:00:00+00:00", "type": "office visit"}],
        "problems": [{"id": "prob_test", "name": "Hypertension", "status": "active", "provenance": {"source": "fhir_import"}}],
        "medications": [{"id": "med_test", "name": "Example medication", "status": "accepted", "provenance": {"source": "fhir_import"},
                         "segments": [{"start": "2025-01-01", "end": None, "dose": "10 mg", "route": "oral", "frequency": "daily"}]}],
        "links": [{"id": "lnk_test", "from": "med_test", "to": "prob_test", "type": "treats", "status": "accepted", "provenance": {"source": "fhir_import"}}],
        "notes": [], "observations": [], "insights": [], "plans": [], "orders": [], "documents": [],
    }


def compile_plan(chart, tmp_path):
    doc = draft_note(chart, "enc_test", proposed_dir=tmp_path)["proposed"]["documents"][0]
    return " ".join(s["text"] for s in doc["sections"] if s["heading"].startswith("Plan")), doc


@pytest.mark.parametrize("destination", ["note", "treatment_plan", "both"])
@pytest.mark.parametrize("kind", ["monitoring", "diagnostic", "referral"])
def test_destination_controls_note_and_chart_independently(chart, tmp_path, destination, kind):
    before_meds = deepcopy(chart["medications"])
    out = add_intent(chart, "prob_test", kind, "Chosen action", destination=destination)
    text, doc = compile_plan(chart, tmp_path)
    assert text.count("Chosen action") == (0 if destination == "treatment_plan" else 1)
    assert len(chart["plans"]) == (0 if destination == "note" else 1)
    assert len(chart["orders"]) == (1 if destination != "note" and kind in ("diagnostic", "referral") else 0)
    assert chart["medications"] == before_meds
    if destination == "note":
        assert out["plan_id"] is None
        assert "review" not in chart["note_plan_items"][0]
        assert chart["note_plan_items"][0]["encounter_id"] == "enc_test"
        assert out["note_item_id"] in doc["provenance"]["evidence"]
    else:
        assert chart["plans"][0]["destination"] == destination
        assert chart["plans"][0]["review"]["decision"] == "accepted"
        assert all(o["destination"] == destination for o in chart["orders"])


@pytest.mark.parametrize("change", ["stop", "dose_change"])
@pytest.mark.parametrize("destination", ["note", "treatment_plan", "both"])
def test_medication_effects_do_not_leak_into_note(chart, tmp_path, change, destination):
    before = deepcopy(chart)
    args = dict(course_id="med_test", change=change, dose="20 mg" if change == "dose_change" else None, destination=destination)
    if destination == "note":
        with pytest.raises(ValueError, match="cannot change medications"):
            add_intent(chart, "prob_test", "therapeutic", "Medication decision", **args)
        assert chart == before
        return
    add_intent(chart, "prob_test", "therapeutic", "Medication decision", **args)
    assert chart["medications"] != before["medications"]
    text, doc = compile_plan(chart, tmp_path)
    if destination == "treatment_plan":
        assert not text
        assert "med_test" not in doc["provenance"]["evidence"]
    else:
        assert "Medication decision" in text
        assert "Example medication" in text


def test_treatment_only_does_not_hide_other_changes_to_same_medication(chart, tmp_path):
    add_intent(chart, "prob_test", "therapeutic", "Private chart decision", course_id="med_test", change="dose_change", dose="20 mg", destination="treatment_plan")
    add_intent(chart, "prob_test", "therapeutic", "Shared decision", course_id="med_test", change="dose_change", dose="30 mg", destination="both")
    text, _ = compile_plan(chart, tmp_path)
    assert "Private chart decision" not in text and "10 mg → 20 mg" not in text
    assert "Shared decision" in text and "20 mg → 30 mg" in text


def test_note_items_are_encounter_scoped_and_persist_without_overwriting_edits(chart, tmp_path):
    d = tmp_path / "patients"
    d.mkdir()
    save_patient(chart, d)
    run_intent("pt_dest", "prob_test", "education", "Initial note text", destination="note", data_dir=d)
    batch = run_draft("pt_dest", "enc_test", data_dir=d)
    sections = batch["proposed"]["documents"][0]["sections"]
    edits = [{"key": s["key"], "text": "" if s["heading"].startswith("Plan") else s["text"]} for s in sections]
    save_draft("pt_dest", "enc_test", edits, batch["draft_revision"], d)
    run_intent("pt_dest", "prob_test", "education", "Another note line", destination="note", data_dir=d)
    assert read_draft("pt_dest", "enc_test", d)["updates_count"] > 0
    preview = preview_updates("pt_dest", "enc_test", edits, d)
    conflict = next(c for c in preview["changes"] if c["heading"].startswith("Plan"))
    assert conflict["conflict"]
    batch = incorporate_updates("pt_dest", "enc_test", edits, preview["revision"], {conflict["key"]: {"choice": "keep"}}, d)
    assert next(s for s in batch["proposed"]["documents"][0]["sections"] if s["heading"].startswith("Plan"))["text"] == ""
    assert batch["updates_count"] == 0
    persisted = load_patient("pt_dest", d)
    assert len(persisted["note_plan_items"]) == 2 and not persisted["plans"]
    for item in persisted["note_plan_items"]:
        item["encounter_id"] = "enc_other"
    assert not compile_plan(persisted, tmp_path)[0]


@pytest.mark.parametrize("destination", ["note", "treatment_plan", "both"])
def test_signed_note_protected_before_any_clinical_side_effect(chart, tmp_path, destination):
    d = tmp_path / "patients"
    d.mkdir()
    save_patient(chart, d)
    run_intent("pt_dest", "prob_test", "monitoring", "Original", destination="both", data_dir=d)
    run_draft("pt_dest", "enc_test", data_dir=d)
    sign_draft("pt_dest", "enc_test", None, data_dir=d)
    before = (d / "pt_dest.json").read_text()
    if destination != "treatment_plan":
        with pytest.raises(ValueError, match="signed"):
            run_intent("pt_dest", "prob_test", "diagnostic", "Later test", destination=destination, data_dir=d)
        assert (d / "pt_dest.json").read_text() == before
    else:
        docs = deepcopy(load_patient("pt_dest", d)["documents"])
        run_intent("pt_dest", "prob_test", "diagnostic", "Later test", destination=destination, data_dir=d)
        assert load_patient("pt_dest", d)["documents"] == docs
        assert read_draft("pt_dest", "enc_test", d)["updates_count"] == 0


def test_invalid_destination_or_dose_does_not_mutate_chart(chart):
    before = deepcopy(chart)
    with pytest.raises(ValueError, match="Choose"):
        add_intent(chart, "prob_test", "monitoring", "Text", destination="unknown")
    with pytest.raises(ValueError, match="new dose"):
        add_intent(chart, "prob_test", "therapeutic", "Text", destination="treatment_plan", course_id="med_test", change="dose_change")
    assert chart == before


def test_note_requires_an_encounter(chart):
    chart["encounters"] = []
    before = deepcopy(chart)
    with pytest.raises(ValueError, match="active encounter"):
        add_intent(chart, "prob_test", "monitoring", "Text", destination="note")
    assert chart == before


def test_explicit_encounter_never_falls_back_to_older_visit(chart):
    before = deepcopy(chart)
    with pytest.raises(ValueError, match="active visit note"):
        add_intent(chart, "prob_test", "monitoring", "Text", destination="note", encounter_id="enc_missing")
    assert chart == before
    chart["encounters"].append({"id": "enc_later", "time": "2026-02-10T09:00:00+00:00", "type": "office visit"})
    result = add_intent(chart, "prob_test", "monitoring", "Text", destination="note", encounter_id="enc_test")
    assert result["encounter_id"] == "enc_test"
