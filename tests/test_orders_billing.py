import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.billing import code_visit  # noqa: E402
from ehr.orders import build_context, propose_orders, validate  # noqa: E402
from ehr.review import accept_item, review_record  # noqa: E402
from tests.test_reason import patient as reason_patient  # noqa: E402,F401

TODAY = "2026-09-13"


@pytest.fixture
def patient(reason_patient):
    p = copy.deepcopy(reason_patient)
    p["problems"][0]["code"] = {"system": "SNOMED-CT", "value": "433144002"}   # CKD stage 3
    p["problems"][1]["code"] = {"system": "SNOMED-CT", "value": "59621000"}    # hypertension
    p["insights"] = [{"id": "ins_ckd_01", "patient_id": "pt_t", "problem_id": "prob_ckd",
                      "statement": "Creatinine up 38% after ibuprofen; metformin on board.", "evidence": ["obs_0003", "med_ibuprofen", "med_metformin"],
                      "suggested_action": "Consider stopping ibuprofen and metformin and repeating creatinine in two weeks.", "status": "accepted",
                      "provenance": {"source": "reasoning", "model": "reasoner-v1/x", "trend_codes": ["2160-0"], "confidence": 0.9},
                      "created_at": f"{TODAY}T09:00:00-04:00", "review": review_record("accepted", "Dr. Chen")}]
    return p


def test_orders_validate(patient):
    ctx = build_context(patient, "prob_ckd", {"start": "2026-05-01", "end": "2026-08-30"})
    assert [i["id"] for i in ctx["signed_insights"]] == ["ins_ckd_01"]
    raw = {"orders": [
        {"kind": "medication_change", "name": "Stop ibuprofen", "detail": "stop now", "loinc": None, "med_id": "med_ibuprofen", "change": "stop",
         "dose": None, "audience": None, "from_insight": "ins_ckd_01", "evidence": ["obs_0003", "obs_9999"], "confidence": 0.9},
        {"kind": "lab", "name": "Serum creatinine", "detail": "repeat in 2 weeks", "loinc": "2160-0", "med_id": None, "change": None,
         "dose": None, "audience": None, "from_insight": "ins_ckd_01", "evidence": ["obs_0003"], "confidence": 0.85},
        {"kind": "lab", "name": "Cystatin C", "detail": "once", "loinc": "33863-2", "med_id": None, "change": None,
         "dose": None, "audience": None, "from_insight": "ins_ckd_01", "evidence": [], "confidence": 0.5},
        {"kind": "medication_change", "name": "Stop ghost", "detail": "", "loinc": None, "med_id": "med_nope", "change": "stop",
         "dose": None, "audience": None, "from_insight": "ins_ckd_01", "evidence": [], "confidence": 0.5},
        {"kind": "referral", "name": "Nephrology", "detail": "urgent", "loinc": None, "med_id": None, "change": None,
         "dose": None, "audience": "nephrology", "from_insight": "ins_made_up", "evidence": [], "confidence": 0.8},
    ]}
    batch = validate(patient, ctx, raw, "claude-test")
    o = batch["proposed"]["orders"]
    assert [x["kind"] for x in o] == ["medication_change", "lab", "lab"]
    assert o[0]["id"] == "ord_ckd_01" and o[0]["med_id"] == "med_ibuprofen" and o[0]["change"] == "stop"
    assert o[0]["provenance"]["evidence"] == ["ins_ckd_01", "med_ibuprofen", "obs_0003"]      # insight first, med, then verified ids
    assert o[1]["code"] == {"system": "LOINC", "value": "2160-0"}
    assert o[2]["code"] is None and any("33863-2" in r["reason"] for r in batch["rejected"])  # unknown code kept without a code
    reasons = " ".join(r["reason"] for r in batch["rejected"])
    assert "med_nope" in reasons and "not derived from a signed insight" in reasons

    # signing the medication-change order closes the course, as a reviewed note change would
    chart = copy.deepcopy(patient)
    done = accept_item(chart, batch, "ord_ckd_01", review=review_record("accepted", "Dr. Chen"))
    assert done[0] == "order ord_ckd_01" and "stopped" in done[1]
    ibu = next(m for m in chart["medications"] if m["id"] == "med_ibuprofen")
    assert ibu["segments"][-1]["end"] is not None and chart["orders"][0]["status"] == "accepted"


def test_orders_need_a_signed_insight(reason_patient):
    batch, raw, _ = propose_orders(reason_patient, "prob_ckd", window={"start": "2026-05-01", "end": "2026-08-30"}, raw={"parsed": {"orders": []}})
    assert batch["proposed"]["orders"] == [] and "sign an insight first" in batch["rejected"][0]["reason"]


def queue_with_signatures(tmp_path, patient, extra_orders=()):
    q = tmp_path / "proposed" / "pt_t"
    q.mkdir(parents=True)
    ins = copy.deepcopy(patient["insights"][0]); ins["status"] = "accepted"
    batch = {"patient_id": "pt_t", "problem_id": "prob_ckd", "model": "reasoner-v1/x", "reasoned_at": f"{TODAY}T09:00:00-04:00",
             "proposed": {"insights": [ins]}, "rejected": []}
    (q / "reason_prob_ckd.json").write_text(json.dumps(batch))
    note = {"patient_id": "pt_t", "note_id": "note_0007", "model": "extractor-v1/x", "extracted_at": f"{TODAY}T08:00:00-04:00",
            "proposed": {"links": [{"id": "lnk_n_01", "from": "note_0007", "to": "prob_ckd", "type": "evidence_for", "status": "accepted",
                                    "provenance": {"source": "nlp_extraction", "note_id": "note_0007", "quote": "nausea", "confidence": 0.9},
                                    "created_at": f"{TODAY}T08:00:00-04:00", "review": review_record("accepted", "Dr. Chen")}]},
            "medication_changes": [{"med_id": "med_metformin", "change": "stop", "effective": TODAY, "status": "accepted",
                                    "provenance": {"source": "nlp_extraction", "quote": "stop metformin", "confidence": 0.9},
                                    "review": review_record("accepted", "Dr. Chen")}],
            "rejected": []}
    (q / "note_0007.json").write_text(json.dumps(note))
    if extra_orders:
        ob = {"patient_id": "pt_t", "problem_id": "prob_ckd", "model": "orderer-v1/x", "ordered_at": f"{TODAY}T10:00:00-04:00",
              "proposed": {"orders": list(extra_orders)}, "rejected": []}
        (q / "orders_prob_ckd.json").write_text(json.dumps(ob))
    return tmp_path / "proposed"


def test_coding_levels_and_codes(patient, tmp_path):
    pd = queue_with_signatures(tmp_path, patient)
    c = code_visit(patient, None, on=TODAY, proposed_dir=pd)
    assert c["status"] == "computed" and c["signed_today"] == 3
    assert [a["problem_id"] for a in c["problems_addressed"]] == ["prob_ckd"]
    m = c["mdm"]
    assert m["problems"]["level"] == "high"          # creatinine rising and out of range
    assert m["data"]["level"] == "low"               # creatinine reviewed + note reviewed = 2 items
    assert m["risk"]["level"] == "moderate"          # prescription drug management (metformin stop)
    assert m["level"] == "moderate" and m["cpt"] == "99214"
    dx = {d["code"]: d for d in c["diagnosis_codes"]}
    assert "N18.30" in dx and dx["N18.30"]["mapping"] == "demo table"
    assert "I12.9" not in dx                         # hypertension was not addressed today

    # a signed lab order adds a data item -> moderate data -> two elements at moderate or above
    order = {"id": "ord_ckd_01", "patient_id": "pt_t", "problem_id": "prob_ckd", "kind": "lab", "name": "Serum creatinine", "detail": "2 weeks",
             "code": {"system": "LOINC", "value": "2160-0"}, "med_id": None, "change": None, "dose": None, "audience": None, "status": "accepted",
             "provenance": {"source": "ordering", "model": "x", "from_insight": "ins_ckd_01", "evidence": ["ins_ckd_01"], "confidence": 0.9},
             "created_at": f"{TODAY}T10:00:00-04:00", "review": review_record("accepted", "Dr. Chen")}
    pd2 = queue_with_signatures(tmp_path / "b", patient, extra_orders=[order])
    c2 = code_visit(patient, None, on=TODAY, proposed_dir=pd2)
    assert c2["mdm"]["data"]["level"] == "moderate" and c2["mdm"]["cpt"] == "99214"

    # nothing signed on another day -> nothing addressed, straightforward
    c3 = code_visit(patient, None, on="2026-01-01", proposed_dir=pd)
    assert c3["problems_addressed"] == [] and c3["mdm"]["cpt"] == "99212"


def test_stop_order_keeps_an_earlier_recorded_stop(reason_patient):
    from ehr.review import accept_medication_change
    p = copy.deepcopy(reason_patient)
    ibu = next(m for m in p["medications"] if m["id"] == "med_ibuprofen")
    ibu["segments"][-1]["end"] = "2026-08-20"                                   # the note said it was stopped on the 20th
    msg = accept_medication_change(p, {"med_id": "med_ibuprofen", "change": "stop", "effective": "2026-08-30", "dose": None, "route": None, "frequency": None, "status": "proposed"})
    assert ibu["segments"][-1]["end"] == "2026-08-20" and msg.startswith("med_ibuprofen already stopped 2026-08-20")
    ibu["segments"][-1]["end"] = None                                           # still running: the order stops it today
    accept_medication_change(p, {"med_id": "med_ibuprofen", "change": "stop", "effective": "2026-08-30", "dose": None, "route": None, "frequency": None, "status": "proposed"})
    assert ibu["segments"][-1]["end"] == "2026-08-30"
