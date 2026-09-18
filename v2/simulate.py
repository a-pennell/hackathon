"""v2: what each option is projected to do to the value this problem is watched by. Computed on demand, never stored.

A projection is the expectation object with a magnitude and a band, made for options before one is chosen: for each
candidate action, the monitored value's path from today, as a range, with the date the full effect is expected. The
sizes are published average effects, shown as ranges and labelled as such. They are not patient-specific and not
probabilities; the patient's own next value is what tells us whether the projection held. Choosing an option is an
ordinary plan line; "the current plan" is the options already on the chart, combined.
"""

from __future__ import annotations

from datetime import date, timedelta

from ehr.reason import _accepted
from ehr.review import open_encounter

HORIZON_WEEKS = 12
COMBINE = 0.8  # second and later agents add about four fifths of their solo effect (Law 2009, combination therapy)

# code -> goal (upper bound) used when the chart's reference range does not carry one
GOALS = {"8480-6": 140.0, "8462-4": 90.0, "4548-4": 7.0}

# Published average effects. low/high are the change in the value at full effect (negative = falls); weeks = time to it.
EFFECTS = [
    {"id": "stop_nsaid", "code": "8480-6", "label": "Stop the NSAID", "kind": "therapeutic", "text": "Stop ibuprofen; acetaminophen instead",
     "low": -6.0, "high": -3.0, "weeks": 2, "source": "Johnson 1994, Ann Intern Med: NSAIDs raise mean arterial pressure about 5 mmHg",
     "applies": lambda c: c["nsaid_ever"], "on_plan": lambda c: c["nsaid_stopped"] or "stop ibuprofen" in c["plan_text"]},
    {"id": "add_acei", "code": "8480-6", "label": "Add an ACE inhibitor at standard dose", "kind": "therapeutic", "text": "Start lisinopril 10 mg daily",
     "low": -12.0, "high": -8.0, "weeks": 4, "source": "Law 2009, BMJ: one drug at standard dose lowers systolic about 9 mmHg",
     "applies": lambda c: True, "on_plan": lambda c: c["on"]("lisinopril") or "lisinopril" in c["plan_text"]},
    {"id": "uptitrate_acei", "code": "8480-6", "label": "Double the ACE inhibitor", "kind": "therapeutic", "text": "Increase lisinopril to 20 mg daily",
     "low": -4.0, "high": -2.0, "weeks": 4, "source": "Law 2009, BMJ: doubling a dose adds about a fifth of the standard-dose effect",
     "applies": lambda c: c["on"]("lisinopril"), "on_plan": lambda c: "lisinopril to 20" in c["plan_text"]},
    {"id": "sodium", "code": "8480-6", "label": "Sodium reduction, DASH pattern", "kind": "education", "text": "Dietary sodium under 2 g a day, DASH eating pattern",
     "low": -6.0, "high": -4.0, "weeks": 4, "source": "Sacks 2001, NEJM (DASH-Sodium)",
     "applies": lambda c: True, "on_plan": lambda c: "sodium" in c["plan_text"] or "dash" in c["plan_text"]},
    {"id": "metformin_taken", "code": "4548-4", "label": "Metformin taken as prescribed (extended-release switch)", "kind": "therapeutic", "text": "Switch metformin to extended-release 1000 mg daily with dinner",
     "low": -1.2, "high": -0.7, "weeks": 12, "source": "Hirst 2012, Diabetes Care: metformin lowers A1c about 1.1 points",
     "applies": lambda c: c["on"]("metformin"), "on_plan": lambda c: "extended-release" in c["plan_text"] or c["dose_changed"]("metformin")},
    {"id": "add_sglt2", "code": "4548-4", "label": "Add an SGLT2 inhibitor", "kind": "therapeutic", "text": "Start empagliflozin 10 mg daily",
     "low": -0.8, "high": -0.5, "weeks": 12, "source": "ADA Standards of Care 2024 §9; favoured with albuminuria",
     "applies": lambda c: True, "on_plan": lambda c: c["on"]("empagliflozin") or c["on"]("dapagliflozin") or "sglt2" in c["plan_text"] or "empagliflozin" in c["plan_text"]},
    {"id": "add_glp1", "code": "4548-4", "label": "Add a GLP-1 receptor agonist", "kind": "therapeutic", "text": "Start semaglutide 0.25 mg weekly, titrate",
     "low": -1.5, "high": -0.8, "weeks": 12, "source": "ADA Standards of Care 2024 §9",
     "applies": lambda c: True, "on_plan": lambda c: c["on"]("semaglutide") or c["on"]("liraglutide") or "glp-1" in c["plan_text"] or "semaglutide" in c["plan_text"]},
]


def _context(patient: dict, problem_ids: set[str]) -> dict:
    meds = _accepted(patient["medications"])
    def segs(name):
        return [m for m in meds if name in m["name"].lower()]
    def on(name):
        return any(not (m["segments"][-1].get("end")) for m in segs(name))
    nsaids = [m for m in meds if any(n in m["name"].lower() for n in ("ibuprofen", "naproxen"))]
    plan_text = " ".join(pl["text"].lower() for pl in patient.get("plans", []) if pl.get("problem_id") in problem_ids or not problem_ids)
    return {"on": on, "plan_text": plan_text, "nsaid_ever": bool(nsaids), "nsaid_stopped": bool(nsaids) and all(m["segments"][-1].get("end") for m in nsaids),
            "dose_changed": lambda name: any(len(m["segments"]) > 1 for m in segs(name))}


def _latest(patient: dict, code: str, on_or_before: str | None = None) -> dict | None:
    pts = [o for o in _accepted(patient["observations"]) if o["code"]["value"] == code and isinstance(o.get("value"), (int, float))
           and (on_or_before is None or o["effective_time"][:10] <= on_or_before)]
    if not pts:
        return None
    newest = max(o["effective_time"] for o in pts)
    return [o for o in pts if o["effective_time"] == newest][-1]  # a repeat reading the same day is the one that counts


def _band(v0: float, t0: date, low: float, high: float, weeks: int) -> list[dict]:
    pts = []
    for w in range(0, HORIZON_WEEKS + 1, 2):
        f = min(1.0, w / weeks) if weeks else 1.0
        pts.append({"t": (t0 + timedelta(weeks=w)).isoformat(), "low": round(v0 + low * f, 2), "high": round(v0 + high * f, 2)})
    return pts


def _reaches(points: list[dict], goal: float) -> str | None:
    """The first date the middle of the band is under the goal."""
    for p in points:
        if (p["low"] + p["high"]) / 2 < goal:
            return p["t"]
    return None


def simulate(patient: dict, problem_id: str, codes: list[str], *, today: date | None = None) -> dict | None:
    """Options for the first monitored series that has an effects table, and the current plan's combined projection."""
    today = today or date.today()
    code = next((c for c in ("8480-6", "4548-4") if c in codes), None)
    if not code:
        return None
    enc_id = open_encounter(patient)
    enc = next((e for e in patient.get("encounters", []) if e["id"] == enc_id), None)
    # A projection starts when the action starts: the visit, while it is recent (its horizon), otherwise today. The
    # starting value is the last one on or before that day, so a result that lands later tests the band, not moves it.
    enc_day = date.fromisoformat(enc["time"][:10]) if enc else None
    recent = bool(enc_day) and 0 <= (today - enc_day).days <= HORIZON_WEEKS * 7
    latest = _latest(patient, code, enc_day.isoformat() if recent else None)
    if not latest:
        return None
    latest_day = date.fromisoformat(latest["effective_time"][:10])
    t0 = enc_day if recent and enc_day >= latest_day else max(latest_day, today)
    v0 = float(latest["value"])
    rr = latest.get("reference_range") or {}
    goal = GOALS.get(code) or rr.get("high")
    if goal is not None and v0 < goal:
        return None  # at or under goal: nothing to project toward, and a low value is not helped by lowering it
    ctx = _context(patient, {problem_id})
    options = []
    for e in EFFECTS:
        if e["code"] != code or not e["applies"](ctx):
            continue
        pts = _band(v0, t0, e["low"], e["high"], e["weeks"])
        options.append({"id": e["id"], "label": e["label"], "kind": e["kind"], "text": e["text"], "on_plan": bool(e["on_plan"](ctx)),
                        "effect": {"low": e["low"], "high": e["high"]}, "weeks": e["weeks"], "full_effect_by": (t0 + timedelta(weeks=e["weeks"])).isoformat(),
                        "points": pts, "reaches_goal_by": _reaches(pts, goal) if goal else None, "source": e["source"]})
    chosen = sorted((o for o in options if o["on_plan"]), key=lambda o: o["effect"]["low"])
    plan = None
    if chosen:
        pts = []
        for w in range(0, HORIZON_WEEKS + 1, 2):
            lo = hi = 0.0
            for i, o in enumerate(chosen):
                f = min(1.0, w / o["weeks"]) * (1.0 if i == 0 else COMBINE)
                lo += o["effect"]["low"] * f
                hi += o["effect"]["high"] * f
            pts.append({"t": (t0 + timedelta(weeks=w)).isoformat(), "low": round(v0 + lo, 2), "high": round(v0 + hi, 2)})
        weeks = max(o["weeks"] for o in chosen)
        full = next(p for p in pts if p["t"] >= (t0 + timedelta(weeks=weeks)).isoformat())
        plan = {"options": [o["id"] for o in chosen], "labels": [o["label"] for o in chosen], "points": pts, "weeks": weeks,
                "full_effect_by": (t0 + timedelta(weeks=weeks)).isoformat(), "at_full_effect": {"low": full["low"], "high": full["high"]},
                "reaches_goal_by": _reaches(pts, goal) if goal else None}
        later = [o for o in _accepted(patient["observations"]) if o["code"]["value"] == code and t0.isoformat() < o["effective_time"][:10] <= today.isoformat()]
        if later:
            last = max(later, key=lambda o: o["effective_time"])
            band = min(pts, key=lambda p: abs((date.fromisoformat(p["t"]) - date.fromisoformat(last["effective_time"][:10])).days))
            plan["observed"] = {"value": last["value"], "time": last["effective_time"][:10], "status": "within" if band["low"] <= last["value"] <= band["high"] else ("better" if last["value"] < band["low"] else "missed")}
    return {"code": code, "name": latest["name"], "unit": latest.get("unit"), "from": {"value": v0, "time": t0.isoformat()}, "goal": goal,
            "options": options, "current_plan": plan,
            "note": "Projections use published average effects, shown as ranges. They are not specific to this patient and are not probabilities; the next value is the test."}


# --------------------------------------------------------------------------- expected moves in the wrong direction

# A projection above is about a value we are trying to improve. These are the other kind: values a change we just made
# is expected to worsen, where the clinical question is how far is too far. The threshold comes from this patient's own
# baseline, which is why the lab's reference range cannot answer it in either direction.
WATCH = [
    {"id": "acei_creatinine", "code": "38483-4", "drugs": ("lisinopril", "enalapril", "ramipril", "losartan", "valsartan"),
     "rise": 0.30, "weeks": 4, "because": "it lowers the pressure inside the glomerulus, so filtration falls before it settles",
     "then": "Look for volume depletion, an NSAID still on board, or renovascular disease before stopping the drug.",
     "source": "Bakris & Weir 2000, Arch Intern Med 160:685 — a rise up to 30% that stabilises is acceptable and the drug is continued; KDIGO 2012 CKD §3.1",
     "tested_by": ("bmp", "basic metabolic", "creatinine", "renal panel")},
    {"id": "acei_potassium", "code": "6298-4", "drugs": ("lisinopril", "enalapril", "ramipril", "losartan", "valsartan", "spironolactone"),
     "ceiling": 5.5, "weeks": 4, "because": "it reduces potassium excretion",
     "then": "Review the other drugs that raise potassium, and repeat it before changing the dose.",
     "source": "ACC/AHA 2017 hypertension guideline §8.1.6; KDIGO 2021 BP guideline §3",
     "tested_by": ("bmp", "basic metabolic", "potassium")},
]

# A change made at the same visit that pushes the same value the other way.
COUNTER = [{"code": "38483-4", "drugs": ("ibuprofen", "naproxen", "diclofenac"),
            "text": "Stopping the NSAID pushes creatinine the other way, so a smaller rise, or none at all, is just as consistent with this plan."}]


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def expectations(patient: dict, problem_id: str, *, today: date | None = None) -> list[dict]:
    """What a change made for this problem is expected to do to the values we watch for safety, and what would mean it
    has gone too far. Rules, not a model; each names its source. Computed on demand, never stored."""
    today = today or date.today()
    meds = _accepted(patient["medications"])
    treats = {l["from"] for l in _accepted(patient["links"]) if l["type"] == "treats" and l["to"] == problem_id}
    plans = patient.get("plans", [])
    out = []
    for w in WATCH:
        for m in meds:
            if m["id"] not in treats or not any(d in m["name"].lower() for d in w["drugs"]):
                continue
            seg = m["segments"][-1]
            start = seg.get("start")
            if not start or seg.get("end"):
                continue
            started = date.fromisoformat(start)
            if not (0 <= (today - started).days <= w["weeks"] * 7 * 2):
                continue  # only while the answer is still ahead of us
            base = _latest(patient, w["code"], start)
            if not base:
                continue
            v0, unit = float(base["value"]), base.get("unit") or ""
            limit = round(v0 * (1 + w["rise"]), 2) if "rise" in w else w["ceiling"]
            rr = base.get("reference_range") or {}
            inside = bool(rr.get("high")) and limit <= rr["high"]
            if "rise" in w:
                expect = f"a rise of up to {int(w['rise'] * 100)}%, to {_fmt(limit)} {unit}, settling within {w['weeks']} weeks".strip()
                beyond = f"above {_fmt(limit)} {unit}".strip() + f", or still rising after {w['weeks']} weeks"
            else:
                expect = f"a rise, staying under {_fmt(limit)} {unit}".strip()
                beyond = f"{_fmt(limit)} {unit} or above".strip()
            if rr.get("high"):
                note = (f"{_fmt(limit)} {unit} is inside the reference range {_fmt(rr['low'])}–{_fmt(rr['high'])}: the range will not flag this, the baseline will."
                        if inside else
                        f"{_fmt(limit)} {unit} is above the reference range {_fmt(rr['low'])}–{_fmt(rr['high'])}: a result flagged high below that is still expected here.")
            else:
                note = ""
            test = next((pl for pl in plans if any(t in pl["text"].lower() for t in w["tested_by"])), None)
            later = [o for o in _accepted(patient["observations"]) if o["code"]["value"] == w["code"] and o["effective_time"][:10] > start]
            observed = None
            if later:
                last = max(later, key=lambda o: o["effective_time"])
                observed = {"value": last["value"], "time": last["effective_time"][:10], "id": last["id"],
                            "status": "beyond" if float(last["value"]) > limit else "within"}
            counter = next((c["text"] for c in COUNTER if c["code"] == w["code"]
                            and any(any(d in x["name"].lower() for d in c["drugs"]) and (x["segments"][-1].get("end") or "") >= start for x in meds)), None)
            out.append({"id": w["id"], "value": {"code": w["code"], "name": base["name"], "unit": unit},
                        "trigger": {"text": f"{m['name']} {seg.get('dose') or ''}".strip() + f" started {started.strftime('%-d %b %Y')}", "ids": [m["id"]]},
                        "baseline": {"value": v0, "time": base["effective_time"][:10], "id": base["id"]},
                        "because": w["because"], "expect": expect, "limit": limit, "by": (started + timedelta(weeks=w["weeks"])).isoformat(),
                        "not_expected": beyond, "then": w["then"], "reference_range": rr or None, "inside_range": inside, "note": note,
                        "tested_by": {"text": test["text"], "ids": [test["id"]]} if test else None,
                        "observed": observed, "source": w["source"], "counter": counter,
                        "ids": [m["id"], base["id"]] + ([test["id"]] if test else [])})
    return out
