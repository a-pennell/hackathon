"""v2: best-practice rules checked against the chart. Each says what a guideline recommends, where it comes from, and
whether the plan already covers it. Rules, not a model; every line names its source."""

from __future__ import annotations

from datetime import date

from ehr.reason import _accepted


def _latest(patient, code):
    pts = [o for o in _accepted(patient["observations"]) if o["code"]["value"] == code and isinstance(o.get("value"), (int, float))]
    return max(pts, key=lambda o: o["effective_time"]) if pts else None


def _on(patient, *names):
    return [m for m in _accepted(patient["medications"]) if any(n in m["name"].lower() for n in names) and not m["segments"][-1].get("end")]


def _plan_has(patient, *words):
    text = " ".join(pl["text"].lower() for pl in patient.get("plans", [])) + " " + " ".join(o["name"].lower() for o in patient.get("orders", []))
    return any(w in text for w in words)


def guidelines(patient: dict, problem: dict, *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    name = problem["name"].lower()
    out = []

    def rule(rid, text, source, covered, ids, action=None):
        out.append({"id": rid, "text": text, "source": source, "status": "covered" if covered else "gap", "ids": [i for i in ids if i], "action": None if covered else action})

    sbp, dbp, a1c, acr = (_latest(patient, c) for c in ("8480-6", "8462-4", "4548-4", "14959-1"))
    diabetes = any("diabetes" in p["name"].lower() and p["status"] == "active" for p in patient["problems"])
    acei = _on(patient, "lisinopril", "enalapril", "ramipril", "losartan", "valsartan")
    nsaid = _on(patient, "ibuprofen", "naproxen")

    if "hypertension" in name:
        above = bool(sbp and dbp and (sbp["value"] >= 140 or dbp["value"] >= 90))
        agents = _on(patient, "hydrochlorothiazide", "chlorthalidone", "amlodipine") + acei
        if above:
            rule("htn_second_agent", "Above goal on one agent: add a second agent of a different class, or uptitrate.", "ACC/AHA 2017 hypertension guideline §8.1",
                 len(agents) >= 2 or _plan_has(patient, "lisinopril", "amlodipine", "losartan"), [sbp["id"], dbp["id"]] + [m["id"] for m in agents],
                 {"kind": "therapeutic", "text": "Start lisinopril 10 mg daily"})
            rule("htn_home_bp", "Confirm and follow with home blood pressure monitoring.", "ACC/AHA 2017 §4.2", _plan_has(patient, "home bp", "home blood pressure"), [sbp["id"]],
                 {"kind": "monitoring", "text": "Home BP log, twice daily for a week before each visit"})
        if nsaid and above:
            rule("htn_nsaid", "An NSAID is on board with pressure above goal: stop it or substitute.", "ACC/AHA 2017 §5.4.1, substances that raise blood pressure",
                 _plan_has(patient, "stop ibuprofen", "stop naproxen"), [m["id"] for m in nsaid], {"kind": "therapeutic", "text": "Stop ibuprofen; acetaminophen instead"})
        if acei:
            start = acei[0]["segments"][-1].get("start") or ""
            k_after = [o for o in _accepted(patient["observations"]) if o["code"]["value"] in ("6298-4", "2160-0", "38483-4") and o["effective_time"][:10] > start]
            rule("acei_bmp", "Potassium and creatinine one to two weeks after starting or changing an ACE inhibitor or ARB.", "ACC/AHA 2017 §8.1.6; KDIGO 2021",
                 bool(k_after) or _plan_has(patient, "bmp", "basic metabolic", "potassium", "creatinine"), [acei[0]["id"]], {"kind": "diagnostic", "text": "BMP 1 to 2 weeks after the lisinopril start"})
        if diabetes and sbp:
            rule("htn_dm_goal", "With diabetes, the pressure goal is under 130/80 if it can be reached safely.", "ADA Standards of Care 2024 §10", sbp["value"] < 130, [sbp["id"]], None)

    if "kidney" in name:
        egfr = _latest(patient, "33914-3")
        metformin = _on(patient, "metformin")
        if egfr and egfr["value"] < 30:
            rule("ckd_metformin", "eGFR under 30: metformin is contraindicated.", "FDA metformin labeling 2016; KDIGO 2022 diabetes in CKD", not metformin or _plan_has(patient, "stop metformin"),
                 [egfr["id"]] + [m["id"] for m in metformin], {"kind": "therapeutic", "text": "Stop metformin"})
            rule("ckd_nephrology", "eGFR under 30: refer to nephrology.", "KDIGO 2012 CKD guideline §5.1", _plan_has(patient, "nephrology"), [egfr["id"]],
                 {"kind": "referral", "text": "Nephrology referral"})
        if nsaid:
            rule("ckd_nsaid", "Chronic kidney disease: avoid NSAIDs.", "KDIGO 2012 CKD guideline §4.4", _plan_has(patient, "stop naproxen", "stop ibuprofen"), [m["id"] for m in nsaid],
                 {"kind": "therapeutic", "text": "Stop the NSAID; acetaminophen instead"})

    if "diabetes" in name:
        if a1c and a1c["value"] >= 7.0:
            age_days = (today - date.fromisoformat(a1c["effective_time"][:10])).days
            rule("dm_a1c_repeat", "A1c above goal: repeat every three months until at goal.", "ADA Standards of Care 2024 §6", _plan_has(patient, "a1c") or age_days < 60, [a1c["id"]],
                 {"kind": "monitoring", "text": "Repeat A1c in 3 months"})
            rule("dm_intensify", "A1c above goal on metformin alone: add an SGLT2 inhibitor or GLP-1 receptor agonist, the former favoured with albuminuria.", "ADA Standards of Care 2024 §9",
                 bool(_on(patient, "empagliflozin", "dapagliflozin", "semaglutide", "liraglutide")) or _plan_has(patient, "empagliflozin", "semaglutide", "sglt2", "glp-1"), [a1c["id"]],
                 {"kind": "therapeutic", "text": "Start empagliflozin 10 mg daily"})
        if acr and acr["value"] >= 30:
            rule("dm_acr_confirm", "One raised albumin/creatinine ratio: confirm with a repeat within three to six months.", "ADA Standards of Care 2024 §11",
                 _plan_has(patient, "albumin", "acr", "uacr"), [acr["id"]], {"kind": "diagnostic", "text": "Repeat urine albumin/creatinine ratio in 3 months"})
            rule("dm_acr_acei", "Diabetes with albuminuria: an ACE inhibitor or ARB.", "ADA Standards of Care 2024 §11; KDIGO 2022", bool(acei) or _plan_has(patient, "lisinopril", "losartan"), [acr["id"]] + [m["id"] for m in acei],
                 {"kind": "therapeutic", "text": "Start lisinopril 10 mg daily"})
        dob = patient["patient"].get("dob")
        if dob:
            age = (today - date.fromisoformat(dob)).days // 365
            if 40 <= age <= 75:
                rule("dm_statin", "Diabetes, age 40 to 75: moderate-intensity statin.", "ADA Standards of Care 2024 §10", bool(_on(patient, "statin")) or _plan_has(patient, "statin"), [],
                     {"kind": "therapeutic", "text": "Start atorvastatin 20 mg daily"})
    return out
