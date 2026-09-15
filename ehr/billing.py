"""Visit coding, derived from decisions: diagnosis codes and the E/M level by medical decision making.

    python3 -m ehr.billing pt_001 --encounter enc_0262

Deterministic. No model. Computed on demand, never stored (like a TrendSummary): the level is
a projection of what the clinician actually signed at this visit, and every element of the
justification points at an id. The system never writes documentation to justify a code.

The 2021 AMA office/outpatient E/M framework sets the level by medical decision making (MDM):
the level met by at least two of three elements. We map:

- Problems addressed: every problem with a signed item at the visit. A chronic problem whose
  monitored series is out of range and moving counts as "chronic illness with severe
  exacerbation or progression" (High). Two or more stable chronic problems -> Moderate. One
  stable chronic problem, or an acute uncomplicated one -> Low. Otherwise Straightforward.
- Data reviewed and ordered: each unique test cited in a signed insight or ordered at the visit
  counts once; an external note reviewed counts once. 3+ -> Moderate; 2 -> Low; else Minimal.
  (High needs two categories, e.g. independent interpretation or discussion with an external
  physician, which this record does not yet capture; it is never inferred.)
- Risk of management: a signed medication stop or dose change is prescription drug management
  -> Moderate; an order flagged as requiring intensive monitoring, or a decision regarding
  hospitalization, -> High; a referral alone or no orders -> Low.

Level: 99212 straightforward, 99213 low, 99214 moderate, 99215 high.

ICD-10 mapping is a small demo table over the SNOMED codes Synthea emits, with the usual
combination codes when the chart supports them (diabetic CKD, hypertensive CKD). Not a
terminology service; every code below is flagged as a demo mapping.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ehr.extract import PROPOSED_DIR
from ehr.reason import monitored_codes
from ehr.review import ledger_for_problem, list_queues
from ehr.trend import DATA_DIR, trend_from_patient

LEVELS = ["straightforward", "low", "moderate", "high"]
CPT = {"straightforward": "99212", "low": "99213", "moderate": "99214", "high": "99215"}

# SNOMED (as Synthea emits it) -> ICD-10-CM. Demo mapping.
ICD10 = {
    "44054006": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "127013003": ("E11.22", "Type 2 diabetes mellitus with diabetic chronic kidney disease"),
    "90781000119102": ("E11.29", "Type 2 diabetes mellitus with other diabetic kidney complication"),
    "157141000119108": ("E11.29", "Type 2 diabetes mellitus with other diabetic kidney complication"),
    "431855005": ("N18.1", "Chronic kidney disease, stage 1"),
    "431856006": ("N18.2", "Chronic kidney disease, stage 2"),
    "433144002": ("N18.30", "Chronic kidney disease, stage 3 unspecified"),
    "431857002": ("N18.4", "Chronic kidney disease, stage 4"),
    "46177005": ("N18.6", "End stage renal disease"),
    "59621000": ("I10", "Essential (primary) hypertension"),
    "88805009": ("I50.22", "Chronic systolic (congestive) heart failure"),
    "53741008": ("I25.10", "Atherosclerotic heart disease of native coronary artery"),
    "414545008": ("I25.10", "Atherosclerotic heart disease of native coronary artery"),
    "302870006": ("E78.1", "Pure hyperglyceridemia"),
    "237602007": ("E88.81", "Metabolic syndrome"),
    "271737000": ("D64.9", "Anemia, unspecified"),
    "80394007": ("R73.9", "Hyperglycemia, unspecified"),
    "368581000119106": ("E11.42", "Type 2 diabetes mellitus with diabetic polyneuropathy"),
    "1551000119108": ("E11.329", "Type 2 diabetes with mild nonproliferative retinopathy without macular edema"),
}
# Name-based fallbacks for proposed problems (which carry no SNOMED code yet).
ICD10_BY_NAME = {
    "chronic kidney disease stage 4": ("N18.4", "Chronic kidney disease, stage 4"),
    "chronic kidney disease stage 5": ("N18.5", "Chronic kidney disease, stage 5"),
    "bilateral knee osteoarthritis": ("M17.0", "Bilateral primary osteoarthritis of knee"),
    "hypotension": ("I95.9", "Hypotension, unspecified"),
}
# Combination adjustments the record can support.
HTN_WITH_CKD = ("I12.9", "Hypertensive chronic kidney disease with stage 1 through stage 4 CKD, or unspecified CKD")
NSAID_ADVERSE = ("T39.395A", "Adverse effect of other NSAID, initial encounter")


def _visit_date(patient: dict, encounter_id: str | None) -> tuple[str | None, str]:
    if encounter_id:
        e = next((e for e in patient["encounters"] if e["id"] == encounter_id), None)
        if e:
            return e["id"], e["time"][:10]
    encs = sorted(patient["encounters"], key=lambda e: e["time"])
    return (encs[-1]["id"], encs[-1]["time"][:10]) if encs else (None, date.today().isoformat())


def _level_at_least(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def code_visit(patient: dict, encounter_id: str | None = None, *, on: str | None = None,
               proposed_dir: Path = PROPOSED_DIR) -> dict:
    """Deterministic diagnosis codes + MDM level for the decisions signed on one day."""
    enc_id, visit_day = _visit_date(patient, encounter_id)
    day = on or visit_day
    pid = patient["patient"]["id"]

    # --- what was signed today, and which problems it touches
    signed_today = []
    for b in list_queues(pid, proposed_dir):
        for k, items in b["proposed"].items():
            for it in items:
                rv = it.get("review")
                if rv and rv["decision"] == "accepted" and rv["at"][:10] == day:
                    signed_today.append((k[:-1], it))
        for ch in b.get("medication_changes", []):
            rv = ch.get("review")
            if rv and rv["decision"] == "accepted" and rv["at"][:10] == day:
                signed_today.append(("medication_change", ch))
    problems_by_id = {p["id"]: p for p in patient["problems"]}
    prob_names_lower = {p["name"].lower(): p for p in patient["problems"]}
    addressed: dict[str, dict] = {}

    def touch(prob_id: str | None, why_id: str):
        if prob_id and prob_id in problems_by_id:
            addressed.setdefault(prob_id, {"problem_id": prob_id, "name": problems_by_id[prob_id]["name"], "evidence": []})
            if why_id not in addressed[prob_id]["evidence"]:
                addressed[prob_id]["evidence"].append(why_id)

    def active_on(p: dict) -> bool:
        # a problem resolved before the coded day no longer owns its monitored series
        return p["status"] == "active" or (p["status"] == "resolved" and (p.get("resolved_date") or "") > day)

    series_owner = {}
    for p in patient["problems"]:
        if not active_on(p):
            continue
        for c in monitored_codes(patient, p["id"]):
            series_owner.setdefault(f"LOINC:{c}", []).append(p["id"])
    for kind, it in signed_today:
        if kind in ("insight", "document", "order"):
            touch(it.get("problem_id"), it["id"])
        elif kind == "link" and it["type"] in ("evidence_for", "relevant_to", "suspected_cause"):
            # a finding, result or causal link addresses the problem; a "treats" confirmation of a
            # medication already on the chart does not, on its own, make the problem addressed
            for end in (it["to"], it["from"]):
                touch(end, it["id"])
                for owner in series_owner.get(end, []):
                    touch(owner, it["id"])
        elif kind == "link" and it["type"] == "treats" and it["from"].startswith("med_") and any(
                m["id"] == it["from"] and m["provenance"]["source"] != "fhir_import" for m in patient["medications"]):
            touch(it["to"], it["id"])  # a newly signed medication does count
        elif kind == "problem":
            touch(it["id"], it["id"])
    # problems signed today that are themselves new: include them
    for kind, it in signed_today:
        if kind == "problem" and it["id"] in problems_by_id:
            touch(it["id"], it["id"])

    # --- element 1: problems
    prob_level, prob_why = "straightforward", []
    chronic_stable, progressing = 0, 0
    for a in addressed.values():
        p = problems_by_id[a["problem_id"]]
        moving = None
        for code in (monitored_codes(patient, p["id"]) if active_on(p) else []):
            t = trend_from_patient(patient, code, "1y", as_of=day)
            if t["n_points"] < 2 or t["direction"] not in ("rising", "falling"):
                continue
            latest = next((o for o in patient["observations"] if o["code"]["value"] == code
                           and o["effective_time"][:10] == t["latest"]["time"] and o["value"] == t["latest"]["value"]), None)
            rr = (latest or {}).get("reference_range") or {}
            v = t["latest"]["value"]
            if (rr.get("high") is not None and v > rr["high"]) or (rr.get("low") is not None and v < rr["low"]):
                moving = t
                moving["_latest_id"] = latest["id"] if latest else None
                break
        if moving:
            progressing += 1
            a["complexity"] = "chronic illness with severe exacerbation or progression"
            if moving.get("_latest_id") and moving["_latest_id"] not in a["evidence"]:
                a["evidence"].append(moving["_latest_id"])
            prob_why.append(f"{p['name']}: {moving['name']} {moving['direction']} {abs(moving['delta_pct'] or 0):.0f}% and outside range")
        elif p["status"] == "active":
            chronic_stable += 1
            a["complexity"] = "chronic illness, stable"
        else:
            a["complexity"] = "resolved / acute uncomplicated"
    if progressing:
        prob_level = "high"
    elif chronic_stable >= 2:
        prob_level = "moderate"; prob_why.append(f"{chronic_stable} stable chronic problems addressed")
    elif chronic_stable == 1 or addressed:
        prob_level = "low"; prob_why.append("one stable chronic problem addressed")

    # --- element 2: data
    data_items: dict[str, str] = {}
    for kind, it in signed_today:
        if kind == "insight":
            for ev in it.get("evidence", []):
                o = next((o for o in patient["observations"] if o["id"] == ev), None)
                if o:
                    data_items.setdefault(o["code"]["value"], f"{o['name']} reviewed ({o['id']})")
        if kind == "order" and it.get("kind") == "lab":
            data_items.setdefault(f"order:{it['id']}", f"{it['name']} ordered ({it['id']})")
        if kind == "link" and it["from"].startswith("note_"):
            data_items.setdefault(it["from"], f"note reviewed ({it['from']})")
    data_level = "moderate" if len(data_items) >= 3 else "low" if len(data_items) == 2 else "straightforward"

    # --- element 3: risk
    risk_level, risk_why = "straightforward", []
    for kind, it in signed_today:
        if kind == "medication_change" or (kind == "order" and it.get("kind") == "medication_change"):
            risk_level = _level_at_least(risk_level, "moderate")
            risk_why.append(f"prescription drug management: {it.get('change', '')} {it.get('med_id', '')}".strip())
        if kind == "order" and it.get("kind") in ("referral", "lab", "imaging"):
            risk_level = _level_at_least(risk_level, "low")
            risk_why.append(f"{it['kind']} ordered: {it['name']}")
        if kind == "order" and any(w in (it.get("detail", "") + it.get("name", "")).lower() for w in ("intensive monitoring", "hospitali", "admit")):
            risk_level = "high"
            risk_why.append(f"decision regarding hospitalization / intensive monitoring: {it['name']}")
        if kind == "document" and it.get("kind") == "referral":
            risk_level = _level_at_least(risk_level, "low")
            risk_why.append(f"referral to {it.get('audience')}")
        if kind == "medication" and it.get("provenance", {}).get("source") == "nlp_extraction":
            risk_level = _level_at_least(risk_level, "moderate")
            risk_why.append(f"medication reconciled: {it['name']}")

    levels = sorted([prob_level, data_level, risk_level], key=LEVELS.index)
    overall = levels[1]  # the level met by at least two elements

    # --- diagnosis codes
    has_ckd = any(problems_by_id[a]["name"].lower().startswith("chronic kidney disease") for a in addressed)
    dx = []
    seen = set()
    for a in addressed.values():
        p = problems_by_id[a["problem_id"]]
        sn = (p.get("code") or {}).get("value")
        entry = ICD10.get(sn) or ICD10_BY_NAME.get(p["name"].lower())
        if sn == "59621000" and has_ckd:
            entry = HTN_WITH_CKD
        if not entry:
            dx.append({"problem_id": p["id"], "name": p["name"], "code": None, "description": "no demo mapping", "mapping": "none"})
            continue
        if entry[0] in seen:
            continue
        seen.add(entry[0])
        dx.append({"problem_id": p["id"], "name": p["name"], "code": entry[0], "description": entry[1], "mapping": "demo table"})
    ckd_rank = {"N18.1": 1, "N18.2": 2, "N18.30": 3, "N18.4": 4, "N18.5": 5, "N18.6": 6}
    ckd = [d for d in dx if d["code"] in ckd_rank]
    if len(ckd) > 1:
        keep = max(ckd, key=lambda d: ckd_rank[d["code"]])
        dx = [d for d in dx if d["code"] not in ckd_rank or d is keep]
    if any(d["code"] and d["code"].startswith("E11.") and d["code"] != "E11.9" for d in dx):
        dx = [d for d in dx if d["code"] != "E11.9"]  # "without complications" is wrong once a complication is coded
    nsaid = [l for l in patient["links"] if l["type"] == "suspected_cause" and l["status"] == "accepted"
             and any(m["id"] == l["from"] and "naproxen" in m["name"].lower() for m in patient["medications"])]
    if nsaid and NSAID_ADVERSE[0] not in seen:
        dx.append({"problem_id": None, "name": "NSAID suspected cause (signed link)", "code": NSAID_ADVERSE[0], "description": NSAID_ADVERSE[1],
                   "mapping": "demo table", "evidence": [nsaid[0]["id"]]})

    return {
        "patient_id": pid, "encounter_id": enc_id, "date": day, "status": "computed",
        "problems_addressed": list(addressed.values()),
        "mdm": {
            "problems": {"level": prob_level, "why": prob_why},
            "data": {"level": data_level, "why": list(data_items.values())},
            "risk": {"level": risk_level, "why": risk_why},
            "level": overall, "cpt": CPT[overall],
            "rule": "level met by at least two of three elements (2021 AMA office/outpatient E/M)",
        },
        "diagnosis_codes": dx,
        "signed_today": len(signed_today),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--encounter")
    ap.add_argument("--on", help="YYYY-MM-DD; default: the encounter's date (or today's signatures)")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    patient = json.loads((data_dir / f"{args.patient_id}.json").read_text())
    c = code_visit(patient, args.encounter, on=args.on, proposed_dir=data_dir.parent / "proposed")
    print(f"Visit coding for {c['patient_id']} on {c['date']} ({c['signed_today']} items signed)")
    m = c["mdm"]
    print(f"  E/M {m['cpt']} ({m['level']}): problems={m['problems']['level']} data={m['data']['level']} risk={m['risk']['level']}")
    for k in ("problems", "data", "risk"):
        for w in m[k]["why"]:
            print(f"    {k}: {w}")
    print("  Diagnoses:")
    for d in c["diagnosis_codes"]:
        print(f"    {d['code'] or '----':<9} {d['description']}  <- {d['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
