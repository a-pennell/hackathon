import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.compose import build_context, build_messages, compose, render_text, validate  # noqa: E402
from ehr.review import accept_item, reject_item, review_record  # noqa: E402
from tests.test_reason import patient as reason_patient  # noqa: E402,F401  (fixture reuse)


@pytest.fixture
def patient(reason_patient):
    p = copy.deepcopy(reason_patient)
    p["insights"] = [{"id": "ins_ckd_01", "patient_id": "pt_t", "problem_id": "prob_ckd", "statement": "Creatinine up 38% after ibuprofen.",
                      "evidence": ["obs_0003", "med_ibuprofen"], "suggested_action": "Consider stopping ibuprofen.", "status": "accepted",
                      "provenance": {"source": "reasoning", "model": "reasoner-v1/x", "trend_codes": ["2160-0"], "confidence": 0.9},
                      "created_at": "2026-09-01T00:00:00-04:00", "review": review_record("accepted", "Dr. Chen", "agree")}]
    return p


def queue_dir_with_ledger(tmp_path):
    """A queue file where one proposal about prob_ckd was rejected with a reason."""
    q = tmp_path / "proposed" / "pt_t"
    q.mkdir(parents=True)
    batch = {"patient_id": "pt_t", "problem_id": "prob_ckd", "model": "reasoner-v1/x", "reasoned_at": "2026-09-02T00:00:00-04:00",
             "proposed": {"insights": [{"id": "ins_ckd_02", "patient_id": "pt_t", "problem_id": "prob_ckd", "statement": "Restage to CKD 4.",
                                        "evidence": ["obs_0003"], "suggested_action": "Restage.", "status": "rejected",
                                        "provenance": {"source": "reasoning", "model": "x", "trend_codes": [], "confidence": 0.7},
                                        "created_at": "2026-09-02T00:00:00-04:00",
                                        "review": review_record("rejected", "Dr. Chen", "single value, repeat serum first", "needs_confirmation")}]},
             "rejected": []}
    (q / "reason_prob_ckd.json").write_text(json.dumps(batch))
    return tmp_path / "proposed"


def test_context_includes_ledger_and_catalog(patient, tmp_path):
    ctx = build_context(patient, "prob_ckd", kind="referral", audience="nephrology",
                        window={"start": "2026-05-01", "end": "2026-08-30"}, proposed_dir=queue_dir_with_ledger(tmp_path))
    assert ctx["document"] == {"kind": "referral", "audience": "nephrology"}
    assert [i["id"] for i in ctx["signed_insights"]] == ["ins_ckd_01"]
    led = ctx["reasoning_ledger"]
    assert len(led) == 1 and led[0]["decision"] == "rejected" and led[0]["reason_code"] == "needs_confirmation"
    assert {"ins_ckd_01", "ins_ckd_02", "obs_0003", "med_ibuprofen", "prob_ckd", "prob_htn"} <= set(ctx["catalog"])
    _, messages = build_messages(ctx)
    assert "repeat serum first" in messages[0]["content"] and "Evidence catalog" in messages[0]["content"]


def test_validate_filters_citations_and_builds_document(patient, tmp_path):
    ctx = build_context(patient, "prob_ckd", kind="referral", audience="nephrology",
                        window={"start": "2026-05-01", "end": "2026-08-30"}, proposed_dir=queue_dir_with_ledger(tmp_path))
    raw = {"title": "Referral: CKD stage 3", "confidence": 0.8, "questions": ["Is dialysis planning warranted?", ""],
           "sections": [
               {"heading": "Reason for referral", "text": "Creatinine rose from 1.3 to 1.8.", "cites": ["obs_0001", "obs_0003", "obs_9999"]},
               {"heading": "Medications", "text": "Ibuprofen started in June.", "cites": ["med_ibuprofen"]},
               {"heading": "Our reasoning", "text": "We deferred restaging pending a serum creatinine.", "cites": ["ins_ckd_02"]},
               {"heading": "Empty", "text": "", "cites": []},
               {"heading": "Uncited", "text": "Patient prefers morning appointments.", "cites": []}]}
    batch = validate(patient, ctx, raw, "claude-test")
    docs = batch["proposed"]["documents"]
    assert len(docs) == 1
    d = docs[0]
    assert d["id"] == "doc_ckd_referral_01" and d["kind"] == "referral" and d["audience"] == "nephrology" and d["status"] == "proposed"
    assert [s["heading"] for s in d["sections"]] == ["Reason for referral", "Medications", "Our reasoning", "Uncited"]
    assert d["sections"][0]["cites"] == ["obs_0001", "obs_0003"]
    assert d["questions"] == ["Is dialysis planning warranted?"]
    assert d["provenance"]["source"] == "composition" and set(d["provenance"]["evidence"]) == {"obs_0001", "obs_0003", "med_ibuprofen", "ins_ckd_02"}
    assert any("obs_9999" in r["reason"] for r in batch["rejected"])
    assert "Uncited" in batch["review_hints"]["doc_ckd_referral_01"]
    assert "REASON FOR REFERRAL" in render_text(d)

    # a document with no citable section is rejected outright
    bad = validate(patient, ctx, {"title": "x", "confidence": 0.5, "questions": [], "sections": [{"heading": "h", "text": "t", "cites": ["nope"]}]}, "m")
    assert bad["proposed"]["documents"] == [] and any("no section carries" in r["reason"] for r in bad["rejected"])


def test_replay_path_and_review(patient, tmp_path):
    raw = {"parsed": {"title": "Referral", "confidence": 0.7, "questions": ["q"],
                      "sections": [{"heading": "Why", "text": "Rising creatinine.", "cites": ["obs_0003", "ins_ckd_01"]}]}, "model": "claude-test"}
    batch, _, _ = compose(patient, "prob_ckd", window={"start": "2026-05-01", "end": "2026-08-30"}, raw=raw,
                          proposed_dir=queue_dir_with_ledger(tmp_path))
    chart = copy.deepcopy(patient)
    done = accept_item(chart, batch, "doc_ckd_referral_01", review=review_record("accepted", "Dr. Chen", "sent"))
    assert done == ["document doc_ckd_referral_01"]
    assert chart["documents"][0]["status"] == "accepted" and chart["documents"][0]["review"]["reason"] == "sent"


def test_review_records_on_reject_and_accept(reason_patient):
    from ehr.reason import reason_problem
    batch, _, _ = reason_problem(reason_patient, "prob_ckd", window={"start": "2026-05-01", "end": "2026-08-30"}, rules_only=True)
    msg = reject_item(batch, "ins_ckd_01", review_record("rejected", "Dr. Chen", "already discussed", "already_known"))
    it = batch["proposed"]["insights"][0]
    assert msg.endswith("rejected") and it["review"]["decision"] == "rejected" and it["review"]["reason_code"] == "already_known"
    assert it["review"]["by"] == "Dr. Chen" and it["review"]["at"].endswith(("-04:00", "-07:00", "+00:00")) or "T" in it["review"]["at"]
    with pytest.raises(ValueError):
        review_record("rejected", reason_code="because")
