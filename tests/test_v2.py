import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.trend import load_patient  # noqa: E402
from v2.monitor import problem_list, problem_view  # noqa: E402

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
    assert set(a) == {"happening", "means", "changed", "doing", "uncertain", "next", "change_course"}
    assert a["happening"] and a["happening"][0]["ids"]
    assert a["means"]["text"] and a["means"]["cites"]
    assert a["changed"]["lines"] and all(d["acknowledged"] is False for d in a["changed"]["detected"])
    assert "tripwires" in a["change_course"] and a["change_course"]["tripwires"]
    assert v["problem"]["standing"] == "off_course"
