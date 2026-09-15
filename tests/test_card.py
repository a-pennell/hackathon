import copy
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.card import problem_card  # noqa: E402
from tests.test_reason import link, obs, patient as reason_patient  # noqa: E402,F401

TODAY = date(2026, 8, 31)
WIN = {"start": "2026-05-01", "end": "2026-08-31"}


def test_card_is_a_view_with_cited_representation(reason_patient, tmp_path):
    c = problem_card(reason_patient, "prob_ckd", WIN, proposed_dir=tmp_path, today=TODAY)
    assert c["kind"] == "concern" and c["epistemic"]["value"] == "working"      # no code on the chart
    labels = [q["label"] for q in c["qualifiers"]]
    assert "chronic" in labels and "worsening" in labels                         # onset 2021; creatinine rising above range
    rep = c["representation"]
    assert rep["tier"] == "proposed" and rep["source"] == "computed"
    assert rep["text"].startswith("76F. Creatinine 1.3 → 1.8 between 14 May 2026 and 30 Aug 2026")   # HTN has no monitored series, so it says nothing here
    assert "Ibuprofen 600 mg since 20 Jun 2026, recorded as a suspected cause." in rep["text"]
    assert "From the note of 30 Aug 2026: “nausea”." in rep["text"]
    known = {x["id"] for k in ("problems", "observations", "medications", "notes", "links") for x in reason_patient[k]}
    assert rep["cites"] and all(i in known for i in rep["cites"])
    assert c["assessment"] is None                                               # the system never writes one
    assert [x["kind"] for x in c["supporting"]] == ["result", "medication", "finding"]
    assert c["supporting"][2]["source"] == "clinician-documented"
    assert c["doesnt_fit"] == [] and c["expected"] is None and c["plan"] == []


def test_doesnt_fit_rules(reason_patient, tmp_path):
    p = copy.deepcopy(reason_patient)
    # a second assay for the same analyte on the same day, wildly different
    p["observations"].append(obs(20, "2026-08-30", 4.2, code="38483-4", name="Creatinine (whole blood)"))
    p["links"].append(link(20, "LOINC:38483-4", "prob_ckd", "monitors"))
    # a dip while ibuprofen continued
    p["observations"].append(obs(21, "2026-07-20", 1.0))
    # metformin with an eGFR under 30
    p["observations"].append(obs(22, "2026-08-30", 22.0, code="33914-3", name="eGFR"))
    p["links"].append(link(21, "LOINC:33914-3", "prob_ckd", "monitors"))
    c = problem_card(p, "prob_ckd", WIN, proposed_dir=tmp_path, today=TODAY)
    kinds = {x["kind"]: x for x in c["doesnt_fit"]}
    assert set(kinds) == {"discordance", "counter_trend", "contradiction"}
    assert kinds["discordance"]["valence"] == "against" and set(kinds["discordance"]["ids"]) == {"obs_0003", "obs_0020"}
    assert kinds["counter_trend"]["valence"] == "unexplained" and "while Ibuprofen continued" in kinds["counter_trend"]["text"]
    assert kinds["contradiction"]["text"] == "Metformin 500 mg still active with eGFR 22"


def test_expectation_from_a_stopped_cause(reason_patient, tmp_path):
    p = copy.deepcopy(reason_patient)
    p["medications"][0]["segments"][0]["end"] = "2026-08-20"                    # ibuprofen stopped
    c = problem_card(p, "prob_ckd", WIN, proposed_dir=tmp_path, today=TODAY)
    e = c["expected"]
    assert e["statement"] == "Creatinine falling within 14 days of stopping Ibuprofen"
    assert e["code"] == "2160-0" and e["direction"] == "falling" and e["by"] == "2026-09-03"
    assert e["ref_value"] == 1.5 and e["target_value"] == 1.12                 # the value at the stop, and a quarter's fall: the corridor
    assert e["status"] == "not_yet"                                              # 1.8 on 30 Aug is above 1.5 at the stop, but the horizon is open
    assert e["tier"] == "proposed" and e["reconsider_if"][0]["trigger"] == "no fall in Creatinine by 3 Sep 2026"
    # past the horizon with no fall: missed, and it shows up as a qualifier and under doesn't fit
    late = problem_card(p, "prob_ckd", WIN, proposed_dir=tmp_path, today=date(2026, 9, 10))
    assert late["expected"]["status"] == "missed"
    assert "unexpected" in [q["label"] for q in late["qualifiers"]]
    assert any(x["kind"] == "expectation" for x in late["doesnt_fit"])
    # a result after the stop that fell: met
    p["observations"].append(obs(30, "2026-08-31", 1.2))
    met = problem_card(p, "prob_ckd", WIN, proposed_dir=tmp_path, today=TODAY)
    assert met["expected"]["status"] == "met" and "obs_0030" in met["expected"]["ids"]


def test_plan_reads_signed_orders(reason_patient, tmp_path):
    p = copy.deepcopy(reason_patient)
    p["orders"] = [{"id": "ord_ckd_01", "patient_id": "pt_t", "problem_id": "prob_ckd", "kind": "medication_change", "name": "Stop ibuprofen",
                    "detail": "", "code": None, "med_id": "med_ibuprofen", "change": "stop", "dose": None, "audience": None, "status": "accepted",
                    "provenance": {"source": "ordering", "model": "x", "from_insight": "ins_1", "evidence": ["med_ibuprofen"]}, "created_at": "2026-08-30T10:00:00-04:00"},
                   {"id": "ord_ckd_02", "patient_id": "pt_t", "problem_id": "prob_ckd", "kind": "lab", "name": "Creatinine", "detail": "in one week",
                    "code": {"system": "LOINC", "value": "2160-0"}, "med_id": None, "change": None, "dose": None, "audience": None, "status": "accepted",
                    "provenance": {"source": "ordering", "model": "x", "from_insight": "ins_1", "evidence": []}, "created_at": "2026-08-30T10:00:00-04:00"}]
    c = problem_card(p, "prob_ckd", WIN, proposed_dir=tmp_path, today=TODAY)
    assert [(x["plan_kind"], x["text"]) for x in c["plan"]] == [("therapeutic", "stop Ibuprofen"), ("diagnostic", "Creatinine")]
