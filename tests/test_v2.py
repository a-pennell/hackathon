import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.trend import load_patient  # noqa: E402
from v2.monitor import attest, manifest, problem_list, problem_view, unattested  # noqa: E402

PROPOSED = ROOT / "data" / "proposed"


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
