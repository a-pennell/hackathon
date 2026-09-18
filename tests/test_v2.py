import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.trend import load_patient  # noqa: E402
from v2.monitor import attest, manifest, problem_list, problem_view, unattested  # noqa: E402

from ehr.trend import DATA_DIR  # noqa: E402

PROPOSED = DATA_DIR.parent / "proposed"  # the clean copy built by conftest.py, never the live demo state


def test_gate_sorts_problems_by_standing_on_jeane():
    out = problem_list(load_patient("pt_002"), proposed_dir=PROPOSED, today=date(2026, 9, 16))
    by = {r["id"]: r for r in out["problems"]}
    assert by["prob_0007"]["standing"] == "off_course" and by["prob_0009"]["standing"] == "off_course"
    assert by["prob_0011"]["standing"] == "unmonitored"
    assert [r["standing"] for r in out["problems"]] == sorted((r["standing"] for r in out["problems"]), key=["off_course", "watch", "good", "unmonitored"].index)
    assert out["counts"]["off_course"] == 2 and "here_for" in out


def test_seven_answers_are_all_present_for_hypertension():
    v = problem_view(load_patient("pt_002"), "prob_0007", proposed_dir=PROPOSED, today=date(2026, 9, 16))
    a = v["answers"]
    assert {"happening", "means", "changed", "doing", "uncertain", "next", "change_course"} <= set(a)  # the seven; options and guidelines ride with "next"
    assert a["happening"] and a["happening"][0]["ids"]
    assert a["means"]["text"] and a["means"]["cites"]
    assert a["changed"]["lines"] and all(d["acknowledged"] is False for d in a["changed"]["detected"])
    assert "tripwires" in a["change_course"] and a["change_course"]["tripwires"]
    assert v["problem"]["standing"] == "off_course"


def test_manifest_and_attestation_on_a_scratch_visit(tmp_path):
    from tests.test_draft import _visit
    from ehr.trend import load_patient as lp
    from ehr.extract import save_patient
    d = _visit(tmp_path)
    p = lp("pt_002", d)
    m = manifest(p, "enc_c002", proposed_dir=d.parent / "proposed")
    kinds = {g["kind"]: g for g in m}
    assert kinds["problems"]["count"] == 2 and kinds["causes"]["count"] >= 1 and kinds["rejected"]["count"] == 1
    assert kinds["plans"]["count"] >= 9 and kinds["courses"]["count"] >= 3
    assert all(not it["attested"] for g in m if g["kind"] != "rejected" for it in g["items"])  # None counts as not attested
    assert unattested(p) > 0
    n = attest(p, "enc_c002", "doc_enc_c002_note")
    save_patient(p, d)
    assert n > 0 and unattested(lp("pt_002", d)) == 0
    m2 = manifest(lp("pt_002", d), "enc_c002", proposed_dir=d.parent / "proposed")
    assert all(it["attested"] in (True, None) for g in m2 for it in g["items"])


def test_guidelines_and_options_on_the_golden_chart():
    v = problem_view(load_patient("pt_002"), "prob_0009", proposed_dir=PROPOSED, today=date(2026, 9, 17))
    rules = {g["id"]: g for g in v["answers"]["guidelines"]}
    assert rules["dm_acr_acei"]["status"] == "gap" and rules["dm_statin"]["status"] == "gap" and rules["dm_acr_acei"]["action"]["kind"] == "therapeutic"
    assert all(g["source"] for g in v["answers"]["guidelines"])
    opts = {o["id"]: o for o in v["answers"]["options"]}
    assert opts["metformin_taken"]["effect"] == {"low": -1.2, "high": -0.7} and opts["metformin_taken"]["points"][0]["low"] == 7.9
    assert v["answers"]["change_course"]["projection"] is None  # nothing on the plan yet moves the value


def test_current_plan_projection_after_the_visit(tmp_path):
    from tests.test_draft import _visit
    from ehr.trend import load_patient as lp
    d = _visit(tmp_path)
    v = problem_view(lp("pt_002", d), "prob_0007", proposed_dir=d.parent / "proposed", today=date(2026, 9, 17))
    pj = v["answers"]["change_course"]["projection"]
    assert set(pj["options"]) == {"stop_nsaid", "add_acei"} and pj["reaches_goal_by"] is not None
    assert pj["points"][0]["low"] == 150.0 and pj["at_full_effect"]["high"] < 140
    on = {o["id"]: o["on_plan"] for o in v["answers"]["options"]}
    assert on["stop_nsaid"] and on["add_acei"] and not on["sodium"]
    rules = {g["id"]: g["status"] for g in v["answers"]["guidelines"]}
    assert rules["htn_nsaid"] if "htn_nsaid" in rules else True
    assert rules["htn_second_agent"] == "covered" and rules["acei_bmp"] == "covered"
    row = next(r for r in problem_list(lp("pt_002", d), proposed_dir=d.parent / "proposed", today=date(2026, 9, 17))["problems"] if r["id"] == "prob_0007")
    assert "projected under 140" in row["forecast"]


def test_willie_kidney_guidelines_and_no_projection_for_a_low_pressure():
    p = load_patient("pt_001")
    v = problem_view(p, "prob_0057", proposed_dir=PROPOSED, today=date(2026, 9, 17))
    rules = {g["id"]: g for g in v["answers"]["guidelines"]}
    assert rules["ckd_metformin"]["status"] == "gap" and rules["ckd_nephrology"]["status"] == "gap"
    assert rules["ckd_metformin"]["source"].startswith("FDA")
    rows = {r["name"]: r for r in problem_list(p, proposed_dir=PROPOSED, today=date(2026, 9, 17))["problems"]}
    assert rows["Essential hypertension"]["forecast"] is None  # his pressure is low; lowering it further is not a projection


def test_a_drug_started_at_this_visit_sets_an_expectation_the_reference_range_cannot_express(tmp_path):
    """Starting an ACE inhibitor is expected to push creatinine and potassium the wrong way. How far is too far is set
    from this patient's own baseline, so the threshold can fall inside the lab's range (creatinine) or outside it
    (potassium) — which is exactly what a range-only chart gets wrong in both directions."""
    from datetime import date as _date
    from tests.test_draft import _visit
    from ehr.trend import load_patient as lp
    from v2.simulate import expectations
    d = _visit(tmp_path)
    p = lp("pt_002", d)
    moves = {m["id"]: m for m in expectations(p, "prob_0007", today=_date(2026, 9, 17))}
    assert set(moves) == {"acei_creatinine", "acei_potassium"}

    cr = moves["acei_creatinine"]
    assert cr["baseline"]["value"] == 0.8 and cr["limit"] == 1.04          # 30% above this patient's own baseline
    assert cr["inside_range"] and cr["reference_range"]["high"] == 1.2      # ...and still "normal" to the lab
    assert "the range will not flag this, the baseline will" in cr["note"]
    assert "lisinopril" in cr["trigger"]["text"].lower()
    assert cr["tested_by"]["text"] == "BMP in 2 weeks"                      # the plan already orders what answers it
    assert cr["counter"] and "NSAID" in cr["counter"]                       # the ibuprofen stop pushes the other way
    assert "Bakris" in cr["source"] and cr["observed"] is None

    k = moves["acei_potassium"]
    assert k["limit"] == 5.5 and not k["inside_range"] and k["reference_range"]["high"] == 5.1
    assert "still expected here" in k["note"]

    # it is an expectation of this problem's drug, not a global banner: a problem the drug does not treat has none
    assert expectations(p, "prob_0009", today=_date(2026, 9, 17)) == []
    # and it lapses once the answer is no longer ahead of us
    assert expectations(p, "prob_0007", today=_date(2027, 3, 1)) == []


def test_a_live_expectation_replaces_the_standing_tripwire_and_is_answered_by_the_follow_up(tmp_path):
    """Two halves of one claim. The standing rule watches for a ±25% move, which would flag the very rise the ACE
    inhibitor is expected to cause; while the expectation is live it is the threshold instead. Then the BMP lands and
    the expectation is tested against it."""
    from datetime import date as _date
    from tests.test_draft import _visit
    from ehr.trend import load_patient as lp
    from ehr.extract import save_patient
    from v2.monitor import problem_view
    from v2.simulate import expectations
    d = _visit(tmp_path)
    PROPOSED = d.parent / "proposed"

    cc = problem_view(lp("pt_002", d), "prob_0007", proposed_dir=PROPOSED, today=_date(2026, 9, 17))["answers"]["change_course"]
    cr = next(t for t in cc["tripwires"] if t["code"] == "38483-4")
    assert cr["threshold"] == "above 1.04 mg/dL, or still rising after 4 weeks" and "Lisinopril" in cr["set_by"]
    assert "25%" not in cr["threshold"]  # the standing rule would have fired on a rise the plan predicts
    assert cr["state"] == "as expected"

    # the basic metabolic panel comes back two weeks later, as the plan ordered
    p = lp("pt_002", d)
    p["observations"].append({"id": "obs_followup_cr", "patient_id": "pt_002", "name": "Creatinine (whole blood)",
                              "code": {"system": "LOINC", "value": "38483-4"}, "value": 0.9, "unit": "mg/dL",
                              "effective_time": "2026-09-29T09:15:00-05:00", "reference_range": {"low": 0.6, "high": 1.2},
                              "status": "accepted", "provenance": {"source": "curated", "followup": True}})
    save_patient(p, d)
    answered = next(m for m in expectations(lp("pt_002", d), "prob_0007", today=_date(2026, 9, 30)) if m["id"] == "acei_creatinine")
    assert answered["observed"] == {"value": 0.9, "time": "2026-09-29", "id": "obs_followup_cr", "status": "within"}
