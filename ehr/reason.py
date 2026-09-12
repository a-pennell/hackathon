"""Reasoning layer: TrendSummaries in, proposed Insights out (schema §9 -> §10).

    python3 -m ehr.reason pt_001 --problem prob_0057 [--window 1y]
    python3 -m ehr.reason pt_001 --all                      # every active problem with monitored series
    python3 -m ehr.reason pt_001 --problem prob_0057 --rules-only   # deterministic, no API call
    python3 -m ehr.reason pt_001 --problem prob_0057 --replay data/proposed/pt_001/reason_prob_0057.raw.json

What the model sees (non-negotiable 4): the problem, one TrendSummary per `monitors`
series, the medications on board (with their events in the window), the note-derived
links to this problem, and an *evidence catalog* of ids it may cite. Never raw value arrays.

What comes out: Insight objects, status "proposed", provenance {source: "reasoning",
model: "reasoner-v1/<model>", trend_codes}. `evidence` is filtered to ids that exist in the
chart; an insight whose evidence is empty after filtering is rejected (non-negotiable 2).
Insights land in the review queue at data/proposed/<patient>/reason_<problem_id>.json.

`--rules-only` produces a plain-language insight from the trend numbers alone, so the demo
has something to show even without an API key.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from ehr.trend import DATA_DIR, trend_from_patient

DEFAULT_MODEL = "claude-opus-5"
REASONER_VERSION = "reasoner-v1"
PROPOSED_DIR = DATA_DIR.parent / "proposed"
DEFAULT_WINDOW = "1y"

SYSTEM_PROMPT = """You are the reasoning step of a problem-oriented electronic health record.
For ONE problem on a patient's chart you receive trend summaries of its monitored lab series,
the medications on board with their start / stop / dose-change events inside the window, and
the note-derived findings that were linked to this problem. You return zero or more Insights
for a clinician to review. Nothing you write reaches the chart until a clinician accepts it.

Rules
- Only write an insight when the data supports a specific, actionable observation: a series
  moving out of range, a change that lines up in time with a medication event, a medication
  that needs review at the current level of a monitored value. If nothing warrants attention,
  return an empty list.
- `statement`: 2-4 sentences, concrete, quantitative, in the past-to-present voice a clinician
  would use in a chart ("Creatinine has risen 38% over 3 months..."). Name the numbers and the
  timing. Say what may be contributing and what may need review. Do not invent values, dates,
  medications or diagnoses that are not in the input.
- `evidence`: ONLY ids from the evidence catalog. Cite the observations, medications, notes and
  links that a reader would want to tap through to. An insight with no evidence is discarded.
- `suggested_action`: one sentence, phrased as something to consider, never as an order.
- `trend_codes`: the LOINC codes of the trend summaries the insight relies on.
- `confidence`: your 0-1 estimate that a clinician will accept the insight as written.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["insights"],
    "properties": {
        "insights": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["statement", "evidence", "suggested_action", "trend_codes", "confidence"],
            "properties": {
                "statement": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "suggested_action": {"type": "string"},
                "trend_codes": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            }}},
    },
}


# ------------------------------------------------------------------ context building

def _accepted(items):
    return [x for x in items if x.get("status") in ("accepted", "active", "resolved")]


def monitored_codes(patient: dict, problem_id: str) -> list[str]:
    codes = []
    for l in _accepted(patient.get("links", [])):
        if l["type"] == "monitors" and l["to"] == problem_id and l["from"].startswith("LOINC:"):
            code = l["from"][6:]
            if code not in codes:
                codes.append(code)
    return codes


def _obs_id_at(patient: dict, code: str, point: dict | None) -> str | None:
    """Find the chart observation an (value, time) TrendSummary point came from."""
    if not point:
        return None
    for o in patient.get("observations", []):
        if (o.get("status") == "accepted" and o["code"]["value"] == code
                and o["effective_time"][:10] == point["time"] and o["value"] == point["value"]):
            return o["id"]
    return None


def build_context(patient: dict, problem_id: str, window=DEFAULT_WINDOW) -> dict:
    """Everything the model gets, plus the evidence catalog used to validate its citations."""
    problem = next((p for p in patient["problems"] if p["id"] == problem_id), None)
    if problem is None:
        raise KeyError(f"{problem_id} not on this chart")
    catalog: dict[str, str] = {problem_id: f"problem: {problem['name']}"}

    trends = []
    for code in monitored_codes(patient, problem_id):
        t = trend_from_patient(patient, code, window)
        if t["n_points"] == 0:
            continue
        ev = {}
        for key in ("baseline", "latest"):
            oid = _obs_id_at(patient, code, t.get(key))
            if oid:
                ev[key] = oid
                catalog[oid] = f"{t['name']} {t[key]['value']} on {t[key]['time']} ({key})"
        cross = t.get("ref_range_crossing")
        if cross:
            for o in patient["observations"]:
                if (o["code"]["value"] == code and o["effective_time"][:10] == cross["at"]
                        and o.get("status") == "accepted"):
                    ev["ref_range_crossing"] = o["id"]
                    catalog[o["id"]] = f"{t['name']} {o['value']} on {cross['at']} (first out of range: {cross['crossed']})"
                    break
        t["evidence_ids"] = ev
        trends.append(t)
    if not trends:
        return {"problem": problem, "trends": [], "medications": [], "note_findings": [], "catalog": catalog}

    start, end = trends[0]["window"]["start"], trends[0]["window"]["end"]
    treats = {l["from"] for l in _accepted(patient.get("links", [])) if l["type"] == "treats" and l["to"] == problem_id}
    meds = []
    for m in _accepted(patient.get("medications", [])):
        segs = m["segments"]
        last = segs[-1]
        active_in_window = any((s["end"] is None or s["end"] >= start) and (s["start"] or "") <= end for s in segs)
        if not active_in_window:
            continue
        events = [e for t in trends for e in t["events_in_window"] if e["med_id"] == m["id"]]
        seen, uniq = set(), []
        for e in events:
            k = (e["kind"], e["time"])
            if k not in seen:
                seen.add(k); uniq.append({"kind": e["kind"], "time": e["time"], "label": e["name"]})
        meds.append({"id": m["id"], "name": m["name"], "dose": last["dose"], "route": last["route"],
                     "frequency": last["frequency"], "since": last["start"], "ongoing": last["end"] is None,
                     "treats_this_problem": m["id"] in treats, "events_in_window": uniq,
                     "source": m["provenance"]["source"]})
        catalog[m["id"]] = f"medication: {m['name']} {last['dose'] or ''}".strip()

    note_findings = []
    for l in _accepted(patient.get("links", [])):
        if l["type"] in ("evidence_for", "suspected_cause", "relevant_to") and l["provenance"].get("source") == "nlp_extraction" \
                and (l["to"] == problem_id or l["from"] == problem_id
                     or any(l["to"] == f"LOINC:{t['code']}" for t in trends)):
            note_findings.append({"link_id": l["id"], "type": l["type"], "from": l["from"], "to": l["to"],
                                  "note_id": l["provenance"].get("note_id"), "quote": l["provenance"].get("quote")})
            catalog[l["id"]] = f"link {l['type']}: {l['from']} -> {l['to']} ({l['provenance'].get('quote', '')[:60]!r})"
            if l["provenance"].get("note_id"):
                catalog[l["provenance"]["note_id"]] = "note"
            if l["from"] in {m["id"] for m in patient["medications"]}:
                catalog[l["from"]] = catalog.get(l["from"], f"medication {l['from']}")
    return {"problem": {k: problem[k] for k in ("id", "name", "status", "onset_date")},
            "window": {"start": start, "end": end},
            "trends": [{k: v for k, v in t.items() if k != "patient_id"} for t in trends],
            "medications": meds, "note_findings": note_findings, "catalog": catalog}


def build_messages(ctx: dict) -> tuple[list[dict], list[dict]]:
    payload = {k: v for k, v in ctx.items() if k != "catalog"}
    catalog_text = "\n".join(f"  {k}: {v}" for k, v in ctx["catalog"].items())
    user = ("Problem context (JSON):\n" + json.dumps(payload, indent=1, sort_keys=True)
            + "\n\nEvidence catalog - the ONLY ids you may cite:\n" + catalog_text)
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}], \
           [{"role": "user", "content": user}]


# ------------------------------------------------------------------------ validation

def _conf(x) -> float:
    try:
        return round(min(1.0, max(0.0, float(x))), 2)
    except (TypeError, ValueError):
        return 0.5


def validate(patient: dict, ctx: dict, raw: dict, model: str, existing_ids: set[str] | None = None) -> dict:
    """Raw model output -> §10 Insight objects with only real evidence ids."""
    problem_id = ctx["problem"]["id"]
    chart_ids = {x["id"] for key in ("problems", "observations", "medications", "encounters", "notes", "links")
                 for x in patient.get(key, [])}
    allowed = set(ctx["catalog"]) & chart_ids
    trend_codes_avail = {t["code"] for t in ctx["trends"]}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    taken = set(existing_ids or ()) | {i["id"] for i in patient.get("insights", [])}
    proposed, rejected = [], []
    n = 0
    for it in raw.get("insights") or []:
        evidence = [e for e in dict.fromkeys(it.get("evidence") or []) if e in allowed]
        dropped = [e for e in it.get("evidence") or [] if e not in allowed]
        if not evidence:
            rejected.append({"reason": "no evidence ids exist in the chart", "item": it})
            continue
        codes = [c for c in it.get("trend_codes") or [] if c in trend_codes_avail] or sorted(trend_codes_avail)
        n += 1
        iid = f"ins_{problem_id[5:]}_{n:02d}"
        while iid in taken:
            n += 1
            iid = f"ins_{problem_id[5:]}_{n:02d}"
        taken.add(iid)
        proposed.append({
            "id": iid, "patient_id": patient["patient"]["id"], "problem_id": problem_id,
            "statement": it.get("statement", "").strip(),
            "evidence": evidence,
            "suggested_action": it.get("suggested_action", "").strip(),
            "status": "proposed",
            "provenance": {"source": "reasoning", "model": f"{REASONER_VERSION}/{model}", "trend_codes": codes,
                           "confidence": _conf(it.get("confidence"))},
            "created_at": now,
        })
        if dropped:
            rejected.append({"reason": f"{iid}: dropped evidence ids not in chart: {dropped}", "item": None})
    return {"patient_id": patient["patient"]["id"], "problem_id": problem_id, "window": ctx.get("window"),
            "model": f"{REASONER_VERSION}/{model}", "reasoned_at": now,
            "proposed": {"insights": proposed}, "rejected": rejected}


# ------------------------------------------------------------------ rules-only path

def rules_insights(ctx: dict) -> dict:
    """Deterministic fallback: one templated insight if any monitored series moved."""
    out = []
    for t in ctx["trends"]:
        if t["direction"] not in ("rising", "falling") or t["n_points"] < 3:
            continue
        b, l = t["baseline"], t["latest"]
        s = (f"{t['name']} has been {t['direction']} over the window {t['window']['start']} to {t['window']['end']}: "
             f"{b['value']} on {b['time']} to {l['value']} on {l['time']} ({t['delta_pct']:+.0f}%).")
        cross = t.get("ref_range_crossing")
        if cross:
            s += f" It has been {'above' if cross['crossed'] == 'high' else 'below'} the reference range since {cross['at']}."
        med_events = [e for e in t["events_in_window"]]
        if med_events:
            s += " Medication events in the window: " + "; ".join(
                f"{e['name']} {e['kind'].replace('med_', '').replace('_', ' ')} {e['time']}" for e in med_events) + "."
        on_board = [m for m in ctx["medications"] if m["ongoing"]]
        if on_board:
            s += " Currently on board: " + ", ".join(f"{m['name']} {m['dose'] or ''}".strip() for m in on_board) + "."
        evidence = [v for v in t["evidence_ids"].values()] + [e["med_id"] for e in med_events] + [ctx["problem"]["id"]]
        out.append({"statement": s, "evidence": list(dict.fromkeys(evidence)),
                    "suggested_action": f"Review the {t['name'].lower()} trend and the medications on board against current kidney function." if "reatinine" in t["name"] or "GFR" in t["name"] else f"Review the {t['name'].lower()} trend with the medications on board.",
                    "trend_codes": [t["code"]], "confidence": 0.5})
    return {"insights": out}


# ---------------------------------------------------------------------- pipeline

def reason_problem(patient: dict, problem_id: str, *, window=DEFAULT_WINDOW, model: str = DEFAULT_MODEL,
                   raw: dict | None = None, rules_only: bool = False) -> tuple[dict, dict, dict]:
    ctx = build_context(patient, problem_id, window)
    if not ctx["trends"]:
        return ({"patient_id": patient["patient"]["id"], "problem_id": problem_id, "window": None,
                 "model": "none", "reasoned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "proposed": {"insights": []}, "rejected": [{"reason": "no monitored series with data in window", "item": None}]},
                {"parsed": {"insights": []}}, ctx)
    if raw is None:
        if rules_only:
            raw = {"parsed": rules_insights(ctx), "model": "rules"}
        else:
            from ehr.llm import call_structured
            system_blocks, messages = build_messages(ctx)
            raw = call_structured(system_blocks, messages, OUTPUT_SCHEMA, model=model)
    batch = validate(patient, ctx, raw["parsed"], raw.get("model", model))
    batch["usage"] = raw.get("usage")
    return batch, raw, ctx


def problems_with_monitors(patient: dict) -> list[str]:
    seen = []
    for p in patient["problems"]:
        if p["status"] == "active" and monitored_codes(patient, p["id"]) and p["id"] not in seen:
            seen.append(p["id"])
    return seen


def run_reasoning(patient_id: str, problem_id: str, *, window=DEFAULT_WINDOW, model: str = DEFAULT_MODEL,
                  rules_only: bool = False, replay: str | Path | None = None, data_dir: Path = DATA_DIR,
                  save: bool = True) -> dict:
    """Reason about one problem and write its queue file (used by the CLI and the API)."""
    data_dir = Path(data_dir)
    patient = json.loads((data_dir / f"{patient_id}.json").read_text())
    raw = json.loads(Path(replay).read_text()) if replay else None
    batch, raw, _ = reason_problem(patient, problem_id, window=window, model=model, raw=raw, rules_only=rules_only)
    qp = data_dir.parent / "proposed" / patient_id / f"reason_{problem_id}.json"
    if save:
        qp.parent.mkdir(parents=True, exist_ok=True)
        qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        if not replay and not rules_only:
            from ehr.extract import record_response
            record_response(qp, raw)
    batch["queue_path"] = str(qp)
    return batch


def summarize(batch: dict) -> str:
    lines = [f"=== reasoning for {batch['problem_id']} ({batch['model']}, window {batch.get('window')}) ==="]
    for i in batch["proposed"]["insights"]:
        lines.append(f"  + {i['id']} (conf {i['provenance']['confidence']}, trends {i['provenance']['trend_codes']})")
        lines.append(f"      {i['statement']}")
        lines.append(f"      action: {i['suggested_action']}")
        lines.append(f"      evidence: {i['evidence']}")
    for r in batch["rejected"]:
        lines.append(f"  x {r['reason']}")
    if batch.get("usage"):
        lines.append(f"usage: {batch['usage']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--problem", action="append", default=[], help="problem id (repeatable)")
    ap.add_argument("--all", action="store_true", help="every active problem that has monitored series")
    ap.add_argument("--window", default=DEFAULT_WINDOW, help="'1y', '90d', or START:END")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--rules-only", action="store_true", help="deterministic templated insight, no API call")
    ap.add_argument("--replay", help="saved *.raw.json model response to validate instead of calling the API")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt, no API call")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    patient = json.loads((data_dir / f"{args.patient_id}.json").read_text())
    window = args.window
    if ":" in window:
        a, b = window.split(":", 1)
        window = {"start": a, "end": b}
    problems = args.problem or (problems_with_monitors(patient) if args.all else [])
    if not problems:
        print("nothing to do: pass --problem <id> or --all", file=sys.stderr)
        return 2

    for pid in problems:
        if args.dry_run:
            ctx = build_context(patient, pid, window)
            system_blocks, messages = build_messages(ctx)
            print(system_blocks[0]["text"]); print(messages[0]["content"]); continue
        try:
            batch = run_reasoning(args.patient_id, pid, window=window, model=args.model,
                                  rules_only=args.rules_only, replay=args.replay, data_dir=data_dir)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(summarize(batch))
        print(f"review queue: {batch['queue_path']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
