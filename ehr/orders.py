"""Orders: signed insights -> proposed orders (labs, medication changes, referrals, imaging).

    python3 -m ehr.orders pt_001 --problem prob_0057            # live (one structured call)
    python3 -m ehr.orders pt_001 --problem prob_0057 --replay data/proposed/pt_001/orders_prob_0057.raw.json

The insight's `suggested_action` is prose; an Order is the structured thing a clinician signs.
Only SIGNED insights feed this step (a rejected insight cannot generate an order). Every order
carries the insight it came from and evidence ids; a medication-change order must name a course
that exists; on signing, a medication change is applied to the course exactly as a reviewed
note change is (schema §4: close a segment, open the next).

FLAGGED schema addition (not in docs/patient-model-schema.md): an Order entity
    {id: "ord_...", patient_id, problem_id, kind: "lab"|"medication_change"|"referral"|"imaging",
     name, detail, code: {system, value}|null, med_id, change ("stop"|"dose_change"|null),
     dose, audience, status: "proposed", provenance: {source: "ordering", model, from_insight,
     evidence, confidence}, created_at}
queued at data/proposed/<pid>/orders_<problem_id>.json; signed orders live under a new top-level
`orders` list in the patient file, and a signed medication-change order edits the course.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ehr.codes import EXTRACTABLE_LOINC
from ehr.extract import PROPOSED_DIR, record_response
from ehr.reason import build_context as reasoning_context
from ehr.trend import DATA_DIR

DEFAULT_MODEL = "claude-opus-5"
ORDERER_VERSION = "orderer-v1"
KINDS = ("lab", "medication_change", "referral", "imaging")

SYSTEM_PROMPT = """You turn a clinician's SIGNED insights into concrete orders for their signature. You do not
add clinical ideas of your own: every order must be the structured form of something a signed
insight's suggested action already says. If a signed insight suggests nothing orderable, return
no orders for it.

Kinds: "lab" (name the test; use a LOINC code from the allowed list when one fits, else null),
"medication_change" (must name an existing medication id from the context and a change of "stop"
or "dose_change" with the new dose when stated), "referral" (name the audience), "imaging".
`detail` is one line of specifics a clinician would write on the order (frequency, timing,
what to look for). `from_insight` is the signed insight id. `evidence` cites ONLY ids from the
evidence catalog. `confidence` is your 0-1 estimate the clinician signs it as written."""

OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["orders"],
    "properties": {"orders": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "name", "detail", "loinc", "med_id", "change", "dose", "audience", "from_insight", "evidence", "confidence"],
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "name": {"type": "string"},
            "detail": {"type": "string"},
            "loinc": {"type": ["string", "null"]},
            "med_id": {"type": ["string", "null"]},
            "change": {"anyOf": [{"type": "string", "enum": ["stop", "dose_change"]}, {"type": "null"}]},
            "dose": {"type": ["string", "null"]},
            "audience": {"type": ["string", "null"]},
            "from_insight": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        }}}},
}


def build_context(patient: dict, problem_id: str, window="1y") -> dict:
    ctx = reasoning_context(patient, problem_id, window)
    signed = [i for i in patient.get("insights", []) if i["problem_id"] == problem_id and i.get("status") == "accepted"]
    for i in signed:
        ctx["catalog"][i["id"]] = f"signed insight: {i['statement'][:80]!r}"
    existing_orders = [o for o in patient.get("orders", []) if o["problem_id"] == problem_id]
    return {**ctx, "signed_insights": [{"id": i["id"], "statement": i["statement"], "suggested_action": i["suggested_action"],
                                        "review": i.get("review")} for i in signed],
            "existing_orders": [{"id": o["id"], "kind": o["kind"], "name": o["name"], "status": o["status"]} for o in existing_orders]}


def build_messages(ctx: dict) -> tuple[list[dict], list[dict]]:
    payload = {k: v for k, v in ctx.items() if k not in ("catalog", "trends", "note_findings")}
    loinc_menu = "\n".join(f"  {c}  {n}" for c, (n, _u, _r) in EXTRACTABLE_LOINC.items())
    catalog_text = "\n".join(f"  {k}: {v}" for k, v in ctx["catalog"].items())
    user = ("Context (JSON):\n" + json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
            + "\n\nAllowed LOINC codes for lab orders:\n" + loinc_menu
            + "\n\nEvidence catalog - the ONLY ids you may cite:\n" + catalog_text)
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}], [{"role": "user", "content": user}]


def validate(patient: dict, ctx: dict, raw: dict, model: str, existing_ids: set[str] | None = None) -> dict:
    pid = patient["patient"]["id"]
    problem_id = ctx["problem"]["id"]
    chart_ids = {x["id"] for key in ("problems", "observations", "medications", "encounters", "notes", "links", "insights", "documents", "orders")
                 for x in patient.get(key, [])}
    allowed = set(ctx["catalog"]) & (chart_ids | set(ctx["catalog"]))
    signed_ids = {i["id"] for i in ctx["signed_insights"]}
    med_ids = {m["id"] for m in patient.get("medications", []) if m.get("status") == "accepted"}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    taken = set(existing_ids or ()) | {o["id"] for o in patient.get("orders", [])}
    proposed, rejected = [], []
    n = 0
    for it in raw.get("orders") or []:
        kind = it.get("kind")
        if kind not in KINDS:
            rejected.append({"reason": f"unknown order kind {kind!r}", "item": it}); continue
        if it.get("from_insight") not in signed_ids:
            rejected.append({"reason": f"order is not derived from a signed insight ({it.get('from_insight')!r})", "item": it}); continue
        evidence = [e for e in dict.fromkeys(it.get("evidence") or []) if e in allowed]
        if it["from_insight"] not in evidence:
            evidence.insert(0, it["from_insight"])
        code, med_id, change = None, None, None
        if kind == "lab" and it.get("loinc"):
            if it["loinc"] in EXTRACTABLE_LOINC:
                code = {"system": "LOINC", "value": it["loinc"]}
            else:
                rejected.append({"reason": f"lab code {it['loinc']!r} not in the allowed table; order kept without a code", "item": None})
        if kind == "medication_change":
            med_id, change = it.get("med_id"), it.get("change")
            if med_id not in med_ids:
                rejected.append({"reason": f"medication change names {med_id!r}, which is not an active course on the chart", "item": it}); continue
            if change not in ("stop", "dose_change"):
                rejected.append({"reason": f"medication change needs 'stop' or 'dose_change' (got {change!r})", "item": it}); continue
            if change == "dose_change" and not it.get("dose"):
                rejected.append({"reason": "dose_change without a new dose", "item": it}); continue
            evidence.insert(1, med_id) if med_id not in evidence else None
        n += 1
        oid = f"ord_{problem_id[5:]}_{n:02d}"
        while oid in taken:
            n += 1; oid = f"ord_{problem_id[5:]}_{n:02d}"
        taken.add(oid)
        proposed.append({
            "id": oid, "patient_id": pid, "problem_id": problem_id, "kind": kind,
            "name": (it.get("name") or "").strip(), "detail": (it.get("detail") or "").strip(),
            "code": code, "med_id": med_id, "change": change, "dose": it.get("dose") if kind == "medication_change" else None,
            "audience": it.get("audience") if kind == "referral" else None,
            "status": "proposed",
            "provenance": {"source": "ordering", "model": f"{ORDERER_VERSION}/{model}", "from_insight": it["from_insight"],
                           "evidence": evidence, "confidence": round(min(1.0, max(0.0, float(it.get("confidence") or 0.5))), 2)},
            "created_at": now,
        })
    return {"patient_id": pid, "problem_id": problem_id, "model": f"{ORDERER_VERSION}/{model}", "ordered_at": now,
            "proposed": {"orders": proposed}, "rejected": rejected}


def propose_orders(patient: dict, problem_id: str, *, window="1y", model: str = DEFAULT_MODEL, raw: dict | None = None) -> tuple[dict, dict, dict]:
    ctx = build_context(patient, problem_id, window)
    if not ctx["signed_insights"]:
        return ({"patient_id": patient["patient"]["id"], "problem_id": problem_id, "model": "none",
                 "ordered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "proposed": {"orders": []}, "rejected": [{"reason": "no signed insights on this problem; sign an insight first", "item": None}]},
                {"parsed": {"orders": []}}, ctx)
    if raw is None:
        from ehr.llm import call_structured
        system_blocks, messages = build_messages(ctx)
        raw = call_structured(system_blocks, messages, OUTPUT_SCHEMA, model=model, effort="medium", max_tokens=4000)
    batch = validate(patient, ctx, raw["parsed"], raw.get("model", model))
    batch["usage"] = raw.get("usage")
    return batch, raw, ctx


def run_orders(patient_id: str, problem_id: str, *, window="1y", model: str = DEFAULT_MODEL, replay: str | Path | None = None,
               data_dir: Path = DATA_DIR, save: bool = True) -> dict:
    data_dir = Path(data_dir)
    proposed_dir = data_dir.parent / "proposed"
    patient = json.loads((data_dir / f"{patient_id}.json").read_text())
    raw = json.loads(Path(replay).read_text()) if replay else None
    batch, raw, _ = propose_orders(patient, problem_id, window=window, model=model, raw=raw)
    qp = proposed_dir / patient_id / f"orders_{problem_id}.json"
    if save:
        qp.parent.mkdir(parents=True, exist_ok=True)
        qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        if not replay and batch["model"] != "none":
            record_response(qp, raw)
    batch["queue_path"] = str(qp)
    return batch


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--problem", required=True)
    ap.add_argument("--window", default="1y")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--replay")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    try:
        batch = run_orders(args.patient_id, args.problem, window=args.window, model=args.model, replay=args.replay, data_dir=Path(args.data_dir))
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr); return 1
    print(f"=== orders for {batch['problem_id']} ({batch['model']}) ===")
    for o in batch["proposed"]["orders"]:
        code = f" [{o['code']['system']} {o['code']['value']}]" if o.get("code") else ""
        extra = f" {o['change']} {o['med_id']}{' -> ' + o['dose'] if o.get('dose') else ''}" if o["kind"] == "medication_change" else (f" to {o['audience']}" if o.get("audience") else "")
        print(f"  + {o['id']} {o['kind']}: {o['name']}{code}{extra} (conf {o['provenance']['confidence']}, from {o['provenance']['from_insight']})")
        print(f"      {o['detail']}")
    for r in batch["rejected"]:
        print("  x", r["reason"])
    if batch.get("usage"):
        print("usage:", batch["usage"])
    print(f"review queue: {batch['queue_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
