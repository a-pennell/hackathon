"""The visit note, compiled from what the clinician did: the chart writes the note.

    python3 -m ehr.draft pt_002 --encounter enc_c002

The demo runs one way today: a note arrives, it is read, proposals reach the chart once signed. This is the
same machinery the other way. Every action taken at a visit is already a dated, signed event with the visit
stamped on it (review.encounter_id): a problem raised, a cause asserted, a course stopped, a plan item set,
an insight signed, a proposal rejected with its reason. The draft selects the events of one encounter and
renders them into sections, each carrying the ids it came from. The transcript's own narrative, if the
visit had one, is the first section, verbatim. The clinician edits the prose and signs; nothing here is
authored by the system beyond the sentences that restate the record, and nothing reaches the chart until
the signature (queue `visitnote_<encounter_id>`, kind `encounter_note`, the Document shape of ehr/compose.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from ehr.card import problem_card
from ehr.extract import PROPOSED_DIR, save_patient
from ehr.reason import _accepted
from ehr.review import DEFAULT_REVIEWER, accept_item, list_queues, load_queue, review_record
from ehr.trend import DATA_DIR, load_patient

DRAFTER = "drafter-v1/rules"
KIND = "encounter_note"


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _nice(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{f:.0f}" if abs(f) >= 100 else f"{f:.1f}" if abs(f) >= 10 else f"{f:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _in_encounter(x: dict, enc_id: str, enc_day: str, note_id: str | None) -> bool:
    """An item belongs to the visit if its signature says so, or (older stamps) if it came from the visit's note."""
    r = x.get("review") or {}
    if r.get("encounter_id"):
        return r["encounter_id"] == enc_id
    prov = x.get("provenance") or {}
    return bool(note_id) and prov.get("note_id") == note_id


def draft_note(patient: dict, encounter_id: str, *, proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> dict:
    """Compile the visit note for one encounter as a proposed Document. Deterministic; no model call."""
    today = today or date.today()
    enc = next((e for e in patient.get("encounters", []) if e["id"] == encounter_id), None)
    if enc is None:
        raise KeyError(f"{encounter_id} is not on this chart")
    enc_day = enc["time"][:10]
    note = next((n for n in patient.get("notes", []) if n.get("encounter_id") == encounter_id), None)
    note_id = note["id"] if note else None
    names = {p["id"]: p["name"] for p in patient["problems"]}
    names.update({m["id"]: m["name"] for m in patient["medications"]})
    queues = list_queues(patient["patient"]["id"], proposed_dir)
    mine = lambda x: _in_encounter(x, encounter_id, enc_day, note_id)  # noqa: E731

    sections: list[dict] = []

    def add(heading, text, cites, source, problem_id=None):
        text = text.strip()
        if text:
            sections.append({"heading": heading, "text": text, "cites": list(dict.fromkeys(c for c in cites if c)), "source": source,
                             **({"problem_id": problem_id} if problem_id else {})})

    # 1. Subjective: the transcript, verbatim.
    if note:
        add("Subjective", note["text"], [note["id"]], "transcript")

    # 2. Objective: results recorded at the visit, and results reviewed at it.
    recorded = [o for o in _accepted(patient["observations"]) if o["effective_time"][:10] == enc_day]
    reviewed_ids = {l["from"] for l in _accepted(patient["links"]) if mine(l) and l["from"].startswith("obs_")}
    reviewed = [o for o in _accepted(patient["observations"]) if o["id"] in reviewed_ids and o["effective_time"][:10] != enc_day]
    parts = []
    if recorded:
        parts.append("Recorded at this visit: " + "; ".join(f"{o['name']} {_nice(o['value'])}{(' ' + o['unit']) if o.get('unit') else ''}" for o in recorded) + ".")
    if reviewed:
        parts.append("Reviewed: " + "; ".join(f"{o['name']} {_nice(o['value'])}{(' ' + o['unit']) if o.get('unit') else ''} ({_dmy(o['effective_time'])})" for o in reviewed) + ".")
    add("Objective", " ".join(parts), [o["id"] for o in recorded + reviewed], "compiled")

    # 3. Problems addressed: anything the visit's signatures touched.
    touched: dict[str, dict] = {}
    def touch(pid):
        if pid in names and pid.startswith("prob_"):
            touched.setdefault(pid, {"raised": False, "causes": [], "rejected": [], "insights": [], "plans": [], "orders": [], "courses": [], "evidence": []})
    for p in patient["problems"]:
        if p["status"] == "active" and mine(p):
            touch(p["id"]); touched[p["id"]]["raised"] = True
    for l in _accepted(patient["links"]):
        if not mine(l):
            continue
        for end in (l["from"], l["to"]):
            touch(end)
        if l["type"] == "suspected_cause" and l["to"] in touched:
            touched[l["to"]]["causes"].append(l)
        elif l["type"] == "evidence_for" and l["to"] in touched:
            touched[l["to"]]["evidence"].append(l)
    for b in queues:
        for l in b["proposed"].get("links", []):
            if l.get("status") == "rejected" and mine(l) and l["type"] == "suspected_cause":
                touch(l["to"])
                if l["to"] in touched:
                    touched[l["to"]]["rejected"].append(l)
    for i in patient.get("insights", []):
        if i.get("status") == "accepted" and mine(i):
            touch(i["problem_id"]); touched.get(i["problem_id"], {}).setdefault("insights", []).append(i)
    for pl in patient.get("plans", []):
        if mine(pl):
            touch(pl["problem_id"]); touched.get(pl["problem_id"], {}).setdefault("plans", []).append(pl)
    for o in patient.get("orders", []):
        if mine(o):
            touch(o["problem_id"]); touched.get(o["problem_id"], {}).setdefault("orders", []).append(o)
    # courses changed on the visit day, attached to the problems they are linked to
    for m in _accepted(patient["medications"]):
        events = []
        segs = m.get("segments") or []
        for i, seg in enumerate(segs):
            prev = segs[i - 1] if i else None
            if seg.get("start") == enc_day:
                events.append(f"{m['name']} {prev.get('dose') or '?'} → {seg.get('dose') or '?'}" if prev and prev.get("end") == enc_day else f"{m['name']} {seg.get('dose') or ''} started".replace("  ", " "))
            if seg.get("end") == enc_day and not (i + 1 < len(segs) and segs[i + 1].get("start") == enc_day):
                events.append(f"{m['name']} {seg.get('dose') or ''} stopped".replace("  ", " "))
        if not events:
            continue
        linked = {l["to"] for l in _accepted(patient["links"]) if l["from"] == m["id"] and l["type"] in ("treats", "suspected_cause")}
        for pid in linked:
            touch(pid)
            if pid in touched:
                touched[pid]["courses"] += [(e, m["id"]) for e in events]

    order = [p["id"] for p in patient["problems"] if p["id"] in touched]
    win = {"start": (date.fromisoformat(enc_day).replace(year=date.fromisoformat(enc_day).year - 1)).isoformat(), "end": enc_day}
    for pid in order:
        t = touched[pid]
        pname = names[pid]
        lines, cites = [], [pid]
        if t["raised"]:
            lines.append(f"{pname}, raised at this visit.")
            if note_id:
                cites.append(note_id)
        try:
            card = problem_card(patient, pid, win, proposed_dir=proposed_dir, today=today)
            rep = (card.get("representation") or {}).get("text")
            if rep:
                lines.append(rep)
                cites += (card.get("representation") or {}).get("cites") or []
        except Exception:
            pass
        rep_text = " ".join(lines).lower()
        for l in t["causes"]:
            cause = names.get(l["from"], l["from"])
            if cause.lower() not in rep_text:  # the representation already says it when the course is linked
                lines.append(f"{cause} is recorded as a suspected cause of {pname}.")
            cites += [l["id"], l["from"]]
        for l in t["rejected"]:
            r = l.get("review") or {}
            why = f" {r['reason']}" if r.get("reason") else ""
            lines.append(f"{names.get(l['from'], l['from'])} was proposed as a cause and rejected:{why}".rstrip(":") + ("" if why else "."))
            cites.append(l["id"])
        for i in t["insights"]:
            lines.append(i["statement"])
            cites += [i["id"]] + list(i.get("evidence") or [])
        if lines:
            add(f"Assessment · {pname}", " ".join(lines), cites, "compiled", pid)
        plan_lines, pcites = [], [pid]
        plan_text = " ".join(pl["text"] for pl in t["plans"]).lower()
        for e, mid in t["courses"]:
            if names.get(mid, "").split(" ")[0].lower() in plan_text:  # the plan item already says it
                pcites.append(mid); continue
            plan_lines.append(e + "."); pcites.append(mid)
        for pl in t["plans"]:
            plan_lines.append(f"{pl['kind'].replace('_', ' ').capitalize()}: {pl['text']}."); pcites.append(pl["id"])
        for o in t["orders"]:
            plan_lines.append(f"Order: {o['name']}" + (f", {o['detail']}" if o.get("detail") else "") + "."); pcites.append(o["id"])
        for i in t["insights"]:
            if i.get("suggested_action"):
                plan_lines.append(i["suggested_action"].removeprefix("Consider ").capitalize().rstrip(".") + " (signed insight)."); pcites.append(i["id"])
        if plan_lines:
            add(f"Plan · {pname}", " ".join(plan_lines), pcites, "compiled", pid)

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    author = (note or {}).get("author") or DEFAULT_REVIEWER
    doc = {
        "id": f"doc_{encounter_id}_note", "patient_id": patient["patient"]["id"], "problem_id": None, "encounter_id": encounter_id,
        "kind": KIND, "audience": "chart", "title": f"Visit note · {_dmy(enc['time'])} · {author}",
        "sections": sections, "questions": [], "problems_addressed": order, "status": "proposed",
        "provenance": {"source": "composition", "model": DRAFTER, "evidence": list(dict.fromkeys(c for s in sections for c in s["cites"])),
                       "confidence": 1.0, **({"note_id": note_id} if note_id else {})},
        "created_at": now,
    }
    return {"patient_id": patient["patient"]["id"], "encounter_id": encounter_id, "kind": KIND, "model": DRAFTER, "composed_at": now,
            "proposed": {"documents": [doc]}, "review_hints": {}, "rejected": []}


def stem_for(encounter_id: str) -> str:
    return f"visitnote_{encounter_id}"


def run_draft(patient_id: str, encounter_id: str, *, data_dir: Path = DATA_DIR) -> dict:
    """Compile and queue the draft. Re-running replaces an unsigned draft; a signed one is left alone."""
    data_dir = Path(data_dir)
    proposed_dir = data_dir.parent / "proposed"
    patient = load_patient(patient_id, data_dir)
    qp = proposed_dir / patient_id / f"{stem_for(encounter_id)}.json"
    if qp.exists():
        old = json.loads(qp.read_text())
        if any(d.get("status") == "accepted" for d in old["proposed"].get("documents", [])):
            old["stem"] = qp.stem
            return old
    batch = draft_note(patient, encounter_id, proposed_dir=proposed_dir)
    qp.parent.mkdir(parents=True, exist_ok=True)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    batch["stem"] = qp.stem
    return batch


def sign_draft(patient_id: str, encounter_id: str, sections: list[dict] | None, *, by: str = DEFAULT_REVIEWER,
               data_dir: Path = DATA_DIR) -> dict:
    """Take the clinician's edited text, keep every citation, and sign the note into the chart's documents."""
    data_dir = Path(data_dir)
    qp, batch = load_queue(patient_id, stem_for(encounter_id), data_dir.parent / "proposed")
    doc = batch["proposed"]["documents"][0]
    if sections:
        for i, sec in enumerate(sections):
            if i < len(doc["sections"]) and isinstance(sec.get("text"), str):
                if sec["text"].strip() != doc["sections"][i]["text"].strip():
                    doc["sections"][i]["text"] = sec["text"].strip()
                    doc["sections"][i]["edited"] = True
    patient = load_patient(patient_id, data_dir)
    done = accept_item(patient, batch, doc["id"], review=review_record("accepted", by, encounter_id=encounter_id))
    save_patient(patient, data_dir)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    return {"document_id": doc["id"], "signed_at": doc["review"]["at"], "by": by, "done": done}


def render_text(doc: dict) -> str:
    out = [doc["title"], ""]
    for s in doc["sections"]:
        out += [s["heading"].upper(), s["text"], ""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--encounter", required=True)
    ap.add_argument("--sign", action="store_true", help="sign the queued draft as it stands")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    if args.sign:
        print(json.dumps(sign_draft(args.patient_id, args.encounter, None, data_dir=Path(args.data_dir)), indent=2))
        return 0
    batch = run_draft(args.patient_id, args.encounter, data_dir=Path(args.data_dir))
    print(render_text(batch["proposed"]["documents"][0]))
    print(f"\nreview queue: {Path(args.data_dir).parent / 'proposed' / args.patient_id / (batch['stem'] + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
