"""Review chart updates against a draft without discarding clinician wording."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from threading import RLock

from ehr.draft import draft_note, stem_for
from ehr.review import load_queue
from ehr.trend import DATA_DIR, load_patient

LOCK = RLock()


def section_key(section):
    role = section["heading"].split(" · ")[0] if section.get("problem_id") else section["heading"]
    return section.get("key") or f"{section.get('source', 'compiled')}:{section.get('problem_id', 'visit')}:{role}"


def keyed(sections):
    return [{**deepcopy(s), "key": section_key(s)} for s in sections]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def content(section):
    if section is None:
        return None
    return {k: section.get(k) for k in ("heading", "text", "cites", "source", "problem_id")}


def edited_sections(original, edits):
    sections = keyed(original)
    if edits is None:
        return sections
    by_key = {s["key"]: s for s in sections}
    by_heading = {s["heading"]: s["key"] for s in sections}
    seen = set()
    for edit in edits:
        key = edit.get("key") or by_heading.get(edit.get("heading"))
        if key not in by_key or key in seen or not isinstance(edit.get("text"), str):
            raise ValueError("Draft sections changed. Reopen the note before saving.")
        seen.add(key)
        section = by_key[key]
        if edit["text"] != section["text"]:
            section["text"] = edit["text"]
            section["edited"] = True
    if seen != set(by_key):
        raise ValueError("Submit every draft section, including sections with removed text.")
    return sections


def state(pid, eid, data_dir, edits=None):
    path, batch = load_queue(pid, stem_for(eid), Path(data_dir).parent / "proposed")
    doc = batch["proposed"]["documents"][0]
    current = edited_sections(doc["sections"], edits)
    baseline = keyed(batch.get("source_sections", doc["sections"]))
    if doc["status"] == "accepted":
        return path, batch, current, baseline, doc
    fresh = draft_note(load_patient(pid, data_dir), eid, proposed_dir=Path(data_dir).parent / "proposed")["proposed"]["documents"][0]
    fresh["sections"] = keyed(fresh["sections"])
    return path, batch, current, baseline, fresh


def changes_for(current, baseline, latest):
    old = {s["key"]: s for s in baseline}
    new = {s["key"]: s for s in latest}
    ours = {s["key"]: s for s in current}
    changes = []
    for key in dict.fromkeys([*new, *old]):
        if content(old.get(key)) == content(new.get(key)):
            continue
        section = ours.get(key)
        original = old.get(key)
        edited = section is not None and (section.get("edited") or section["text"] != (original or {}).get("text"))
        changes.append({"key": key, "heading": (new.get(key) or original)["heading"], "current": section,
                        "incoming": new.get(key), "conflict": bool(edited),
                        "kind": "added" if key not in old else "removed" if key not in new else "changed"})
    return changes


def read_draft(pid, eid, data_dir=DATA_DIR):
    path, batch, current, baseline, fresh = state(pid, eid, data_dir)
    changes = [] if batch["proposed"]["documents"][0]["status"] == "accepted" else changes_for(current, baseline, fresh["sections"])
    result = deepcopy(batch)
    result["proposed"]["documents"][0]["sections"] = current
    result.update(stem=path.stem, draft_revision=fingerprint(batch), updates_count=len(changes))
    return result


def preview_updates(pid, eid, sections=None, data_dir=DATA_DIR):
    _, batch, current, baseline, fresh = state(pid, eid, data_dir, sections)
    if batch["proposed"]["documents"][0]["status"] != "proposed":
        raise ValueError("A signed note requires an amendment.")
    changes = changes_for(current, baseline, fresh["sections"])
    return {"revision": fingerprint([batch, current, [content(s) for s in fresh["sections"]]]), "changes": changes}


def save_draft(pid, eid, sections, expected_revision, data_dir=DATA_DIR):
    with LOCK:
        path, batch, current, baseline, _ = state(pid, eid, data_dir, sections)
        if batch["proposed"]["documents"][0]["status"] != "proposed":
            raise ValueError("A signed note requires an amendment.")
        if fingerprint(batch) != expected_revision:
            raise ValueError("This draft changed elsewhere. Reopen it before saving.")
        batch["source_sections"] = baseline
        batch["proposed"]["documents"][0]["sections"] = current
        path.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        return read_draft(pid, eid, data_dir)


def incorporate_updates(pid, eid, sections, expected_revision, resolutions, data_dir=DATA_DIR):
    with LOCK:
        preview = preview_updates(pid, eid, sections, data_dir)
        if preview["revision"] != expected_revision:
            raise ValueError("The chart or draft changed. Review the latest updates before applying them.")
        path, batch, current, baseline, fresh = state(pid, eid, data_dir, sections)
        ours = {s["key"]: s for s in current}
        for change in preview["changes"]:
            key = change["key"]
            resolution = resolutions.get(key, {})
            choice = resolution.get("choice", "update" if not change["conflict"] else None)
            if choice not in ("keep", "update", "edit"):
                raise ValueError(f"Choose how to incorporate changes to {change['heading']}.")
            if choice == "update":
                if change["incoming"] is None:
                    ours.pop(key, None)
                else:
                    ours[key] = deepcopy(change["incoming"])
            elif choice == "edit":
                if not isinstance(resolution.get("text"), str):
                    raise ValueError("Enter the merged section text.")
                merged = deepcopy(change["incoming"] or change["current"])
                merged.update(text=resolution["text"], edited=True)
                ours[key] = merged
        order = list(dict.fromkeys([s["key"] for s in fresh["sections"]] + [s["key"] for s in current]))
        doc = batch["proposed"]["documents"][0]
        doc["sections"] = [ours[k] for k in order if k in ours]
        doc["problems_addressed"] = list(dict.fromkeys(s["problem_id"] for s in doc["sections"] if s.get("problem_id") and s["text"].strip()))
        doc["provenance"]["evidence"] = list(dict.fromkeys(c for s in doc["sections"] if s["text"].strip() for c in s["cites"]))
        batch["source_sections"] = fresh["sections"]
        path.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        return read_draft(pid, eid, data_dir)
