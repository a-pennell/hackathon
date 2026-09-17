import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.timeline import LANES, patient_timeline  # noqa: E402
from ehr.trend import DATA_DIR, load_patient  # noqa: E402


def test_timeline_folds_five_lanes_on_the_golden_chart():
    t = patient_timeline(load_patient("pt_002"), proposed_dir=DATA_DIR.parent / "proposed", today=date(2026, 9, 16))
    assert set(t["lanes"]) == set(LANES)
    lanes = {x["lane"] for x in t["items"]}
    assert {"sessions", "results", "documents", "changes"} <= lanes
    # the curated story is on the results lane, monitored series first, newest first
    res = [x for x in t["items"] if x["lane"] == "results"]
    assert res[0]["day"] == "2026-08-02" and "Hemoglobin A1c 7.9 %" in res[0]["detail"] and "out of range" in (res[0]["tag"] or "")
    # courses are changes with their clinical date, not their signing date
    assert any(x["kind"] == "course" and x["text"].startswith("Hydrochlorothiazide") and x["day"] == "2022-07-10" for x in t["items"])
    # the January note is a signed document on the day it was written
    assert any(x["lane"] == "documents" and x["tag"] == "signed" and x["day"] == "2026-01-25" for x in t["items"])
    assert t["items"] == sorted(t["items"], key=lambda x: x["day"], reverse=True)
