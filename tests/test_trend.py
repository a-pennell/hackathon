import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ehr.trend import DATA_DIR, trend, trend_from_patient  # noqa: E402

RR = {"low": 0.6, "high": 1.2}


def obs(i, t, v, code="2160-0", status="accepted"):
    return {"id": f"obs_{i:04d}", "patient_id": "pt_t", "code": {"system": "LOINC", "value": code},
            "name": "Creatinine", "value": v, "unit": "mg/dL", "reference_range": RR,
            "effective_time": f"{t}T09:00:00-04:00", "status": status, "provenance": {"source": "fhir_import"}}


@pytest.fixture
def patient():
    return {
        "patient": {"id": "pt_t", "name": "T", "dob": "1950-01-01", "sex": "F"},
        "problems": [],
        "observations": [
            obs(1, "2026-04-10", 1.0),
            obs(2, "2026-05-14", 1.3),
            obs(3, "2026-06-25", 1.1),   # dips back in range
            obs(4, "2026-07-02", 1.5),
            obs(5, "2026-08-30", 1.8),
            obs(6, "2026-08-30", 9.9, status="proposed"),  # NLP-proposed: must be ignored
            obs(7, "2026-08-30", 50.0, code="33914-3"),    # other code: must be ignored
        ],
        "medications": [
            {"id": "med_ibuprofen", "patient_id": "pt_t", "name": "Ibuprofen", "status": "accepted",
             "code": {"system": "RxNorm", "value": "1"}, "provenance": {"source": "fhir_import"},
             "segments": [{"start": "2026-06-20", "end": None, "dose": "600 mg", "route": "PO", "frequency": "tid"}]},
            {"id": "med_lisinopril", "patient_id": "pt_t", "name": "Lisinopril", "status": "accepted",
             "code": {"system": "RxNorm", "value": "2"}, "provenance": {"source": "fhir_import"},
             "segments": [{"start": "2022-01-10", "end": "2026-07-15", "dose": "10 mg", "route": "PO", "frequency": "daily"},
                          {"start": "2026-07-15", "end": None, "dose": "20 mg", "route": "PO", "frequency": "daily"}]},
            {"id": "med_amox", "patient_id": "pt_t", "name": "Amoxicillin", "status": "accepted",
             "code": {"system": "RxNorm", "value": "3"}, "provenance": {"source": "fhir_import"},
             "segments": [{"start": "2026-05-01", "end": "2026-05-08", "dose": "500 mg", "route": "PO", "frequency": "tid"}]},
            {"id": "med_ghost", "patient_id": "pt_t", "name": "Ghost", "status": "proposed",
             "code": None, "provenance": {"source": "nlp_extraction"},
             "segments": [{"start": "2026-06-01", "end": None, "dose": "1 mg", "route": None, "frequency": None}]},
        ],
        "encounters": [], "notes": [], "links": [], "insights": [],
    }


def test_shape_and_numbers(patient):
    s = trend_from_patient(patient, "2160-0", {"start": "2026-05-01", "end": "2026-08-30"})
    assert set(s) == {"patient_id", "code", "name", "window", "n_points", "latest", "baseline", "delta_abs",
                      "delta_pct", "slope_per_week", "direction", "ref_range_crossing", "events_in_window"}
    assert s["patient_id"] == "pt_t" and s["code"] == "2160-0" and s["name"] == "Creatinine"
    assert s["window"] == {"start": "2026-05-01", "end": "2026-08-30"}
    assert s["n_points"] == 4                       # proposed + other-code excluded, April excluded
    assert s["baseline"] == {"value": 1.3, "time": "2026-05-14"}
    assert s["latest"] == {"value": 1.8, "time": "2026-08-30"}
    assert s["delta_abs"] == 0.5 and s["delta_pct"] == 38.5
    assert s["slope_per_week"] > 0
    assert s["direction"] == "rising"


def test_ref_range_crossing_is_first_out_of_range_point(patient):
    s = trend_from_patient(patient, "2160-0", {"start": "2026-04-01", "end": "2026-08-30"})
    assert s["ref_range_crossing"] == {"crossed": "high", "at": "2026-05-14"}
    s2 = trend_from_patient(patient, "2160-0", {"start": "2026-04-01", "end": "2026-04-30"})
    assert s2["ref_range_crossing"] is None and s2["direction"] == "insufficient_data"


def test_events_in_window(patient):
    s = trend_from_patient(patient, "2160-0", {"start": "2026-05-01", "end": "2026-08-30"})
    kinds = [(e["kind"], e["med_id"], e["time"]) for e in s["events_in_window"]]
    assert kinds == [
        ("med_start", "med_amox", "2026-05-01"),
        ("med_stop", "med_amox", "2026-05-08"),
        ("med_start", "med_ibuprofen", "2026-06-20"),
        ("med_dose_change", "med_lisinopril", "2026-07-15"),
    ]
    dose_change = s["events_in_window"][-1]
    assert dose_change["name"] == "Lisinopril 10 mg → 20 mg"
    assert all(e["med_id"] != "med_ghost" for e in s["events_in_window"])  # proposed meds excluded


def test_trailing_window_anchors_on_latest_observation(patient):
    s = trend_from_patient(patient, "2160-0", "90d")
    assert s["window"] == {"start": "2026-06-01", "end": "2026-08-30"}
    assert s["n_points"] == 3
    s2 = trend_from_patient(patient, "2160-0", "4w", as_of="2026-07-05")
    assert s2["window"]["end"] == "2026-07-05" and s2["n_points"] == 2


def test_no_data_window(patient):
    s = trend_from_patient(patient, "2160-0", {"start": "2020-01-01", "end": "2020-12-31"})
    assert s["n_points"] == 0 and s["direction"] == "no_data"
    assert s["latest"] is None and s["baseline"] is None and s["events_in_window"] == []
    assert trend_from_patient(patient, "9999-9", "1y", as_of="2026-01-01")["n_points"] == 0


def test_bad_window(patient):
    with pytest.raises(ValueError):
        trend_from_patient(patient, "2160-0", "soon")


@pytest.mark.skipif(not (DATA_DIR / "pt_001.json").exists(), reason="golden patient not imported")
def test_golden_patient_creatinine_rises():
    s = trend("pt_001", "38483-4", {"start": "2025-09-01", "end": "2026-09-09"})
    assert s["n_points"] >= 5
    assert s["direction"] == "rising"
    assert s["ref_range_crossing"]["crossed"] == "high"
    assert isinstance(s["events_in_window"], list)
