"""The Care tab: what we are doing, per problem. Computed from the chart, never stored.

    python3 -m ehr.care pt_002

One card per concern (problems that monitor identical series fold into one, as on the overview),
each with the modules the care mockup names: the plan (signed plan items and orders, by kind),
the measures a goal would be set on (monitored series with their move since the last routine
visit), the open loops (orders awaiting a result, referrals awaiting a reply), and what is
waiting for a signature. The same objects pivot by kind across problems: plans, orders and
requests, referrals, follow-ups, measures.

States that are not categories come out as a strip: a monitored measure that is due or overdue
by a simple interval table. "Screenings due" is a state, not a kind of thing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from ehr.card import problem_card
from ehr.extract import PROPOSED_DIR
from ehr.focus import clusters
from ehr.overview import _pending_for, _pending_loops, _since
from ehr.reason import _accepted
from ehr.review import list_queues
from ehr.trend import DATA_DIR, load_patient

# Monitored series and how often they should be repeated. A latest value older than this is due.
DUE_DAYS = {"4548-4": 180, "14959-1": 365, "8480-6": 180, "6298-4": 365, "38483-4": 365, "2160-0": 365, "33914-3": 365}
PLAN_KIND_OF_ORDER = {"lab": "diagnostic", "imaging": "diagnostic", "medication_change": "therapeutic", "referral": "referral"}


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _one_liner(representation: str) -> str:
    """The trajectory sentence of the representation, after the context sentence: what the card leads with."""
    sentences = re.split(r"\.\s+(?=[A-Z])", representation.strip().rstrip("."))
    return (sentences[1] if len(sentences) > 1 else sentences[0]).strip() + "."


def _due_strip(patient: dict, today: date) -> list[dict]:
    out = []
    names = {p["id"]: p["name"] for p in patient["problems"]}
    seen = set()
    for cl in clusters(patient):
        for code in cl["codes"]:
            if code in seen or code not in DUE_DAYS:
                continue
            seen.add(code)
            pts = [o for o in _accepted(patient["observations"]) if o["code"]["value"] == code]
            if not pts:
                continue
            last = max(pts, key=lambda o: o["effective_time"])
            due = date.fromisoformat(last["effective_time"][:10]) + timedelta(days=DUE_DAYS[code])
            if due <= today:
                out.append({"code": code, "name": last["name"], "last": last["effective_time"][:10], "due": due.isoformat(),
                            "overdue_days": (today - due).days, "problem_id": cl["problem"]["id"], "problem_name": names[cl["problem"]["id"]]})
    return sorted(out, key=lambda x: -x["overdue_days"])


def care_view(patient: dict, *, proposed_dir: Path = PROPOSED_DIR, today: date | None = None) -> dict:
    today = today or date.today()
    since = _since(patient, today)
    win = {"start": since["baseline"], "end": today.isoformat()}
    queues = list_queues(patient["patient"]["id"], proposed_dir)
    loops = _pending_loops(patient, queues)
    cards, kinds = [], {"plans": [], "orders": [], "referrals": [], "follow_ups": [], "measures": []}
    for cl in clusters(patient):
        p = cl["problem"]
        ids = [p["id"]] + [m["id"] for m in cl["members"]]
        card = problem_card(patient, p["id"], win, proposed_dir=proposed_dir, today=today) if cl["codes"] else None
        plan = []
        for pl in patient.get("plans", []):
            if pl["problem_id"] in ids:
                src = "you" if pl["provenance"].get("source") == "clinician" else "note"
                plan.append({"id": pl["id"], "kind": pl["kind"], "text": pl["text"], "status": "signed", "source": src, "at": (pl.get("review") or {}).get("at") or pl["created_at"]})
        for o in patient.get("orders", []):
            if o["problem_id"] in ids:
                text = o["name"] + (f" · {o['audience']}" if o.get("audience") else "")
                if o.get("provenance", {}).get("from_plan"):
                    continue  # a clinician's diagnostic or referral intent is already in the plan; the order is its execution
                plan.append({"id": o["id"], "kind": PLAN_KIND_OF_ORDER.get(o["kind"], o["kind"]), "text": text, "status": "signed", "source": "order", "at": o.get("ordered_at") or o["created_at"]})
        plan.sort(key=lambda x: ({"therapeutic": 0, "diagnostic": 1, "monitoring": 2, "referral": 3, "education": 4, "follow_up": 5}.get(x["kind"], 9), x["text"]))
        measures = []
        if card:
            for x in card["supporting"]:
                if x["kind"] == "result":
                    measures.append({"text": x["text"], "detail": x["detail"], "ids": x["ids"], "latest_time": x.get("latest_time")})
        my_loops = [l for l in loops if l["problem_id"] in ids]
        pending = _pending_for(patient, ids, cl["codes"], queues)
        entry = {
            "id": p["id"], "name": p["name"], "code": p.get("code"), "status": p["status"], "onset_date": p.get("onset_date"),
            "members": [{"id": m["id"], "name": m["name"]} for m in cl["members"]],
            "epistemic": card["epistemic"]["value"] if card else ("suspected" if p["provenance"].get("source") == "nlp_extraction" else "confirmed" if p.get("code") else "working"),
            "qualifiers": [q["label"] for q in card["qualifiers"]] if card else [],
            "one_liner": _one_liner(card["representation"]["text"]) if card else None,
            "assessment": None,
            "plan": plan, "measures": measures, "loops": my_loops, "pending": pending,
            "expected": {k: card["expected"][k] for k in ("statement", "by", "status")} if card and card["expected"] else None,
            "decisions": card["decisions"] if card else 0,
        }
        cards.append(entry)
        for x in plan:
            row = {**x, "problem_id": p["id"], "problem_name": p["name"]}
            kinds["plans"].append(row)
            if x["kind"] == "referral":
                kinds["referrals"].append(row)
            elif x["kind"] == "follow_up":
                kinds["follow_ups"].append(row)
            if x["source"] == "order":
                kinds["orders"].append(row)
        for m in measures:
            kinds["measures"].append({**m, "problem_id": p["id"], "problem_name": p["name"]})

    def order(c):
        bad = 0 if ("worsening" in c["qualifiers"] or "unexpected" in c["qualifiers"]) else 1
        return (0 if c["status"] == "active" else 1, 0 if c["pending"] else 1, bad, 0 if c["measures"] else 1, -(int((c["onset_date"] or "0000")[:4])))
    cards.sort(key=order)
    return {"patient_id": patient["patient"]["id"], "as_of": today.isoformat(), "since": since, "cards": cards, "kinds": kinds,
            "due": _due_strip(patient, today), "loops": loops}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patient_id")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    print(json.dumps(care_view(load_patient(args.patient_id, data_dir), proposed_dir=data_dir.parent / "proposed"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
