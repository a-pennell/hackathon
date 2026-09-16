"""The patient Timeline: everything that happened, on one list, in five lanes. Computed, never stored.

    python3 -m ehr.timeline pt_002

Sessions (visits, with the note that documented them), results (one row per day of results, the
monitored series called out), documents (notes and letters, signed or not), changes (courses
opened, changed and closed; problems raised and resolved; plan items; orders) and reasoning
(insights, causes asserted, rejections with their reasons). A visit log shows only the first lane;
a record shows all five. Each item carries the ids it is about, so the views can hover them.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ehr.extract import PROPOSED_DIR
from ehr.reason import monitored_codes
from ehr.record import record_events
from ehr.trend import DATA_DIR, load_patient

LANES = ("sessions", "results", "documents", "changes", "reasoning")
LANE_RANK = {l: i for i, l in enumerate(LANES)}
SOURCE_WORD = {"fhir_import": "imported", "curated": "curated", "nlp_extraction": "from a note", "reasoning": "reasoned", "rules": "by rule", "orders": "from an insight", "clinician": "your decision"}


def _nice(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{f:.0f}" if abs(f) >= 100 else f"{f:.1f}" if abs(f) >= 10 else f"{f:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _out(o: dict) -> bool:
    rr = o.get("reference_range") or {}
    v = o.get("value")
    if not isinstance(v, (int, float)):
        return False
    return (rr.get("low") is not None and v < rr["low"]) or (rr.get("high") is not None and v > rr["high"])


def _note_tag(n: dict) -> str:
    """A note signed here, a note that arrived and is not yet signed, or a note that came with the import."""
    if n.get("status") == "signed" or n.get("review"):
        return "signed"
    return "unsigned" if n["id"].startswith("note_demo") else "imported"


def _when(x: dict, fallback: str) -> str:
    r = x.get("review") or {}
    return r.get("at") or x.get("created_at") or fallback


def _source(x: dict, notes: dict[str, dict]) -> str:
    prov = x.get("provenance") or {}
    src = prov.get("source")
    if src == "nlp_extraction" and prov.get("note_id") in notes:
        n = notes[prov["note_id"]]
        return f"from {n.get('author', 'the')}'s note of {n['time'][:10]}"
    return SOURCE_WORD.get(src, src or "")


def patient_timeline(patient: dict, *, proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> dict:
    today = today or date.today()
    names = {p["id"]: p["name"] for p in patient["problems"]}
    names.update({m["id"]: m["name"] for m in patient["medications"]})
    notes = {n["id"]: n for n in patient.get("notes", [])}
    note_by_enc = {n.get("encounter_id"): n for n in notes.values() if n.get("encounter_id")}
    monitored: set[str] = set()
    for p in patient["problems"]:
        monitored |= set(monitored_codes(patient, p["id"]))
    items: list[dict] = []

    def add(lane, at, kind, text, *, detail="", by=None, ids=(), tag=None):
        items.append({"lane": lane, "at": at, "day": at[:10], "kind": kind, "text": text, "detail": detail, "by": by, "ids": list(ids), "tag": tag})

    # sessions
    for e in patient.get("encounters", []):
        n = note_by_enc.get(e["id"])
        detail = f"note by {n['author']} · {_note_tag(n)}" if n else ""
        kind_text = f"{e['type'][0].upper()}{e['type'][1:]}"
        summary = e.get("summary") or ""
        text = kind_text if summary.lower() == e["type"].lower() else f"{kind_text} · {summary}".strip(" ·")
        add("sessions", e["time"], "visit", text, detail=detail, ids=[e["id"]] + ([n["id"]] if n else []))

    # results: one row per day, monitored series first
    by_day: dict[str, list[dict]] = {}
    for o in patient.get("observations", []):
        if o.get("status") == "accepted" and isinstance(o.get("value"), (int, float)):
            by_day.setdefault(o["effective_time"][:10], []).append(o)
    for day, obs in by_day.items():
        obs.sort(key=lambda o: (0 if o["code"]["value"] in monitored else 1, 0 if _out(o) else 1, o["name"]))
        lead = [o for o in obs if o["code"]["value"] in monitored]
        shown = lead[:6] or obs[:4]
        parts = [f"{o['name']} {_nice(o['value'])}{(' ' + o['unit']) if o.get('unit') else ''}" for o in shown]
        rest = len(obs) - len(shown)
        out = [o for o in obs if _out(o)]
        at = max(o["effective_time"] for o in obs)
        add("results", at, "results", f"{len(obs)} result{'s' if len(obs) != 1 else ''}",
            detail=", ".join(parts) + (f" · +{rest} more" if rest > 0 else ""), ids=[o["id"] for o in obs],
            tag=f"{len(out)} out of range" if out else None)

    # documents
    for n in notes.values():
        r = n.get("review") or {}
        add("documents", n["time"], "note", f"Note by {n.get('author', '?')}", detail=(n.get("text") or "").strip().replace("\n", " ")[:110] + "…",
            by=r.get("by"), ids=[n["id"]] + ([n["encounter_id"]] if n.get("encounter_id") else []), tag=_note_tag(n))
    for d in patient.get("documents", []):
        visit = d.get("kind") == "encounter_note"
        detail = ("addresses " + ", ".join(names.get(x, x) for x in d.get("problems_addressed") or [])) if visit \
            else f"{names.get(d.get('problem_id'), '')} · {d.get('audience', '')}".strip(" ·")
        add("documents", _when(d, d.get("created_at", today.isoformat())), "visit note" if visit else d.get("kind", "document"), d.get("title", "Document"),
            detail=detail, by=(d.get("review") or {}).get("by"), ids=[d["id"], d.get("problem_id"), d.get("encounter_id")] + list(d.get("problems_addressed") or []),
            tag="signed" if d.get("status") == "accepted" else d.get("status"))

    # changes: courses, problems, plans, orders
    for m in patient.get("medications", []):
        if m.get("status") != "accepted":
            continue
        segs = m.get("segments") or []
        src = _source(m, notes)
        for i, seg in enumerate(segs):
            prev = segs[i - 1] if i else None
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            # A later segment on an imported course came from a signed change, not the import; the segment carries
            # no provenance of its own (schema gap), so say nothing rather than "imported".
            later = "" if (i > 0 and (m.get("provenance") or {}).get("source") == "fhir_import") else src
            if seg.get("start"):
                if prev and prev.get("end") == seg["start"]:
                    add("changes", seg["start"], "dose", f"{m['name']} {prev.get('dose') or '?'} → {seg.get('dose') or '?'}", detail=later, ids=[m["id"]])
                else:
                    add("changes", seg["start"], "course", f"{m['name']} {seg.get('dose') or ''} started".replace("  ", " "), detail=later, ids=[m["id"]])
            if seg.get("end") and not (nxt and nxt.get("start") == seg["end"]):
                add("changes", seg["end"], "stopped", f"{m['name']} {seg.get('dose') or ''} stopped".replace("  ", " "), detail=later if i > 0 else src, ids=[m["id"]])
    for p in patient.get("problems", []):
        if p.get("status") == "proposed":
            continue
        src = _source(p, notes)
        if p.get("onset_date"):
            add("changes", p["onset_date"], "problem", f"Problem raised: {p['name']}", detail=src, ids=[p["id"]])
        if p.get("resolved_date"):
            add("changes", p["resolved_date"], "resolved", f"Problem resolved: {p['name']}", detail=src, ids=[p["id"]])
    for pl in patient.get("plans", []):
        add("changes", _when(pl, today.isoformat()), "plan", f"Plan ({pl['kind'].replace('_', ' ')}): {pl['text']}", detail=names.get(pl.get("problem_id"), ""),
            by=(pl.get("review") or {}).get("by"), ids=[pl["id"], pl.get("problem_id")], tag=pl.get("status") if pl.get("status") != "accepted" else "signed")
    for o in patient.get("orders", []):
        add("changes", o.get("ordered_at") or _when(o, today.isoformat()), "order", f"Order: {o['name']}", detail=names.get(o.get("problem_id"), ""),
            by=(o.get("review") or {}).get("by"), ids=[o["id"], o.get("problem_id")], tag="signed")

    # reasoning: insights, causes asserted, rejections
    for i in patient.get("insights", []):
        st = i.get("status")
        add("reasoning", _when(i, today.isoformat()), "insight", (i.get("statement") or "")[:170] + ("…" if len(i.get("statement") or "") > 170 else ""),
            detail=f"{names.get(i.get('problem_id'), '')} · {(i.get('provenance') or {}).get('model', '')}".strip(" ·"), by=(i.get("review") or {}).get("by"),
            ids=[i["id"], i.get("problem_id")] + list(i.get("evidence") or []), tag="signed" if st == "accepted" else st)
    for l in patient.get("links", []):
        if l.get("type") != "suspected_cause":
            continue
        n = notes.get((l.get("provenance") or {}).get("note_id"))
        at = (l.get("review") or {}).get("at") or l.get("created_at") or (n["time"] if n else today.isoformat())
        add("reasoning", at, "cause", f"{names.get(l['from'], l['from'])} is a suspected cause of {names.get(l['to'], l['to'])}",
            detail=_source(l, notes), by=(l.get("review") or {}).get("by"), ids=[l["id"], l["from"], l["to"]], tag="signed" if l.get("status") == "accepted" else l.get("status"))
    for ev in record_events(patient, proposed_dir):
        if ev["kind"] in ("chart.corrected", "note.amended"):
            add("documents" if ev["kind"] == "note.amended" else "changes", ev["at"], ev["kind"], ev["text"],
                detail=ev.get("quote") or "", by=ev.get("by"), ids=ev.get("ids") or [], tag="signed correction")
        if ev["kind"] == "proposal.rejected":
            add("reasoning", ev["at"], "rejected", ev["text"], detail=ev.get("quote") or "", by=ev.get("by"), ids=ev.get("ids") or [], tag="rejected")

    items.sort(key=lambda x: (x["at"][:10], -LANE_RANK[x["lane"]], x["at"]))
    items.reverse()  # newest day first; inside a day, sessions then results, documents, changes, reasoning
    lanes = {l: sum(1 for x in items if x["lane"] == l) for l in LANES}
    return {"patient_id": patient["patient"]["id"], "as_of": today.isoformat(), "lanes": lanes, "items": items}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    print(json.dumps(patient_timeline(load_patient(args.patient_id, data_dir), proposed_dir=data_dir.parent / "proposed"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
