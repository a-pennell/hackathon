"""What a change made at a visit is expected to push the wrong way, and how far is too far.

A drug started for a problem can be expected to move a value we watch for safety — an ACE inhibitor raises creatinine
and potassium — and the clinical question is the size of the move. The threshold comes from this patient's own
baseline, so it can sit inside the lab's reference range (and the range will not flag it) or outside it (and the range
will flag something that is expected). Rules, not a model; each names its source. Computed on demand, never stored.

It lives here rather than in v2 because the visit note records it: an expectation set at a visit is part of the
reasoning, and the note compiler (ehr/draft.py) is below the view layers in the stack.
"""

from __future__ import annotations

from datetime import date, timedelta

from ehr.reason import _accepted


def _latest(patient: dict, code: str, on_or_before: str | None = None) -> dict | None:
    pts = [o for o in _accepted(patient["observations"]) if o["code"]["value"] == code and isinstance(o.get("value"), (int, float))
           and (on_or_before is None or o["effective_time"][:10] <= on_or_before)]
    if not pts:
        return None
    newest = max(o["effective_time"] for o in pts)
    return [o for o in pts if o["effective_time"] == newest][-1]  # a repeat reading the same day is the one that counts


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
                        "because": w["because"], "expect": expect, "limit": limit, "limit_kind": "rise" if "rise" in w else "ceiling",
                        "by": (started + timedelta(weeks=w["weeks"])).isoformat(),
                        "not_expected": beyond, "then": w["then"], "reference_range": rr or None, "inside_range": inside, "note": note,
                        "tested_by": {"text": test["text"], "ids": [test["id"]]} if test else None,
                        "observed": observed, "source": w["source"], "counter": counter,
                        "ids": [m["id"], base["id"]] + ([test["id"]] if test else [])})
    return out
