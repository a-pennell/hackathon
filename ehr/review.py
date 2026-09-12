"""Review queue: the human step between extraction and the chart.

    python3 -m ehr.review pt_001 note_demo_002 --list
    python3 -m ehr.review pt_001 note_demo_002 --accept obs_demo_002_01 lnk_demo_002_03
    python3 -m ehr.review pt_001 note_demo_002 --accept-all
    python3 -m ehr.review pt_001 note_demo_002 --reject med_demo_002_01
    python3 -m ehr.review pt_001 reason_prob_0057 --accept-all      # insight queues work the same way

Accepting an item copies it into the patient file with status "accepted" (provenance is kept,
so the chart still shows it came from a note). Accepting a link whose endpoints are still
proposed also accepts those endpoints - a link to something not on the chart is meaningless.
Rejected items stay in the queue file, marked rejected, for the audit trail.

Every decision is recorded on the item as a review record (FLAGGED schema addition, not in
docs/patient-model-schema.md yet):
    "review": {"by": "Dr. Chen", "at": "<iso>", "decision": "accepted"|"rejected",
               "reason_code": "already_known"|"not_relevant"|"disagree"|"needs_confirmation"|"other"|null,
               "reason": "<free text or null>"}
A rejection with a reason is where the clinician's judgment becomes explicit - it is the most
valuable thing this module captures.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ehr.extract import PROPOSED_DIR, queue_path, save_patient
from ehr.trend import DATA_DIR, load_patient

KINDS = ("problems", "observations", "medications", "links", "insights", "documents")
REASON_CODES = ("already_known", "not_relevant", "disagree", "needs_confirmation", "other")
DEFAULT_REVIEWER = "Dr. Chen"


def review_record(decision: str, by: str = DEFAULT_REVIEWER, reason: str | None = None,
                  reason_code: str | None = None) -> dict:
    if reason_code is not None and reason_code not in REASON_CODES:
        raise ValueError(f"reason_code must be one of {REASON_CODES}")
    return {"by": by, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "decision": decision,
            "reason_code": reason_code, "reason": (reason or "").strip() or None}


def load_queue(patient_id: str, note_id: str, proposed_dir: Path = PROPOSED_DIR) -> tuple[Path, dict]:
    p = queue_path(patient_id, note_id, proposed_dir)
    return p, json.loads(p.read_text())


def _find(batch: dict, item_id: str) -> tuple[str, dict] | tuple[None, None]:
    for kind in KINDS:
        for it in batch["proposed"].get(kind, []):
            if it["id"] == item_id:
                return kind, it
    return None, None


def accept_item(patient: dict, batch: dict, item_id: str, _seen: set | None = None,
                review: dict | None = None) -> list[str]:
    """Move one proposed item (and, for links, its proposed endpoints) into the chart."""
    _seen = _seen if _seen is not None else set()
    if item_id in _seen:
        return []
    _seen.add(item_id)
    kind, it = _find(batch, item_id)
    if it is None:
        raise KeyError(f"{item_id} is not in this queue")
    if it["status"] == "rejected":
        raise ValueError(f"{item_id} was rejected; un-reject it first")
    done = []
    if kind == "links":
        chart_ids = {x["id"] for key in ("problems", "observations", "medications", "encounters", "notes", "links", "insights", "documents")
                     for x in patient.get(key, [])}
        for end in (it["from"], it["to"]):
            if end.startswith("LOINC:"):
                continue
            k, endpoint = _find(batch, end)
            if k and endpoint["status"] == "proposed":
                done += accept_item(patient, batch, end, _seen, review)
            elif k and endpoint["status"] == "rejected":
                raise ValueError(f"{item_id} points at {end}, which was rejected; a link to a rejected item cannot be signed")
            elif not k and end not in chart_ids:
                raise ValueError(f"{item_id} points at {end}, which is not on the chart")
    if it["status"] == "accepted":
        return done
    it["status"] = "accepted"
    it["review"] = review or review_record("accepted")
    chart_item = dict(it)
    chart_item["status"] = "active" if kind == "problems" else "accepted"
    target = patient.setdefault(kind, [])
    if not any(x["id"] == chart_item["id"] for x in target):
        target.append(chart_item)
    done.append(f"{kind[:-1]} {item_id}")
    return done


def reject_item(batch: dict, item_id: str, review: dict | None = None) -> str:
    kind, it = _find(batch, item_id)
    if it is None:
        raise KeyError(f"{item_id} is not in this queue")
    it["status"] = "rejected"
    it["review"] = review or review_record("rejected")
    return f"{kind[:-1]} {item_id} rejected"


def accept_medication_change(patient: dict, change: dict, review: dict | None = None) -> str:
    """Apply a proposed stop / dose or frequency change to an existing course (schema §4)."""
    med = next(m for m in patient["medications"] if m["id"] == change["med_id"])
    last = med["segments"][-1]
    eff = change["effective"]
    change["review"] = review or review_record("accepted")
    if change["change"] == "stop":
        last["end"] = eff
        change["status"] = "accepted"
        return f"{med['id']} stopped {eff}"
    last["end"] = eff
    med["segments"].append({"start": eff, "end": None,
                            "dose": change.get("dose") or last["dose"],
                            "route": change.get("route") or last["route"],
                            "frequency": change.get("frequency") or last["frequency"]})
    change["status"] = "accepted"
    return f"{med['id']} new segment from {eff}"


def list_queue(batch: dict) -> str:
    lines = [f"queue {batch.get('note_id') or 'reason ' + batch.get('problem_id', '')} for {batch['patient_id']} ({batch['model']})"]
    for kind in KINDS:
        for it in batch["proposed"].get(kind, []):
            hint = batch.get("review_hints", {}).get(it["id"])
            desc = {
                "problems": lambda x: x["name"],
                "observations": lambda x: f"{x['name']} = {x['value']} {x['unit']} @ {x['effective_time'][:10]}",
                "medications": lambda x: f"{x['name']} {x['segments'][0]['dose']} {x['segments'][0]['frequency']}",
                "links": lambda x: f"{x['from']} -{x['type']}-> {x['to']}",
                "insights": lambda x: f"{x['statement']}\n{'':14}action: {x['suggested_action']}\n{'':14}evidence: {x['evidence']}",
                "documents": lambda x: f"{x['kind']} to {x['audience']}: {x['title']} ({len(x['sections'])} sections)",
            }[kind](it)
            rv = it.get("review")
            if rv and (rv.get("reason") or rv.get("reason_code")):
                hint = f"{rv['decision']} by {rv['by']}: {rv.get('reason_code') or ''} {rv.get('reason') or ''}".strip() + (f" | {hint}" if hint else "")
            tail = (f"  quote={it['provenance']['quote']!r}" if "quote" in it["provenance"] else "")
            lines.append(f"  [{it['status']:<8}] {it['id']:<22} {desc}"
                         f"  conf={it['provenance'].get('confidence')}{tail}"
                         + (f"\n{'':14}hint: {hint}" if hint else ""))
    for ch in batch.get("medication_changes", []):
        lines.append(f"  [{ch['status']:<8}] change {ch['med_id']}: {ch['change']} effective {ch['effective']}"
                     f"  quote={ch['provenance']['quote']!r}")
    for r in batch.get("rejected", []):
        lines.append(f"  [dropped ] {r['kind']}: {r['reason']}")
    return "\n".join(lines)


def _summary_of(kind: str, it: dict) -> str:
    if kind == "insights":
        return it["statement"]
    if kind == "problems":
        return f"problem: {it['name']}"
    if kind == "medications":
        s = it["segments"][0]
        return f"medication: {it['name']} {s.get('dose') or ''} {s.get('start') or ''}..{s.get('end') or 'ongoing'}"
    if kind == "observations":
        return f"result: {it['name']} {it['value']} {it.get('unit') or ''} on {it['effective_time'][:10]}"
    if kind == "links":
        return f"link: {it['from']} {it['type']} {it['to']}"
    if kind == "documents":
        return f"{it.get('kind', 'document')} to {it.get('audience', '')}: {it.get('title', '')}"
    return it.get("title") or it["id"]


def ledger_for_problem(patient: dict, problem_id: str, proposed_dir: Path = PROPOSED_DIR,
                       include_pending: bool = False) -> list[dict]:
    """The decision trail: every reviewed proposal that touches this problem, with who/when/why.

    Touches = about the problem, about one of its monitored series, linked to it by a proposed
    link in the same batch, or a proposal that supersedes it (review hint). Oldest first."""
    from ehr.reason import monitored_codes
    focus = {problem_id} | {f"LOINC:{c}" for c in monitored_codes(patient, problem_id)}
    out = []
    for b in list_queues(patient["patient"]["id"], proposed_dir):
        links = b["proposed"].get("links", [])
        hints = b.get("review_hints") or {}
        for k, items in b["proposed"].items():
            for it in items:
                rv = it.get("review")
                if not rv and not (include_pending and it.get("status") == "proposed"):
                    continue
                touches = (it.get("problem_id") == problem_id or it.get("id") == problem_id
                           or it.get("to") in focus or it.get("from") in focus
                           or problem_id in hints.get(it.get("id"), "")
                           or any((l.get("to") in focus and l.get("from") == it.get("id"))
                                  or (l.get("from") in focus and l.get("to") == it.get("id")) for l in links))
                if not touches:
                    continue
                out.append({"id": it["id"], "kind": k[:-1], "what": _summary_of(k, it), "queue": b["stem"],
                            "source": (it.get("provenance") or {}).get("source"), "confidence": (it.get("provenance") or {}).get("confidence"),
                            "quote": (it.get("provenance") or {}).get("quote"),
                            "decision": rv["decision"] if rv else "pending", "reason_code": rv.get("reason_code") if rv else None,
                            "reason": rv.get("reason") if rv else None, "by": rv["by"] if rv else None,
                            "at": rv["at"] if rv else (b.get("extracted_at") or b.get("reasoned_at") or b.get("composed_at") or "")})
        for ch in b.get("medication_changes", []):
            rv = ch.get("review")
            if rv or (include_pending and ch["status"] == "proposed"):
                out.append({"id": ch["med_id"], "kind": "medication_change", "what": f"{ch['change'].replace('_', ' ')} {ch['med_id']} effective {ch['effective']}",
                            "queue": b["stem"], "source": ch["provenance"].get("source"), "confidence": ch["provenance"].get("confidence"),
                            "quote": ch["provenance"].get("quote"),
                            "decision": rv["decision"] if rv else "pending", "reason_code": rv.get("reason_code") if rv else None,
                            "reason": rv.get("reason") if rv else None, "by": rv["by"] if rv else None,
                            "at": rv["at"] if rv else (b.get("extracted_at") or "")})
    out.sort(key=lambda x: x["at"] or "")
    return out


def list_queues(patient_id: str, proposed_dir: Path = PROPOSED_DIR) -> list[dict]:
    """Every queue batch for a patient (note extractions and reasoning runs), newest first."""
    d = proposed_dir / patient_id
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".raw.json"):
            continue
        b = json.loads(p.read_text())
        b["stem"] = p.stem
        out.append(b)
    out.sort(key=lambda b: b.get("extracted_at") or b.get("reasoned_at") or "", reverse=True)
    return out


def apply_review(patient_id: str, stem: str, *, accept: list[str] = (), reject: list[str] = (),
                 accept_all: bool = False, accept_changes: bool = False,
                 reason: str | None = None, reason_code: str | None = None, by: str = DEFAULT_REVIEWER,
                 data_dir: Path = DATA_DIR) -> list[str]:
    """Accept / reject queue items and persist both the chart and the queue file.
    `reason` / `reason_code` apply to every decision in this call (one call per reasoned decision)."""
    data_dir = Path(data_dir)
    qp, batch = load_queue(patient_id, stem, data_dir.parent / "proposed")
    patient = load_patient(patient_id, data_dir)
    done = []
    for iid in reject:
        done.append(reject_item(batch, iid, review_record("rejected", by, reason, reason_code)))
    ids = list(accept)
    if accept_all:
        ids = [it["id"] for k in KINDS for it in batch["proposed"].get(k, []) if it["status"] == "proposed"]
    for iid in ids:
        done += accept_item(patient, batch, iid, review=review_record("accepted", by, reason, reason_code))
    if accept_changes:
        for ch in batch.get("medication_changes", []):
            if ch["status"] == "proposed":
                done.append(accept_medication_change(patient, ch, review_record("accepted", by, reason, reason_code)))
    if done:
        save_patient(patient, data_dir)
        qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    return done


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("note_id", help="queue file stem: a note id, or reason_<problem_id>")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--accept", nargs="*", default=[])
    ap.add_argument("--reject", nargs="*", default=[])
    ap.add_argument("--accept-all", action="store_true")
    ap.add_argument("--accept-changes", action="store_true", help="apply all proposed medication changes")
    ap.add_argument("--reason", help="free-text reason recorded on every decision in this call")
    ap.add_argument("--reason-code", choices=REASON_CODES)
    ap.add_argument("--by", default=DEFAULT_REVIEWER)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    qp, batch = load_queue(args.patient_id, args.note_id, data_dir.parent / "proposed")
    patient = load_patient(args.patient_id, data_dir)

    done = []
    for iid in args.reject:
        done.append(reject_item(batch, iid, review_record("rejected", args.by, args.reason, args.reason_code)))
    ids = args.accept
    if args.accept_all:
        ids = [it["id"] for k in KINDS for it in batch["proposed"].get(k, []) if it["status"] == "proposed"]
    for iid in ids:
        done += accept_item(patient, batch, iid, review=review_record("accepted", args.by, args.reason, args.reason_code))
    if args.accept_changes:
        for ch in batch.get("medication_changes", []):
            if ch["status"] == "proposed":
                done.append(accept_medication_change(patient, ch, review_record("accepted", args.by, args.reason, args.reason_code)))

    if done:
        save_patient(patient, data_dir)
        qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        print("\n".join(done))
    if args.list or not done:
        print(list_queue(batch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
