"""Signed corrections with immutable before/after snapshots and an impact preview.

Current chart collections remain the input to clinical calculations. Removed entries
move to archived_items; corrections retain signatures and changes for the record.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from ehr.extract import save_patient
from ehr.trend import DATA_DIR, load_patient

KINDS = ("problems", "observations", "medications", "links", "insights", "plans", "orders", "notes", "documents", "course_changes")
LOCK = RLock()
WORDS = {"entered_in_error": "Marked entered in error", "stop": "Medication stopped", "resolve": "Problem resolved",
         "cancel": "Order canceled", "end_plan": "Plan ended", "amend": "Note amended"}


def label(item: dict, patient: dict | None = None) -> str:
    if "effective_time" in item and "value" in item:
        return f"{item.get('name', 'Result')} {item['value']} {item.get('unit') or ''} - {item['effective_time'][:10]}".strip()
    if "author" in item and "time" in item:
        return f"Note by {item['author']} - {item['time'][:10]}"
    if "from" in item and "to" in item:
        names = {x["id"]: x.get("name") or x.get("title") or x["id"] for _, x in entries(patient or {})}
        return f"{names.get(item['from'], item['from'])} {item.get('type', 'related to').replace('_', ' ')} {names.get(item['to'], item['to'])}"
    if item.get("segments"):
        seg = item["segments"][-1]
        return f"{item['name']} {seg.get('dose') or ''} {seg.get('frequency') or ''} - since {seg.get('start') or 'unknown'}".strip()
    return item.get("name") or item.get("title") or item.get("statement") or item.get("text", "")[:160] or item["id"]


def entries(patient: dict):
    for kind in KINDS:
        for item in patient.get(kind, []):
            yield kind, item


def actions(kind: str, item: dict) -> list[str]:
    if kind in ("notes", "documents"):
        return ["amend"] if item.get("review") or item.get("status") in ("signed", "accepted") else []
    out = ["entered_in_error"]
    if kind == "medications" and item.get("segments") and not item["segments"][-1].get("end"):
        out.append("stop")
    if kind == "problems" and item.get("status") == "active":
        out.append("resolve")
    if kind == "orders":
        out.append("cancel")
    if kind == "plans":
        out.append("end_plan")
    return out


def refs(item: dict) -> set[str]:
    prov = item.get("provenance", {})
    return {x for x in [item.get("from"), item.get("to"), item.get("problem_id"), item.get("med_id"),
                       prov.get("from_insight"), prov.get("from_plan"), prov.get("note_id"),
                       *item.get("evidence", []), *prov.get("evidence", []),
                       *[c for s in item.get("sections", []) for c in s.get("cites", [])]] if x}


def revision(patient: dict, queues: list[tuple[Path, dict]]) -> str:
    return hashlib.sha256(json.dumps([patient, [b for _, b in queues]], sort_keys=True).encode()).hexdigest()


def queues_for(pid: str, data_dir: Path):
    folder = Path(data_dir).parent / "proposed" / pid
    return [(p, json.loads(p.read_text())) for p in sorted(folder.glob("*.json")) if not p.name.endswith(".raw.json")]


def correction_patient(pid: str, data_dir: Path) -> dict:
    p = load_patient(pid, data_dir)
    # Older note-driven medication changes live only in their extraction queue.
    p["course_changes"] = []
    for path, batch in queues_for(pid, data_dir):
        for index, change in enumerate(batch.get("medication_changes", [])):
            if change.get("status") != "accepted":
                continue
            med = next((m for m in p.get("medications", []) if m["id"] == change["med_id"]), {})
            p["course_changes"].append({**deepcopy(change), "id": f"change_{path.stem}_{index}",
                "name": f"{med.get('name', change['med_id'])}: {change['change'].replace('_', ' ')} on {change['effective']}",
                "queue_stem": path.stem, "queue_index": index})
    return p


def catalog(pid: str, data_dir: Path = DATA_DIR) -> dict:
    p = correction_patient(pid, data_dir)
    return {"items": [{"id": x["id"], "kind": k, "label": label(x, p), "actions": actions(k, x), "item": x}
                      for k, x in entries(p) if actions(k, x)], "history": p.get("corrections", [])}


def preview(pid: str, item_id: str, action: str, data_dir: Path = DATA_DIR) -> dict:
    p = correction_patient(pid, data_dir)
    queues = queues_for(pid, data_dir)
    found = next(((k, x) for k, x in entries(p) if x["id"] == item_id), None)
    if not found:
        raise ValueError("This entry is no longer current. Reopen the correction panel.")
    kind, item = found
    if action not in actions(kind, item):
        raise ValueError("That action is not available for this entry.")
    affected = {item_id}
    withdrawn = []
    pending = [(k, x) for _, b in queues for k, xs in b.get("proposed", {}).items() for x in xs if x.get("status") == "proposed"]
    if action == "entered_in_error":
        # Links and insights relying on invalid evidence must leave current reasoning.
        while True:
            additions = [(k, x) for k, x in [*entries(p), *pending] if k in ("links", "insights")
                         and x["id"] not in affected and refs(x) & affected]
            if not additions:
                break
            withdrawn.extend(additions)
            affected.update(x["id"] for _, x in additions)
    related = [{"id": x["id"], "kind": k, "label": label(x, p)} for k, x in entries(p)
               if x["id"] not in affected and refs(x) & affected]
    related.extend({"id": x["id"], "kind": f"pending {k}", "label": label(x, p)} for k, x in pending
                   if x["id"] not in affected and refs(x) & affected)
    warnings = []
    blockers = []
    effect = item.get("medication_effect")
    if kind == "course_changes" and not effect:
        blockers.append("This older medication change has no saved prior course. Review the current medication and record the intended treatment separately.")
    if action == "entered_in_error" and effect:
        med = next((m for m in p.get("medications", []) if m["id"] == effect["med_id"]), None)
        if not med or med["segments"] != effect["after"]:
            blockers.append("The medication has changed since this entry. Correct its current course separately first.")
        else:
            warnings.append("The medication course will be restored to the version before this entry.")
    if kind == "orders" and item.get("kind") == "medication_change":
        if action == "entered_in_error" and not effect:
            blockers.append("This older order has no saved medication version. Its medication effect cannot be safely reversed here.")
        if action == "cancel":
            warnings.append("Canceling this order does not reverse a medication change already recorded on the chart.")
    if action == "entered_in_error" and kind in ("problems", "medications"):
        if any(x["kind"] in ("plans", "orders") for x in related):
            blockers.append("Active plans or orders refer to this entry. Correct or end those entries before marking it in error.")
    warnings.append("Signed notes retain their original text. Amend affected notes separately.")
    if action == "amend":
        warnings = ["This adds a signed amendment. The original note and signature remain unchanged. Chart entries and orders are not changed."]
    return {"revision": revision(p, queues), "item": item, "kind": kind, "action": action,
            "withdrawn": [{"id": x["id"], "kind": k, "label": label(x, p)} for k, x in withdrawn],
            "related": related, "warnings": warnings, "blockers": blockers}


def apply_correction(pid: str, item_id: str, action: str, *, reason: str, expected_revision: str,
                     text: str = "", effective: str | None = None, by: str = "Dr. Chen", data_dir: Path = DATA_DIR) -> dict:
    with LOCK:
        impact = preview(pid, item_id, action, data_dir)
        if impact["revision"] != expected_revision:
            raise ValueError("The chart changed. Preview this correction again before signing.")
        if impact["blockers"]:
            raise ValueError(" ".join(impact["blockers"]))
        if not reason.strip() or not by.strip():
            raise ValueError("A reason and signing clinician are required.")
        if action == "amend" and not text.strip():
            raise ValueError("Enter the amendment text.")
        day = effective or date.today().isoformat()
        if action in ("stop", "resolve", "cancel", "end_plan"):
            parsed = date.fromisoformat(day)
            if parsed > date.today():
                raise ValueError("The effective date cannot be in the future.")
            start = impact["item"].get("onset_date")
            if action == "stop":
                start = impact["item"]["segments"][-1].get("start")
            if action in ("cancel", "end_plan"):
                start = impact["item"].get("ordered_at") or impact["item"].get("created_at")
            if start and day < start[:10]:
                raise ValueError("The effective date cannot precede this entry.")
        p = correction_patient(pid, data_dir)
        kind = impact["kind"]
        item = next(x for x in p[kind] if x["id"] == item_id)
        before = deepcopy(item)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        cid = "correction_" + uuid4().hex
        stamp = {"id": cid, "by": by.strip(), "at": now, "reason": reason.strip(), "text": text.strip()}
        archived = []
        removed_ids = set()
        if action in ("entered_in_error", "cancel", "end_plan"):
            removed_ids = {item_id, *[x["id"] for x in impact["withdrawn"]]}
            for k in KINDS:
                for x in p.get(k, []):
                    if x["id"] in removed_ids:
                        archived.append({"kind": k, "item": deepcopy(x), "correction_id": cid})
                p[k] = [x for x in p.get(k, []) if x["id"] not in removed_ids]
            p.setdefault("archived_items", []).extend(archived)
            if action == "entered_in_error" and item.get("medication_effect"):
                effect = item["medication_effect"]
                med = next(m for m in p["medications"] if m["id"] == effect["med_id"])
                med["segments"] = deepcopy(effect["before"])
        elif action == "stop":
            item["segments"][-1]["end"] = day
        elif action == "resolve":
            item["status"] = "resolved"
            item["resolved_date"] = day
        elif action == "amend":
            item.setdefault("amendments", []).append(stamp)
        event = {**stamp, "action": action, "effective": day, "item_id": item_id, "kind": kind, "label": label(before, p),
                 "before": before, "after": None if removed_ids else deepcopy(item), "archived": archived,
                 "related": impact["related"], "note_id": item_id if kind == "notes" else before.get("provenance", {}).get("note_id"),
                 "problem_id": item_id if kind == "problems" else before.get("problem_id")}
        p.setdefault("corrections", []).append(event)
        # Queue copies may never resurrect an archived entry. Keep their old review stamps.
        for path, batch in queues_for(pid, data_dir):
            changed = False
            if kind == "course_changes" and path.stem == before["queue_stem"]:
                batch["medication_changes"][before["queue_index"]]["status"] = action
                batch["medication_changes"][before["queue_index"]]["correction_id"] = cid
                changed = True
            for k, xs in batch.get("proposed", {}).items():
                for x in xs:
                    if x["id"] in removed_ids:
                        x["status"] = action if x["id"] == item_id else "superseded"
                        x["correction_id"] = cid
                        changed = True
                    elif x["id"] == item_id:
                        x.update(deepcopy(item))
                        if k == "problems":
                            x["status"] = "accepted"
                        changed = True
                    elif x.get("status") == "proposed" and refs(x) & removed_ids:
                        x["status"] = "superseded"
                        x["correction_id"] = cid
                        changed = True
            if changed:
                path.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        p.pop("course_changes", None)
        save_patient(p, data_dir)
        return event
