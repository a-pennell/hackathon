import copy
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.overview import _since, clusters, patient_overview  # noqa: E402
from tests.test_reason import link, obs, patient as reason_patient  # noqa: E402,F401

TODAY = date(2026, 8, 31)


def with_visits(p):
    p = copy.deepcopy(p)
    p["encounters"] = [
        {"id": "enc_1", "patient_id": "pt_t", "time": "2026-05-14T09:00:00-04:00", "type": "encounter for check up", "summary": "routine"},
        {"id": "enc_2", "patient_id": "pt_t", "time": "2026-08-25T09:00:00-04:00", "type": "telemedicine consultation with patient", "summary": "call"},
        {"id": "enc_3", "patient_id": "pt_t", "time": "2026-08-30T09:00:00-04:00", "type": "office visit", "summary": "today"},
    ]
    return p


def test_since_is_the_last_routine_visit_at_least_two_weeks_before_the_newest(reason_patient):
    p = with_visits(reason_patient)
    s = _since(p, TODAY)
    assert s["date"] == "2026-05-14" and s["encounter_id"] == "enc_1"          # the telemedicine call five days earlier does not count
    assert s["baseline"] == "2026-02-13"                                        # no routine visit before it: trends start 90 days earlier
    p["encounters"] = p["encounters"][2:]
    assert _since(p, TODAY)["date"] == "2026-06-02"                              # nothing earlier: 90 days


def test_problems_with_identical_monitors_are_one_concern(reason_patient):
    p = copy.deepcopy(reason_patient)
    p["problems"].append({"id": "prob_ckd_old", "patient_id": "pt_t", "name": "CKD stage 2", "code": None, "status": "active",
                          "onset_date": "2019-01-01", "resolved_date": None, "provenance": {"source": "fhir_import"}})
    p["links"].append(link(9, "LOINC:2160-0", "prob_ckd_old", "monitors"))
    cl = {c["problem"]["id"]: c for c in clusters(p)}
    assert set(cl) == {"prob_ckd", "prob_htn"}                                   # the newer entry represents the pair
    assert [m["id"] for m in cl["prob_ckd"]["members"]] == ["prob_ckd_old"] and cl["prob_ckd"]["codes"] == ["2160-0"]
    o = patient_overview(with_visits(p), proposed_dir=Path("/nonexistent"), today=TODAY)
    ckd = next(c for c in o["concerns"] if c["id"] == "prob_ckd")
    assert ckd["members"] == [{"id": "prob_ckd_old", "name": "CKD stage 2"}]
    assert not any(c["id"] == "prob_ckd_old" for c in o["concerns"])


def test_changes_are_ranked_by_meaning(reason_patient, tmp_path, monkeypatch):
    monkeypatch.setattr("ehr.overview.TOP_CHANGES", 10)                          # see the whole ranked list, not the top five
    p = with_visits(reason_patient)
    p["medications"][0]["segments"][0]["end"] = "2026-08-30"                    # ibuprofen (suspected cause) stopped today
    p["medications"][1]["segments"] = [{"start": "2020-01-01", "end": "2026-08-28", "dose": "500 mg", "route": "PO", "frequency": "bid"},
                                       {"start": "2026-08-28", "end": None, "dose": "1000 mg", "route": "PO", "frequency": "bid"}]  # metformin, unlinked
    q = tmp_path / "pt_t"
    q.mkdir()
    (q / "note_0007.json").write_text(json.dumps({
        "patient_id": "pt_t", "note_id": "note_0007", "model": "x", "extracted_at": "2026-08-30T10:00:00-04:00",
        "proposed": {"problems": [{"id": "prob_n_01", "patient_id": "pt_t", "name": "CKD stage 4", "code": None, "status": "proposed", "onset_date": None,
                                   "resolved_date": None, "provenance": {"source": "nlp_extraction", "note_id": "note_0007", "quote": "CKD progressing", "confidence": 0.6}}],
                     "observations": [], "medications": [], "links": []},
        "review_hints": {"prob_n_01": "supersedes prob_ckd; on accept, consider resolving it"}, "rejected": []}))
    o = patient_overview(p, proposed_dir=tmp_path, today=TODAY)
    kinds = [(l["rank"], l["kind"]) for l in o["changes"]]
    assert kinds[:4] == [(2, "restage"), (3, "medication"), (3, "medication"), (4, "trend")]
    assert [l["text"] for l in o["changes"][1:3]] == ["Ibuprofen 600 mg started, 20 Jun", "Ibuprofen 600 mg stopped, 30 Aug"]   # both inside the window
    assert o["changes"][2]["ids"] == ["med_ibuprofen"]
    assert o["changes"][3]["text"] == "Creatinine 1.3 → 1.8" and o["changes"][3]["tag"] == "worsening"
    assert any(l["kind"] == "queue" and l["rank"] == 8 for l in o["changes"])
    tail = [l for l in o["changes"] if l["kind"] == "medication" and l["problem_name"] == "Medications"]
    assert tail and tail[0]["text"] == "Metformin 500 mg → 1000 mg, 28 Aug"         # a dose change nobody is linked to still shows, last
    ckd = o["concerns"][0]
    assert ckd["id"] == "prob_ckd" and ckd["pending"] == 1 and ckd["action"] == {"label": "Review 1 change", "kind": "review"}
    assert "worsening" in ckd["qualifiers"]
    htn = next(c for c in o["concerns"] if c["id"] == "prob_htn")
    assert htn["action"] is None                                                  # nothing owed: no button


def test_pending_loops_follow_the_loop_rule(reason_patient):
    p = with_visits(reason_patient)
    p["orders"] = [
        {"id": "ord_1", "patient_id": "pt_t", "problem_id": "prob_ckd", "kind": "lab", "name": "Creatinine", "detail": "", "code": {"system": "LOINC", "value": "2160-0"},
         "med_id": None, "change": None, "dose": None, "audience": None, "status": "accepted", "provenance": {"source": "ordering", "model": "x", "evidence": []},
         "created_at": "2026-08-30T10:00:00-04:00", "ordered_at": "2026-08-30T10:00:00-04:00"},
        {"id": "ord_2", "patient_id": "pt_t", "problem_id": "prob_ckd", "kind": "referral", "name": "Nephrology", "detail": "", "code": None, "med_id": None,
         "change": None, "dose": None, "audience": "nephrology", "status": "accepted", "provenance": {"source": "ordering", "model": "x", "evidence": []},
         "created_at": "2026-08-30T10:00:00-04:00", "ordered_at": "2026-08-30T10:00:00-04:00"},
    ]
    o = patient_overview(p, proposed_dir=Path("/nonexistent"), today=TODAY)
    assert [(x["kind"], x["status"]) for x in o["pending"]] == [("lab", "awaiting"), ("referral", "awaiting")]
    p["observations"].append(obs(40, "2026-08-31", 1.6))                         # the result lands: the loop closes
    o = patient_overview(p, proposed_dir=Path("/nonexistent"), today=TODAY)
    assert [(x["kind"], x["status"]) for x in o["pending"]] == [("referral", "awaiting"), ("lab", "resulted")]


def test_a_change_on_two_concerns_goes_to_the_higher_ranked_one(reason_patient):
    p = with_visits(reason_patient)
    p["medications"][0]["segments"][0]["end"] = "2026-08-30"                    # ibuprofen stopped; a suspected cause on CKD
    p["problems"].append({"id": "prob_knee", "patient_id": "pt_t", "name": "Aching knee", "code": None, "status": "active",
                          "onset_date": "2026-06-01", "resolved_date": None, "provenance": {"source": "fhir_import"}})
    p["links"].append(link(30, "med_ibuprofen", "prob_knee", "treats"))         # ...and it treats the knee, which sorts first by name
    o = patient_overview(p, proposed_dir=Path("/nonexistent"), today=TODAY)
    stop = next(l for l in o["changes"] if l["text"] == "Ibuprofen 600 mg stopped, 30 Aug")
    assert stop["problem_id"] == "prob_ckd"                                     # CKD is worsening, so it ranks above the knee
    assert sum(1 for l in o["changes"] if l["text"] == stop["text"]) == 1
