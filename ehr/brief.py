"""Pre-visit brief: what changed on this problem, ready before the chart is opened.

    python3 -m ehr.brief pt_001 --problem prob_0057 [--window 90d]
    python3 -m ehr.brief pt_001 --problem prob_0057 --live          # Claude-composed, recorded for replay
    python3 -m ehr.brief pt_001 --problem prob_0057 --replay data/proposed/pt_001/brief_prob_0057.raw.json

Two versions of the same thing:

- `deterministic_brief` is computed on demand from TrendSummaries (§9), medication events, the
  review queue and the ledger. No model, no network, never stored: it is the synthesis that is
  simply *there* when the clinician opens the problem. Every sentence carries the ids it was
  computed from, so the UI can light them up on the sheet.
- `live_brief` asks Claude for three or four sentences over the same context, validated so every
  cited id exists. It is displayed, not written to the chart (a brief is a reading aid, not a
  chart entry), and the raw response is recorded for replay like every other model call.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from ehr.extract import PROPOSED_DIR, record_response
from ehr.reason import build_context as reasoning_context
from ehr.review import ledger_for_problem, list_queues
from ehr.trend import DATA_DIR

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_WINDOW = "90d"

SYSTEM_PROMPT = """You write the pre-visit brief for ONE problem on a patient's chart: three or four sentences a
clinician reads in the ten seconds before opening the chart. What changed, in numbers and dates;
what is waiting for their decision; what they decided last time and why. Past-to-present voice,
no advice, no diagnosis, no adjectives. Every sentence cites only ids from the evidence catalog.
If nothing changed, say so in one sentence."""

OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["sentences"],
    "properties": {"sentences": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["text", "cites"],
        "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}}}},
}


def _nice(v: float) -> str:
    return (f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}").rstrip("0").rstrip(".")


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')}"


def _window(window, today: date | None = None) -> dict:
    today = today or date.today()
    if isinstance(window, dict):
        return window
    n, unit = int(window[:-1]), window[-1]
    days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n
    return {"start": (today - timedelta(days=days)).isoformat(), "end": today.isoformat()}


def deterministic_brief(patient: dict, problem_id: str, window=DEFAULT_WINDOW, *, proposed_dir: Path = PROPOSED_DIR,
                        today: date | None = None) -> dict:
    win = _window(window, today)
    ctx = reasoning_context(patient, problem_id, win)
    problem = ctx["problem"]
    lines: list[dict] = []

    # 1. each monitored series, the one that moved most first: latest vs baseline inside the window
    for t in sorted(ctx["trends"], key=lambda t: -abs(t["delta_pct"] or 0)):
        ev = t.get("evidence_ids", {})
        ids = [i for i in (ev.get("latest"), ev.get("baseline")) if i]
        lat, base = t["latest"], t["baseline"]
        rr = t.get("ref_range_crossing")
        if t["n_points"] == 1:
            text = f"{t['name']} {_nice(lat['value'])} on {_dmy(lat['time'])}, the only result in the window."
        else:
            verb = {"rising": "up", "falling": "down"}.get(t["direction"], "steady")
            pct = f" {abs(t['delta_pct']):.0f}%" if t["delta_pct"] is not None and t["direction"] != "stable" else ""
            text = (f"{t['name']} {_nice(lat['value'])} on {_dmy(lat['time'])}, {verb}{pct} from {_nice(base['value'])} on {_dmy(base['time'])}"
                    f" across {t['n_points']} results.")
        if rr:
            text += f" Outside the reference range ({rr['crossed']}) since {_dmy(rr['at'])}."
            if ev.get("ref_range_crossing"):
                ids.append(ev["ref_range_crossing"])
        lines.append({"kind": "trend", "text": text, "ids": list(dict.fromkeys(ids)), "code": t["code"]})

    # 2. medication events inside the window (any monitored series carries the same list)
    events = ctx["trends"][0]["events_in_window"] if ctx["trends"] else []
    seen = set()
    for e in events:
        key = (e["med_id"], e["kind"], e["time"])
        if key in seen:
            continue
        seen.add(key)
        verb = {"med_start": "started", "med_stop": "stopped", "med_dose_change": "changed dose"}[e["kind"]]
        med = next((m for m in patient["medications"] if m["id"] == e["med_id"]), None)
        src = " (signed from a note)" if med and med["provenance"]["source"] == "nlp_extraction" else ""
        lines.append({"kind": "med", "text": f"{e['name']} {verb} {_dmy(e['time'])}{src}.", "ids": [e["med_id"]]})
    if ctx["trends"] and not events:
        on_board = [m for m in ctx["medications"] if m["ongoing"]]
        if on_board:
            lines.append({"kind": "med", "text": f"No medication changes in the window; {len(on_board)} medications on board.",
                          "ids": [m["id"] for m in on_board][:8]})

    # 3. encounters in the window
    encs = [e for e in patient["encounters"] if win["start"] <= e["time"][:10] <= win["end"]]
    if encs:
        last = max(encs, key=lambda e: e["time"])
        lines.append({"kind": "visit", "text": f"{len(encs)} encounter{'s' if len(encs) != 1 else ''} in the window, last {_dmy(last['time'])} ({last['type']}).",
                      "ids": [last["id"]]})

    # 4. what is waiting, and what was decided
    pending, pending_ids = 0, []
    focus = {problem_id} | {f"LOINC:{t['code']}" for t in ctx["trends"]}
    for b in list_queues(patient["patient"]["id"], proposed_dir):
        plinks = [l for l in b["proposed"].get("links", []) if l["status"] == "proposed" and (l["to"] in focus or l["from"] in focus)]
        touched = {l["from"] for l in plinks} | {l["to"] for l in plinks}
        for k, items in b["proposed"].items():
            for it in items:
                if it["status"] == "proposed" and (it.get("problem_id") == problem_id or it["id"] in touched or it["id"] in focus or k == "links" and it in plinks):
                    pending += 1
                    pending_ids.append(it["id"])
    if pending:
        lines.append({"kind": "queue", "text": f"{pending} proposal{'s' if pending != 1 else ''} about this problem waiting for your decision.",
                      "ids": pending_ids[:12]})
    ledger = ledger_for_problem(patient, problem_id, proposed_dir)
    rejected = [l for l in ledger if l["decision"] == "rejected" and l.get("reason")]
    if rejected:
        r = rejected[-1]
        lines.append({"kind": "ledger", "text": f"Last time you rejected {r['what'].split(':', 1)[-1].strip()} ({r['at'][:10]}): “{r['reason']}”.",
                      "ids": [r["id"]]})
    signed = [i for i in patient.get("insights", []) if i["problem_id"] == problem_id]
    if signed:
        i = signed[-1]
        lines.append({"kind": "insight", "text": f"Signed insight {i['created_at'][:10]}: {i['suggested_action']}", "ids": [i["id"]]})

    if not ctx["trends"]:
        lines.insert(0, {"kind": "trend", "text": f"No monitored series for {problem['name']} has results in this window.", "ids": [problem_id]})
    return {"patient_id": patient["patient"]["id"], "problem_id": problem_id, "window": win, "source": "computed",
            "lines": lines, "pending": pending}


def build_messages(ctx: dict, computed: dict) -> tuple[list[dict], list[dict]]:
    payload = {k: v for k, v in ctx.items() if k != "catalog"}
    payload["computed_brief"] = [l["text"] for l in computed["lines"]]
    payload["reasoning_ledger"] = computed.get("ledger", [])
    catalog_text = "\n".join(f"  {k}: {v}" for k, v in ctx["catalog"].items())
    user = ("Problem context (JSON):\n" + json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
            + "\n\nEvidence catalog - the ONLY ids you may cite:\n" + catalog_text)
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}], [{"role": "user", "content": user}]


def live_brief(patient: dict, problem_id: str, window=DEFAULT_WINDOW, *, model: str = DEFAULT_MODEL, raw: dict | None = None,
               proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> tuple[dict, dict]:
    computed = deterministic_brief(patient, problem_id, window, proposed_dir=proposed_dir, today=today)
    ctx = reasoning_context(patient, problem_id, computed["window"])
    ledger = ledger_for_problem(patient, problem_id, proposed_dir)
    for l in ledger:
        ctx["catalog"].setdefault(l["id"], f"{l['decision']} {l['kind']}: {l['what'][:70]}")
    computed["ledger"] = ledger
    if raw is None:
        from ehr.llm import call_structured
        system_blocks, messages = build_messages(ctx, computed)
        raw = call_structured(system_blocks, messages, OUTPUT_SCHEMA, model=model, effort="medium", max_tokens=2000)
    chart_ids = {x["id"] for key in ("problems", "observations", "medications", "encounters", "notes", "links", "insights", "documents")
                 for x in patient.get(key, [])}
    allowed = set(ctx["catalog"]) | (set(ctx["catalog"]) & chart_ids)
    lines, dropped = [], []
    for s in raw["parsed"].get("sentences") or []:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        ids = [c for c in dict.fromkeys(s.get("cites") or []) if c in allowed]
        dropped += [c for c in s.get("cites") or [] if c not in allowed]
        lines.append({"kind": "model", "text": text, "ids": ids})
    return ({"patient_id": patient["patient"]["id"], "problem_id": problem_id, "window": computed["window"],
             "source": f"brief-v1/{raw.get('model', model)}", "lines": lines, "pending": computed["pending"],
             "dropped_citations": sorted(set(dropped)), "usage": raw.get("usage")}, raw)


def run_live_brief(patient_id: str, problem_id: str, window=DEFAULT_WINDOW, *, model: str = DEFAULT_MODEL,
                   replay: str | Path | None = None, data_dir: Path = DATA_DIR) -> dict:
    data_dir = Path(data_dir)
    proposed_dir = data_dir.parent / "proposed"
    patient = json.loads((data_dir / f"{patient_id}.json").read_text())
    raw = json.loads(Path(replay).read_text()) if replay else None
    brief, raw = live_brief(patient, problem_id, window, model=model, raw=raw, proposed_dir=proposed_dir)
    if not replay:
        qp = proposed_dir / patient_id / f"brief_{problem_id}.json"  # never written: a brief is not a chart entry
        qp.parent.mkdir(parents=True, exist_ok=True)
        record_response(qp, raw)
    return brief


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--problem", required=True)
    ap.add_argument("--window", default=DEFAULT_WINDOW)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--replay")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    if args.live or args.replay:
        try:
            brief = run_live_brief(args.patient_id, args.problem, args.window, model=args.model, replay=args.replay, data_dir=data_dir)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr); return 1
    else:
        patient = json.loads((data_dir / f"{args.patient_id}.json").read_text())
        brief = deterministic_brief(patient, args.problem, args.window, proposed_dir=data_dir.parent / "proposed")
    print(f"Brief for {brief['problem_id']} ({brief['source']}, {brief['window']['start']} to {brief['window']['end']})")
    for l in brief["lines"]:
        print(f"  {l['text']}   [{', '.join(l['ids'])}]")
    if brief.get("dropped_citations"):
        print("  dropped citations:", brief["dropped_citations"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
