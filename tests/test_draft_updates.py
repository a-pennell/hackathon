import json
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ehr.draft import run_draft, sign_draft
from ehr.assessment import sign_assessment
from ehr.draft_updates import read_draft, preview_updates, incorporate_updates, save_draft
from ehr.extract import save_patient
from ehr.intent import run_intent
from ehr.review import accept_item, review_record
from ehr.trend import load_patient


@pytest.fixture
def draft(tmp_path):
    d = tmp_path / "patients"
    d.mkdir()
    p = {"patient": {"id": "pt_update", "name": "Test", "dob": "1970-01-01", "sex": "F"},
         "encounters": [{"id": "enc_test", "time": "2026-01-10T09:00:00+00:00", "type": "office visit", "summary": "Review"}],
         "notes": [{"id": "note_test", "encounter_id": "enc_test", "author": "Dr. Chen", "text": "Patient history.", "time": "2026-01-10T09:00:00+00:00"}],
         "problems": [{"id": "prob_test", "name": "Hypertension", "status": "active", "onset_date": "2025-01-01", "provenance": {"source": "fhir_import"}}],
         "medications": [], "observations": [], "links": [], "insights": [], "orders": [], "plans": [], "documents": []}
    save_patient(p, d)
    run_intent("pt_update", "prob_test", "monitoring", "Home BP log", data_dir=d)
    run_draft("pt_update", "enc_test", data_dir=d)
    return d


def edits(batch, heading_prefix=None, text=None):
    return [{"key": s["key"], "heading": s["heading"], "text": text if heading_prefix and s["heading"].startswith(heading_prefix) else s["text"]}
            for s in batch["proposed"]["documents"][0]["sections"]]


def update(d, text="Return in two weeks"):
    return run_intent("pt_update", "prob_test", "follow_up", text, data_dir=d)


def test_new_accepted_changes_detected_and_merged_without_losing_other_edits(draft):
    b = read_draft("pt_update", "enc_test", draft)
    e = edits(b, "As dictated", "My own history wording.")
    update(draft)
    assert read_draft("pt_update", "enc_test", draft)["updates_count"] > 0
    preview = preview_updates("pt_update", "enc_test", e, draft)
    assert preview["changes"] and not any(c["conflict"] for c in preview["changes"])
    b = incorporate_updates("pt_update", "enc_test", e, preview["revision"], {}, draft)
    secs = b["proposed"]["documents"][0]["sections"]
    assert secs[0]["text"] == "My own history wording."
    assert any("Return in two weeks" in s["text"] for s in secs)
    assert b["updates_count"] == 0
    assert preview_updates("pt_update", "enc_test", edits(b), draft)["changes"] == []


def test_edited_section_requires_explicit_resolution_and_keep_is_persistent(draft):
    b = read_draft("pt_update", "enc_test", draft)
    e = edits(b, "Plan", "My plan, in my words.")
    update(draft)
    preview = preview_updates("pt_update", "enc_test", e, draft)
    conflict = next(c for c in preview["changes"] if c["conflict"])
    with pytest.raises(ValueError, match="Choose how"):
        incorporate_updates("pt_update", "enc_test", e, preview["revision"], {}, draft)
    b = incorporate_updates("pt_update", "enc_test", e, preview["revision"], {conflict["key"]: {"choice": "keep"}}, draft)
    assert next(s for s in b["proposed"]["documents"][0]["sections"] if s["key"] == conflict["key"])["text"] == "My plan, in my words."
    assert read_draft("pt_update", "enc_test", draft)["updates_count"] == 0
    assert run_draft("pt_update", "enc_test", data_dir=draft)["proposed"] == b["proposed"]


def test_manual_merge_and_explicit_replacement(draft):
    b = read_draft("pt_update", "enc_test", draft)
    e = edits(b, "Plan", "Personal wording.")
    update(draft)
    preview = preview_updates("pt_update", "enc_test", e, draft)
    key = next(c["key"] for c in preview["changes"] if c["conflict"])
    b = incorporate_updates("pt_update", "enc_test", e, preview["revision"], {key: {"choice": "edit", "text": "Personal wording. Return in two weeks."}}, draft)
    assert next(s for s in b["proposed"]["documents"][0]["sections"] if s["key"] == key)["edited"]
    update(draft, "Bring medication list")
    preview = preview_updates("pt_update", "enc_test", edits(b), draft)
    b = incorporate_updates("pt_update", "enc_test", edits(b), preview["revision"], {key: {"choice": "update"}}, draft)
    assert "Bring medication list" in next(s for s in b["proposed"]["documents"][0]["sections"] if s["key"] == key)["text"]


def test_save_and_reopen_retain_edits_and_removed_text(draft):
    b = read_draft("pt_update", "enc_test", draft)
    b = save_draft("pt_update", "enc_test", edits(b, "Plan", ""), b["draft_revision"], draft)
    assert next(s for s in run_draft("pt_update", "enc_test", data_dir=draft)["proposed"]["documents"][0]["sections"] if s["heading"].startswith("Plan"))["text"] == ""
    update(draft)
    assert any(c["conflict"] for c in preview_updates("pt_update", "enc_test", edits(b), draft)["changes"])


def test_stale_preview_and_stale_signing_do_not_write(draft):
    b = read_draft("pt_update", "enc_test", draft)
    update(draft)
    before = (draft.parent / "proposed" / "pt_update" / "visitnote_enc_test.json").read_text()
    with pytest.raises(ValueError, match="Updates are available"):
        sign_draft("pt_update", "enc_test", edits(b), data_dir=draft)
    preview = preview_updates("pt_update", "enc_test", edits(b), draft)
    update(draft, "Another chart change")
    with pytest.raises(ValueError, match="chart or draft changed"):
        incorporate_updates("pt_update", "enc_test", edits(b), preview["revision"], {}, draft)
    assert (draft.parent / "proposed" / "pt_update" / "visitnote_enc_test.json").read_text() == before


def test_concurrent_draft_save_is_rejected(draft):
    b = read_draft("pt_update", "enc_test", draft)
    save_draft("pt_update", "enc_test", edits(b, "Plan", "First editor"), b["draft_revision"], draft)
    with pytest.raises(ValueError, match="changed elsewhere"):
        save_draft("pt_update", "enc_test", edits(b, "Plan", "Second editor"), b["draft_revision"], draft)


def test_signed_notes_never_refresh_from_workspace(draft):
    b = read_draft("pt_update", "enc_test", draft)
    sign_draft("pt_update", "enc_test", edits(b), data_dir=draft)
    original = deepcopy(load_patient("pt_update", draft)["documents"])
    run_intent("pt_update", "prob_test", "follow_up", "Return in two weeks", destination="treatment_plan", data_dir=draft)
    assert read_draft("pt_update", "enc_test", draft)["updates_count"] == 0
    with pytest.raises(ValueError, match="amendment"):
        preview_updates("pt_update", "enc_test", None, draft)
    assert load_patient("pt_update", draft)["documents"] == original


def test_new_sections_do_not_shift_existing_edits(draft):
    b = read_draft("pt_update", "enc_test", draft)
    e = edits(b, "Plan", "Preserve hypertension wording")
    p = load_patient("pt_update", draft)
    p["problems"].insert(0, {"id": "prob_first", "name": "Earlier problem", "status": "active", "onset_date": None, "provenance": {"source": "fhir_import"}})
    save_patient(p, draft)
    run_intent("pt_update", "prob_first", "monitoring", "New plan in an earlier section", data_dir=draft)
    preview = preview_updates("pt_update", "enc_test", e, draft)
    b = incorporate_updates("pt_update", "enc_test", e, preview["revision"], {}, draft)
    sections = b["proposed"]["documents"][0]["sections"]
    assert next(s for s in sections if s["heading"] == "Plan · Hypertension")["text"] == "Preserve hypertension wording"
    assert "New plan" in next(s for s in sections if s["heading"] == "Plan · Earlier problem")["text"]


def test_accepting_workspace_insight_updates_assessment_and_plan(draft):
    p = load_patient("pt_update", draft)
    i = {"id": "ins_new", "problem_id": "prob_test", "statement": "New signed assessment.", "suggested_action": "Return for review", "evidence": ["prob_test"], "status": "proposed", "provenance": {"source": "reasoning"}}
    accept_item(p, {"proposed": {"insights": [i]}}, "ins_new", review=review_record("accepted", encounter_id="enc_test"))
    save_patient(p, draft)
    preview = preview_updates("pt_update", "enc_test", data_dir=draft)
    assert any("New signed assessment" in (c["incoming"] or {}).get("text", "") for c in preview["changes"])
    assert any("Return for review" in (c["incoming"] or {}).get("text", "") for c in preview["changes"])


def test_decisions_from_another_encounter_do_not_enter_active_draft(draft):
    p = load_patient("pt_update", draft)
    p["plans"].append({**deepcopy(p["plans"][0]), "id": "plan_elsewhere", "text": "Different visit", "review": review_record("accepted", encounter_id="enc_other")})
    save_patient(p, draft)
    assert read_draft("pt_update", "enc_test", draft)["updates_count"] == 0


def test_workspace_assessment_and_representation_are_signed_and_reach_draft(draft):
    rep = sign_assessment("pt_update", "prob_test", "Accepted representation.", "representation", ["prob_test"], data_dir=draft)
    assert rep["review"]["encounter_id"] == "enc_test"
    preview = preview_updates("pt_update", "enc_test", data_dir=draft)
    assert any((c["incoming"] or {}).get("text") == "Accepted representation." for c in preview["changes"])
    assessment = sign_assessment("pt_update", "prob_test", "My full assessment. Additional clinical reasoning.", "assessment", data_dir=draft)
    sign_assessment("pt_update", "prob_test", "Newer generated representation.", "representation", ["prob_test"], data_dir=draft)
    preview = preview_updates("pt_update", "enc_test", data_dir=draft)
    section = next(c["incoming"] for c in preview["changes"] if c["heading"].startswith("Assessment"))
    assert section["text"] == "My full assessment. Additional clinical reasoning."
    assert assessment["id"] in section["cites"]
    assert len(load_patient("pt_update", draft)["insights"]) == 3


def test_removal_from_chart_can_remove_an_edited_draft_section(draft):
    b = read_draft("pt_update", "enc_test", draft)
    e = edits(b, "Plan", "Personal wording of a plan now withdrawn")
    p = load_patient("pt_update", draft)
    p["plans"] = []
    save_patient(p, draft)
    preview = preview_updates("pt_update", "enc_test", e, draft)
    c = next(c for c in preview["changes"] if c["heading"].startswith("Plan"))
    assert c["kind"] == "removed" and c["conflict"]
    b = incorporate_updates("pt_update", "enc_test", e, preview["revision"], {c["key"]: {"choice": "update"}}, draft)
    assert not any(s["heading"].startswith("Plan") for s in b["proposed"]["documents"][0]["sections"])
    assert b["updates_count"] == 0
