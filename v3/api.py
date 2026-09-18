"""v3: the visit as one surface. The transcript plays; the recorded reading is revealed as the transcript reaches each
finding's passage; findings land on the problem they touch; decisions wait as chips; the note grows the whole time.
No new model call: the same recorded extraction, positioned in the transcript by each finding's verbatim quote."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from fastapi import APIRouter, HTTPException

from datetime import date

from pydantic import BaseModel

from ehr.draft import draft_note, stem_for
from ehr.extract import PROPOSED_DIR, load_note_file, save_patient, verbatim_quote
from ehr.review import DEFAULT_REVIEWER, accept_item, accept_medication_change, apply_review, list_queues, load_queue, open_encounter, review_record
from ehr.trend import DATA_DIR, load_patient
from v2.monitor import attest, manifest
from v2.api import _attach_note, _next_action, _followup, _today
from v2.monitor import problem_list, unattested

router = APIRouter(prefix="/v3/api")
ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "data" / "notes"

DECISION_LINKS = ("suspected_cause",)
CAUSAL_CUES = ("contribut", "cause", "caus", "due to", "secondary to", "because of", "attribut", "driver", "driven", "from the", "worsen", "raise", "raising", "induced", "related to")
ALIASES = {"ibuprofen": ("nsaid", "advil", "motrin"), "naproxen": ("nsaid", "aleve"), "hydrochlorothiazide": ("hctz", "thiazide"), "lisinopril": ("ace inhibitor", "acei"),
           "metformin": ("metformin",), "acetaminophen": ("tylenol", "acetaminophen")}


def _mentions(quote: str, name: str) -> bool:
    """Does the passage name the thing (or a common alias or class word for it)?"""
    q = quote.lower()
    head = name.lower().split(" ")[0]
    if head in q:
        return True
    return any(a in q for a in ALIASES.get(head, ()))


def _states_problem(quote: str, name: str) -> bool:
    q = quote.lower()
    words = [w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 3 and w not in ("type", "with", "disease", "disorder", "essential", "mellitus")]
    return bool(words) and sum(1 for w in words if w[:5] in q) >= max(1, (len(words) + 1) // 2)


def _origin(kind: str, quote: str | None, *, cause_name: str | None = None, problem_name: str | None = None) -> str:
    """'stated': the passage itself makes the claim, so the dictation already decided it and the note's signature covers
    it. 'inferred': the reading added a relation the passage does not state; that one needs a look."""
    if not quote:
        return "inferred"
    if kind == "cause":
        return "stated" if cause_name and _mentions(quote, cause_name) and any(c in quote.lower() for c in CAUSAL_CUES) else "inferred"
    if kind == "problem":
        return "stated" if problem_name and _states_problem(quote, problem_name) else "inferred"
    return "stated"  # a result, a course, a plan line, a finding: the passage is the claim


def _utterances(text: str) -> list[dict]:
    """The dictation as it would be spoken: one utterance per sentence or line, with character offsets."""
    out, i = [], 0
    for m in re.finditer(r"[^\n]+?(?:(?<=[.!?:])\s+(?=[A-Z0-9\"“])|\n+|$)", text):
        seg = m.group(0)
        s, e = m.start(), m.end()
        if seg.strip():
            out.append({"i": len(out), "start": s, "end": e, "text": seg.strip()})
        i = e
    return out


def _offset(quote: str | None, text: str) -> int | None:
    if not quote:
        return None
    exact = verbatim_quote(quote, text)
    return text.find(exact) if exact else None


@router.get("/patients/{pid}/visit")
def visit(pid: str, as_of: str | None = None):
    """The transcript, and every proposal of the visit's note placed in it."""
    p = load_patient(pid, DATA_DIR)
    listing = problem_list(p, proposed_dir=PROPOSED_DIR, today=_today(as_of))
    _attach_note(pid, p, listing)
    here = listing["here_for"].get("note")
    if not here:
        raise HTTPException(404, "no note for this visit")
    note, enc = load_note_file(ROOT / here["file"])
    text = note["text"]
    names = {x["id"]: x["name"] for x in p["problems"]}
    names.update({m["id"]: m["name"] for m in p["medications"]})
    names.update({o["id"]: f"{o['name']} {o['value']} {o.get('unit') or ''}".strip() for o in p["observations"]})
    batch = next((b for b in list_queues(pid, PROPOSED_DIR) if b.get("note_id") == here["id"]), None)
    proposals = []
    if batch:
        pr = batch["proposed"]
        for x in pr.get("problems", []) + pr.get("medications", []) + pr.get("observations", []) + pr.get("plans", []):
            names[x["id"]] = x.get("name") or x.get("text") or x["id"]
        by_from: dict[str, list[dict]] = {}
        for l in pr.get("links", []):
            by_from.setdefault(l["from"], []).append(l)
        def problems_of(item_id: str, item: dict) -> list[str]:
            ids = set()
            if item.get("problem_id"):
                ids.add(item["problem_id"])
            for l in by_from.get(item_id, []):
                if l["to"].startswith("prob_"):
                    ids.add(l["to"])
            return sorted(ids)
        for kind, items in (("problem", pr.get("problems", [])), ("course", pr.get("medications", [])), ("result", pr.get("observations", [])), ("plan", pr.get("plans", []))):
            for it in items:
                q = (it.get("provenance") or {}).get("quote")
                links = by_from.get(it["id"], [])
                decision = kind == "problem" or any(l["type"] in DECISION_LINKS for l in links)
                text_ = it.get("name") or it.get("text") or it["id"]
                if kind == "result":
                    text_ = f"{it['name']} {it['value']} {it.get('unit') or ''}".strip()
                if kind == "course":
                    seg = (it.get("segments") or [{}])[0]
                    text_ = f"{it['name']} {seg.get('dose') or ''} {seg.get('frequency') or ''}".strip() + (f" · {seg.get('start')} → {seg.get('end') or 'ongoing'}" if seg.get("start") else "")
                cause = [names.get(l["to"], l["to"]) for l in links if l["type"] == "suspected_cause"]
                cause_q = next(((l.get("provenance") or {}).get("quote") for l in links if l["type"] == "suspected_cause"), None)
                origin = _origin("cause", cause_q, cause_name=it.get("name")) if cause else _origin(kind, q, problem_name=it.get("name"))
                proposals.append({"id": it["id"], "kind": "cause" if cause else kind, "text": text_ + (f" · suspected cause of {', '.join(cause)}" if cause else ""),
                                  "problems": problems_of(it["id"], it) or ([it["id"]] if kind == "problem" else []), "quote": cause_q or q, "offset": _offset(cause_q or q, text),
                                  "decision": decision and origin == "inferred", "origin": origin, "status": it.get("status"), "link_ids": [l["id"] for l in links],
                                  "cause_link_ids": [l["id"] for l in links if l["type"] == "suspected_cause"], "stem": batch["stem"]})
        # links whose subject is already on the chart (a finding from the note, a restated result, a cause on an existing course)
        claimed = {x["id"] for k in ("problems", "medications", "observations", "plans") for x in pr.get(k, [])}
        for frm, links in by_from.items():
            if frm in claimed:
                continue
            for l in links:
                q = (l.get("provenance") or {}).get("quote")
                subj = names.get(frm, frm) if not frm.startswith("note_") else (batch.get("review_hints", {}).get(l["id"]) or "finding")
                rel = {"suspected_cause": "suspected cause of", "evidence_for": "evidence for", "relevant_to": "bears on", "treats": "treats"}.get(l["type"], l["type"])
                origin = _origin("cause", q, cause_name=names.get(frm, frm)) if l["type"] == "suspected_cause" else "stated"
                proposals.append({"id": l["id"], "kind": "cause" if l["type"] == "suspected_cause" else "finding", "text": f"{subj} · {rel} {names.get(l['to'], l['to'])}",
                                  "problems": [l["to"]] if l["to"].startswith("prob_") else [], "quote": q, "offset": _offset(q, text),
                                  "decision": l["type"] in DECISION_LINKS and origin == "inferred", "origin": origin, "status": l.get("status"), "link_ids": [l["id"]], "stem": batch["stem"]})
        for c in batch.get("medication_changes", []):
            q = (c.get("provenance") or {}).get("quote")
            proposals.append({"id": f"change:{c['med_id']}", "kind": "course change", "text": f"{names.get(c['med_id'], c['med_id'])}: {c['change'].replace('_', ' ')}" + (f" to {c['dose']}" if c.get("dose") else ""),
                              "problems": [l["to"] for l in p["links"] if l["from"] == c["med_id"] and l["type"] == "treats"], "quote": q, "offset": _offset(q, text),
                              "decision": False, "origin": "stated", "status": c.get("status"), "link_ids": [], "stem": batch["stem"], "change": True})
    proposals.sort(key=lambda x: (x["offset"] if x["offset"] is not None else 10**9))
    return {"note": {"id": here["id"], "author": here["author"], "time": here["time"], "status": here.get("status"), "read": bool(batch), "file": here["file"]},
            "encounter": listing["here_for"]["encounter"], "utterances": _utterances(text), "text": text, "proposals": proposals,
            "problems": listing["problems"], "counts": listing["counts"], "next_action": _next_action(p, listing), "unattested": unattested(p), "followup": _followup(pid, p)}


def _plan_of_signature(v: dict, body: "VisitSignBody") -> tuple[list[str], list[str], list[str], dict]:
    """What the signature does with the visit's proposals: ids to accept, ids rejected with a reason, ids set aside.
    A stated finding is accepted with its links. For an inferred cause the answer applies to the relation only; the
    thing itself (the course, the result) stays."""
    accept, reject_yes, reject_unconfirmed, reason_of = [], [], [], {}
    for p in v["proposals"]:
        if p["status"] != "proposed" or p.get("change"):
            continue
        ids = list(dict.fromkeys([p["id"], *p.get("link_ids", [])]))
        cause_ids = p.get("cause_link_ids") or ([p["id"]] if p["id"].startswith("lnk_") else [])
        rest = [i for i in ids if i not in cause_ids]
        for cid in cause_ids:
            reason_of[cid] = body.reasons.get(p["id"]) or body.reasons.get(cid) or ""
        if p["origin"] == "stated" or body.decisions.get(p["id"]) == "accept":
            accept += ids
        elif body.decisions.get(p["id"]) == "reject":
            reject_yes += cause_ids; accept += rest
        else:
            reject_unconfirmed += cause_ids; accept += rest
    return list(dict.fromkeys(accept)), reject_yes, reject_unconfirmed, reason_of


class VisitSignBody(BaseModel):
    decisions: dict[str, str] = {}       # inferred proposal id -> "accept" | "reject"
    reasons: dict[str, str] = {}         # id -> the clinician's reason for a rejection
    sections: list[dict] | None = None   # edits to the compiled note, by heading
    authored: str | None = None
    by: str = DEFAULT_REVIEWER


@router.post("/patients/{pid}/visit/sign")
def sign_visit(pid: str, body: VisitSignBody, as_of: str | None = None):
    """Dictate, then sign: the one act. Everything the dictation stated is accepted by the signature; what the reading
    inferred beyond the dictation is taken only if the clinician said yes, rejected if they said no, and set aside
    (rejected as unconfirmed, undoable) if they said nothing. Then the note is closed and the visit note is compiled from
    the record as it now stands and signed, with the clinician's edits and their own words."""
    v = visit(pid, as_of)
    stem = next((p["stem"] for p in v["proposals"] if p.get("stem")), None)
    if v["note"].get("status") == "signed":
        raise HTTPException(400, "this visit's note is already signed")
    if stem:
        accept, reject_yes, reject_unconfirmed, reason_of = _plan_of_signature(v, body)
        for rid in reject_yes:
            apply_review(pid, stem, reject=[rid], reason=reason_of.get(rid, ""), reason_code="disagree", by=body.by, data_dir=DATA_DIR)
        if reject_unconfirmed:
            apply_review(pid, stem, reject=reject_unconfirmed, reason="not confirmed at signing", reason_code="needs_confirmation", by=body.by, data_dir=DATA_DIR)
        # what was stated is accepted; a link into something rejected is skipped, not fatal
        done = []
        for aid in accept:
            try:
                done += apply_review(pid, stem, accept=[aid], by=body.by, data_dir=DATA_DIR)
            except (ValueError, KeyError):
                pass
        apply_review(pid, stem, accept_changes=True, by=body.by, data_dir=DATA_DIR)
    # close the dictated note without accepting what was set aside
    p = load_patient(pid, DATA_DIR)
    note = next((n for n in p.get("notes", []) if n["id"] == v["note"]["id"]), None)
    if note is not None:
        note["status"] = "signed"
        note["review"] = review_record("accepted", body.by, encounter_id=note.get("encounter_id") or open_encounter(p))
        save_patient(p, DATA_DIR)
    # the visit note, compiled from the record as it now stands, edited, signed, attesting everything accepted
    p = load_patient(pid, DATA_DIR)
    enc = open_encounter(p)
    batch = draft_note(p, enc, proposed_dir=PROPOSED_DIR, today=_today(as_of))
    doc = batch["proposed"]["documents"][0]
    edits = {(sec.get("heading") or "").strip(): sec.get("text") for sec in (body.sections or []) if isinstance(sec.get("text"), str)}
    for sec in doc["sections"]:
        t = edits.get(sec["heading"])
        if t is not None and t.strip() != sec["text"].strip():
            sec["text"] = t.strip(); sec["edited"] = True
    if body.authored and body.authored.strip():
        doc["sections"].append({"heading": "In the clinician's words", "text": body.authored.strip(), "cites": [], "source": "authored"})
    accept_item(p, batch, doc["id"], review=review_record("accepted", body.by, encounter_id=enc))
    stamped = attest(p, enc, doc["id"])
    save_patient(p, DATA_DIR)
    qp = PROPOSED_DIR / pid / f"{stem_for(enc)}.json"
    qp.parent.mkdir(parents=True, exist_ok=True)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    return {"document_id": doc["id"], "attested": stamped, "signed_at": doc["review"]["at"]}


@router.post("/patients/{pid}/visit/preview")
def preview_visit_note(pid: str, body: VisitSignBody, as_of: str | None = None):
    """The visit note as the signature would produce it, from a copy of the chart with the answers applied. Nothing is
    written: the clinician reads what they are about to sign, edits it, and signs from here or from the visit."""
    v = visit(pid, as_of)
    p = deepcopy(load_patient(pid, DATA_DIR))
    stem = next((x["stem"] for x in v["proposals"] if x.get("stem")), None)
    enc = open_encounter(p)
    if stem and v["note"].get("status") != "signed":
        _, batch = load_queue(pid, stem, PROPOSED_DIR)
        batch = deepcopy(batch)
        accept, reject_yes, reject_unconfirmed, reason_of = _plan_of_signature(v, body)
        for items in batch["proposed"].values():
            for it in items:
                if it["id"] in reject_yes:
                    it["status"] = "rejected"; it["review"] = review_record("rejected", body.by, reason_of.get(it["id"], ""), "disagree", encounter_id=enc)
                elif it["id"] in reject_unconfirmed:
                    it["status"] = "rejected"; it["review"] = review_record("rejected", body.by, "not confirmed at signing", "needs_confirmation", encounter_id=enc)
        for aid in accept:
            try:
                accept_item(p, batch, aid, review=review_record("accepted", body.by, encounter_id=enc))
            except (ValueError, KeyError):
                pass
        for ch in batch.get("medication_changes", []):
            if ch["status"] == "proposed":
                accept_medication_change(p, ch, review_record("accepted", body.by, encounter_id=enc))
        note = next((n for n in p.get("notes", []) if n["id"] == v["note"]["id"]), None)
        if note is not None:
            note["status"] = "signed"; note["review"] = review_record("accepted", body.by, encounter_id=enc)
    if not enc:
        raise HTTPException(404, "no encounter to document")
    doc = draft_note(p, enc, proposed_dir=PROPOSED_DIR, today=_today(as_of))["proposed"]["documents"][0]
    edits = {(sec.get("heading") or "").strip(): sec.get("text") for sec in (body.sections or []) if isinstance(sec.get("text"), str)}
    for sec in doc["sections"]:
        t = edits.get(sec["heading"])
        if t is not None and t.strip() != sec["text"].strip():
            sec["text"] = t.strip(); sec["edited"] = True
    if body.authored and body.authored.strip():
        doc["sections"].append({"heading": "In the clinician's words", "text": body.authored.strip(), "cites": [], "source": "authored"})
    return {"document": doc, "manifest": manifest(p, enc, proposed_dir=PROPOSED_DIR), "preview": True}
