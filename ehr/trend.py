"""TrendSummary — docs/patient-model-schema.md §9.

    trend(patient_id, loinc_code, window) -> dict

Computed on demand from accepted observations + medication segments. Never stored.
The reasoning layer consumes this, never raw value arrays.

`window` is either
  - {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}  (inclusive dates), or
  - a trailing span string like "90d", "6m", "1y", "3w" measured back from `as_of`
    (default: the patient's latest observation of that code).

CLI:  python3 -m ehr.trend pt_001 38483-4 2025-09-01 2026-09-09
      python3 -m ehr.trend pt_001 38483-4 1y
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "patients"

# |delta_pct| below this is reported as "stable".
STABLE_PCT = 10.0

SPAN_RE = re.compile(r"^(\d+)\s*([dwmy])$", re.I)


# --------------------------------------------------------------------------- IO

def load_patient(patient_id: str, data_dir: str | Path = DATA_DIR) -> dict:
    path = Path(data_dir) / f"{patient_id}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ pure helpers

def _day(ts: str | None) -> str | None:
    """ISO timestamp/date -> 'YYYY-MM-DD' (all our timestamps are ISO 8601)."""
    return ts[:10] if ts else None


def _resolve_window(window, as_of: str | None) -> tuple[str, str]:
    if isinstance(window, dict):
        return _day(window["start"]), _day(window["end"])
    if isinstance(window, (tuple, list)) and len(window) == 2:
        return _day(window[0]), _day(window[1])
    if isinstance(window, str):
        m = SPAN_RE.match(window.strip())
        if not m:
            raise ValueError(f"bad window {window!r}; use {{start,end}} or e.g. '90d', '6m', '1y'")
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n
        if not as_of:
            raise ValueError("trailing window needs as_of (no observations to anchor on)")
        end = date.fromisoformat(_day(as_of))
        return (end - timedelta(days=days)).isoformat(), end.isoformat()
    raise ValueError(f"bad window {window!r}")


def _slope_per_week(points: list[dict]) -> float | None:
    """Least-squares slope of value vs. time (weeks since first point)."""
    if len(points) < 2:
        return None
    t0 = date.fromisoformat(_day(points[0]["effective_time"]))
    xs = [(date.fromisoformat(_day(p["effective_time"])) - t0).days / 7.0 for p in points]
    ys = [float(p["value"]) for p in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(sxy / sxx, 4)


def _outside(value: float, rr: dict | None) -> str | None:
    if not rr:
        return None
    if rr.get("high") is not None and value > rr["high"]:
        return "high"
    if rr.get("low") is not None and value < rr["low"]:
        return "low"
    return None


def _ref_range_crossing(points: list[dict]) -> dict | None:
    """First point in the window that sits outside its reference range.

    {"crossed": "high"|"low", "at": "YYYY-MM-DD"}; None if never outside (or no range).
    """
    for p in points:
        side = _outside(float(p["value"]), p.get("reference_range"))
        if side:
            return {"crossed": side, "at": _day(p["effective_time"])}
    return None


def _med_events(medications: list[dict], start: str, end: str) -> list[dict]:
    """Every med start / stop / dose change whose date falls inside [start, end]."""
    events = []

    def add(kind, med, seg_time, label):
        if seg_time and start <= seg_time <= end:
            events.append({"kind": kind, "med_id": med["id"], "name": label, "time": seg_time})

    for med in medications:
        if med.get("status") != "accepted":
            continue
        segs = med.get("segments") or []
        for i, seg in enumerate(segs):
            label = f"{med['name']} {seg.get('dose') or ''}".strip()
            prev = segs[i - 1] if i > 0 else None
            if prev and prev.get("end") == seg.get("start"):
                add("med_dose_change", med, seg.get("start"),
                    f"{med['name']} {prev.get('dose') or '?'} → {seg.get('dose') or '?'}")
            else:
                add("med_start", med, seg.get("start"), label)
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if seg.get("end") and not (nxt and nxt.get("start") == seg.get("end")):
                add("med_stop", med, seg.get("end"), label)
    events.sort(key=lambda e: (e["time"], e["kind"]))
    return events


# ------------------------------------------------------------------------- core

def trend_from_patient(patient: dict, loinc_code: str, window, as_of: str | None = None) -> dict:
    """Pure version: takes the loaded per-patient JSON instead of an id."""
    pid = patient["patient"]["id"]
    series = sorted(
        (o for o in patient.get("observations", [])
         if o.get("status") == "accepted"
         and o.get("code", {}).get("system") == "LOINC"
         and o.get("code", {}).get("value") == loinc_code
         and isinstance(o.get("value"), (int, float))),
        key=lambda o: o["effective_time"],
    )
    name = series[-1]["name"] if series else None
    anchor = as_of or (series[-1]["effective_time"] if series else None)
    start, end = _resolve_window(window, anchor)

    points = [o for o in series if start <= _day(o["effective_time"]) <= end]
    summary = {
        "patient_id": pid,
        "code": loinc_code,
        "name": name,
        "window": {"start": start, "end": end},
        "n_points": len(points),
        "latest": None,
        "baseline": None,
        "delta_abs": None,
        "delta_pct": None,
        "slope_per_week": None,
        "direction": "no_data",
        "ref_range_crossing": None,
        "events_in_window": _med_events(patient.get("medications", []), start, end),
    }
    if not points:
        return summary

    first, last = points[0], points[-1]
    summary["latest"] = {"value": last["value"], "time": _day(last["effective_time"])}
    summary["baseline"] = {"value": first["value"], "time": _day(first["effective_time"])}
    summary["ref_range_crossing"] = _ref_range_crossing(points)
    if len(points) < 2:
        summary["direction"] = "insufficient_data"
        return summary

    delta = float(last["value"]) - float(first["value"])
    summary["delta_abs"] = round(delta, 3)
    if float(first["value"]) != 0:
        summary["delta_pct"] = round(delta / float(first["value"]) * 100.0, 1)
    summary["slope_per_week"] = _slope_per_week(points)
    pct = summary["delta_pct"]
    if pct is None:
        summary["direction"] = "rising" if delta > 0 else "falling" if delta < 0 else "stable"
    elif pct >= STABLE_PCT:
        summary["direction"] = "rising"
    elif pct <= -STABLE_PCT:
        summary["direction"] = "falling"
    else:
        summary["direction"] = "stable"
    return summary


def trend(patient_id: str, loinc_code: str, window, as_of: str | None = None,
          data_dir: str | Path = DATA_DIR) -> dict:
    """TrendSummary for one LOINC series of one patient over a window (schema §9)."""
    return trend_from_patient(load_patient(patient_id, data_dir), loinc_code, window, as_of)


# -------------------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(__doc__, file=sys.stderr)
        return 2
    pid, code = argv[0], argv[1]
    window = {"start": argv[2], "end": argv[3]} if len(argv) == 4 else argv[2]
    print(json.dumps(trend(pid, code, window), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
