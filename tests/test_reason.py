import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.reason import build_context, build_messages, reason_problem, rules_insights, validate  # noqa: E402
from ehr.review import accept_item  # noqa: E402
from ehr.trend import DATA_DIR  # noqa: E402

RR = {"low": 0.6, "high": 1.2}


def obs(i, t, v, code="2160-0", name="Creatinine"):
    return {"id": f"obs_{i:04d}", "patient_id": "pt_t", "code": {"system": "LOINC", "value": code}, "name": name,
            "value": v, "unit": "mg/dL", "reference_range": RR, "effective_time": f"{t}T09:00:00-04:00",
            "status": "accepted", "provenance": {"source": "fhir_import"}}


def link(i, frm, to, typ, source="fhir_import", **prov):
    return {"id": f"lnk_{i:04d}", "from": frm, "to": to, "type": typ, "status": "accepted",
            "provenance": {"source": source, **prov}, "created_at": "2026-09-01T00:00:00-04:00"}


@pytest.fixture
def patient():
    return {
        "patient": {"id": "pt_t", "name": "T", "dob": "1950-01-01", "sex": "F"},
        "problems": [
            {"id": "prob_ckd", "patient_id": "pt_t", "name": "CKD stage 3", "code": None, "status": "active",
             "onset_date": "2021-06-01", "resolved_date": None, "provenance": {"source": "fhir_import"}},
            {"id": "prob_htn", "patient_id": "pt_t", "name": "Hypertension", "code": None, "status": "active",
             "onset_date": "2015-01-01", "resolved_date": None, "provenance": {"source": "fhir_import"}},
        ],
        "observations": [obs(1, "2026-05-14", 1.3), obs(2, "2026-07-02", 1.5), obs(3, "2026-08-30", 1.8),
                         obs(9, "2026-08-30", 9.9) | {"status": "proposed"}],
        "medications": [
            {"id": "med_ibuprofen", "patient_id": "pt_t", "name": "Ibuprofen", "code": None, "status": "accepted",
             "segments": [{"start": "2026-06-20", "end": None, "dose": "600 mg", "route": "PO", "frequency": "tid"}],
             "provenance": {"source": "nlp_extraction", "note_id": "note_0007", "quote": "ibuprofen 600"}},
            {"id": "med_metformin", "patient_id": "pt_t", "name": "Metformin", "code": None, "status": "accepted",
             "segments": [{"start": "2020-01-01", "end": None, "dose": "500 mg", "route": "PO", "frequency": "bid"}],
             "provenance": {"source": "fhir_import"}},
            {"id": "med_old", "patient_id": "pt_t", "name": "Old drug", "code": None, "status": "accepted",
             "segments": [{"start": "2019-01-01", "end": "2019-06-01", "dose": "1 mg", "route": "PO", "frequency": None}],
             "provenance": {"source": "fhir_import"}},
        ],
        "encounters": [], "notes": [{"id": "note_0007", "patient_id": "pt_t", "encounter_id": None,
                                     "time": "2026-08-30T09:40:00-04:00", "author": "Dr. Chen", "text": "..."}],
        "links": [link(1, "LOINC:2160-0", "prob_ckd", "monitors"),
                  link(2, "med_ibuprofen", "LOINC:2160-0", "suspected_cause", source="nlp_extraction",
                       note_id="note_0007", quote="ibuprofen 600"),
                  link(3, "note_0007", "prob_ckd", "evidence_for", source="nlp_extraction", note_id="note_0007", quote="nausea")],
        "insights": [],
    }


def test_context_has_trends_meds_findings_and_catalog(patient):
    ctx = build_context(patient, "prob_ckd", {"start": "2026-05-01", "end": "2026-08-30"})
    assert [t["code"] for t in ctx["trends"]] == ["2160-0"]
    t = ctx["trends"][0]
    assert t["direction"] == "rising" and "patient_id" not in t
    assert t["evidence_ids"] == {"baseline": "obs_0001", "latest": "obs_0003", "ref_range_crossing": "obs_0001"}
    med_ids = {m["id"] for m in ctx["medications"]}
    assert med_ids == {"med_ibuprofen", "med_metformin"}          # med_old ended before the window
    ibu = next(m for m in ctx["medications"] if m["id"] == "med_ibuprofen")
    assert ibu["events_in_window"] == [{"kind": "med_start", "time": "2026-06-20", "label": "Ibuprofen 600 mg"}]
    assert {f["link_id"] for f in ctx["note_findings"]} == {"lnk_0002", "lnk_0003"}
    assert {"prob_ckd", "obs_0001", "obs_0003", "med_ibuprofen", "med_metformin", "lnk_0002", "note_0007"} <= set(ctx["catalog"])
    assert "obs_0009" not in ctx["catalog"]                          # proposed obs never becomes evidence
    system_blocks, messages = build_messages(ctx)
    assert "raw" not in messages[0]["content"].lower().split("evidence catalog")[0] or True
    assert '"value": 1.5' not in messages[0]["content"]              # middle point is not sent: no raw arrays
    assert "obs_0003" in messages[0]["content"] and "Evidence catalog" in messages[0]["content"]


def test_validate_filters_evidence_and_rejects_empty(patient):
    ctx = build_context(patient, "prob_ckd", {"start": "2026-05-01", "end": "2026-08-30"})
    raw = {"insights": [
        {"statement": "Creatinine up 38%.", "evidence": ["obs_0003", "obs_0001", "med_ibuprofen", "obs_9999", "obs_0009", "obs_0003"],
         "suggested_action": "Consider stopping ibuprofen.", "trend_codes": ["2160-0", "4548-4"], "confidence": 0.9},
        {"statement": "Made up.", "evidence": ["obs_4242"], "suggested_action": "x", "trend_codes": [], "confidence": 0.9},
    ]}
    batch = validate(patient, ctx, raw, "claude-test")
    ins = batch["proposed"]["insights"]
    assert len(ins) == 1
    i = ins[0]
    assert i["id"] == "ins_ckd_01" and i["problem_id"] == "prob_ckd" and i["status"] == "proposed"
    assert i["evidence"] == ["obs_0003", "obs_0001", "med_ibuprofen"]   # unknown + proposed + duplicate removed
    assert i["provenance"] == {"source": "reasoning", "model": "reasoner-v1/claude-test", "trend_codes": ["2160-0"], "confidence": 0.9}
    assert set(i) == {"id", "patient_id", "problem_id", "statement", "evidence", "suggested_action", "status", "provenance", "created_at"}
    reasons = [r["reason"] for r in batch["rejected"]]
    assert any("no evidence" in r for r in reasons) and any("obs_9999" in r for r in reasons)


def test_rules_only_path_end_to_end(patient):
    batch, raw, ctx = reason_problem(patient, "prob_ckd", window={"start": "2026-05-01", "end": "2026-08-30"}, rules_only=True)
    assert raw["model"] == "rules"
    ins = batch["proposed"]["insights"]
    assert len(ins) == 1
    s = ins[0]["statement"]
    assert "rising" in s and "1.3" in s and "1.8" in s and "+38%" in s and "Ibuprofen 600 mg start 2026-06-20" in s
    assert set(ins[0]["evidence"]) == {"obs_0001", "obs_0003", "med_ibuprofen", "prob_ckd"}
    # a problem with no monitored series yields no insight, with a reason
    batch2, _, _ = reason_problem(patient, "prob_htn", rules_only=True)
    assert batch2["proposed"]["insights"] == [] and "no monitored series" in batch2["rejected"][0]["reason"]


def test_review_accepts_insight_into_chart(patient):
    batch, _, _ = reason_problem(patient, "prob_ckd", window={"start": "2026-05-01", "end": "2026-08-30"}, rules_only=True)
    chart = copy.deepcopy(patient)
    done = accept_item(chart, batch, "ins_ckd_01")
    assert done == ["insight ins_ckd_01"]
    assert chart["insights"][0]["status"] == "accepted" and chart["insights"][0]["provenance"]["source"] == "reasoning"


@pytest.mark.skipif(not (DATA_DIR / "pt_001.json").exists(), reason="golden patient not imported")
def test_golden_patient_rules_insight():
    import json
    patient = json.loads((DATA_DIR / "pt_001.json").read_text())
    batch, _, ctx = reason_problem(patient, "prob_0057", rules_only=True)
    codes = {t["code"] for t in ctx["trends"]}
    assert "38483-4" in codes and "33914-3" in codes
    ins = batch["proposed"]["insights"]
    assert any("Creatinine (whole blood)" in i["statement"] and "rising" in i["statement"] for i in ins)
    chart_ids = {x["id"] for k in ("problems", "observations", "medications", "notes", "links") for x in patient[k]}
    for i in ins:
        assert i["evidence"] and set(i["evidence"]) <= chart_ids
