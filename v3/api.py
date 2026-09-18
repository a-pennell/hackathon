"""v3: the visit as one surface. The transcript plays; the recorded reading is revealed as the transcript reaches each
finding's passage; findings land on the problem they touch; decisions wait as chips; the note grows the whole time.
No new model call: the same recorded extraction, positioned in the transcript by each finding's verbatim quote."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ehr.extract import PROPOSED_DIR, load_note_file, verbatim_quote
from ehr.review import list_queues
from ehr.trend import DATA_DIR, load_patient
from v2.api import _attach_note, _next_action, _followup, _today
from v2.monitor import problem_list, unattested

router = APIRouter(prefix="/v3/api")
ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "data" / "notes"

DECISION_LINKS = ("suspected_cause",)


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
                proposals.append({"id": it["id"], "kind": "cause" if cause else kind, "text": text_ + (f" · suspected cause of {', '.join(cause)}" if cause else ""),
                                  "problems": problems_of(it["id"], it) or ([it["id"]] if kind == "problem" else []), "quote": q, "offset": _offset(q, text),
                                  "decision": decision, "status": it.get("status"), "link_ids": [l["id"] for l in links], "stem": batch["stem"]})
        # links whose subject is already on the chart (a finding from the note, a restated result, a cause on an existing course)
        claimed = {x["id"] for k in ("problems", "medications", "observations", "plans") for x in pr.get(k, [])}
        for frm, links in by_from.items():
            if frm in claimed:
                continue
            for l in links:
                q = (l.get("provenance") or {}).get("quote")
                subj = names.get(frm, frm) if not frm.startswith("note_") else (batch.get("review_hints", {}).get(l["id"]) or "finding")
                rel = {"suspected_cause": "suspected cause of", "evidence_for": "evidence for", "relevant_to": "bears on", "treats": "treats"}.get(l["type"], l["type"])
                proposals.append({"id": l["id"], "kind": "cause" if l["type"] == "suspected_cause" else "finding", "text": f"{subj} · {rel} {names.get(l['to'], l['to'])}",
                                  "problems": [l["to"]] if l["to"].startswith("prob_") else [], "quote": q, "offset": _offset(q, text),
                                  "decision": l["type"] in DECISION_LINKS, "status": l.get("status"), "link_ids": [l["id"]], "stem": batch["stem"]})
        for c in batch.get("medication_changes", []):
            q = (c.get("provenance") or {}).get("quote")
            proposals.append({"id": f"change:{c['med_id']}", "kind": "course change", "text": f"{names.get(c['med_id'], c['med_id'])}: {c['change'].replace('_', ' ')}" + (f" to {c['dose']}" if c.get("dose") else ""),
                              "problems": [l["to"] for l in p["links"] if l["from"] == c["med_id"] and l["type"] == "treats"], "quote": q, "offset": _offset(q, text),
                              "decision": True, "status": c.get("status"), "link_ids": [], "stem": batch["stem"], "change": True})
    proposals.sort(key=lambda x: (x["offset"] if x["offset"] is not None else 10**9))
    return {"note": {"id": here["id"], "author": here["author"], "time": here["time"], "status": here.get("status"), "read": bool(batch), "file": here["file"]},
            "encounter": listing["here_for"]["encounter"], "utterances": _utterances(text), "text": text, "proposals": proposals,
            "problems": listing["problems"], "counts": listing["counts"], "next_action": _next_action(p, listing), "unattested": unattested(p), "followup": _followup(pid, p)}
