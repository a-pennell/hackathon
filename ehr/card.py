"""The problem card: the clinician's model of one concern, computed on demand from the chart.

    python3 -m ehr.card pt_001 --problem prob_0057 [--window 1y]

Like a TrendSummary, a card is a view: recomputed every time, never stored. It answers the seven
questions of docs/design/clinical-reasoning-ehr.md from what is already on the chart and in the
review queue:

    representation   one sentence in illness-script order (context -> presentation -> trajectory
                     -> current state), PROPOSED by rules with citations; the clinician accepts,
                     edits or rejects it. Never rendered as authored.
    supporting       findings that stand for the current reading, each a chart id.
    doesnt_fit       rule checks that stand against it or fit no explanation: discordant assays
                     on one day, a counter-trend move while a suspected cause continued, a
                     medication that contradicts the problem state, a missed expectation.
    plan             signed orders and medication changes on this problem, typed by plan kind.
    expected         a proposed expectation when a suspected cause was stopped: which series,
                     which direction, by when; evaluated against results that arrive after it.
    reconsider_if    proposed contingencies read off the same expectation.
    changed          the computed brief's lines: what moved, what changed on the list, what waits.

Nothing here writes to the chart. Authored fields (an accepted representation, an assessment, a
clinician-set expectation) are the flagged schema additions in the design doc's appendix and are
not persisted by this slice.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from ehr.brief import deterministic_brief
from ehr.extract import PROPOSED_DIR
from ehr.focus import cluster_of
from ehr.reason import _accepted, build_context, monitored_codes
from ehr.review import ledger_for_problem, list_queues
from ehr.trend import DATA_DIR, load_patient

PLAN_KIND = {"lab": "diagnostic", "imaging": "diagnostic", "medication_change": "therapeutic", "referral": "referral"}
EXPECTATION_DAYS = 14
EXPECTATION_MOVE = 0.25   # the corridor is drawn from the value at the stop toward a quarter's move
ABBREV = {"Diabetes mellitus type 2": "T2DM", "Chronic congestive heart failure": "HFrEF", "Essential hypertension": "HTN",
          "Chronic kidney disease stage 3": "CKD 3", "Ischemic heart disease": "IHD"}


def _nice(v: float) -> str:
    s = f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s  # never strip the zeros of 150


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _age(dob: str, today: date) -> int:
    b = date.fromisoformat(dob)
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def _series(patient: dict, code: str, start: str, end: str) -> list[dict]:
    pts = [o for o in patient["observations"] if o.get("status") == "accepted" and o["code"]["value"] == code
           and start <= o["effective_time"][:10] <= end]
    return sorted(pts, key=lambda o: o["effective_time"])


def _worse_when_rising(t: dict) -> bool | None:
    """Direction of harm for a monitored series, read off where the latest value sits against its range."""
    cross = t.get("ref_range_crossing")
    if cross:
        return cross["crossed"] == "high"
    return None


def _targets(patient: dict, problem: dict) -> set[str]:
    """Ids a link can point at to count as 'about this problem': the problem and its monitored series."""
    return {problem["id"]} | {f"LOINC:{c}" for c in monitored_codes(patient, problem["id"])}


def _stem(name: str) -> str:
    return " ".join(name.lower().split()[:3])


def _epistemic(problem: dict) -> tuple[str, str]:
    src = problem.get("provenance", {}).get("source")
    name = problem["name"].lower()
    if src == "nlp_extraction" or "likely" in name or "suspected" in name or "possible" in name:
        return "suspected", "raised from a note without a confirmed code"
    if problem.get("code"):
        return "confirmed", "coded on import"
    return "working", "no code on the chart"


def _lead(trends: list[dict]) -> dict | None:
    """The series the clinician is here for: one outside its range first, then the one that moved most."""
    return min(trends, key=lambda t: (0 if t.get("ref_range_crossing") else 1, -abs(t["delta_pct"] or 0)), default=None)


def _worsening(t: dict) -> bool | None:
    """True when the series sits outside its range on the harmful side and has moved further that way
    since the baseline, whatever the size of the move; False when it is coming back; None when it
    never left its range or has not moved."""
    wr = _worse_when_rising(t)
    if wr is None or not t.get("latest") or not t.get("baseline"):
        return None
    lat, base = t["latest"]["value"], t["baseline"]["value"]
    if lat == base:
        return None
    return (lat > base) == wr


def _qualifiers(patient: dict, problem: dict, lead: dict | None, today: date, expectation: dict | None, trends: list[dict] = ()) -> list[dict]:
    q = []
    kin = [p for p in patient["problems"] if _stem(p["name"]) == _stem(problem["name"]) and p.get("onset_date")]
    first = min(kin, key=lambda p: p["onset_date"]) if kin else problem
    onset = first.get("onset_date")
    if onset:
        days = (today - date.fromisoformat(onset[:10])).days
        why = f"onset {_dmy(onset)}" + (f" ({first['name']})" if first["id"] != problem["id"] else "")
        q.append({"label": "chronic" if days > 365 else "new", "computed": True, "why": why})
    bad = [t for t in trends if _worsening(t)] or ([lead] if lead and _worsening(lead) else [])
    if bad:
        t = bad[0]
        q.append({"label": "worsening", "computed": True, "why": f"{t['name']} {t['direction']} {abs(t['delta_pct'] or 0):.0f}% over the window"})
    elif lead and lead.get("direction") in ("rising", "falling"):
        good = _worsening(lead) is False
        q.append({"label": "improving" if good else "progressive", "computed": True,
                  "why": f"{lead['name']} {lead['direction']} {abs(lead['delta_pct'] or 0):.0f}% over the window"})
    elif lead:
        q.append({"label": "stable", "computed": True, "why": f"{lead['name']} steady"})
    if expectation and expectation.get("status") == "missed":
        q.append({"label": "unexpected", "computed": True, "why": expectation["statement"]})
    return q


def _representation(patient: dict, problem: dict, ctx: dict, today: date, win: dict) -> dict:
    pt = patient["patient"]
    cites: list[str] = [problem["id"]]
    others = [p for p in patient["problems"] if p["status"] == "active" and p["id"] != problem["id"]
              and _stem(p["name"]) != _stem(problem["name"]) and (p["name"] in ABBREV or monitored_codes(patient, p["id"]))]
    others.sort(key=lambda p: (p["name"] not in ABBREV, p.get("onset_date") or ""))
    context = f"{_age(pt['dob'], today)}{pt['sex']}"
    if others:
        names = [ABBREV.get(p["name"], p["name"]) for p in others[:3]]
        context += " with " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0])
        cites += [p["id"] for p in others[:3]]
    parts = [context + "."]

    trends = sorted(ctx["trends"], key=lambda t: (0 if t.get("ref_range_crossing") else 1, -abs(t["delta_pct"] or 0)))
    if trends:
        t = trends[0]
        ev = t.get("evidence_ids", {})
        lat, base = t["latest"], t["baseline"]
        s = f"{t['name']} {_nice(base['value'])} → {_nice(lat['value'])} between {_dmy(base['time'])} and {_dmy(lat['time'])}"
        if t.get("ref_range_crossing"):
            s += f", outside range since {_dmy(t['ref_range_crossing']['at'])}"
        cites += [i for i in (ev.get("baseline"), ev.get("latest"), ev.get("ref_range_crossing")) if i]
        for o in trends[1:3]:
            if o["direction"] in ("rising", "falling"):
                s += f"; {o['name']} {o['direction']} to {_nice(o['latest']['value'])}"
                cites += [i for i in (o.get("evidence_ids") or {}).values() if i]
        parts.append(s + ".")

    targets = _targets(patient, problem)
    causes = [l for l in _accepted(patient["links"]) if l["type"] == "suspected_cause" and l["to"] in targets]
    seen = set()
    for l in causes:
        med = next((m for m in patient["medications"] if m["id"] == l["from"]), None)
        if not med or med["id"] in seen:
            continue
        seen.add(med["id"])
        seg = med["segments"][0]
        s = f"{med['name']} {seg.get('dose') or ''}".strip()
        if seg.get("start"):
            s += f" since {_dmy(seg['start'])}"
        if med["segments"][-1].get("end"):
            s += f", stopped {_dmy(med['segments'][-1]['end'])}"
        parts.append(s + ", recorded as a suspected cause.")
        cites += [med["id"], l["id"]]

    findings = [f for f in ctx["note_findings"] if f["type"] == "evidence_for" and f["to"] == problem["id"] and f.get("quote")]
    if findings:
        notes = {n["id"]: n for n in patient["notes"]}
        latest_note = max((f["note_id"] for f in findings if f["note_id"] in notes), key=lambda nid: notes[nid]["time"], default=None)
        if latest_note:
            qs = [f for f in findings if f["note_id"] == latest_note][:2]
            parts.append(f"From the note of {_dmy(notes[latest_note]['time'])}: " + "; ".join(f"“{f['quote'].strip().rstrip('.')[:110]}”" for f in qs) + ".")
            cites += [latest_note] + [f["link_id"] for f in qs]

    still = [m for m in ctx["medications"] if m["ongoing"] and m["treats_this_problem"]]
    if still:
        parts.append("Still on " + ", ".join(f"{m['name']} {m['dose'] or ''}".strip() for m in still[:3]) + ".")
        cites += [m["id"] for m in still[:3]]

    return {"text": " ".join(parts), "tier": "proposed", "source": "computed", "cites": list(dict.fromkeys(cites)),
            "as_of": today.isoformat(), "window": win}


def _supporting(patient: dict, problem: dict, ctx: dict) -> list[dict]:
    out = []
    for t in sorted(ctx["trends"], key=lambda t: (0 if t.get("ref_range_crossing") else 1, -abs(t["delta_pct"] or 0))):
        ev = t.get("evidence_ids", {})
        moved = t["direction"] in ("rising", "falling")
        worse = _worsening(t)
        if (moved or worse is not None) and ev.get("latest") and t["n_points"] > 1:
            pct = t["delta_pct"] or 0
            word = t["direction"] if moved else ("up" if pct > 0 else "down")
            detail = f"{word} {abs(pct):.0f}% since {_dmy(t['baseline']['time'])}" + (", above range" if worse and _worse_when_rising(t) else ", below range" if worse else "")
            out.append({"id": ev["latest"], "ids": [i for i in (ev.get("baseline"), ev.get("latest")) if i], "kind": "result", "latest_time": t["latest"]["time"],
                        "text": f"{t['name']} {_nice(t['baseline']['value'])} → {_nice(t['latest']['value'])}",
                        "detail": detail, "source": "measured", "valence": "for"})
    for l in _accepted(patient["links"]):
        if l["type"] == "suspected_cause" and l["to"] in _targets(patient, problem):
            med = next((m for m in patient["medications"] if m["id"] == l["from"]), None)
            if med and not any(x["id"] == med["id"] for x in out):
                seg = med["segments"][0]
                out.append({"id": med["id"], "ids": [med["id"], l["id"]], "kind": "medication",
                            "text": f"{med['name']} {seg.get('dose') or ''}".strip() + (f" since {_dmy(seg['start'])}" if seg.get("start") else ""),
                            "detail": "suspected cause" + (f" · {l['provenance'].get('quote', '')[:80]}" if l["provenance"].get("quote") else ""),
                            "source": "note" if l["provenance"].get("source") == "nlp_extraction" else "chart", "valence": "for"})
    for f in ctx["note_findings"]:
        if f["type"] == "evidence_for" and f["to"] == problem["id"] and f.get("quote"):
            out.append({"id": f["link_id"], "ids": [f["link_id"], f["note_id"]], "kind": "finding",
                        "text": f["quote"].strip().rstrip(".")[:120], "detail": f"note {f['note_id'].replace('note_', '')}",
                        "source": "patient-reported" if any(w in f["quote"].lower() for w in ("reports", "he ", "she ", "feels")) else "clinician-documented",
                        "valence": "for"})
    return out


def _doesnt_fit(patient: dict, problem: dict, ctx: dict, start: str, end: str, expectation: dict | None) -> list[dict]:
    out = []
    codes = monitored_codes(patient, problem["id"])
    series = {c: _series(patient, c, start, end) for c in codes}
    names = {c: (s[-1]["name"] if s else c) for c, s in series.items()}

    # 1. two series for one analyte disagree on the same day (P9: surfaced, never averaged)
    stems = {}
    for c in codes:
        stems.setdefault(names[c].split(" (")[0].split(",")[0].lower(), []).append(c)
    for stem, cs in stems.items():
        if len(cs) < 2:
            continue
        by_day = {}
        for c in cs:
            for o in series[c]:
                by_day.setdefault(o["effective_time"][:10], []).append(o)
        for day, obs in sorted(by_day.items(), reverse=True):
            vals = sorted(obs, key=lambda o: o["value"])
            if len(vals) >= 2 and vals[0]["value"] > 0 and vals[-1]["value"] / vals[0]["value"] > 1.5:
                lo, hi = vals[0], vals[-1]
                out.append({"kind": "discordance", "valence": "against", "ids": [lo["id"], hi["id"]],
                            "text": f"{lo['name']} {_nice(lo['value'])} and {hi['name']} {_nice(hi['value'])} on the same day, {_dmy(day)}",
                            "detail": "two assays, one analyte; which is real decides the staging"})
                break

    # 2. a counter-trend move in the lead series while a suspected-cause course continued
    lead = _lead(ctx["trends"])
    if lead and lead["direction"] in ("rising", "falling"):
        pts = series.get(lead["code"], [])
        targets = _targets(patient, problem)
        causes = [m for m in _accepted(patient["medications"]) if any(
            l["type"] == "suspected_cause" and l["from"] == m["id"] and l["to"] in targets for l in _accepted(patient["links"]))]
        for prev, cur in zip(pts, pts[1:]):
            if prev["value"] <= 0:
                continue
            change = (cur["value"] - prev["value"]) / prev["value"]
            against = change < -0.25 if lead["direction"] == "rising" else change > 0.25
            if not against:
                continue
            day = cur["effective_time"][:10]
            active = [m for m in causes if any((s.get("start") or "") <= day and (s.get("end") is None or s["end"] >= day) for s in m["segments"])]
            if active:
                m = active[0]
                out.append({"kind": "counter_trend", "valence": "unexplained", "ids": [cur["id"], prev["id"], m["id"]],
                            "text": f"{lead['name']} {'fell' if change < 0 else 'rose'} to {_nice(cur['value'])} on {_dmy(day)} while {m['name']} continued",
                            "detail": f"from {_nice(prev['value'])} on {_dmy(prev['effective_time'])}; a cause that was still present did not stop the move"})
                break

    # 3. a medication that contradicts the problem state (rule: metformin with eGFR under 30)
    egfr = next((t for t in ctx["trends"] if t["code"] == "33914-3"), None)
    if egfr and egfr["latest"]["value"] < 30:
        for m in _accepted(patient["medications"]):
            if "metformin" in m["name"].lower() and m["segments"][-1].get("end") is None:
                oid = (egfr.get("evidence_ids") or {}).get("latest")
                out.append({"kind": "contradiction", "valence": "against", "ids": [m["id"]] + ([oid] if oid else []),
                            "text": f"{m['name']} {m['segments'][-1].get('dose') or ''} still active with eGFR {_nice(egfr['latest']['value'])}".strip(),
                            "detail": "medication ↔ problem state; contraindicated below 30"})

    # 4. a missed expectation
    if expectation and expectation.get("status") == "missed":
        out.append({"kind": "expectation", "valence": "against", "ids": expectation.get("ids", []),
                    "text": f"expected {expectation['statement'][0].lower() + expectation['statement'][1:]}; it did not",
                    "detail": f"due {_dmy(expectation['by'])}"})
    return out


def _expectation(patient: dict, problem: dict, ctx: dict, today: date) -> dict | None:
    """When a suspected cause was stopped, propose what should happen next and check whether it has."""
    lead = _lead(ctx["trends"])
    if not lead:
        return None
    stopped = []
    targets = _targets(patient, problem)
    for l in _accepted(patient["links"]):
        if l["type"] != "suspected_cause" or l["to"] not in targets:
            continue
        med = next((m for m in patient["medications"] if m["id"] == l["from"]), None)
        if med and med["segments"][-1].get("end"):
            stopped.append((med["segments"][-1]["end"], med, l))
    if not stopped:
        return None
    end, med, link = max(stopped)
    by = (date.fromisoformat(end) + timedelta(days=EXPECTATION_DAYS)).isoformat()
    at_stop = sorted((o for o in patient["observations"] if o.get("status") == "accepted" and o["code"]["value"] == lead["code"]
                      and lead["window"]["start"] <= o["effective_time"][:10] <= end), key=lambda o: o["effective_time"])
    after = [o for o in patient["observations"] if o.get("status") == "accepted" and o["code"]["value"] == lead["code"] and o["effective_time"][:10] > end]
    # The expectation is fixed at the moment of the stop: the direction the series had up to then,
    # not the direction it has once the answer arrives.
    if len(at_stop) >= 2 and at_stop[-1]["value"] != at_stop[0]["value"]:
        before = "rising" if at_stop[-1]["value"] > at_stop[0]["value"] else "falling"
    elif lead["direction"] in ("rising", "falling"):
        before = lead["direction"]
    else:
        return None
    want = "falling" if before == "rising" else "rising"
    ref = at_stop[-1]["value"] if at_stop else None
    status, ids = "not_yet", [med["id"], link["id"]]
    if after and ref is not None:
        latest = max(after, key=lambda o: o["effective_time"])
        ids.append(latest["id"])
        met = latest["value"] < ref if want == "falling" else latest["value"] > ref
        status = "met" if met else ("missed" if today.isoformat() > by else "not_yet")
    elif today.isoformat() > by:
        status = "missed"
    statement = f"{lead['name']} {want} within {EXPECTATION_DAYS} days of stopping {med['name']}"
    target = None if ref is None else round(ref * (1 - EXPECTATION_MOVE) if want == "falling" else ref * (1 + EXPECTATION_MOVE), 2)
    return {"statement": statement, "code": lead["code"], "name": lead["name"], "direction": want, "since": end, "by": by, "status": status,
            "ref_value": ref, "target_value": target,
            "tier": "proposed", "source": "computed", "ids": ids,
            "reconsider_if": [
                {"trigger": f"no {'fall' if want == 'falling' else 'rise'} in {lead['name']} by {_dmy(by)}",
                 "then": "a cause still present, or a different one: look further"},
            ] + ([{"trigger": "potassium above 5.5", "then": "same-day review"}] if "2823-3" in monitored_codes(patient, problem["id"]) else [])}


def _plan(patient: dict, problem: dict, proposed_dir: Path) -> list[dict]:
    out = []
    for o in patient.get("orders", []):
        if o["problem_id"] != problem["id"]:
            continue
        text = o["name"]
        if o["kind"] == "medication_change" and o.get("med_id"):
            med = next((m for m in patient["medications"] if m["id"] == o["med_id"]), None)
            text = f"{'stop' if o.get('change') == 'stop' else 'change'} {med['name'] if med else o['med_id']}" + (f" → {o['dose']}" if o.get("dose") else "")
        elif o["kind"] == "referral" and o.get("audience"):
            text = f"{o['name']} · {o['audience']}"
        out.append({"id": o["id"], "plan_kind": PLAN_KIND.get(o["kind"], o["kind"]), "text": text, "detail": o.get("detail", ""),
                    "status": "signed", "ids": [o["id"]] + list(o["provenance"].get("evidence", []))[:4]})
    for pl in patient.get("plans", []):
        if pl["problem_id"] == problem["id"]:
            out.append({"id": pl["id"], "plan_kind": pl["kind"], "text": pl["text"], "detail": f"from note {pl['provenance'].get('note_id', '').replace('note_', '')}",
                        "status": "signed", "ids": [pl["id"]] + ([pl["provenance"]["note_id"]] if pl["provenance"].get("note_id") else [])})
    for e in ledger_for_problem(patient, problem["id"], proposed_dir):
        if e["kind"] == "medication_change" and e["decision"] == "accepted":
            med = next((m for m in patient["medications"] if m["id"] == e["id"]), None)
            name = med["name"] if med else e["id"]
            change, _, eff = e["what"].partition(f" {e['id']} effective ")
            what = f"{change} {name}" + (f" · {_dmy(eff)}" if eff else "")
            if not any(x["plan_kind"] == "therapeutic" and name in x["text"] for x in out):
                out.append({"id": e["id"], "plan_kind": "therapeutic", "text": what, "detail": "from the note, signed",
                            "status": "signed", "ids": [e["id"]]})
    return out


TRIPWIRE_PCT = 25
REVIEW_DAYS = 90


def _linked(patient: dict, problem: dict, ctx: dict) -> list[dict]:
    """What this problem is linked to in the graph: courses that treat it, suspected causes, notes that evidence it."""
    out = []
    targets = _targets(patient, problem)
    meds = {m["id"]: m for m in patient["medications"]}
    seen = set()
    for l in _accepted(patient["links"]):
        if l["to"] not in targets:
            continue
        if l["type"] in ("treats", "suspected_cause") and l["from"] in meds and (l["from"], l["type"]) not in seen:
            seen.add((l["from"], l["type"]))
            m = meds[l["from"]]
            seg = m["segments"][-1]
            out.append({"rel": "treated by" if l["type"] == "treats" else "suspected cause", "id": m["id"], "text": f"{m['name']} {seg.get('dose') or ''}".strip(),
                        "detail": "stopped " + _dmy(seg["end"]) if seg.get("end") else "active", "ids": [m["id"], l["id"]]})
    notes = {n["id"]: n for n in patient["notes"]}
    for nid in sorted({l["from"] for l in _accepted(patient["links"]) if l["type"] == "evidence_for" and l["to"] == problem["id"] and l["from"] in notes}, key=lambda i: notes[i]["time"], reverse=True):
        n = notes[nid]
        out.append({"rel": "documented in", "id": nid, "text": f"note · {_dmy(n['time'])} · {n['author']}", "detail": (n.get("status") or "received"), "ids": [nid]})
    return out


def _surveillance(patient: dict, problem: dict, ctx: dict, expectation: dict | None, today: date) -> dict:
    """What would change this problem's status: each monitored series with its threshold and where it stands."""
    rows = []
    for t in ctx["trends"]:
        crossed = t.get("ref_range_crossing")
        moved = t["delta_pct"] is not None and abs(t["delta_pct"]) >= TRIPWIRE_PCT
        rows.append({"code": t["code"], "name": t["name"], "latest": t["latest"], "threshold": f"±{TRIPWIRE_PCT}% over the window, or outside range",
                     "state": "outside range" if crossed else "moved" if moved else "quiet", "tripped": bool(crossed or moved),
                     "ids": [i for i in (t.get("evidence_ids") or {}).values() if i]})
    rows.sort(key=lambda r: (not r["tripped"], r["name"]))
    next_review = expectation["by"] if expectation else (today + timedelta(days=REVIEW_DAYS)).isoformat()
    return {"rows": rows, "next_review": next_review, "expected": expectation}


def problem_card(patient: dict, problem_id: str, window="1y", *, proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> dict:
    today = today or date.today()
    problem = next((p for p in patient["problems"] if p["id"] == problem_id), None)
    if problem is None:
        raise KeyError(f"{problem_id} not on this chart")
    if isinstance(window, str):
        n, unit = int(window[:-1]), window[-1]
        days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n
        win = {"start": (today - timedelta(days=days)).isoformat(), "end": today.isoformat()}
    else:
        win = window
    ctx = build_context(patient, problem_id, win)
    lead = _lead(ctx["trends"])
    expectation = _expectation(patient, problem, ctx, today)
    epistemic, why = _epistemic(problem)
    brief = deterministic_brief(patient, problem_id, "90d", proposed_dir=proposed_dir, today=today)
    ledger = ledger_for_problem(patient, problem_id, proposed_dir)
    cl = cluster_of(patient, problem_id)
    members = [{"id": m["id"], "name": m["name"], "onset_date": m.get("onset_date")} for m in (cl["members"] if cl else [])]
    return {
        "patient_id": patient["patient"]["id"], "problem_id": problem_id, "window": win, "as_of": today.isoformat(),
        "members": members,
        "linked": _linked(patient, problem, ctx),
        "surveillance": _surveillance(patient, problem, ctx, expectation, today),
        "steward": {"name": "Dr. Chen", "role": "PCP"},
        "problem": {k: problem.get(k) for k in ("id", "name", "status", "onset_date", "code", "provenance")},
        "kind": "problem" if problem.get("code") else "concern",
        "epistemic": {"value": epistemic, "computed": True, "why": why},
        "qualifiers": _qualifiers(patient, problem, lead, today, expectation, ctx["trends"]),
        "representation": _representation(patient, problem, ctx, today, win),
        "assessment": None,
        "supporting": _supporting(patient, problem, ctx),
        "doesnt_fit": _doesnt_fit(patient, problem, ctx, win["start"], win["end"], expectation),
        "plan": _plan(patient, problem, proposed_dir),
        "expected": expectation,
        "changed": brief["lines"],
        "pending": brief["pending"],
        "decisions": len(ledger),
        "lead_code": lead["code"] if lead else None,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--problem", required=True)
    ap.add_argument("--window", default="1y")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    card = problem_card(load_patient(args.patient_id, data_dir), args.problem, args.window, proposed_dir=data_dir.parent / "proposed")
    print(json.dumps(card, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
