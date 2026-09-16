"""The record as events: what a note, a signature or a model run wrote to the chart, in order.

    python3 -m ehr.record pt_002 [--note note_demo_102] [--since 2026-09-01]

There is no event ledger yet (PRD-01). This is the ledger *read* off what the chart already
keeps: every item carries provenance (which note, which model, which quote) and, once decided, a
review record (who, when, what). Folding those into one dated list gives the clinician the thing
the design asks for: seeing that a transcription updated the record, and what a signature
committed. Nothing here is stored; the day PRD-01 lands, this file becomes a query.

Event kinds mirror schema-v2-proposal.md §1: note.received, note.signed, problem.raised,
problem.status_changed, observation.recorded, medication.course_opened, medication.segment_closed,
medication.dose_changed, edge.asserted, plan.set, insight.raised, order.placed, document.signed,
proposal.rejected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ehr.extract import PROPOSED_DIR
from ehr.focus import focus_ids
from ehr.review import list_queues
from ehr.trend import DATA_DIR, load_patient

ORDER = ("note.received", "observation.recorded", "problem.raised", "problem.status_changed", "medication.course_opened",
         "medication.dose_changed", "medication.segment_closed", "edge.asserted", "plan.set", "insight.raised", "order.placed",
         "document.signed", "proposal.rejected", "note.signed")


def _names(patient: dict, queues: list[dict]) -> dict[str, str]:
    n = {p["id"]: p["name"] for p in patient["problems"]}
    n.update({m["id"]: m["name"] for m in patient["medications"]})
    n.update({o["id"]: f"{o['name']} {o['value']} {o['unit'] or ''}".strip() for o in patient["observations"]})
    n.update({x["id"]: f"note {x['id'].replace('note_', '')}" for x in patient["notes"]})
    for b in queues:
        for k, items in b["proposed"].items():
            for it in items:
                n.setdefault(it["id"], it.get("name") or it.get("text") or it.get("title") or it["id"])
    return n


def record_events(patient: dict, proposed_dir: Path = PROPOSED_DIR, *, note_id: str | None = None, since: str | None = None,
                  problem_id: str | None = None) -> list[dict]:
    queues = list_queues(patient["patient"]["id"], proposed_dir)
    names = _names(patient, queues)
    ev: list[dict] = []

    def add(kind, at, subject, text, *, by=None, source=None, note=None, quote=None, ids=()):
        ev.append({"kind": kind, "at": at, "subject": subject, "text": text, "by": by, "source": source, "note_id": note,
                   "quote": quote, "ids": [subject] + [i for i in ids if i and i != subject]})

    read = {b.get("note_id") for b in queues if b.get("note_id")}
    for n in patient.get("notes", []):
        if n["id"] in read or n.get("status"):
            add("note.received", n["time"], n["id"], f"Note from {n['author']} arrived", source="narrative", note=n["id"])
            rv = n.get("review")
            if n.get("status") == "signed" and rv:
                add("note.signed", rv["at"], n["id"], f"Note signed by {rv['by']}", by=rv["by"], source="review", note=n["id"])

    def prov_note(it):
        return (it.get("provenance") or {}).get("note_id")

    for x in patient.get("observations", []):
        rv = x.get("review")
        if rv and rv["decision"] == "accepted":
            add("observation.recorded", rv["at"], x["id"], f"{x['name']} {x['value']} {x['unit'] or ''} on {x['effective_time'][:10]}".strip(),
                by=rv["by"], source=x["provenance"]["source"], note=prov_note(x), quote=x["provenance"].get("quote"))
    for x in patient.get("problems", []):
        rv = x.get("review")
        if rv and rv["decision"] == "accepted":
            add("problem.raised", rv["at"], x["id"], f"Problem raised: {x['name']}", by=rv["by"], source=x["provenance"]["source"],
                note=prov_note(x), quote=x["provenance"].get("quote"))
    for m in patient.get("medications", []):
        rv = m.get("review")
        if rv and rv["decision"] == "accepted":
            seg = m["segments"][0]
            add("medication.course_opened", rv["at"], m["id"], f"Course opened: {m['name']} {seg.get('dose') or ''}".strip() + (f" from {seg['start']}" if seg.get("start") else ""),
                by=rv["by"], source=m["provenance"]["source"], note=prov_note(m), quote=m["provenance"].get("quote"))
    for l in patient.get("links", []):
        rv = l.get("review")
        if rv and rv["decision"] == "accepted" and l["type"] in ("suspected_cause", "evidence_for", "treats"):
            word = {"suspected_cause": "suspected cause of", "evidence_for": "evidence for", "treats": "treats"}[l["type"]]
            frm = names.get(l["from"], l["from"]) if not l["from"].startswith("note_") else "the note"
            to = names.get(l["to"], l["to"].replace("LOINC:", "series "))
            add("edge.asserted", rv["at"], l["id"], f"{frm} {word} {to}", by=rv["by"], source=l["provenance"]["source"],
                note=prov_note(l), quote=l["provenance"].get("quote"), ids=[l["from"], l["to"]])
    for pl in patient.get("plans", []):
        rv = pl.get("review")
        if rv and rv["decision"] == "accepted":
            add("plan.set", rv["at"], pl["id"], f"Plan ({pl['kind'].replace('_', ' ')}): {pl['text']} · {names.get(pl['problem_id'], pl['problem_id'])}",
                by=rv["by"], source=pl["provenance"]["source"], note=prov_note(pl), quote=pl["provenance"].get("quote"), ids=[pl["problem_id"]])
    for i in patient.get("insights", []):
        rv = i.get("review")
        if rv and rv["decision"] == "accepted":
            add("insight.raised", rv["at"], i["id"], f"Insight signed: {i['statement'][:90]}…", by=rv["by"], source=i["provenance"]["source"], ids=[i["problem_id"]])
    for o in patient.get("orders", []):
        rv = o.get("review")
        if rv and rv["decision"] == "accepted":
            add("order.placed", rv["at"], o["id"], f"Order: {o['name']}", by=rv["by"], source=o["provenance"]["source"], ids=[o["problem_id"]])
    for d in patient.get("documents", []):
        rv = d.get("review")
        if rv and rv["decision"] == "accepted":
            add("document.signed", rv["at"], d["id"], f"{d['kind'].title()} signed: {d['title'][:80]}", by=rv["by"], source=d["provenance"]["source"], ids=[d["problem_id"]])

    for b in queues:
        for ch in b.get("medication_changes", []):
            rv = ch.get("review")
            if rv and rv["decision"] == "accepted":
                kind = "medication.segment_closed" if ch["change"] == "stop" else "medication.dose_changed"
                what = "stopped" if ch["change"] == "stop" else f"{ch['change'].replace('_', ' ')}" + (f" → {ch['dose']}" if ch.get("dose") else "")
                add(kind, rv["at"], ch["med_id"], f"{names.get(ch['med_id'], ch['med_id'])} {what}, effective {ch['effective']}",
                    by=rv["by"], source=ch["provenance"].get("source"), note=b.get("note_id"), quote=ch["provenance"].get("quote"))
        for k, items in b["proposed"].items():
            for it in items:
                rv = it.get("review")
                if rv and rv["decision"] == "rejected":
                    what = it.get("name") or it.get("text") or it.get("title") or (f"{names.get(it.get('from'), it.get('from'))} → {names.get(it.get('to'), it.get('to'))}" if k == "links" else it["id"])
                    reason = f" · {rv['reason_code'].replace('_', ' ')}" if rv.get("reason_code") else ""
                    reason += f": “{rv['reason']}”" if rv.get("reason") else ""
                    add("proposal.rejected", rv["at"], it["id"], f"Rejected {k[:-1]}: {what}{reason}", by=rv["by"],
                        source=(it.get("provenance") or {}).get("source"), note=b.get("note_id"))

    if problem_id:
        focus = focus_ids(patient, problem_id)
        ev = [e for e in ev if e["kind"] in ("note.received", "note.signed") and any(x["note_id"] == e["note_id"] for x in ev if x["kind"] != "note.received" and set(x["ids"]) & focus)
              or (e["kind"] not in ("note.received", "note.signed") and set(e["ids"]) & focus)]
    if note_id:
        ev = [e for e in ev if e["note_id"] == note_id]
    if since:
        ev = [e for e in ev if e["at"] >= since]
    ev.sort(key=lambda e: (e["at"], ORDER.index(e["kind"]) if e["kind"] in ORDER else 99))
    return ev


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--note")
    ap.add_argument("--problem")
    ap.add_argument("--since")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    for e in record_events(load_patient(args.patient_id, data_dir), data_dir.parent / "proposed", note_id=args.note, since=args.since, problem_id=args.problem):
        print(f"{e['at'][:16]}  {e['kind']:<28} {e['text']}" + (f"  [{e['by']}]" if e["by"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
