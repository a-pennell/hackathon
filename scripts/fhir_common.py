"""Shared helpers for reading Synthea FHIR R4 bundles.

Used by find_golden.py and import_patient.py so both agree on code sets,
name cleanup, and how resources are pulled out of a bundle. Stdlib only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Code sets (SNOMED CT codes as emitted by current Synthea modules)
# ---------------------------------------------------------------------------

CHF_CODES = {"88805009"}  # Chronic congestive heart failure (disorder)
CKD_CODES = {
    "431855005",  # CKD stage 1
    "431856006",  # CKD stage 2
    "433144002",  # CKD stage 3
    "431857002",  # CKD stage 4
    "46177005",   # End-stage renal disease
    "127013003",  # Disorder of kidney due to diabetes mellitus
}
T2DM_CODES = {"44054006"}  # Diabetes mellitus type 2 (disorder)
HTN_CODES = {"59621000"}   # Essential hypertension (disorder)

# Display-text fallbacks in case a module uses a code not listed above.
CHF_RE = re.compile(r"heart failure", re.I)
CKD_RE = re.compile(r"(chronic kidney disease|renal disease|kidney due to diabetes)", re.I)
T2DM_RE = re.compile(r"diabetes mellitus type 2", re.I)
HTN_RE = re.compile(r"essential hypertension", re.I)

# LOINC codes. Synthea emits creatinine under two codes.
CREATININE_CODES = {"2160-0", "38483-4"}
CREATININE_CANONICAL = "2160-0"

# Problem category -> LOINC codes that are "tracked series" for it (§7 monitors).
MONITORS_TABLE = {
    "ckd": ["2160-0", "38483-4", "33914-3", "6299-2"],  # creatinine (serum), creatinine (blood), eGFR, BUN
    "t2dm": ["4548-4", "2339-0", "2345-7"],           # A1c, glucose (blood), glucose (serum)
    "chf": ["33762-6", "29463-7"],                    # NT-proBNP, body weight
    "htn": ["8480-6", "8462-4"],                      # systolic, diastolic
}

# Friendly names for the codes the demo plots. Others keep Synthea's display.
FRIENDLY_NAMES = {
    "2160-0": "Creatinine",
    "38483-4": "Creatinine (whole blood)",
    "33914-3": "eGFR",
    "6299-2": "BUN",
    "4548-4": "Hemoglobin A1c",
    "2339-0": "Glucose",
    "2345-7": "Glucose",
    "33762-6": "NT-proBNP",
    "29463-7": "Body weight",
    "8480-6": "Systolic blood pressure",
    "8462-4": "Diastolic blood pressure",
    "6298-4": "Potassium",
    "2823-3": "Potassium",
    "2947-0": "Sodium",
    "2951-2": "Sodium",
    "14959-1": "Urine albumin/creatinine ratio",
}

# Synthea emits no referenceRange. Hardcoded adult ranges for the plotted codes.
REFERENCE_RANGES = {
    "2160-0": {"low": 0.6, "high": 1.2},
    "38483-4": {"low": 0.6, "high": 1.2},
    "33914-3": {"low": 60.0, "high": None},
    "6299-2": {"low": 7.0, "high": 20.0},
    "4548-4": {"low": 4.0, "high": 5.6},
    "2339-0": {"low": 70.0, "high": 99.0},
    "2345-7": {"low": 70.0, "high": 99.0},
    "33762-6": {"low": 0.0, "high": 125.0},
    "6298-4": {"low": 3.5, "high": 5.1},
    "2823-3": {"low": 3.5, "high": 5.1},
    "8480-6": {"low": 90.0, "high": 120.0},
    "8462-4": {"low": 60.0, "high": 80.0},
}

# Drug-name keyword sets used only for the golden-patient summary line.
NSAID_RE = re.compile(r"\b(ibuprofen|naproxen|meloxicam|diclofenac|celecoxib|ketorolac|indomethacin)\b", re.I)
METFORMIN_RE = re.compile(r"\bmetformin\b", re.I)
ACEI_ARB_RE = re.compile(r"\b(lisinopril|enalapril|captopril|ramipril|losartan|valsartan|olmesartan)\b", re.I)


# ---------------------------------------------------------------------------
# Bundle access
# ---------------------------------------------------------------------------

def load_bundle(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_patient_bundles(fhir_dir: str | Path):
    """Yield (path, bundle) for every per-patient bundle in a Synthea output dir."""
    fhir_dir = Path(fhir_dir)
    for p in sorted(fhir_dir.glob("*.json")):
        if p.name.startswith(("hospitalInformation", "practitionerInformation")):
            continue
        yield p, load_bundle(p)


def resources(bundle: dict, resource_type: str | None = None):
    """Yield resources from a bundle, optionally filtered by resourceType."""
    for entry in bundle.get("entry", []):
        r = entry.get("resource")
        if not r:
            continue
        if resource_type is None or r.get("resourceType") == resource_type:
            yield r


def fullurl_map(bundle: dict) -> dict[str, dict]:
    """Map every entry's fullUrl (urn:uuid:...) and 'Type/id' to its resource."""
    out = {}
    for entry in bundle.get("entry", []):
        r = entry.get("resource")
        if not r:
            continue
        if entry.get("fullUrl"):
            out[entry["fullUrl"]] = r
        if r.get("id"):
            out[f"{r['resourceType']}/{r['id']}"] = r
    return out


def ref_target(ref: dict | None) -> str | None:
    if not ref:
        return None
    return ref.get("reference")


# ---------------------------------------------------------------------------
# Coding helpers
# ---------------------------------------------------------------------------

def first_coding(cc: dict | None) -> dict:
    if not cc:
        return {}
    codings = cc.get("coding") or []
    return codings[0] if codings else {}


def code_of(cc: dict | None) -> str | None:
    return first_coding(cc).get("code")


def display_of(cc: dict | None) -> str:
    c = first_coding(cc)
    return c.get("display") or (cc or {}).get("text") or ""


def condition_category(cond: dict) -> str | None:
    """Return 'chf' | 'ckd' | 't2dm' | 'htn' | None for a Condition resource."""
    code = code_of(cond.get("code"))
    text = display_of(cond.get("code"))
    if code in CHF_CODES or CHF_RE.search(text):
        return "chf"
    if code in CKD_CODES or CKD_RE.search(text):
        return "ckd"
    if code in T2DM_CODES or T2DM_RE.search(text):
        return "t2dm"
    if code in HTN_CODES or HTN_RE.search(text):
        return "htn"
    return None


SOCIAL_SUFFIX_RE = re.compile(r"\((finding|situation)\)\s*$", re.I)


def is_social_history_condition(cond: dict) -> bool:
    """Synthea social/lifestyle conditions end in '(finding)' or '(situation)'."""
    return bool(SOCIAL_SUFFIX_RE.search(display_of(cond.get("code"))))


# ---------------------------------------------------------------------------
# Names, dates
# ---------------------------------------------------------------------------

DIGITS_RE = re.compile(r"\d+")


def clean_name_part(s: str) -> str:
    return DIGITS_RE.sub("", s).strip()


def clean_person_name(s: str | None) -> str | None:
    if not s:
        return s
    return re.sub(r"\s+", " ", DIGITS_RE.sub("", s)).strip()


def patient_display_name(patient: dict) -> str:
    names = patient.get("name") or []
    if not names:
        return "Unknown"
    n = next((x for x in names if x.get("use") == "official"), names[0])
    given = " ".join(clean_name_part(g) for g in n.get("given", []))
    family = clean_name_part(n.get("family", ""))
    return f"{given} {family}".strip()


def parse_dt(s: str | None) -> datetime | None:
    """Parse FHIR dateTime/date strings (tz-aware when present)."""
    if not s:
        return None
    if len(s) == 10:  # YYYY-MM-DD
        return datetime.fromisoformat(s)
    return datetime.fromisoformat(s)


def date_only(s: str | None) -> str | None:
    return s[:10] if s else None


def age_at(dob: str, when: datetime) -> int:
    b = datetime.fromisoformat(dob)
    return when.year - b.year - ((when.month, when.day) < (b.month, b.day))


# ---------------------------------------------------------------------------
# Medication name parsing (RxNorm display strings)
# ---------------------------------------------------------------------------

# "Lisinopril 10 MG Oral Tablet" -> ingredient "Lisinopril", strength "10 MG", form "Oral Tablet"
# "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet"
# "insulin isophane, human 70 UNT/ML / insulin, regular, human 30 UNT/ML Injectable Suspension [Humulin]"
STRENGTH_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:MG|MCG|G|UNT|MEQ|ML|%|MG/ML|MG/ACTUAT|MCG/ACTUAT|UNT/ML|MG/MG|MEQ/ML|MCG/ML|MG/HR|MCG/HR)(?:/\w+)?\b",
    re.I,
)
FORM_WORDS = (
    "Extended Release", "Delayed Release", "Chewable", "Oral Tablet", "Oral Capsule", "Oral Solution",
    "Oral Suspension", "Tablet", "Capsule", "Injectable Solution", "Injectable Suspension", "Injection",
    "Prefilled Syringe", "Pen Injector", "Auto-Injector", "Inhalant", "Metered Dose Inhaler", "Dry Powder Inhaler",
    "Inhalation Solution", "Nasal Spray", "Mucosal Spray", "Transdermal System", "Topical", "Ophthalmic Solution",
    "Ophthalmic", "Cartridge", "Disintegrating", "Effervescent", "Film", "Lozenge", "Patch", "Cream", "Ointment",
    "Oral Gel", "Gel", "Drops", "Solution", "Suspension", "Spray", "Powder", "Granules", "Oral Strip",
)
BRAND_RE = re.compile(r"\s*\[[^\]]*\]\s*$")
LEADING_TIME_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:HR|ACTUAT|ML)\s+", re.I)  # "24 HR ...", "200 ACTUAT ...", "10 ML ..."


def parse_rx_display(display: str) -> dict:
    """Split a Synthea RxNorm display into ingredient / dose / form."""
    raw = display or ""
    s = BRAND_RE.sub("", raw)
    s = LEADING_TIME_RE.sub("", s)
    strengths = [m.group(0).strip() for m in STRENGTH_RE.finditer(s)]
    s_no_strength = STRENGTH_RE.sub(" ", s)
    form = None
    for fw in sorted(FORM_WORDS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(fw) + r"\b", s_no_strength, re.I):
            form = fw
            break
    ingredient = s_no_strength
    for fw in FORM_WORDS:
        ingredient = re.sub(r"\b" + re.escape(fw) + r"\b", " ", ingredient, flags=re.I)
    # Combination products: "A 5 MG / B 10 MG" -> "A / B"
    parts = [p.strip(" ,") for p in ingredient.split("/")]
    parts = [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]
    ingredient = " / ".join(parts) if parts else raw
    ingredient = re.sub(r"\s+", " ", ingredient).strip()
    dose = " / ".join(strengths).lower().replace("unt", "units") if strengths else None
    return {"ingredient": ingredient, "dose": dose, "form": form}


def route_for_form(form: str | None) -> str | None:
    if not form:
        return None
    f = form.lower()
    if "oral" in f or "tablet" in f or "capsule" in f or "chewable" in f or "lozenge" in f or "release" in f:
        return "PO"
    if "injectable solution" in f or f == "injection":
        return "INJ"  # IV/IM/SC not distinguishable from the RxNorm form
    if "inject" in f or "syringe" in f or "pen" in f or "cartridge" in f:
        return "SC"
    if "inhal" in f:
        return "INH"
    if "transdermal" in f or "patch" in f:
        return "TD"
    if "nasal" in f:
        return "NASAL"
    if "ophthalmic" in f or "drops" in f:
        return "OPH"
    if "topical" in f or "cream" in f or "ointment" in f or "gel" in f:
        return "TOP"
    return None


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:64] or "unknown"


def frequency_text(dosage: dict | None) -> str | None:
    if not dosage:
        return None
    if dosage.get("asNeededBoolean"):
        return "as needed"
    rep = (dosage.get("timing") or {}).get("repeat") or {}
    freq, period, unit = rep.get("frequency"), rep.get("period"), rep.get("periodUnit")
    if not freq or not period or not unit:
        return None
    unit_word = {"d": "day", "h": "hour", "wk": "week", "mo": "month"}.get(unit, unit)
    if unit == "d" and period == 1:
        return {1: "daily", 2: "twice daily", 3: "three times daily", 4: "four times daily"}.get(freq, f"{freq}x daily")
    if period == 1:
        return f"{freq}x per {unit_word}"
    return f"{freq}x every {period} {unit_word}s"
