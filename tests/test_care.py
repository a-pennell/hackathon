import copy
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.care import care_view  # noqa: E402
from tests.test_overview import with_visits  # noqa: E402
from tests.test_reason import patient as reason_patient  # noqa: E402,F401

TODAY = date(2026, 8, 31)


def test_care_cards_carry_plan_measures_and_loops(reason_patient):
    p = with_visits(reason_patient)
    p["plans"] = [{"id": "plan_1", "patient_id": "pt_t", "problem_id": "prob_ckd", "kind": "monitoring", "text": "Repeat creatinine in two weeks", "status": "accepted",
                   "provenance": {"source": "nlp_extraction", "note_id": "note_0007", "quote": "Repeat creatinine in two weeks", "confidence": 0.9}, "created_at": "2026-08-30T10:00:00-04:00",
                   "review": {"by": "Dr. Chen", "at": "2026-08-30T10:05:00-04:00", "decision": "accepted", "reason_code": None, "reason": None}}]
    p["orders"] = [{"id": "ord_1", "patient_id": "pt_t", "problem_id": "prob_ckd", "kind": "referral", "name": "Nephrology", "detail": "", "code": None, "med_id": None,
                    "change": None, "dose": None, "audience": "nephrology", "status": "accepted", "provenance": {"source": "ordering", "model": "x", "evidence": []},
                    "created_at": "2026-08-30T10:00:00-04:00", "ordered_at": "2026-08-30T10:00:00-04:00"}]
    v = care_view(p, proposed_dir=Path("/nonexistent"), today=TODAY)
    ckd = next(c for c in v["cards"] if c["id"] == "prob_ckd")
    assert [(x["kind"], x["text"], x["source"]) for x in ckd["plan"]] == [("monitoring", "Repeat creatinine in two weeks", "note"), ("referral", "Nephrology · nephrology", "order")]
    assert ckd["measures"][0]["text"] == "Creatinine 1.3 → 1.8" and "worsening" in ckd["qualifiers"]
    assert [(l["kind"], l["status"]) for l in ckd["loops"]] == [("referral", "awaiting")]
    assert ckd["one_liner"].startswith("Creatinine 1.3 → 1.8")
    assert v["cards"][0]["id"] == "prob_ckd"                                     # the worsening, monitored concern leads
    assert [r["problem_name"] for r in v["kinds"]["referrals"]] == ["CKD stage 3"]
    assert [r["text"] for r in v["kinds"]["plans"]] == ["Repeat creatinine in two weeks", "Nephrology · nephrology"]
    assert v["kinds"]["orders"][0]["id"] == "ord_1" and v["kinds"]["follow_ups"] == []


def test_due_strip_is_a_state_from_the_interval_table(reason_patient):
    p = with_visits(reason_patient)
    v = care_view(p, proposed_dir=Path("/nonexistent"), today=TODAY)
    assert v["due"] == []                                                        # creatinine 30 Aug is fresh
    late = care_view(p, proposed_dir=Path("/nonexistent"), today=date(2027, 9, 15))
    assert [(d["code"], d["overdue_days"] > 0, d["problem_id"]) for d in late["due"]] == [("2160-0", True, "prob_ckd")]
