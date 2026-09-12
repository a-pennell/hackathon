"""Review queue: the human step between extraction and the chart.

    python3 -m ehr.review pt_001 note_demo_002 --list
    python3 -m ehr.review pt_001 note_demo_002 --accept obs_demo_002_01 lnk_demo_002_03
    python3 -m ehr.review pt_001 note_demo_002 --accept-all
    python3 -m ehr.review pt_001 note_demo_002 --reject med_demo_002_01

Accepting an item copies it into the patient file with status "accepted" (provenance is kept,
so the chart still shows it came from a note). Accepting a link whose endpoints are still
proposed also accepts those endpoints - a link to something not on the chart is meaningless.
Rejected items stay in the queue file, marked rejected, for the audit trail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ehr.extract import PROPOSED_DIR, queue_path, save_patient
from ehr.trend import DATA_DIR, load_patient

KINDS = ("problems", "observations", "medications", "links")


def load_queue(patient_id: str, note_id: str, proposed_dir: Path = PROPOSED_DIR) -> tuple[Path, dict]:
    p = queue_path(patient_id, note_id, proposed_dir)
    return p, json.loads(p.read_text())


def _find(batch: dict, item_id: str) -> tuple[str, dict] | tuple[None, None]:
    for kind in KINDS:
        for it in batch["proposed"][kind]:
            if it["id"] == item_id:
                return kind, it
    return None, None


def accept_item(patient: dict, batch: dict, item_id: str, _seen: set | None = None) -> list[str]:
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
        for end in (it["from"], it["to"]):
            k, _ = _find(batch, end)
            if k and _find(batch, end)[1]["status"] == "proposed":
                done += accept_item(patient, batch, end, _seen)
    if it["status"] == "accepted":
        return done
    it["status"] = "accepted"
    chart_item = dict(it)
    chart_item["status"] = "active" if kind == "problems" else "accepted"
    target = patient.setdefault(kind, [])
    if not any(x["id"] == chart_item["id"] for x in target):
        target.append(chart_item)
    done.append(f"{kind[:-1]} {item_id}")
    return done


def reject_item(batch: dict, item_id: str) -> str:
    kind, it = _find(batch, item_id)
    if it is None:
        raise KeyError(f"{item_id} is not in this queue")
    it["status"] = "rejected"
    return f"{kind[:-1]} {item_id} rejected"


def accept_medication_change(patient: dict, change: dict) -> str:
    """Apply a proposed stop / dose or frequency change to an existing course (schema §4)."""
    med = next(m for m in patient["medications"] if m["id"] == change["med_id"])
    last = med["segments"][-1]
    eff = change["effective"]
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
    lines = [f"queue {batch['note_id']} for {batch['patient_id']} ({batch['model']})"]
    for kind in KINDS:
        for it in batch["proposed"][kind]:
            hint = batch.get("review_hints", {}).get(it["id"])
            desc = {
                "problems": lambda x: x["name"],
                "observations": lambda x: f"{x['name']} = {x['value']} {x['unit']} @ {x['effective_time'][:10]}",
                "medications": lambda x: f"{x['name']} {x['segments'][0]['dose']} {x['segments'][0]['frequency']}",
                "links": lambda x: f"{x['from']} -{x['type']}-> {x['to']}",
            }[kind](it)
            lines.append(f"  [{it['status']:<8}] {it['id']:<22} {desc}"
                         f"  conf={it['provenance']['confidence']}  quote={it['provenance']['quote']!r}"
                         + (f"\n{'':14}hint: {hint}" if hint else ""))
    for ch in batch.get("medication_changes", []):
        lines.append(f"  [{ch['status']:<8}] change {ch['med_id']}: {ch['change']} effective {ch['effective']}"
                     f"  quote={ch['provenance']['quote']!r}")
    for r in batch.get("rejected", []):
        lines.append(f"  [dropped ] {r['kind']}: {r['reason']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("note_id")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--accept", nargs="*", default=[])
    ap.add_argument("--reject", nargs="*", default=[])
    ap.add_argument("--accept-all", action="store_true")
    ap.add_argument("--accept-changes", action="store_true", help="apply all proposed medication changes")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    qp, batch = load_queue(args.patient_id, args.note_id, data_dir.parent / "proposed")
    patient = load_patient(args.patient_id, data_dir)

    done = []
    for iid in args.reject:
        done.append(reject_item(batch, iid))
    ids = args.accept
    if args.accept_all:
        ids = [it["id"] for k in KINDS for it in batch["proposed"][k] if it["status"] == "proposed"]
    for iid in ids:
        done += accept_item(patient, batch, iid)
    if args.accept_changes:
        for ch in batch.get("medication_changes", []):
            if ch["status"] == "proposed":
                done.append(accept_medication_change(patient, ch))

    if done:
        save_patient(patient, data_dir)
        qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        print("\n".join(done))
    if args.list or not done:
        print(list_queue(batch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
