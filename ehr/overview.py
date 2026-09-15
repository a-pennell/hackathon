"""The patient overview: orientation in under ten seconds, computed from the chart. Never stored.

    python3 -m ehr.overview pt_001 [--since 2026-07-29]

Answers the Level 1 questions of docs/design/clinical-reasoning-ehr.md §7: who is this, why are
they here, what are the major active concerns, what changed since I last looked, what needs
attention. "What changed" is ranked by clinical meaning (§9), not listed by time:

    1  a missed expectation or a triggered contingency
    2  a proposed status or staging change on an active problem
    3  a medication change on a course linked to an active problem
    4  a monitored parameter crossing its range or moving more than a quarter
    6  a new unexplained finding (a doesn't-fit line dated inside the window)
    8  everything else: other medication changes, proposals waiting, decisions made

(5 goal progress and 7 setting changes have no objects on this chart yet.)

Problems that monitor exactly the same series are one concern here (the four CKD-stage entries
Synthea imports become "Chronic kidney disease stage 3 · 3 related entries"); the merge itself is
a proposal for the steward (PRD-03), never something a view does silently.

`since` defaults to the last routine visit before the newest encounter, at least two weeks earlier,
so a burst of visits in one week reads as one visit.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from ehr.card import problem_card
from ehr.extract import PROPOSED_DIR
from ehr.reason import _accepted, monitored_codes
from ehr.review import list_queues
from ehr.trend import DATA_DIR, load_patient

ROUTINE = ("check up", "office visit", "follow", "general exam", "encounter for problem")
MIN_GAP_DAYS = 14
TOP_CHANGES = 5
TOP_CONCERNS = 6
MOVED_PCT = 25


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')}"


def _since(patient: dict, today: date) -> dict:
    encs = sorted((e for e in patient["encounters"] if e["time"][:10] <= today.isoformat()), key=lambda e: e["time"])
    if not encs:
        return {"date": (today - timedelta(days=90)).isoformat(), "why": "no visits on the chart; last 90 days"}
    newest = encs[-1]
    cutoff = (date.fromisoformat(newest["time"][:10]) - timedelta(days=MIN_GAP_DAYS)).isoformat()
    for e in reversed(encs[:-1]):
        if e["time"][:10] <= cutoff and any(w in e["type"].lower() for w in ROUTINE):
            return {"date": e["time"][:10], "why": f"your last routine visit before {_dmy(newest['time'])} ({e['type']})", "encounter_id": e["id"]}
    return {"date": (today - timedelta(days=90)).isoformat(), "why": "no earlier routine visit; last 90 days"}


def clusters(patient: dict) -> list[dict]:
    """Active problems grouped by identical monitored-series sets; the newest entry represents the group."""
    groups: dict[str, list[dict]] = {}
    codes_of: dict[str, list[str]] = {}
    for p in patient["problems"]:
        if p["status"] != "active":
            continue
        codes = sorted(monitored_codes(patient, p["id"]))
        key = ",".join(codes) if codes else p["id"]
        groups.setdefault(key, []).append(p)
        codes_of[key] = codes
    out = []
    for key, members in groups.items():
        members.sort(key=lambda p: p.get("onset_date") or "", reverse=True)
        out.append({"problem": members[0], "members": members[1:], "codes": codes_of[key]})
    return out


def _linked_meds(patient: dict, problem_ids: list[str], codes: list[str]) -> set[str]:
    targets = set(problem_ids) | {f"LOINC:{c}" for c in codes}
    return {l["from"] for l in _accepted(patient["links"]) if l["type"] in ("treats", "suspected_cause") and l["to"] in targets}


def _med_events(patient: dict, start: str, end: str) -> list[dict]:
    """Every start, stop and dose change on the medication list inside [start, end]."""
    events = []
    for m in _accepted(patient["medications"]):
        segs = m.get("segments") or []
        for i, seg in enumerate(segs):
            prev = segs[i - 1] if i else None
            if seg.get("start") and start <= seg["start"] <= end:
                if prev and prev.get("end") == seg["start"]:
                    events.append({"med_id": m["id"], "kind": "dose change", "date": seg["start"], "text": f"{m['name']} {prev.get('dose') or '?'} → {seg.get('dose') or '?'}"})
                else:
                    events.append({"med_id": m["id"], "kind": "started", "date": seg["start"], "text": f"{m['name']} {seg.get('dose') or ''} started".replace("  ", " ")})
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if seg.get("end") and start <= seg["end"] <= end and not (nxt and nxt.get("start") == seg["end"]):
                events.append({"med_id": m["id"], "kind": "stopped", "date": seg["end"], "text": f"{m['name']} {seg.get('dose') or ''} stopped".replace("  ", " ")})
    return events


def _pending_for(patient: dict, problem_ids: list[str], codes: list[str], queues: list[dict]) -> int:
    focus = set(problem_ids) | {f"LOINC:{c}" for c in codes}
    n = 0
    for b in queues:
        plinks = [l for l in b["proposed"].get("links", []) if l["status"] == "proposed" and (l["to"] in focus or l["from"] in focus)]
        touched = {l["from"] for l in plinks} | {l["to"] for l in plinks}
        hints = b.get("review_hints") or {}
        for k, items in b["proposed"].items():
            for it in items:
                if it["status"] != "proposed":
                    continue
                if (it.get("problem_id") in focus or it["id"] in touched or it["id"] in focus or (k == "links" and it in plinks)
                        or any(pid in hints.get(it["id"], "") for pid in problem_ids)):
                    n += 1
    return n


def _changes_for(patient: dict, cluster: dict, card: dict | None, since: str, today: str, queues: list[dict], med_events: list[dict], obs_dates: dict) -> list[dict]:
    p = cluster["problem"]
    ids = [p["id"]] + [m["id"] for m in cluster["members"]]
    out = []

    def line(rank, kind, text, why, cite, tag=None, key=None):
        out.append({"rank": rank, "kind": kind, "text": text, "why": why, "ids": cite, "problem_id": p["id"], "problem_name": p["name"], "tag": tag, "key": key or (kind, text)})

    if card:
        exp = card.get("expected")
        if exp and exp["status"] == "missed":
            line(1, "expectation", f"Expected {exp['statement'][0].lower() + exp['statement'][1:]}; it did not", f"due {_dmy(exp['by'])}", exp["ids"], "mismatch")

    for b in queues:
        for it in b["proposed"].get("problems", []):
            hint = (b.get("review_hints") or {}).get(it["id"], "")
            if it["status"] == "proposed" and any(pid in hint for pid in ids):
                line(2, "restage", f"{it['name']} proposed in place of {p['name']}", f"from note {b.get('note_id', '').replace('note_', '')} · waiting for your decision", [it["id"], p["id"]], "proposed", key=("restage", it["id"]))

    linked = _linked_meds(patient, ids, cluster["codes"])
    for e in med_events:
        if e["med_id"] in linked:
            line(3, "medication", f"{e['text']}, {_dmy(e['date'])}", "on a course linked to this problem", [e["med_id"]], key=("med", e["med_id"], e["kind"], e["date"]))

    if card:
        lead = next((x for x in card["supporting"] if x["kind"] == "result"), None)
        crossed = any(q["label"] == "worsening" for q in card["qualifiers"])
        if lead:
            pct = 0.0
            try:
                pct = float(lead["detail"].split("%")[0].split()[-1])
            except (ValueError, IndexError):
                pass
            if crossed or pct >= MOVED_PCT:
                line(4, "trend", lead["text"], lead["detail"] + (" · outside its range" if crossed else ""), lead["ids"], "worsening" if crossed else None)
        for x in card["doesnt_fit"]:
            dated = [obs_dates[i] for i in x["ids"] if i in obs_dates]
            if x["kind"] in ("discordance", "counter_trend") and dated and since <= max(dated) <= today:
                line(6, "unexplained", x["text"], x["detail"], x["ids"], "unexplained")
        for l in card["changed"]:
            if l["kind"] == "ledger":
                line(8, "ledger", l["text"].rstrip("."), "your decision, on the record", l["ids"])

    pending = _pending_for(patient, ids, cluster["codes"], queues)
    if pending:
        line(8, "queue", f"{pending} proposal{'s' if pending != 1 else ''} waiting", "from a note or a reasoning run", [p["id"]], "proposed")
    return out, pending


def _pending_loops(patient: dict, queues: list[dict]) -> list[dict]:
    out = []
    names = {p["id"]: p["name"] for p in patient["problems"]}
    for o in patient.get("orders", []):
        if o["status"] != "accepted":
            continue
        placed = (o.get("ordered_at") or o["created_at"])[:10]
        if o["kind"] == "lab":
            code = (o.get("code") or {}).get("value")
            resulted = bool(code) and any(x["code"]["value"] == code and x["effective_time"][:10] > placed and x.get("status") == "accepted" for x in patient["observations"])
            out.append({"id": o["id"], "kind": "lab", "text": o["name"], "detail": f"ordered {_dmy(placed)} · {'result on the chart' if resulted else 'result shows on the card when it lands'}",
                        "status": "resulted" if resulted else "awaiting", "problem_id": o["problem_id"], "problem_name": names.get(o["problem_id"], "")})
        elif o["kind"] in ("referral", "imaging"):
            out.append({"id": o["id"], "kind": o["kind"], "text": o["name"] + (f" · {o['audience']}" if o.get("audience") else ""), "detail": f"signed {_dmy(placed)} · no reply on the chart",
                        "status": "awaiting", "problem_id": o["problem_id"], "problem_name": names.get(o["problem_id"], "")})
    for b in queues:
        for d in b["proposed"].get("documents", []):
            if d["status"] == "proposed":
                out.append({"id": d["id"], "kind": "document", "text": d["title"], "detail": f"{d['kind']} drafted, unsigned", "status": "unsigned",
                            "problem_id": d["problem_id"], "problem_name": names.get(d["problem_id"], "")})
    return [x for x in out if x["status"] != "resulted"] + [x for x in out if x["status"] == "resulted"]


def patient_overview(patient: dict, *, since: str | None = None, proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> dict:
    today = today or date.today()
    since_info = {"date": since, "why": "as requested"} if since else _since(patient, today)
    win = {"start": since_info["date"], "end": today.isoformat()}
    queues = list_queues(patient["patient"]["id"], proposed_dir)
    obs_dates = {o["id"]: o["effective_time"][:10] for o in patient["observations"]}
    med_events = _med_events(patient, win["start"], win["end"])

    concerns, changes, seen_meds = [], [], set()
    for cl in clusters(patient):
        p = cl["problem"]
        card = problem_card(patient, p["id"], win, proposed_dir=proposed_dir, today=today) if cl["codes"] else None
        lines, pending = _changes_for(patient, cl, card, win["start"], win["end"], queues, med_events, obs_dates)
        for l in lines:
            if l["kind"] == "medication":
                seen_meds.add(l["key"])
        changes += lines
        top = min((l["rank"] for l in lines), default=9)
        lead = next(({"text": x["text"], "detail": x["detail"]} for x in card["supporting"] if x["kind"] == "result"), None) if card else None
        action = None
        if pending:
            action = {"label": f"Review {pending} change{'s' if pending != 1 else ''}", "kind": "review"}
        elif any(l["kind"] == "restage" for l in lines):
            action = {"label": "Review restage", "kind": "review"}
        elif card and card["expected"] and card["expected"]["status"] == "missed":
            action = {"label": "Reassess", "kind": "reassess"}
        concerns.append({
            "id": p["id"], "name": p["name"], "status": p["status"], "onset_date": p.get("onset_date"),
            "members": [{"id": m["id"], "name": m["name"]} for m in cl["members"]],
            "epistemic": card["epistemic"]["value"] if card else ("suspected" if p["provenance"].get("source") == "nlp_extraction" else "confirmed" if p.get("code") else "working"),
            "qualifiers": [q["label"] for q in card["qualifiers"]] if card else [],
            "monitored": bool(cl["codes"]), "pending": pending, "top_rank": top, "lead": lead, "action": action,
            "decisions": card["decisions"] if card else 0,
        })

    # medication changes nobody is linked to still happened: one line each, at the bottom
    for e in med_events:
        if not any(k[1] == e["med_id"] and k[2] == e["kind"] and k[3] == e["date"] for k in seen_meds):
            changes.append({"rank": 8, "kind": "medication", "text": f"{e['text']}, {_dmy(e['date'])}", "why": "on the medication list, not linked to an active problem",
                            "ids": [e["med_id"]], "problem_id": None, "problem_name": "Medications", "tag": None, "key": ("med", e["med_id"], e["kind"], e["date"])})
    uniq, seen = [], set()
    for l in sorted(changes, key=lambda l: (l["rank"], l["problem_name"] or "")):
        if l["key"] in seen:
            continue
        seen.add(l["key"])
        uniq.append({k: v for k, v in l.items() if k != "key"})

    def order(c):
        urgent = 0 if c["top_rank"] <= 2 else 1
        bad = 0 if ("worsening" in c["qualifiers"] or "unexpected" in c["qualifiers"]) else 1
        return (urgent, bad, c["top_rank"], 0 if c["monitored"] else 1, 0 if c["pending"] else 1, -(int((c["onset_date"] or "0000")[:4])))
    concerns.sort(key=order)
    newest = max(patient["encounters"], key=lambda e: e["time"], default=None)
    return {
        "patient": patient["patient"], "as_of": today.isoformat(), "since": since_info,
        "here_for": {"encounter": {k: newest[k] for k in ("id", "time", "type", "summary")} if newest else None},
        "changes": uniq[:TOP_CHANGES], "other_changes": max(0, len(uniq) - TOP_CHANGES),
        "concerns": concerns[:TOP_CONCERNS], "more_concerns": max(0, len(concerns) - TOP_CONCERNS),
        "pending": _pending_loops(patient, queues),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--since")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    print(json.dumps(patient_overview(load_patient(args.patient_id, data_dir), since=args.since, proposed_dir=data_dir.parent / "proposed"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
