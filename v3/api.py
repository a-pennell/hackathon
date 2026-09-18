"""v3: the visit as one surface. The transcript plays; the recorded reading is revealed as the transcript reaches each
finding's passage; findings land on the problem they touch; decisions wait as chips; the note grows the whole time.
No new model call: the same recorded extraction, positioned in the transcript by each finding's verbatim quote."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException

from datetime import date, timedelta

from pydantic import BaseModel

from ehr.draft import draft_note, stem_for
from ehr.extract import PROPOSED_DIR, load_note_file, save_patient, verbatim_quote
from ehr.review import DEFAULT_REVIEWER, accept_item, apply_review, list_queues, open_encounter, review_record
from ehr.trend import DATA_DIR, load_patient
from v2.monitor import attest, manifest
from v2.guidelines import guidelines
from v2.simulate import EFFECTS, _context, expectations
from v2.api import _attach_note, _next_action, _followup, _today
from v2.monitor import problem_list, problem_view, unattested

router = APIRouter(prefix="/v3/api")
ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "data" / "notes"

DECISION_LINKS = ("suspected_cause",)
CAUSAL_CUES = ("contribut", "cause", "caus", "due to", "secondary to", "because of", "attribut", "driver", "driven", "from the", "worsen", "raise", "raising", "induced", "related to",
               "explain", "blame", "aggravat", "exacerbat", "precipitat", "trigger", "responsible for", "accounts for", "account for", "on the back of", "culprit", "the result of", "provoked")
# A dictation says what is not so as often as what is. The cue words above appear in both, so a passage carrying any of
# these is never read as asserting a relation: it falls to "inferred", which asks. The asymmetry is the whole point —
# a wrong "inferred" costs one click, a wrong "stated" attests a claim the clinician did not make.
# When the extractor has judged the passage itself, that judgement stands. This narrow list is the one veto kept over
# it — phrases that deny the relation outright — because a model saying "asserted" about a sentence that says the
# opposite is the single error the signature cannot absorb. It is deliberately much shorter than NEGATION below.
DENIAL = re.compile(r"\b(not due to|not from|not the cause|no evidence|no reason to think|doubt|unlikely|ruled? out|denies|denied|rather than)\b", re.I)
NEGATION = re.compile(r"\b(no|not|n't|never|none|negative|without|denies|denied|doubt|doubtful|unlikely|ruled? out|rules out|excluded?|absent|rather than|resolved|against|nothing|neither|nor)\b", re.I)
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


def _origin(kind: str, quote: str | None, *, cause_name: str | None = None, problem_name: str | None = None,
            asserted: bool | None = None) -> str:
    """'stated': the passage itself makes the claim, so the dictation already decided it and the note's signature covers
    it. 'inferred': the reading went past what the passage says, or the passage is not plainly asserting it; that one is
    put to the clinician.

    `asserted` is the extractor's own answer to that question, recorded when it read the passage (schema §13). It is
    better evidence than anything recoverable afterwards from cue words, so it decides — subject to one narrow veto.
    Without it the rule below applies, and because the rule cannot read, it is blunt on purpose: only a cause or a new
    problem can be waved through at all, and any negation in the passage sends it to the clinician instead."""
    if not quote:
        return "inferred"
    if kind in ("cause", "problem") and asserted is not None:
        if not asserted:
            return "inferred"
        return "inferred" if DENIAL.search(quote) else "stated"
    if kind in ("cause", "problem") and NEGATION.search(quote):
        return "inferred"  # the passage may be denying it; a denial read as an assertion is the one error we cannot make
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


def _practice(patient: dict, today: date | None) -> list[dict]:
    """Best practice for each active problem, against the plan as it stands. Before the visit that is the chart; while
    the note builds it is the draft's copy, so an item the clinician has just dictated reads as covered. Deciding is a
    step of the reasoning, and this is its checklist — sourced rules, not a model, and never written to the note."""
    out = []
    for pr in patient["problems"]:
        if pr["status"] != "active":
            continue
        for r in guidelines(patient, pr, today=today or date.today()):
            out.append({"problem_id": pr["id"], "problem": pr["name"], **{k: r[k] for k in ("id", "text", "source", "status", "action")}})
    return out


def _options_on_plan(patient: dict) -> dict[str, list[str]]:
    """Which projected options each problem's plan already covers, by the same on_plan rules the options themselves use
    (v2/simulate.py). Evaluated on the draft's copy of the chart, so an option the clinician has just dictated — the
    metformin extended-release switch — reads as on the plan instead of offering to add it again."""
    out = {}
    for pr in patient["problems"]:
        if pr["status"] != "active":
            continue
        ctx = _context(patient, {pr["id"]})
        ids = [e["id"] for e in EFFECTS if e["applies"](ctx) and e["on_plan"](ctx)]
        if ids:
            out[pr["id"]] = ids
    return out


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
                cause_l = next((l for l in links if l["type"] == "suspected_cause"), None)
                cause_q = ((cause_l or {}).get("provenance") or {}).get("quote")
                origin = (_origin("cause", cause_q, cause_name=it.get("name"), asserted=((cause_l or {}).get("provenance") or {}).get("asserted")) if cause
                          else _origin(kind, q, problem_name=it.get("name"), asserted=(it.get("provenance") or {}).get("asserted")))
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
                origin = _origin("cause", q, cause_name=names.get(frm, frm), asserted=(l.get("provenance") or {}).get("asserted")) if l["type"] == "suspected_cause" else "stated"
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
            "problems": listing["problems"], "counts": listing["counts"], "next_action": _next_action(p, listing), "unattested": unattested(p), "followup": _followup(pid, p),
            "practice": _practice(p, _today(as_of))}


def _plan_of_signature(v: dict, body: "VisitSignBody") -> tuple[list[str], list[str], list[str], dict]:
    """What the signature does with the visit's proposals: ids to accept, ids rejected with a reason, ids set aside.
    A stated finding is accepted with its links. For an inferred cause the answer applies to the relation only; the
    thing itself (the course, the result) stays."""
    accept, reject_yes, reject_unconfirmed, reason_of = [], [], [], {}
    heard = set(body.heard) if body.heard is not None else None
    for p in v["proposals"]:
        if p["status"] != "proposed" or p.get("change"):
            continue
        if heard is not None and p["id"] not in heard:
            continue  # not spoken yet: neither taken nor set aside
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
    sections: list[dict] | None = None   # edits to the compiled note, by section key
    authored: str | None = None
    by: str = DEFAULT_REVIEWER
    # How far the dictation has got, for the note as it builds: the proposals the transcript has reached, and the
    # character it has reached. A preview only. A clinician signs the visit when the dictation is finished, not partway.
    heard: list[str] | None = None
    upto: int | None = None


@contextmanager
def _scratch(pid: str):
    """A throwaway copy of the chart and the queue. The preview runs the real signature against this, so reading the
    note and signing it are the same code, not two implementations that have to be kept in agreement."""
    with tempfile.TemporaryDirectory(prefix="visit-preview-") as tmp:
        root = Path(tmp)
        (root / "patients").mkdir()
        (root / "proposed" / pid).mkdir(parents=True)
        shutil.copy(DATA_DIR / f"{pid}.json", root / "patients" / f"{pid}.json")
        for q in (PROPOSED_DIR / pid).glob("*.json"):
            shutil.copy(q, root / "proposed" / pid / q.name)
        yield root / "patients", root / "proposed"


def _perform_signature(pid: str, v: dict, body: "VisitSignBody", *, data_dir: Path, proposed_dir: Path, as_of: str | None):
    """Everything the signature does, against whichever chart it is handed: the real one when signing, a throwaway copy
    when the clinician is only reading what they would sign. Returns the chart as it now stands, the encounter, the
    compiled batch and the note itself — edited and in the clinician's words, ready to be written or read."""
    stem = next((x["stem"] for x in v["proposals"] if x.get("stem")), None)
    if stem and v["note"].get("status") != "signed":
        accept, reject_yes, reject_unconfirmed, reason_of = _plan_of_signature(v, body)
        for rid in reject_yes:
            apply_review(pid, stem, reject=[rid], reason=reason_of.get(rid, ""), reason_code="disagree", by=body.by, data_dir=data_dir)
        if reject_unconfirmed:
            apply_review(pid, stem, reject=reject_unconfirmed, reason="not confirmed at signing", reason_code="needs_confirmation", by=body.by, data_dir=data_dir)
        # what was stated is accepted; a link into something rejected is skipped, not fatal
        for aid in accept:
            try:
                apply_review(pid, stem, accept=[aid], by=body.by, data_dir=data_dir)
            except (ValueError, KeyError):
                pass
        # course changes are taken together; while the note is building they wait until all of them have been spoken
        changes = [x["id"] for x in v["proposals"] if x.get("change")]
        if body.heard is None or set(changes) <= set(body.heard):
            apply_review(pid, stem, accept_changes=True, by=body.by, data_dir=data_dir)
        # close the dictated note without accepting what was set aside
        p = load_patient(pid, data_dir)
        note = next((n for n in p.get("notes", []) if n["id"] == v["note"]["id"]), None)
        if note is not None:
            note["status"] = "signed"
            note["review"] = review_record("accepted", body.by, encounter_id=note.get("encounter_id") or open_encounter(p))
            save_patient(p, data_dir)
    # the visit note, compiled from the record as it now stands
    p = load_patient(pid, data_dir)
    enc = open_encounter(p)
    if not enc:
        raise HTTPException(404, "no encounter to document")
    batch = draft_note(p, enc, proposed_dir=proposed_dir, today=_today(as_of), transcript_upto=body.upto)
    doc = batch["proposed"]["documents"][0]
    edits = {(sec.get("key") or sec.get("heading") or "").strip(): sec.get("text") for sec in (body.sections or []) if isinstance(sec.get("text"), str)}
    for sec in doc["sections"]:
        t = edits.get(sec.get("key")) or edits.get(sec["heading"])
        if t is not None and t.strip() != sec["text"].strip():
            sec["text"] = t.strip(); sec["edited"] = True
    if body.authored and body.authored.strip():
        doc["sections"].append({"heading": "In the clinician's words", "text": body.authored.strip(), "cites": [], "source": "authored"})
    return p, enc, batch, doc


@router.post("/patients/{pid}/visit/sign")
def sign_visit(pid: str, body: VisitSignBody, as_of: str | None = None):
    """Dictate, then sign: the one act. Everything the dictation stated is accepted by the signature; what the reading
    inferred beyond the dictation is taken only if the clinician said yes, rejected if they said no, and set aside
    (rejected as unconfirmed, undoable) if they said nothing. Then the note is closed and the visit note is compiled from
    the record as it now stands and signed, with the clinician's edits and their own words."""
    v = visit(pid, as_of)
    if v["note"].get("status") == "signed":
        raise HTTPException(400, "this visit's note is already signed")
    if body.heard is not None or body.upto is not None:
        raise HTTPException(400, "the visit is signed whole, once the dictation is finished; heard and upto are for the note as it builds")
    p, enc, batch, doc = _perform_signature(pid, v, body, data_dir=DATA_DIR, proposed_dir=PROPOSED_DIR, as_of=as_of)
    accept_item(p, batch, doc["id"], review=review_record("accepted", body.by, encounter_id=enc))
    stamped = attest(p, enc, doc["id"])
    save_patient(p, DATA_DIR)
    qp = PROPOSED_DIR / pid / f"{stem_for(enc)}.json"
    qp.parent.mkdir(parents=True, exist_ok=True)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    return {"document_id": doc["id"], "attested": stamped, "signed_at": doc["review"]["at"]}


@router.post("/patients/{pid}/visit/preview")
def preview_visit_note(pid: str, body: VisitSignBody, as_of: str | None = None):
    """The visit note as the signature would produce it: the same signature, run against a copy of the chart that is
    thrown away. Nothing is written. The clinician reads what they are about to sign, edits it, and signs from here."""
    v = visit(pid, as_of)
    with _scratch(pid) as (data_dir, proposed_dir):
        p, enc, _, doc = _perform_signature(pid, v, body, data_dir=data_dir, proposed_dir=proposed_dir, as_of=as_of)
        return {"document": doc, "manifest": manifest(p, enc, proposed_dir=proposed_dir), "preview": True,
                "practice": _practice(p, _today(as_of)), "on_plan": _options_on_plan(p)}


# --------------------------------------------------------------------------- what the signature committed to

WHEN = re.compile(r"\bin (\d+)\s*(day|week|month)s?\b", re.I)


def _dmy(iso: str) -> str:
    return date.fromisoformat(iso[:10]).strftime("%-d %b %Y")


def _due(text: str, start: date) -> str | None:
    """A plan line that says when ("BMP in 2 weeks") is a date the chart can wait for."""
    m = WHEN.search(text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return (start + timedelta(days=n * {"day": 1, "week": 7, "month": 30}[unit])).isoformat()


@router.get("/patients/{pid}/commitments")
def commitments(pid: str, as_of: str | None = None):
    """What the visit committed to, once it is signed: the values the plan is expected to move and how far, what the
    plan promised and when, and what was left unanswered. The signature is not the end of the visit — it is the point
    where the chart starts waiting for something, and this is the list of what."""
    p = load_patient(pid, DATA_DIR)
    today = _today(as_of) or date.today()
    enc = open_encounter(p) or next((e["id"] for e in reversed(p.get("encounters", []))), None)
    e = next((x for x in p.get("encounters", []) if x["id"] == enc), None)
    day = date.fromisoformat(e["time"][:10]) if e else today
    names = {x["id"]: x["name"] for x in p["problems"]}
    touched = [x for x in p["problems"] if x["status"] == "active" and any(pl.get("problem_id") == x["id"] for pl in p.get("plans", []))]
    watching: list[dict] = []
    seen = set()
    for prob in touched:
        for m in expectations(p, prob["id"], today=today):
            key = (m["id"], m["value"]["code"])
            if key in seen:
                continue
            seen.add(key)
            o = m["observed"]
            watching.append({"kind": "expectation", "problem": prob["name"], "problem_id": prob["id"],
                             "text": f"{m['value']['name']} {'at or under' if m['limit_kind'] == 'rise' else 'under'} {m['limit']} {m['value']['unit']}".strip(),
                             "detail": f"from {m['baseline']['value']} on {_dmy(m['baseline']['time'])} · {m['expect']}",
                             "by": m["by"], "tested_by": (m["tested_by"] or {}).get("text"), "ids": m["ids"],
                             "status": o["status"] if o else "waiting", "observed": o, "source": m["source"]})
        # the projection comes from the same view the problem page renders, so the two cannot disagree
        cc = problem_view(p, prob["id"], proposed_dir=PROPOSED_DIR, today=today)["answers"]["change_course"]
        cp, of = cc.get("projection"), cc.get("projection_of")
        if cp and of:
            ob = cp.get("observed")
            watching.append({"kind": "projection", "problem": prob["name"], "problem_id": prob["id"],
                             "text": f"{of['name']} {cp['at_full_effect']['low']} to {cp['at_full_effect']['high']} {of.get('unit') or ''}".strip(),
                             "detail": f"on the current plan: {'; '.join(cp['labels']).lower()}", "by": cp["full_effect_by"],
                             "tested_by": None, "ids": [], "status": ob["status"] if ob else "waiting", "observed": ob, "source": of["note"]})
    for pl in p.get("plans", []):
        due = _due(pl["text"], day)
        if due:
            watching.append({"kind": "plan", "problem": names.get(pl.get("problem_id"), ""), "problem_id": pl.get("problem_id"),
                             "text": pl["text"], "detail": "promised at this visit", "by": due, "tested_by": None,
                             "ids": [pl["id"]], "status": "waiting", "observed": None, "source": None})
    aside = next((g for g in manifest(p, enc, proposed_dir=PROPOSED_DIR) if g["kind"] == "set_aside"), None)
    for it in (aside or {}).get("items", []):
        watching.append({"kind": "set_aside", "problem": "", "problem_id": None, "text": it["text"], "detail": "undoable, and off the note until it is answered",
                         "by": None, "tested_by": None, "ids": [it["id"]], "status": "unanswered", "observed": None, "source": None})
    # a promise whose answer is already on the chart is not still waiting: the expectations it was to settle say so
    answered_by = {}
    for w in watching:
        if w["kind"] == "expectation" and w["tested_by"] and w["observed"]:
            prev = answered_by.get(w["tested_by"])
            if not prev or w["observed"]["time"] < prev["time"]:
                answered_by[w["tested_by"]] = w["observed"]
    for w in watching:
        if w["kind"] == "plan" and w["text"] in answered_by:
            w["status"], w["observed"] = "resulted", answered_by[w["text"]]
    watching.sort(key=lambda w: (w["by"] or "9999"))
    open_ = [w for w in watching if w["status"] == "waiting"]
    return {"as_of": today.isoformat(), "encounter": enc, "signed": _signed_note(p, enc), "watching": watching,
            "open": len(open_), "next_date": next((w["by"] for w in open_ if w["by"]), None), "followup": _followup(pid, p)}


def _signed_note(patient: dict, enc: str | None) -> dict | None:
    d = next((x for x in patient.get("documents", []) if x.get("kind") == "encounter_note" and (x.get("review") or {}).get("encounter_id") == enc), None)
    return {"id": d["id"], "title": d["title"]} if d else None
