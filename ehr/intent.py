"""A clinician's own decision on a problem: a typed intent, signed as it is made, stamped with the visit.

    python3 -m ehr.intent pt_002 --problem prob_0007 --kind monitoring --text "Home BP log, review in two weeks"
    python3 -m ehr.intent pt_002 --problem prob_0007 --kind therapeutic --text "Stop hydrochlorothiazide" --course med_hydrochlorothiazide --change stop

The model's proposals wait for a signature (non-negotiable 1). A clinician's own order does not: it is written
with provenance `clinician` and a review record by its author, carrying the encounter, so the Care card, the
workspace, the Timeline and the compiled visit note all read it the same way they read a signed proposal.
A treatment-plan or both destination also places diagnostic/referral orders and applies explicit course
changes. Note-only additions are unsigned, encounter-scoped text with no clinical side effects. The
compiler excludes treatment-only entries from Note: Plan. Legacy callers default to both destinations.
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
               change: str | None = None, dose: str | None = None, by: str = DEFAULT_REVIEWER,
               destination: str = "both", encounter_id: str | None = None) -> dict:
    if destination not in ("note", "treatment_plan", "both"):
        raise ValueError("Choose Note: Plan, Treatment plan, or Both")
    if kind not in PLAN_KINDS:
        raise ValueError(f"kind must be one of {PLAN_KINDS}")
    text = (text or "").strip()
    if not text:
        raise ValueError("an intent needs a line of text")
    if not any(p["id"] == problem_id for p in patient["problems"]):
        raise KeyError(f"{problem_id} is not on this chart")
    pid = patient["patient"]["id"]
    if encounter_id and not any(e["id"] == encounter_id for e in patient.get("encounters", [])):
        raise ValueError("Read the active visit note before adding plan items. Its encounter is not on the chart yet.")
    enc_id = encounter_id or open_encounter(patient)
    if destination != "treatment_plan":
        if not enc_id:
            raise ValueError("An active encounter is required for Note: Plan")
        if any(d.get("kind") == "encounter_note" and d.get("encounter_id") == enc_id
               and d.get("status") == "accepted" for d in patient.get("documents", [])):
            raise ValueError("The visit note is signed. Add an amendment or choose Treatment plan only.")
    if destination == "note" and any((course_id, change, dose)):
        raise ValueError("Note-only additions cannot change medications")
    if any((course_id, change, dose)):
        if kind != "therapeutic" or not course_id or change not in ("stop", "dose_change"):
            raise ValueError("A medication change needs a therapeutic intent, course, and valid change")
        med = next((m for m in patient["medications"] if m["id"] == course_id), None)
        if med is None:
            raise KeyError(f"{course_id} is not on this chart")
        if not med.get("segments") or med["segments"][-1].get("end"):
            raise ValueError("Choose an active medication course")
        if change == "dose_change" and not (dose or "").strip():
            raise ValueError("Enter the new dose")
    enc = next((e for e in patient.get("encounters", []) if e["id"] == enc_id), None)
    day = (enc["time"] if enc else datetime.now().astimezone().isoformat())[:10]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    review = review_record("accepted", by, encounter_id=enc_id)
    prov = {"source": "clinician", "by": by}
    done = []

    archived_ids = {x["item"]["id"] for x in patient.get("archived_items", [])}
    if destination == "note":
        item_id = _next_id("noteplan_", {x["id"] for x in patient.get("note_plan_items", [])})
        patient.setdefault("note_plan_items", []).append({
            "id": item_id, "patient_id": pid, "problem_id": problem_id, "encounter_id": enc_id,
            "kind": kind, "text": text, "provenance": prov, "created_at": now,
        })
        return {"plan_id": None, "note_item_id": item_id, "destination": destination,
                "done": [f"note text {item_id}"], "encounter_id": enc_id, "effective": day}
    plan_id = _next_id("plan_clin_", {x["id"] for x in patient.get("plans", [])} | archived_ids)
    patient.setdefault("plans", []).append({"id": plan_id, "patient_id": pid, "problem_id": problem_id, "kind": kind, "text": text,
                                            "destination": destination, "status": "accepted", "provenance": prov, "created_at": now, "review": review})
    done.append(f"plan {plan_id}")

    if kind in ORDER_KIND:
        oid = _next_id("ord_clin_", {x["id"] for x in patient.get("orders", [])} | archived_ids)
        patient.setdefault("orders", []).append({
            "id": oid, "patient_id": pid, "problem_id": problem_id, "kind": ORDER_KIND[kind], "name": text, "detail": "",
            "code": None, "med_id": None, "change": None, "dose": None, "audience": text if kind == "referral" else None,
            "destination": destination, "status": "accepted", "provenance": {**prov, "from_plan": plan_id}, "created_at": now, "review": review, "ordered_at": review["at"]})
        done.append(f"order {oid}")

    if course_id and change in ("stop", "dose_change"):
        if not any(m["id"] == course_id for m in patient["medications"]):
            raise KeyError(f"{course_id} is not on this chart")
        course_change = {"med_id": course_id, "change": change, "effective": day, "dose": dose,
                                                       "route": None, "frequency": None, "status": "proposed",
                                                       "provenance": prov}
        done.append(accept_medication_change(patient, course_change, review))
        patient["plans"][-1]["medication_effect"] = course_change["medication_effect"]
    return {"plan_id": plan_id, "destination": destination, "done": done, "encounter_id": enc_id, "effective": day}


def run_intent(patient_id: str, problem_id: str, kind: str, text: str, *, course_id: str | None = None, change: str | None = None,
               dose: str | None = None, by: str = DEFAULT_REVIEWER, data_dir: Path = DATA_DIR,
               destination: str = "both", encounter_id: str | None = None) -> dict:
    data_dir = Path(data_dir)
    patient = load_patient(patient_id, data_dir)
    out = add_intent(patient, problem_id, kind, text, course_id=course_id, change=change, dose=dose, by=by, destination=destination, encounter_id=encounter_id)
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
    ap.add_argument("--destination", choices=["note", "treatment_plan", "both"], default="both")
    ap.add_argument("--by", default=DEFAULT_REVIEWER)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    a = ap.parse_args(argv)
    print(json.dumps(run_intent(a.patient_id, a.problem, a.kind, a.text, course_id=a.course, change=a.change, dose=a.dose, by=a.by, data_dir=Path(a.data_dir), destination=a.destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
