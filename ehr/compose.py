"""Composition: chart state + reasoning ledger -> a generated document (referral letter).

    python3 -m ehr.compose pt_001 --problem prob_0057 --kind referral --audience nephrology
    python3 -m ehr.compose pt_001 --problem prob_0057 --replay data/proposed/pt_001/referral_prob_0057.raw.json
    python3 -m ehr.compose pt_001 --problem prob_0057 --dry-run

The note becomes a projection: nothing here is authored, it is rendered from the chart (§1-§7),
the TrendSummaries (§9), the signed Insights (§10) and the clinician's review decisions, for one
audience. Every section carries `cites`: ids the reader can tap through to. Citations are
filtered to ids that exist; a document with no citable section is rejected.

FLAGGED schema addition (not in docs/patient-model-schema.md): a Document entity
    {id: "doc_...", patient_id, problem_id, kind: "referral", audience, title,
     sections: [{heading, text, cites: [ids]}], questions: [str], status: "proposed",
     provenance: {source: "composition", model, evidence: [ids], confidence}, created_at}
queued at data/proposed/<pid>/<kind>_<problem_id>.json and, once signed, stored under a new
top-level `documents` list in the patient file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ehr.extract import PROPOSED_DIR, record_response
from ehr.reason import build_context as reasoning_context
from ehr.review import list_queues
from ehr.trend import DATA_DIR

DEFAULT_MODEL = "claude-opus-5"
COMPOSER_VERSION = "composer-v1"

SYSTEM_PROMPT = """You compose clinical documents from a problem-oriented chart. You write for ONE audience,
from structured chart state and the clinician's recorded decisions. You never write from memory
of the patient; everything you state must be traceable to an id in the evidence catalog.

Rules
- Write the document the audience needs, not a summary of the chart. A referral letter to a
  specialist states why the patient is being referred, the relevant trajectory with numbers and
  dates, what has been tried or changed, what the referring clinician has already decided and
  why (the reasoning ledger), and the specific questions being asked.
- Every section carries `cites`: ONLY ids from the evidence catalog that support what the
  section says. A claim you cannot cite does not go in the document.
- Where the clinician rejected a system proposal and gave a reason, represent the clinician's
  position, not the system's. The ledger is the clinician's judgment.
- Plain clinical prose, past-to-present voice, no headings inside `text` (headings are the
  `heading` field). 4-7 sections. No salutations or signature blocks: the system renders those.
- `questions`: 2-4 specific questions for the recipient.
- `confidence`: your 0-1 estimate that the referring clinician will sign this as written.
"""

OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "sections", "questions", "confidence"],
    "properties": {
        "title": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["heading", "text", "cites"],
            "properties": {"heading": {"type": "string"}, "text": {"type": "string"},
                           "cites": {"type": "array", "items": {"type": "string"}}}}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
}


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
    return it.get("title") or it["id"]


def build_context(patient: dict, problem_id: str, *, kind: str, audience: str, window="1y",
                  proposed_dir: Path = PROPOSED_DIR) -> dict:
    """Reuses the reasoning context (trends, meds, note findings, catalog) and adds the ledger."""
    ctx = reasoning_context(patient, problem_id, window)
    catalog = dict(ctx["catalog"])
    pid = patient["patient"]["id"]

    signed = [i for i in patient.get("insights", []) if i["problem_id"] == problem_id]
    for i in signed:
        catalog[i["id"]] = f"signed insight: {i['statement'][:80]!r}"

    # Reasoning ledger: every reviewed proposal that touches this problem, with the clinician's reason.
    focus = {problem_id} | {f"LOINC:{t['code']}" for t in ctx["trends"]}
    ledger = []
    for b in list_queues(pid, proposed_dir):
        for k, items in b["proposed"].items():
            for it in items:
                rv = it.get("review")
                if not rv:
                    continue
                hint = (b.get("review_hints") or {}).get(it.get("id"), "")
                touches = (it.get("problem_id") == problem_id or it.get("id") == problem_id
                           or it.get("to") in focus or it.get("from") in focus
                           or problem_id in hint  # e.g. a proposed stage that "supersedes prob_0057"
                           or any((l.get("to") in focus and l.get("from") == it.get("id"))
                                  or (l.get("from") in focus and l.get("to") == it.get("id"))
                                  for l in b["proposed"].get("links", [])))
                if touches:
                    ledger.append({"id": it["id"], "kind": k[:-1], "what": _summary_of(k, it), "decision": rv["decision"],
                                   "reason_code": rv.get("reason_code"), "reason": rv.get("reason"), "by": rv["by"], "at": rv["at"][:10]})
                    catalog.setdefault(it["id"], f"{rv['decision']} {k[:-1]}: {_summary_of(k, it)[:70]}")
        for ch in b.get("medication_changes", []):
            rv = ch.get("review")
            if rv:
                ledger.append({"id": ch["med_id"], "kind": "medication_change", "what": f"{ch['change']} {ch['med_id']} effective {ch['effective']}",
                               "decision": rv["decision"], "reason_code": rv.get("reason_code"), "reason": rv.get("reason"), "by": rv["by"], "at": rv["at"][:10]})

    other_active = [{"id": p["id"], "name": p["name"]} for p in patient["problems"]
                    if p["status"] == "active" and p["id"] != problem_id and not p["name"].startswith(("Gingiv", "Loss of teeth"))]
    for p in other_active:
        catalog[p["id"]] = f"problem: {p['name']}"
    recent = sorted(patient["encounters"], key=lambda e: e["time"])[-6:]
    for e in recent:
        catalog[e["id"]] = f"encounter {e['time'][:10]}: {e['type']}"

    return {
        "document": {"kind": kind, "audience": audience},
        "patient": patient["patient"],
        "problem": ctx["problem"], "window": ctx.get("window"),
        "trends": ctx["trends"], "medications": ctx["medications"], "note_findings": ctx["note_findings"],
        "other_active_problems": other_active,
        "signed_insights": [{"id": i["id"], "statement": i["statement"], "suggested_action": i["suggested_action"],
                             "review": i.get("review")} for i in signed],
        "reasoning_ledger": ledger,
        "recent_encounters": [{"id": e["id"], "time": e["time"][:10], "type": e["type"], "summary": e["summary"]} for e in recent],
        "catalog": catalog,
    }


def build_messages(ctx: dict) -> tuple[list[dict], list[dict]]:
    payload = {k: v for k, v in ctx.items() if k != "catalog"}
    catalog_text = "\n".join(f"  {k}: {v}" for k, v in ctx["catalog"].items())
    user = (f"Compose a {ctx['document']['kind']} for: {ctx['document']['audience']}.\n\n"
            "Chart context (JSON):\n" + json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
            + "\n\nEvidence catalog - the ONLY ids you may cite:\n" + catalog_text)
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}], [{"role": "user", "content": user}]


def validate(patient: dict, ctx: dict, raw: dict, model: str, existing_ids: set[str] | None = None) -> dict:
    pid = patient["patient"]["id"]
    problem_id = ctx["problem"]["id"]
    chart_ids = {x["id"] for key in ("problems", "observations", "medications", "encounters", "notes", "links", "insights", "documents")
                 for x in patient.get(key, [])}
    allowed = set(ctx["catalog"]) & (chart_ids | set(ctx["catalog"]))  # catalog entries already verified to exist or be reviewed items
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    kind, audience = ctx["document"]["kind"], ctx["document"]["audience"]
    taken = set(existing_ids or ()) | {d["id"] for d in patient.get("documents", [])}
    n = 1
    did = f"doc_{problem_id[5:]}_{kind}_{n:02d}"
    while did in taken:
        n += 1
        did = f"doc_{problem_id[5:]}_{kind}_{n:02d}"

    sections, dropped, uncited = [], [], []
    for sec in raw.get("sections") or []:
        cites = [c for c in dict.fromkeys(sec.get("cites") or []) if c in allowed]
        dropped += [c for c in sec.get("cites") or [] if c not in allowed]
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        if not cites:
            uncited.append(sec.get("heading", ""))
        sections.append({"heading": (sec.get("heading") or "").strip(), "text": text, "cites": cites})
    rejected = []
    if dropped:
        rejected.append({"reason": f"dropped citations not in chart: {sorted(set(dropped))}", "item": None})
    proposed = []
    if sections and any(s["cites"] for s in sections):
        evidence = list(dict.fromkeys(c for s in sections for c in s["cites"]))
        proposed.append({
            "id": did, "patient_id": pid, "problem_id": problem_id, "kind": kind, "audience": audience,
            "title": (raw.get("title") or f"{kind.title()} to {audience}").strip(),
            "sections": sections, "questions": [q.strip() for q in (raw.get("questions") or []) if q and q.strip()],
            "status": "proposed",
            "provenance": {"source": "composition", "model": f"{COMPOSER_VERSION}/{model}", "evidence": evidence,
                           "confidence": round(min(1.0, max(0.0, float(raw.get("confidence") or 0.5))), 2)},
            "created_at": now,
        })
    else:
        rejected.append({"reason": "no section carries a verifiable citation", "item": raw})
    hints = {did: f"uncited sections: {', '.join(uncited)}"} if uncited and proposed else {}
    return {"patient_id": pid, "problem_id": problem_id, "kind": kind, "audience": audience,
            "model": f"{COMPOSER_VERSION}/{model}", "composed_at": now,
            "proposed": {"documents": proposed}, "review_hints": hints, "rejected": rejected}


def compose(patient: dict, problem_id: str, *, kind: str = "referral", audience: str = "nephrology",
            window="1y", model: str = DEFAULT_MODEL, raw: dict | None = None,
            proposed_dir: Path = PROPOSED_DIR) -> tuple[dict, dict, dict]:
    ctx = build_context(patient, problem_id, kind=kind, audience=audience, window=window, proposed_dir=proposed_dir)
    if raw is None:
        from ehr.llm import call_structured
        system_blocks, messages = build_messages(ctx)
        raw = call_structured(system_blocks, messages, OUTPUT_SCHEMA, model=model)
    batch = validate(patient, ctx, raw["parsed"], raw.get("model", model))
    batch["usage"] = raw.get("usage")
    return batch, raw, ctx


def run_compose(patient_id: str, problem_id: str, *, kind: str = "referral", audience: str = "nephrology",
                window="1y", model: str = DEFAULT_MODEL, replay: str | Path | None = None,
                data_dir: Path = DATA_DIR, save: bool = True) -> dict:
    data_dir = Path(data_dir)
    proposed_dir = data_dir.parent / "proposed"
    patient = json.loads((data_dir / f"{patient_id}.json").read_text())
    raw = json.loads(Path(replay).read_text()) if replay else None
    batch, raw, _ = compose(patient, problem_id, kind=kind, audience=audience, window=window, model=model, raw=raw, proposed_dir=proposed_dir)
    qp = proposed_dir / patient_id / f"{kind}_{problem_id}.json"
    if save:
        qp.parent.mkdir(parents=True, exist_ok=True)
        qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        if not replay:
            record_response(qp, raw)
    batch["queue_path"] = str(qp)
    return batch


def render_text(doc: dict) -> str:
    """Plain-text rendering (for the CLI and for anyone who wants the letter as text)."""
    out = [doc["title"], ""]
    for s in doc["sections"]:
        out += [s["heading"].upper(), s["text"], f"  [cites: {', '.join(s['cites']) or 'none'}]", ""]
    if doc.get("questions"):
        out += ["QUESTIONS FOR THE RECIPIENT"] + [f"  {i}. {q}" for i, q in enumerate(doc["questions"], 1)]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--problem", required=True)
    ap.add_argument("--kind", default="referral")
    ap.add_argument("--audience", default="nephrology")
    ap.add_argument("--window", default="1y")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--replay")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    if args.dry_run:
        patient = json.loads((data_dir / f"{args.patient_id}.json").read_text())
        ctx = build_context(patient, args.problem, kind=args.kind, audience=args.audience, window=args.window,
                            proposed_dir=data_dir.parent / "proposed")
        system_blocks, messages = build_messages(ctx)
        print(system_blocks[0]["text"]); print(messages[0]["content"]); return 0
    try:
        batch = run_compose(args.patient_id, args.problem, kind=args.kind, audience=args.audience, window=args.window,
                            model=args.model, replay=args.replay, data_dir=data_dir)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr); return 1
    for d in batch["proposed"]["documents"]:
        print(render_text(d)); print()
        print(f"confidence {d['provenance']['confidence']} · evidence {len(d['provenance']['evidence'])} ids")
    for r in batch["rejected"]:
        print("x", r["reason"])
    if batch.get("usage"):
        print("usage:", batch["usage"])
    print(f"review queue: {batch['queue_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
