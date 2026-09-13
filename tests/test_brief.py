import copy
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.brief import deterministic_brief, live_brief  # noqa: E402
from ehr.review import ledger_for_problem, review_record  # noqa: E402
from tests.test_reason import patient as reason_patient  # noqa: E402,F401

TODAY = date(2026, 8, 31)


def queue_dir(tmp_path, with_pending=True):
    q = tmp_path / "proposed" / "pt_t"
    q.mkdir(parents=True)
    batch = {"patient_id": "pt_t", "note_id": "note_0007", "model": "extractor-v1/x", "extracted_at": "2026-08-30T10:00:00-04:00",
             "proposed": {
                 "problems": [{"id": "prob_n_01", "patient_id": "pt_t", "name": "CKD stage 4", "code": None, "status": "rejected",
                               "onset_date": None, "resolved_date": None, "provenance": {"source": "nlp_extraction", "note_id": "note_0007", "quote": "CKD progressing", "confidence": 0.6},
                               "review": review_record("rejected", "Dr. Chen", "repeat serum creatinine first", "needs_confirmation")}],
                 "observations": [], "medications": [],
                 "links": [{"id": "lnk_n_01", "from": "obs_0003", "to": "prob_ckd", "type": "relevant_to", "status": "proposed" if with_pending else "accepted",
                            "provenance": {"source": "nlp_extraction", "note_id": "note_0007", "quote": "Cr 1.8", "confidence": 0.9}, "created_at": "2026-08-30T10:00:00-04:00"}]},
             "review_hints": {"prob_n_01": "supersedes prob_ckd; on accept, consider resolving it"},
             "rejected": []}
    (q / "note_0007.json").write_text(json.dumps(batch))
    return tmp_path / "proposed"


def test_deterministic_brief_lines(reason_patient, tmp_path):
    pd = queue_dir(tmp_path)
    b = deterministic_brief(reason_patient, "prob_ckd", "90d", proposed_dir=pd, today=TODAY)
    assert b["source"] == "computed" and b["window"] == {"start": "2026-06-02", "end": "2026-08-31"}
    kinds = [l["kind"] for l in b["lines"]]
    assert kinds == ["trend", "med", "queue", "ledger"]          # four short lines, nothing the lanes already show
    trend = b["lines"][0]
    assert trend["text"] == "Creatinine 1.8 on 30 Aug, up 20% since 2 Jul, outside range since 2 Jul."
    assert set(trend["ids"]) == {"obs_0003", "obs_0002"}          # latest, baseline (crossing point is the baseline itself)
    med = next(l for l in b["lines"] if l["kind"] == "med")
    assert med["text"] == "Ibuprofen 600 mg started 20 Jun (from a note)." and med["ids"] == ["med_ibuprofen"]
    q = next(l for l in b["lines"] if l["kind"] == "queue")
    assert b["pending"] == 1 and q["text"] == "1 proposal waiting for your decision." and q["ids"] == ["lnk_n_01"]
    assert sum(len(l["text"]) for l in b["lines"]) < 400
    led = next(l for l in b["lines"] if l["kind"] == "ledger")
    assert "repeat serum creatinine first" in led["text"] and led["ids"] == ["prob_n_01"]
    # every id the brief cites exists on the chart or in the queue
    known = {x["id"] for k in ("problems", "observations", "medications", "encounters", "notes", "links") for x in reason_patient[k]} | {"prob_n_01", "lnk_n_01"}
    assert all(i in known for l in b["lines"] for i in l["ids"])


def test_brief_with_no_series_in_window(reason_patient, tmp_path):
    b = deterministic_brief(reason_patient, "prob_htn", "90d", proposed_dir=queue_dir(tmp_path), today=TODAY)
    assert b["lines"][0]["text"].startswith("No monitored series for Hypertension")


def test_live_brief_validates_citations(reason_patient, tmp_path):
    raw = {"parsed": {"sentences": [{"text": "Creatinine has risen to 1.8.", "cites": ["obs_0003", "obs_9999"]},
                                    {"text": "", "cites": []},
                                    {"text": "You declined to restage last week.", "cites": ["prob_n_01"]}]}, "model": "claude-test"}
    brief, _ = live_brief(reason_patient, "prob_ckd", "90d", raw=raw, proposed_dir=queue_dir(tmp_path), today=TODAY)
    assert brief["source"] == "brief-v1/claude-test"
    assert [l["ids"] for l in brief["lines"]] == [["obs_0003"], ["prob_n_01"]]
    assert brief["dropped_citations"] == ["obs_9999"]


def test_ledger_for_problem_includes_supersedes_and_pending(reason_patient, tmp_path):
    pd = queue_dir(tmp_path)
    decided = ledger_for_problem(reason_patient, "prob_ckd", pd)
    assert [(e["id"], e["decision"], e["reason_code"]) for e in decided] == [("prob_n_01", "rejected", "needs_confirmation")]
    everything = ledger_for_problem(reason_patient, "prob_ckd", pd, include_pending=True)
    assert {(e["id"], e["decision"]) for e in everything} == {("prob_n_01", "rejected"), ("lnk_n_01", "pending")}
    assert all(e["at"] for e in everything)
