import json
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ehr.corrections import apply_correction, catalog, preview
from ehr.extract import save_patient
from ehr.review import accept_item, accept_medication_change, apply_review, undo_review, sign_note, ledger_for_problem
from ehr.record import record_events
from ehr.trend import load_patient


@pytest.fixture
def chart(tmp_path):
    d = tmp_path / "patients"
    d.mkdir()
    q = tmp_path / "proposed" / "pt_test"
    q.mkdir(parents=True)
    rv = {"decision": "accepted", "by": "Dr. Chen", "at": "2026-01-10T10:00:00+00:00"}
    prov = {"source": "nlp_extraction", "note_id": "note_test", "quote": "Glucose 150"}
    p = {"patient": {"id": "pt_test", "name": "Test"}, "encounters": [], "notes": [
        {"id": "note_test", "text": "Original signed note", "time": rv["at"], "author": "Dr. Chen", "status": "signed", "review": rv}],
        "problems": [{"id": "prob_test", "name": "Diabetes", "status": "active", "onset_date": "2025-01-01", "provenance": prov, "review": rv}],
        "observations": [{"id": "obs_test", "name": "Glucose", "value": 150, "unit": "mg/dL", "code": {"value": "2345-7"},
                          "effective_time": rv["at"], "reference_range": None, "status": "accepted", "provenance": prov, "review": rv}],
        "medications": [{"id": "med_test", "name": "Metformin", "status": "accepted", "provenance": prov, "review": rv,
                         "segments": [{"start": "2025-01-01", "end": None, "dose": "500 mg", "route": "PO", "frequency": "daily"}]}],
        "links": [{"id": "lnk_test", "from": "obs_test", "to": "prob_test", "type": "evidence_for", "status": "accepted", "provenance": prov, "review": rv}],
        "insights": [{"id": "ins_test", "problem_id": "prob_test", "statement": "Glucose elevated", "evidence": ["obs_test"], "suggested_action": "Review",
                      "status": "accepted", "provenance": {"source": "reasoning"}, "created_at": rv["at"], "review": rv}],
        "plans": [], "orders": [], "documents": []}
    save_patient(p, d)
    (q / "note_test.json").write_text(json.dumps({"patient_id": "pt_test", "note_id": "note_test", "model": "test", "proposed": {
        "observations": deepcopy(p["observations"]), "links": deepcopy(p["links"]), "insights": deepcopy(p["insights"])}, "rejected": []}))
    return d


def correct(d, item, action, **kw):
    impact = preview("pt_test", item, action, d)
    return apply_correction("pt_test", item, action, reason="Recorded on the wrong encounter", expected_revision=impact["revision"], data_dir=d, **kw)


def test_error_archives_evidence_and_dependent_reasoning_preserving_signatures(chart):
    original = load_patient("pt_test", chart)
    impact = preview("pt_test", "obs_test", "entered_in_error", chart)
    assert {r["id"] for r in impact["withdrawn"]} == {"lnk_test", "ins_test"}
    event = correct(chart, "obs_test", "entered_in_error")
    p = load_patient("pt_test", chart)
    assert p["observations"] == p["links"] == p["insights"] == []
    assert event["before"] == original["observations"][0]
    assert p["archived_items"][0]["item"]["review"]["by"] == "Dr. Chen"
    assert any(e["kind"] == "observation.recorded" for e in record_events(p, chart.parent / "proposed"))
    assert any(e["kind"] == "chart.corrected" for e in record_events(p, chart.parent / "proposed", note_id="note_test"))
    with pytest.raises(ValueError, match="corrected"):
        apply_review("pt_test", "note_test", accept=["obs_test"], data_dir=chart)


def test_stale_preview_and_blank_reason_do_not_write(chart):
    first = preview("pt_test", "obs_test", "entered_in_error", chart)
    before = (chart / "pt_test.json").read_text()
    with pytest.raises(ValueError, match="reason"):
        apply_correction("pt_test", "obs_test", "entered_in_error", reason=" ", expected_revision=first["revision"], data_dir=chart)
    assert (chart / "pt_test.json").read_text() == before
    correct(chart, "note_test", "amend", text="Clarifying the original note.")
    with pytest.raises(ValueError, match="changed"):
        apply_correction("pt_test", "obs_test", "entered_in_error", reason="Error", expected_revision=first["revision"], data_dir=chart)


def test_amendments_append_without_changing_note_or_clinical_data(chart):
    original = load_patient("pt_test", chart)
    correct(chart, "note_test", "amend", text="The assessment should read differently.")
    correct(chart, "note_test", "amend", text="Additional clarification.")
    p = load_patient("pt_test", chart)
    assert p["notes"][0]["text"] == original["notes"][0]["text"]
    assert p["notes"][0]["review"] == original["notes"][0]["review"]
    assert len(p["notes"][0]["amendments"]) == 2
    assert p["medications"] == original["medications"] and p["observations"] == original["observations"]


def test_stop_resolve_and_cancel_retain_history(chart):
    correct(chart, "med_test", "stop", effective="2026-01-12")
    correct(chart, "prob_test", "resolve", effective="2026-01-12")
    p = load_patient("pt_test", chart)
    assert p["medications"][0]["segments"][0]["end"] == "2026-01-12"
    assert p["problems"][0]["status"] == "resolved"
    assert len(p["corrections"]) == 2
    assert "stop" not in next(x for x in catalog("pt_test", chart)["items"] if x["id"] == "med_test")["actions"]


def test_invalid_date_prevents_mutation(chart):
    before = (chart / "pt_test.json").read_text()
    with pytest.raises(ValueError, match="precede"):
        correct(chart, "med_test", "stop", effective="2020-01-01")
    with pytest.raises(ValueError, match="future"):
        correct(chart, "prob_test", "resolve", effective="2999-01-01")
    assert (chart / "pt_test.json").read_text() == before


def add_order(chart):
    p = load_patient("pt_test", chart)
    original_segments = deepcopy(p["medications"][0]["segments"])
    order = {"id": "ord_test", "kind": "medication_change", "name": "Stop metformin", "med_id": "med_test", "change": "stop",
             "status": "proposed", "provenance": {"source": "reasoning"}, "problem_id": "prob_test"}
    b = {"proposed": {"orders": [order]}}
    accept_item(p, b, "ord_test")
    save_patient(p, chart)
    return original_segments


def test_medication_order_error_restores_exact_course(chart):
    original = add_order(chart)
    correct(chart, "ord_test", "entered_in_error")
    p = load_patient("pt_test", chart)
    assert p["medications"][0]["segments"] == original
    assert p["orders"] == []
    assert p["archived_items"][0]["item"]["review"]["decision"] == "accepted"


def test_cancel_order_does_not_reverse_completed_medication_effect(chart):
    add_order(chart)
    segments = load_patient("pt_test", chart)["medications"][0]["segments"]
    correct(chart, "ord_test", "cancel")
    p = load_patient("pt_test", chart)
    assert p["medications"][0]["segments"] == segments
    assert p["orders"] == []


def test_later_medication_changes_block_unsafe_reversal(chart):
    add_order(chart)
    p = load_patient("pt_test", chart)
    p["medications"][0]["segments"][-1]["dose"] = "1000 mg"
    save_patient(p, chart)
    assert preview("pt_test", "ord_test", "entered_in_error", chart)["blockers"]
    with pytest.raises(ValueError, match="changed since"):
        correct(chart, "ord_test", "entered_in_error")


def test_referenced_problem_cannot_disappear_under_an_order(chart):
    add_order(chart)
    assert preview("pt_test", "prob_test", "entered_in_error", chart)["blockers"]
    with pytest.raises(ValueError, match="Active plans or orders"):
        correct(chart, "prob_test", "entered_in_error")


def test_signed_undo_is_blocked_and_rejected_undo_remains(chart):
    with pytest.raises(ValueError, match="recorded correction"):
        undo_review("pt_test", "note_test", ["obs_test"], data_dir=chart)
    q = chart.parent / "proposed" / "pt_test" / "note_test.json"
    b = json.loads(q.read_text())
    b["proposed"]["observations"][0].update(status="rejected", review={"decision": "rejected"})
    q.write_text(json.dumps(b))
    undo_review("pt_test", "note_test", ["obs_test"], data_dir=chart)
    assert json.loads(q.read_text())["proposed"]["observations"][0]["status"] == "proposed"


def test_note_medication_change_reverses_and_leaves_current_plan(chart):
    p = load_patient("pt_test", chart)
    before = deepcopy(p["medications"][0]["segments"])
    ch = {"med_id": "med_test", "change": "dose_change", "effective": "2026-01-12", "dose": "1000 mg", "provenance": {"source": "nlp_extraction"}, "status": "proposed"}
    accept_medication_change(p, ch)
    save_patient(p, chart)
    qp = chart.parent / "proposed" / "pt_test" / "note_test.json"
    batch = json.loads(qp.read_text()); batch["medication_changes"] = [ch]; qp.write_text(json.dumps(batch))
    change = next(x for x in catalog("pt_test", chart)["items"] if x["kind"] == "course_changes")
    correct(chart, change["id"], "entered_in_error")
    p = load_patient("pt_test", chart)
    assert p["medications"][0]["segments"] == before
    assert json.loads(qp.read_text())["medication_changes"][0]["status"] == "entered_in_error"
    assert not any(x["kind"] == "course_changes" for x in catalog("pt_test", chart)["items"])
    trail = ledger_for_problem(p, "prob_test", chart.parent / "proposed")
    assert next(x for x in trail if x["kind"] == "medication_change")["decision"] == "corrected"


def test_legacy_medication_change_is_explained_and_blocked(chart):
    add_order(chart)
    p = load_patient("pt_test", chart)
    p["orders"][0].pop("medication_effect")
    save_patient(p, chart)
    with pytest.raises(ValueError, match="older order"):
        correct(chart, "ord_test", "entered_in_error")
    assert len(load_patient("pt_test", chart)["orders"]) == 1


def test_note_cannot_be_resigned_after_amendment(chart):
    correct(chart, "note_test", "amend", text="Clarification")
    with pytest.raises(ValueError, match="already signed"):
        sign_note("pt_test", "note_test", data_dir=chart)


def test_catalog_distinguishes_results_by_value_and_date(chart):
    rows = catalog("pt_test", chart)["items"]
    assert next(x for x in rows if x["id"] == "obs_test")["label"] == "Glucose 150 mg/dL - 2026-01-10"
    assert next(x for x in rows if x["id"] == "note_test")["label"] == "Note by Dr. Chen - 2026-01-10"
