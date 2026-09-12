#!/usr/bin/env python3
"""Rank Synthea bundles as golden-patient candidates.

Looks for co-occurring CHF / CKD / T2DM, a multi-year encounter history, and a
creatinine series with real movement. Prints the top N with a one-line summary.

    python3 scripts/find_golden.py [--dir data/synthea/fhir] [--top 5] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fhir_common import (  # noqa: E402
    ACEI_ARB_RE, CREATININE_CODES, METFORMIN_RE, NSAID_RE, age_at, code_of, condition_category,
    display_of, iter_patient_bundles, parse_dt, parse_rx_display, patient_display_name, resources,
)

CKD_STAGE_LABEL = {
    "431855005": "CKD1", "431856006": "CKD2", "433144002": "CKD3", "431857002": "CKD4",
    "46177005": "ESRD", "127013003": "DMkidney",
}


def analyze(path: Path, bundle: dict) -> dict:
    patient = next(resources(bundle, "Patient"))
    now = datetime.now(timezone.utc)
    dob = patient.get("birthDate")
    deceased = bool(patient.get("deceasedDateTime"))

    cats: dict[str, list[str]] = {"chf": [], "ckd": [], "t2dm": [], "htn": []}
    active_cats: set[str] = set()
    for cond in resources(bundle, "Condition"):
        cat = condition_category(cond)
        if not cat:
            continue
        code = code_of(cond.get("code"))
        label = CKD_STAGE_LABEL.get(code, cat.upper())
        cats[cat].append(label)
        if not cond.get("abatementDateTime"):
            active_cats.add(cat)

    enc_times = sorted(
        parse_dt((e.get("period") or {}).get("start")) for e in resources(bundle, "Encounter")
        if (e.get("period") or {}).get("start")
    )
    span_years = (enc_times[-1] - enc_times[0]).days / 365.25 if len(enc_times) >= 2 else 0.0

    cr: list[tuple[datetime, float, str]] = []
    for obs in resources(bundle, "Observation"):
        code = code_of(obs.get("code"))
        if code in CREATININE_CODES and "valueQuantity" in obs:
            t = parse_dt(obs.get("effectiveDateTime"))
            if t is not None:
                cr.append((t, float(obs["valueQuantity"]["value"]), code))
    cr.sort()
    cr_vals = [v for _, v, _ in cr]
    cr_by_code = {c: sum(1 for _, _, cc in cr if cc == c) for c in CREATININE_CODES}
    cr_range = (max(cr_vals) - min(cr_vals)) if cr_vals else 0.0
    cr_max_step = max((abs(b - a) for a, b in zip(cr_vals, cr_vals[1:])), default=0.0)

    ingredients: set[str] = set()
    for mr in resources(bundle, "MedicationRequest"):
        ingredients.add(parse_rx_display(display_of(mr.get("medicationCodeableConcept"))).get("ingredient", ""))
    ing_text = " | ".join(ingredients)
    has_metformin = bool(METFORMIN_RE.search(ing_text))
    has_nsaid = bool(NSAID_RE.search(ing_text))
    has_acei = bool(ACEI_ARB_RE.search(ing_text))

    score = 0.0
    score += 3 * bool(cats["chf"]) + 3 * bool(cats["ckd"]) + 3 * bool(cats["t2dm"]) + 1 * bool(cats["htn"])
    score += 2 if len(cr_vals) >= 5 else 0
    score += 2 if cr_range >= 0.3 else 0
    score += min(span_years, 5) * 0.5
    score += 1 if has_metformin else 0
    score += 1 if has_nsaid else 0
    score -= 2 if deceased else 0  # a dead patient makes a weaker live demo

    return {
        "file": path.name,
        "name": patient_display_name(patient),
        "sex": (patient.get("gender") or "?")[0].upper(),
        "age": age_at(dob, now) if dob else None,
        "deceased": deceased,
        "conditions": {k: sorted(set(v)) for k, v in cats.items() if v},
        "active": sorted(active_cats),
        "encounters": len(enc_times),
        "enc_start": enc_times[0].date().isoformat() if enc_times else None,
        "enc_end": enc_times[-1].date().isoformat() if enc_times else None,
        "span_years": round(span_years, 1),
        "creatinine": {
            "n": len(cr_vals),
            "by_code": cr_by_code,
            "min": min(cr_vals) if cr_vals else None,
            "max": max(cr_vals) if cr_vals else None,
            "first": cr_vals[0] if cr_vals else None,
            "last": cr_vals[-1] if cr_vals else None,
            "range": round(cr_range, 2),
            "max_step": round(cr_max_step, 2),
        },
        "n_meds": len(ingredients),
        "flags": [f for f, ok in (("metformin", has_metformin), ("NSAID", has_nsaid), ("ACEi/ARB", has_acei)) if ok],
        "score": round(score, 1),
    }


def summary_line(rank: int, r: dict) -> str:
    conds = "+".join(
        "/".join(v) for k, v in r["conditions"].items()
    ) or "none of CHF/CKD/T2DM/HTN"
    cr = r["creatinine"]
    cr_txt = (
        f"Cr n={cr['n']} (2160-0: {cr['by_code'].get('2160-0', 0)}, 38483-4: {cr['by_code'].get('38483-4', 0)}) "
        f"{cr['first']}→{cr['last']} (range {cr['range']}, max step {cr['max_step']})"
        if cr["n"] else "Cr n=0"
    )
    dead = " DECEASED" if r["deceased"] else ""
    return (
        f"#{rank}  score {r['score']:>4}  {r['name']} ({r['sex']}, {r['age']}){dead}  {conds}  "
        f"enc {r['enc_start']}→{r['enc_end']} ({r['span_years']}y, {r['encounters']} visits)  "
        f"{cr_txt}  meds {r['n_meds']} {r['flags']}\n"
        f"      file={r['file']}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="data/synthea/fhir")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="emit full JSON for the top N instead of one-liners")
    args = ap.parse_args()

    fhir_dir = Path(args.dir)
    if not fhir_dir.is_dir():
        print(f"No such directory: {fhir_dir}", file=sys.stderr)
        return 1

    results = []
    for path, bundle in iter_patient_bundles(fhir_dir):
        try:
            results.append(analyze(path, bundle))
        except Exception as e:  # keep scanning; report the bad bundle
            print(f"skip {path.name}: {e}", file=sys.stderr)

    results.sort(key=lambda r: (-r["score"], -r["creatinine"]["n"], -r["span_years"]))
    top = results[: args.top]

    if args.json:
        print(json.dumps(top, indent=2))
        return 0

    triple = sum(1 for r in results if {"chf", "ckd", "t2dm"} <= set(r["conditions"]))
    print(f"Scanned {len(results)} patients in {fhir_dir}; {triple} with CHF+CKD+T2DM co-occurring.\n")
    for i, r in enumerate(top, 1):
        print(summary_line(i, r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
