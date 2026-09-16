"""Persist explicitly signed workspace prose as encounter-scoped clinical reasoning."""
from datetime import datetime
from uuid import uuid4

from ehr.extract import save_patient
from ehr.review import open_encounter, review_record
from ehr.trend import DATA_DIR, load_patient


def sign_assessment(pid, problem_id, text, kind, evidence=(), by="Dr. Chen", data_dir=DATA_DIR):
    if kind not in ("assessment", "representation") or not text.strip():
        raise ValueError("An assessment or representation needs text before it can be signed.")
    p = load_patient(pid, data_dir)
    if not any(x["id"] == problem_id for x in p["problems"]):
        raise ValueError("This problem is no longer on the chart.")
    encounter = open_encounter(p)
    if not encounter:
        raise ValueError("An encounter is required to sign an assessment.")
    ids = {x["id"] for k in ("problems", "medications", "observations", "notes", "insights", "plans", "orders", "links") for x in p.get(k, [])}
    if set(evidence) - ids - {x for x in evidence if x.startswith("LOINC:")}:
        raise ValueError("The supporting evidence changed. Reopen the workspace before signing.")
    insight = {"id": "ins_" + uuid4().hex, "patient_id": pid, "problem_id": problem_id, "kind": kind,
               "statement": text.strip(), "suggested_action": "", "evidence": list(dict.fromkeys([problem_id, *evidence])),
               "status": "accepted", "created_at": datetime.now().astimezone().isoformat(),
               "provenance": {"source": "clinician"}, "review": review_record("accepted", by, encounter_id=encounter)}
    p.setdefault("insights", []).append(insight)
    save_patient(p, data_dir)
    return insight
