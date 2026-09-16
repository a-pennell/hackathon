"""v2 API: the gate, the seven answers, acknowledging a detected change, and the assembled note."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ehr.draft import draft_note, stem_for
from ehr.extract import PROPOSED_DIR, load_note_file, save_patient
from ehr.review import DEFAULT_REVIEWER, accept_item, list_queues, open_encounter, review_record
from ehr.trend import DATA_DIR, load_patient
from v2.monitor import problem_list, problem_view

router = APIRouter(prefix="/v2/api")
ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "data" / "notes"


def _attach_note(pid: str, patient: dict, listing: dict) -> None:
    """The note that arrived with the newest visit, if a demo note file carries it, and whether it has been read."""
    enc = (listing["here_for"] or {}).get("encounter")
    newest = None
    for f in sorted(NOTES_DIR.glob("*.json")):
        n, e = load_note_file(f)
        if n["patient_id"] != pid or not e:
            continue
        if newest is None or e["time"] > newest[1]["time"]:
            newest = (n, e, f)
    note = None
    if newest and (not enc or newest[1]["time"][:10] >= enc["time"][:10]):
        n, e, f = newest
        listing["here_for"]["encounter"] = {k: e[k] for k in ("id", "time", "type", "summary")}
        on_chart = next((x for x in patient.get("notes", []) if x["id"] == n["id"]), None)
        note = {"id": n["id"], "file": str(f.relative_to(ROOT)), "author": n["author"], "time": n["time"],
                "has_queue": (PROPOSED_DIR / pid / f"{n['id']}.json").exists(),
                "has_replay": (PROPOSED_DIR / pid / f"{n['id']}.raw.json").exists(),
                "status": (on_chart or {}).get("status", "received")}
    listing["here_for"]["note"] = note


def _patient(pid: str) -> dict:
    try:
        return load_patient(pid, DATA_DIR)
    except FileNotFoundError:
        raise HTTPException(404, f"no patient {pid}")


def _next_action(patient: dict, listing: dict) -> dict:
    """The one thing owed, in visit order: read the note, decide and sign it, then assemble and sign the visit note."""
    pid = patient["patient"]["id"]
    queues = {b["stem"]: b for b in list_queues(pid, PROPOSED_DIR)}
    here = listing["here_for"].get("note")
    enc = listing["here_for"].get("encounter")
    if here:
        b = queues.get(here["id"])
        if not b:
            return {"kind": "read", "label": "Read the note", "hint": f"{here['author']}'s note from this visit has not been read", "note_id": here["id"]}
        waiting = sum(1 for k, items in b["proposed"].items() for it in items if it.get("status") == "proposed") + sum(1 for c in b.get("medication_changes", []) if c["status"] == "proposed")
        if waiting:
            return {"kind": "review", "label": f"Review the note · {waiting}", "hint": "decide what it proposed, then sign it", "note_id": here["id"]}
        if here.get("status") != "signed":
            return {"kind": "sign", "label": "Sign the note", "hint": "everything it proposed is decided", "note_id": here["id"]}
    if enc and here and here.get("status") == "signed":
        signed = any(d.get("kind") == "encounter_note" and d.get("encounter_id") == enc["id"] for d in patient.get("documents", []))
        if not signed:
            draft = queues.get(stem_for(enc["id"]))
            return {"kind": "sign-draft" if draft else "draft", "label": "Finish the visit note" if draft else "Assemble the visit note",
                    "hint": "assembled from what was decided at this visit; edit, add, then sign", "encounter_id": enc["id"]}
    return {"kind": "done", "label": "Nothing owed", "hint": "the visit is documented"}


@router.get("/patients/{pid}/problems")
def problems(pid: str):
    p = _patient(pid)
    out = problem_list(p, proposed_dir=PROPOSED_DIR)
    _attach_note(pid, p, out)
    out["next_action"] = _next_action(p, out)
    return out


@router.get("/patients/{pid}/problems/{prob}")
def problem(pid: str, prob: str):
    p = _patient(pid)
    if not any(x["id"] == prob for x in p["problems"]):
        raise HTTPException(404, f"no problem {prob}")
    return problem_view(p, prob, proposed_dir=PROPOSED_DIR)


class AckBody(BaseModel):
    text: str
    ids: list[str] = []
    by: str = DEFAULT_REVIEWER


@router.post("/patients/{pid}/problems/{prob}/acknowledge")
def acknowledge(pid: str, prob: str, body: AckBody):
    """A rule-detected change, signed into the record as an insight from rules: the clinician saw it. From then on it
    is a fact of the visit and assembles into the note."""
    p = _patient(pid)
    ids = {x["id"] for k in ("observations", "medications", "links", "problems") for x in p.get(k, [])}
    evidence = [i for i in body.ids if i in ids]
    n = 1 + sum(1 for i in p.get("insights", []) if i["id"].startswith(f"ins_{prob[5:]}_r"))
    iid = f"ins_{prob[5:]}_r{n:02d}"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    p.setdefault("insights", []).append({"id": iid, "patient_id": pid, "problem_id": prob, "statement": body.text.strip(), "evidence": evidence,
                                         "suggested_action": "", "status": "accepted",
                                         "provenance": {"source": "rules", "model": "monitor-v2", "confidence": 1.0}, "created_at": now,
                                         "review": review_record("accepted", body.by, encounter_id=open_encounter(p))})
    save_patient(p, DATA_DIR)
    return {"insight_id": iid, "evidence": evidence}


@router.get("/patients/{pid}/note")
def note(pid: str):
    """The visit note as assembled right now for the open encounter, unsaved, plus what is already signed."""
    p = _patient(pid)
    enc = open_encounter(p)
    if not enc:
        raise HTTPException(404, "no encounter to document")
    signed = next((d for d in p.get("documents", []) if d.get("kind") == "encounter_note" and d.get("encounter_id") == enc), None)
    qp = PROPOSED_DIR / pid / f"{stem_for(enc)}.json"
    draft = json.loads(qp.read_text())["proposed"]["documents"][0] if qp.exists() else None
    compiled = draft_note(p, enc, proposed_dir=PROPOSED_DIR)["proposed"]["documents"][0]
    e = next(x for x in p["encounters"] if x["id"] == enc)
    return {"encounter": e, "signed": signed, "draft": draft, "compiled": compiled}


class NoteSignBody(BaseModel):
    sections: list[dict] | None = None
    authored: str | None = None
    by: str = DEFAULT_REVIEWER


@router.post("/patients/{pid}/note/sign")
def sign_note_v2(pid: str, body: NoteSignBody):
    """Assemble the note from the record as it stands right now, apply the clinician's edits by section, add their own
    words, and sign it into the chart's documents. v2 does not keep a draft between visits to the page: the record is the
    draft, and the edits travel with the signature."""
    p = _patient(pid)
    enc = open_encounter(p)
    if not enc:
        raise HTTPException(404, "no encounter to document")
    if any(d.get("kind") == "encounter_note" and d.get("encounter_id") == enc for d in p.get("documents", [])):
        raise HTTPException(400, "the visit note is already signed")
    batch = draft_note(p, enc, proposed_dir=PROPOSED_DIR)
    doc = batch["proposed"]["documents"][0]
    edits = {(sec.get("heading") or "").strip(): sec.get("text") for sec in (body.sections or []) if isinstance(sec.get("text"), str)}
    for sec in doc["sections"]:
        t = edits.get(sec["heading"])
        if t is not None and t.strip() != sec["text"].strip():
            sec["text"] = t.strip()
            sec["edited"] = True
    if body.authored and body.authored.strip():
        doc["sections"].append({"heading": "In the clinician's words", "text": body.authored.strip(), "cites": [], "source": "authored"})
    qp = PROPOSED_DIR / pid / f"{stem_for(enc)}.json"
    qp.parent.mkdir(parents=True, exist_ok=True)
    done = accept_item(p, batch, doc["id"], review=review_record("accepted", body.by, encounter_id=enc))
    save_patient(p, DATA_DIR)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    return {"document_id": doc["id"], "signed_at": doc["review"]["at"], "by": body.by, "done": done}
