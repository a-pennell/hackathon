#!/usr/bin/env python3
"""Curate the second golden patient: Jeane Lueilwitz, type 2 diabetes and hypertension.

    python3 scripts/import_patient.py data/synthea/fhir/Jeane173_*.json --id pt_002
    python3 scripts/curate_pt_002.py            # rewrites data/patients/pt_002.json in place

Synthea gives a living woman with diabetes and hypertension on metformin and hydrochlorothiazide,
but buries her under its metabolic cluster (anemia, hypertriglyceridemia, metabolic syndrome,
fibromyalgia, sinusitis) and repeats the same A1c for years. This script keeps three problems,
two medication courses and the series the demo needs, and gives those series a twelve-month
story that the hand-written notes in data/notes/ quote exactly:

    A1c      6.4 (Jul 2025) -> 7.1 (Jan 2026) -> 7.9 (Aug 2026)
    BP       128/80 -> 142/88 -> 148/92 -> 154/94
    ACR      18 -> 48 mg/g            (new albuminuria)
    glucose  fasting 142 -> 168

Every value this script sets or adds carries provenance {"source": "curated"} so the chart says
what was measured by Synthea and what was written for the demo. Nothing is proposed: the chart
is the starting state the reset returns to.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "data" / "patients" / "pt_002.json"

KEEP_PROBLEMS = {"prob_0007": "Essential hypertension", "prob_0009": "Diabetes mellitus type 2", "prob_0011": "Hypertriglyceridemia"}
KEEP_MEDS = {"med_metformin_hydrochloride", "med_hydrochlorothiazide"}
KEEP_CODES = {"4548-4", "2339-0", "8480-6", "8462-4", "29463-7", "39156-5", "8867-4", "38483-4", "6299-2", "6298-4", "2947-0", "14959-1"}
UNITS = {"4548-4": ("Hemoglobin A1c", "%", {"low": 4.0, "high": 5.6}),
         "2339-0": ("Glucose", "mg/dL", {"low": 70.0, "high": 99.0}),
         "8480-6": ("Systolic blood pressure", "mm[Hg]", {"low": 90.0, "high": 120.0}),
         "8462-4": ("Diastolic blood pressure", "mm[Hg]", {"low": 60.0, "high": 80.0}),
         "29463-7": ("Body weight", "kg", None),
         "14959-1": ("Urine albumin/creatinine ratio", "mg/g", {"low": 0.0, "high": 30.0}),
         "6298-4": ("Potassium", "mmol/L", {"low": 3.5, "high": 5.1}),
         "38483-4": ("Creatinine (whole blood)", "mg/dL", {"low": 0.6, "high": 1.2})}

# (code, date) -> value: existing points are overwritten, missing ones are added on that date.
STORY = {
    ("4548-4", "2017-07-23"): 5.7, ("4548-4", "2019-07-28"): 5.9, ("4548-4", "2020-11-15"): 6.0,
    ("4548-4", "2021-05-23"): 6.1, ("4548-4", "2021-05-30"): 6.2, ("4548-4", "2021-06-06"): 6.2, ("4548-4", "2021-07-04"): 6.3,
    ("4548-4", "2022-07-10"): 7.5, ("4548-4", "2023-02-12"): 6.8, ("4548-4", "2023-07-16"): 6.3, ("4548-4", "2024-07-21"): 6.2,
    ("4548-4", "2025-07-27"): 6.4, ("4548-4", "2026-01-25"): 7.1, ("4548-4", "2026-08-02"): 7.9,
    ("8480-6", "2024-07-21"): 134.0, ("8462-4", "2024-07-21"): 84.0,
    ("8480-6", "2025-07-27"): 128.0, ("8462-4", "2025-07-27"): 80.0,
    ("8480-6", "2026-01-25"): 142.0, ("8462-4", "2026-01-25"): 88.0,
    ("8480-6", "2026-07-11"): 148.0, ("8462-4", "2026-07-11"): 92.0,
    ("8480-6", "2026-08-02"): 154.0, ("8462-4", "2026-08-02"): 94.0,
    ("2339-0", "2025-07-27"): 112.0, ("2339-0", "2026-01-25"): 142.0, ("2339-0", "2026-08-02"): 168.0,
    ("14959-1", "2025-07-27"): 18.0, ("14959-1", "2026-08-02"): 48.0,
    ("29463-7", "2025-07-27"): 83.5, ("29463-7", "2026-01-25"): 84.2, ("29463-7", "2026-08-02"): 85.6,
    ("6298-4", "2026-08-02"): 4.1, ("38483-4", "2026-08-02"): 0.8,
}
LAST_VISIT = "2026-08-02"
DROP_DATES = {("4548-4", "2023-02-19")}          # a duplicate A1c a week after the first
PRIOR_NOTES = ["data/notes/note_demo_101.json"]   # signed before the demo starts; note_demo_102 is the one that arrives
NEW_ENCOUNTERS = [{"id": "enc_c001", "time": "2026-01-25T09:30:00-05:00", "type": "encounter for check up", "summary": "Follow-up, diabetes and hypertension"}]
EXTRA_MONITORS = [("LOINC:14959-1", "prob_0009"), ("LOINC:6298-4", "prob_0007"), ("LOINC:38483-4", "prob_0007")]


def main() -> int:
    chart = json.loads(CHART.read_text())
    pid = chart["patient"]["id"]
    chart["problems"] = [p for p in chart["problems"] if p["id"] in KEEP_PROBLEMS]
    chart["medications"] = [m for m in chart["medications"] if m["id"] in KEEP_MEDS]
    keep_ids = set(KEEP_PROBLEMS) | KEEP_MEDS
    chart["links"] = [l for l in chart["links"]
                      if (l["from"] in keep_ids or l["from"].startswith("LOINC:")) and l["to"] in keep_ids]

    obs = [o for o in chart["observations"] if o["code"]["value"] in KEEP_CODES and (o["code"]["value"], o["effective_time"][:10]) not in DROP_DATES]
    by_key = {(o["code"]["value"], o["effective_time"][:10]): o for o in obs}
    n = 0
    for (code, day), value in STORY.items():
        o = by_key.get((code, day))
        if o:
            o["value"] = value
            o["provenance"] = {"source": "curated"}
        else:
            n += 1
            name, unit, rr = UNITS[code]
            o = {"id": f"obs_c{n:04d}", "patient_id": pid, "code": {"system": "LOINC", "value": code}, "name": name, "value": value,
                 "unit": unit, "reference_range": rr, "effective_time": f"{day}T09:15:00-05:00", "status": "accepted",
                 "provenance": {"source": "curated"}}
            obs.append(o)
            by_key[(code, day)] = o
    obs.sort(key=lambda o: o["effective_time"])
    chart["observations"] = obs

    # The story's last charted visit is the 2 Aug labs; the note that arrives brings the next one.
    chart["encounters"] = [e for e in chart["encounters"] if e["time"][:10] <= LAST_VISIT]
    kept_enc = {e["id"] for e in chart["encounters"]}
    chart["notes"] = [n for n in chart["notes"] if not n.get("encounter_id") or n["encounter_id"] in kept_enc]
    chart["observations"] = [o for o in chart["observations"] if o["effective_time"][:10] <= LAST_VISIT]
    have = {e["id"] for e in chart["encounters"]}
    for e in NEW_ENCOUNTERS:
        if e["id"] not in have:
            chart["encounters"].append({**e, "patient_id": pid})
    chart["encounters"].sort(key=lambda e: e["time"])
    # Dr. Chen's January note is on the chart, signed: the reader's last look, which the overview's "since" uses.
    for f in PRIOR_NOTES:
        note = json.loads((ROOT / f).read_text())["note"]
        if not any(n["id"] == note["id"] for n in chart["notes"]):
            chart["notes"].append({**note, "status": "signed", "review": {"by": note["author"], "at": note["time"], "decision": "accepted", "reason_code": None, "reason": None}})
    chart["notes"].sort(key=lambda n: n["time"])

    have_links = {(l["from"], l["to"]) for l in chart["links"]}
    k = 0
    for frm, to in EXTRA_MONITORS:
        if (frm, to) not in have_links:
            k += 1
            chart["links"].append({"id": f"lnk_c{k:04d}", "from": frm, "to": to, "type": "monitors", "status": "accepted",
                                   "provenance": {"source": "curated"}, "created_at": "2026-09-15T00:00:00-05:00"})
    chart["insights"] = []
    chart.pop("documents", None)
    chart.pop("orders", None)
    CHART.write_text(json.dumps(chart, indent=2, ensure_ascii=False))
    print(f"{pid}: {len(chart['problems'])} problems, {len(chart['medications'])} courses, {len(chart['observations'])} observations, "
          f"{len(chart['encounters'])} encounters, {len(chart['links'])} links ({n} observations added)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
