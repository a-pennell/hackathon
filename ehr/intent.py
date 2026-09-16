"""A clinician's own decision on a problem: a typed intent, signed as it is made, stamped with the visit.

    python3 -m ehr.intent pt_002 --problem prob_0007 --kind monitoring --text "Home BP log, review in two weeks"
    python3 -m ehr.intent pt_002 --problem prob_0007 --kind therapeutic --text "Stop hydrochlorothiazide" --course med_hydrochlorothiazide --change stop

The model's proposals wait for a signature (non-negotiable 1). A clinician's own order does not: it is written
with provenance `clinician` and a review record by its author, carrying the encounter, so the Care card, the
workspace, the Timeline and the compiled visit note all read it the same way they read a signed proposal.
A diagnostic or referral intent also places the order; a therapeutic intent that names a course on the chart
stops it or changes its dose on the visit day, closing the segment as a signed medication change would.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ehr.extract import PLAN_KINDS, save_patient
from ehr.review import DEFAULT_REVIEWER, accept_medication_change, open_encounter, review_record
from ehr.trend import DATA_DIR, load_patient

ORDER_KIND = {"diagnostic": "lab", "referral": "referral"}


def _next_id(prefix: str, taken: set[str]) -> str:
    n = 1
    while f"{prefix}{n:02d}" in taken:
        n += 1
    return f"{prefix}{n:02d}"


def add_intent(patient: dict, problem_id: str, kind: str, text: str, *, course_id: str | None = None,
               change: str | None = None, dose: str | None = None, by: str = DEFAULT_REVIEWER) -> dict:
    if kind not in PLAN_KINDS:
        raise ValueError(f"kind must be one of {PLAN_KINDS}")
    text = (text or "").strip()
    if not text:
        raise ValueError("an intent needs a line of text")
    if not any(p["id"] == problem_id for p in patient["problems"]):
        raise KeyError(f"{problem_id} is not on this chart")
    pid = patient["patient"]["id"]
    enc_id = open_encounter(patient)
    enc = next((e for e in patient.get("encounters", []) if e["id"] == enc_id), None)
    day = (enc["time"] if enc else datetime.now().astimezone().isoformat())[:10]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    review = review_record("accepted", by, encounter_id=enc_id)
    prov = {"source": "clinician", "by": by}
    done = []

    plan_id = _next_id("plan_clin_", {x["id"] for x in patient.get("plans", [])})
    patient.setdefault("plans", []).append({"id": plan_id, "patient_id": pid, "problem_id": problem_id, "kind": kind, "text": text,
                                            "status": "accepted", "provenance": prov, "created_at": now, "review": review})
    done.append(f"plan {plan_id}")

    if kind in ORDER_KIND:
        oid = _next_id("ord_clin_", {x["id"] for x in patient.get("orders", [])})
        patient.setdefault("orders", []).append({
            "id": oid, "patient_id": pid, "problem_id": problem_id, "kind": ORDER_KIND[kind], "name": text, "detail": "",
            "code": None, "med_id": None, "change": None, "dose": None, "audience": text if kind == "referral" else None,
            "status": "accepted", "provenance": {**prov, "from_plan": plan_id}, "created_at": now, "review": review, "ordered_at": review["at"]})
        done.append(f"order {oid}")

    if course_id and change in ("stop", "dose_change"):
        if not any(m["id"] == course_id for m in patient["medications"]):
            raise KeyError(f"{course_id} is not on this chart")
        done.append(accept_medication_change(patient, {"med_id": course_id, "change": change, "effective": day, "dose": dose,
                                                       "route": None, "frequency": None, "status": "proposed",
                                                       "provenance": prov}, review))
    return {"plan_id": plan_id, "done": done, "encounter_id": enc_id, "effective": day}


def run_intent(patient_id: str, problem_id: str, kind: str, text: str, *, course_id: str | None = None, change: str | None = None,
               dose: str | None = None, by: str = DEFAULT_REVIEWER, data_dir: Path = DATA_DIR) -> dict:
    data_dir = Path(data_dir)
    patient = load_patient(patient_id, data_dir)
    out = add_intent(patient, problem_id, kind, text, course_id=course_id, change=change, dose=dose, by=by)
    save_patient(patient, data_dir)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--problem", required=True)
    ap.add_argument("--kind", required=True, choices=PLAN_KINDS)
    ap.add_argument("--text", required=True)
    ap.add_argument("--course")
    ap.add_argument("--change", choices=["stop", "dose_change"])
    ap.add_argument("--dose")
    ap.add_argument("--by", default=DEFAULT_REVIEWER)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    a = ap.parse_args(argv)
    print(json.dumps(run_intent(a.patient_id, a.problem, a.kind, a.text, course_id=a.course, change=a.change, dose=a.dose, by=a.by, data_dir=Path(a.data_dir)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
