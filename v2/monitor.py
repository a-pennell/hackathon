"""v2: the problem list as a gate, and the problem card as seven answers. Computed from the chart, never stored.

The first glance is standing: which problems are in good standing and which are not. Rules decide it from the
monitored series, the expectation set when a course closed, the open loops and the unexplained findings. No model
runs here. Then one problem opens onto the seven questions a clinician should be able to answer on leaving it:
what is happening, what we think it means, what changed, what we are doing, what we are uncertain about, what
should happen next, what would make us change course. Everything comes from ehr/card.py, ehr/overview.py and the
chart; this module only arranges it.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ehr.card import problem_card
from ehr.extract import PROPOSED_DIR
from ehr.focus import clusters
from ehr.overview import _pending_loops, _since, patient_overview
from ehr.reason import _accepted
from ehr.review import list_queues

STANDING_WORD = {"off_course": "off course", "watch": "watch", "good": "in good standing", "unmonitored": "not monitored"}


def _window(today: date) -> dict:
    return {"start": (today - timedelta(days=365)).isoformat(), "end": today.isoformat()}


def _standing(card: dict | None, loops: list[dict]) -> tuple[str, str]:
    """The gate. Off course: an expectation missed, or a monitored series outside range and still moving the wrong way.
    Watch: outside range but steady, a change made and not yet answered, an unexplained finding, or a loop open.
    Good: monitored, in range, steady. Unmonitored: no series to watch."""
    if card is None:
        return "unmonitored", "no monitored series"
    exp = card.get("expected")
    quals = {q["label"] for q in card.get("qualifiers", [])}
    tripped = [r for r in card["surveillance"]["rows"] if r.get("tripped")]
    if exp and exp.get("status") == "missed":
        return "off_course", f"expected {exp['statement'].lower()} by {exp['by']}; it did not"
    if "worsening" in quals or "unexpected" in quals:
        res = next((x for x in card["supporting"] if x.get("kind") == "result"), None)
        lead = f"{res['text']} · {res['detail']}" if res else next((q["why"] for q in card["qualifiers"] if q["label"] in ("worsening", "unexpected")), "")
        return "off_course", lead
    if exp and exp.get("status") == "not_yet":
        return "watch", f"waiting to see {exp['statement'].lower()} by {exp['by']}"
    if tripped:
        r = tripped[0]
        return "watch", f"{r['name']} {r['latest']['value']:g} · {r['state']}, steady"
    if card.get("doesnt_fit"):
        return "watch", card["doesnt_fit"][0]["text"]
    if loops:
        return "watch", f"{len(loops)} waiting on an answer"
    return "good", "monitored, in range, steady"


def _next_for(card: dict | None, loops: list[dict]) -> str | None:
    if loops:
        return loops[0]["text"] + " · " + loops[0].get("detail", "")
    if card and card.get("expected") and card["expected"].get("status") == "not_yet":
        return f"reassess by {card['expected']['by']}"
    if card and card["surveillance"].get("next_review"):
        return f"next review {card['surveillance']['next_review']}"
    return None


def problem_list(patient: dict, *, proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> dict:
    today = today or date.today()
    win = _window(today)
    ov = patient_overview(patient, proposed_dir=proposed_dir, today=today)
    queues = list_queues(patient["patient"]["id"], proposed_dir)
    loops = _pending_loops(patient, queues)
    rows = []
    for cl in clusters(patient):
        p = cl["problem"]
        ids = [p["id"]] + [m["id"] for m in cl["members"]]
        card = problem_card(patient, p["id"], win, proposed_dir=proposed_dir, today=today) if cl["codes"] else None
        my_loops = [l for l in loops if l["problem_id"] in ids]
        standing, why = _standing(card, my_loops)
        concern = next((c for c in ov["concerns"] if c["id"] == p["id"]), None)
        if standing == "off_course" and concern and concern.get("lead"):
            why = f"{concern['lead']['text']} · {concern['lead']['detail']}"
        last = None
        if card:
            times = [x.get("latest_time") for x in card["supporting"] if x.get("latest_time")]
            last = max(times) if times else None
        rows.append({
            "id": p["id"], "name": p["name"], "members": [{"id": m["id"], "name": m["name"]} for m in cl["members"]],
            "standing": standing, "standing_word": STANDING_WORD[standing], "why": why,
            "epistemic": card["epistemic"]["value"] if card else (concern or {}).get("epistemic", "confirmed"),
            "lead": (concern or {}).get("lead"), "pending": (concern or {}).get("pending", 0) if concern else 0,
            "expected": {k: card["expected"][k] for k in ("statement", "by", "status")} if card and card.get("expected") else None,
            "next": _next_for(card, my_loops), "last_change": last, "onset": p.get("onset_date"),
        })
    order = {"off_course": 0, "watch": 1, "good": 2, "unmonitored": 3}
    rows.sort(key=lambda r: (order[r["standing"]], r["name"]))
    return {"patient": patient["patient"], "as_of": today.isoformat(), "since": ov["since"], "here_for": ov["here_for"],
            "problems": rows, "counts": {k: sum(1 for r in rows if r["standing"] == k) for k in order}}


def _detected(card: dict) -> list[dict]:
    """Rule-detected changes on this problem: what the system noticed without being asked."""
    out = []
    for r in card["surveillance"]["rows"]:
        if r.get("tripped"):
            out.append({"id": f"det_{card['problem_id']}_{r['code']}", "text": f"{r['name']} {r['latest']['value']:g} on {r['latest']['time']} · {r['state']}", "ids": r["ids"], "code": r["code"]})
    exp = card.get("expected")
    if exp and exp.get("status") in ("missed", "met"):
        out.append({"id": f"det_{card['problem_id']}_expect", "text": f"Expectation {exp['status']}: {exp['statement']} by {exp['by']}", "ids": exp.get("ids", []), "code": exp.get("code")})
    for x in card.get("doesnt_fit", []):
        out.append({"id": f"det_{card['problem_id']}_" + "".join(ch for ch in x["text"][:24] if ch.isalnum()), "text": x["text"] + (f" · {x['detail']}" if x.get("detail") else ""), "ids": x.get("ids", []), "code": None})
    return out


def problem_view(patient: dict, problem_id: str, *, proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> dict:
    today = today or date.today()
    win = _window(today)
    card = problem_card(patient, problem_id, win, proposed_dir=proposed_dir, today=today)
    queues = list_queues(patient["patient"]["id"], proposed_dir)
    loops = [l for l in _pending_loops(patient, queues) if l["problem_id"] in {problem_id} | {m["id"] for m in card.get("members", [])}]
    standing, why = _standing(card, loops)
    names = {p["id"]: p["name"] for p in patient["problems"]}
    names.update({m["id"]: m["name"] for m in patient["medications"]})
    insights = [i for i in patient.get("insights", []) if i.get("problem_id") == problem_id and i.get("status") == "accepted"]
    proposed_insights = [i for b in queues for i in b["proposed"].get("insights", []) if i.get("problem_id") == problem_id and i.get("status") == "proposed"]
    causes = [l for l in _accepted(patient["links"]) if l["type"] == "suspected_cause" and l["to"] == problem_id]
    rejected = [l for b in queues for l in b["proposed"].get("links", []) if l.get("status") == "rejected" and l["type"] == "suspected_cause" and l["to"] == problem_id]
    acknowledged = {tuple(sorted(i.get("evidence", []))) for i in insights if (i.get("provenance") or {}).get("source") == "rules"}
    detected = _detected(card)
    for d in detected:
        d["acknowledged"] = tuple(sorted(d["ids"])) in acknowledged

    happening = [{"text": x["text"], "detail": x.get("detail", ""), "ids": x["ids"], "source": x.get("source", "")} for x in card["supporting"]]
    means = {"text": card["representation"]["text"], "cites": card["representation"]["cites"], "epistemic": card["epistemic"],
             "causes": [{"text": f"{names.get(l['from'], l['from'])} is a suspected cause", "ids": [l["id"], l["from"]], "signed": True} for l in causes]
                       + [{"text": f"{names.get(l['from'], l['from'])} was proposed as a cause and rejected" + (f": {l['review']['reason']}" if (l.get('review') or {}).get('reason') else ""), "ids": [l["id"], l["from"]], "signed": False} for l in rejected],
             "insights": [{"id": i["id"], "text": i["statement"], "action": i.get("suggested_action"), "ids": i.get("evidence", []), "status": "signed", "source": (i.get("provenance") or {}).get("source")} for i in insights if (i.get("provenance") or {}).get("source") != "rules"]
                         + [{"id": i["id"], "text": i["statement"], "action": i.get("suggested_action"), "ids": i.get("evidence", []), "status": "proposed", "confidence": (i.get("provenance") or {}).get("confidence")} for i in proposed_insights]}
    changed = {"since": card["window"]["start"], "lines": [{"text": x["text"], "ids": x["ids"], "kind": x["kind"]} for x in card["changed"]], "detected": detected}
    doing = {"plan": card["plan"], "linked": card["linked"], "loops": loops}
    uncertain = ([{"text": x["text"], "detail": x.get("detail", ""), "ids": x["ids"], "valence": x.get("valence")} for x in card["doesnt_fit"]]
                 + [{"text": i["statement"], "detail": f"proposed insight · confidence {i['provenance'].get('confidence', 0):.2f}", "ids": i.get("evidence", []), "valence": "unx"} for i in proposed_insights if (i.get("provenance") or {}).get("confidence", 1) < 0.7]
                 + [{"text": l["text"], "detail": "waiting on an answer", "ids": [l["id"]], "valence": "unx"} for l in loops])
    nxt = ([{"text": l["text"], "detail": l.get("detail", ""), "ids": [l["id"]], "kind": l["kind"]} for l in loops]
           + [{"text": i["suggested_action"].removeprefix("Consider ").capitalize(), "detail": "from a signed insight", "ids": [i["id"]], "kind": "insight"} for i in insights if i.get("suggested_action")])
    if card["surveillance"].get("next_review"):
        nxt.append({"text": f"Next review {card['surveillance']['next_review']}", "detail": "from the monitoring interval", "ids": [], "kind": "review"})
    change_course = {"expected": card["expected"], "tripwires": [{"name": r["name"], "code": r["code"], "threshold": r["threshold"], "state": r["state"], "latest": r["latest"], "ids": r["ids"]} for r in card["surveillance"]["rows"]],
                     "reconsider_if": [f"{r['trigger']} → {r['then']}" if isinstance(r, dict) else str(r) for r in ((card.get("expected") or {}).get("reconsider_if") or [])]}
    return {"problem": {"id": problem_id, "name": card["problem"]["name"], "standing": standing, "standing_word": STANDING_WORD[standing], "why": why,
                        "epistemic": card["epistemic"], "qualifiers": card["qualifiers"], "steward": card.get("steward"), "onset": card["problem"].get("onset_date"),
                        "members": card.get("members", [])},
            "window": card["window"], "as_of": today.isoformat(),
            "answers": {"happening": happening, "means": means, "changed": changed, "doing": doing, "uncertain": uncertain, "next": nxt, "change_course": change_course},
            "decisions": card.get("decisions", 0), "pending": card.get("pending", 0)}
