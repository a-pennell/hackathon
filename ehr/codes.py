"""Observation codes the extractor is allowed to emit.

Kept deliberately small: anything not in this table is rejected at validation
time so the chart never grows a LOINC code the timeline doesn't know how to plot.
Names and ranges match scripts/fhir_common.py so extracted and imported values
render identically.
"""

# code -> (display name, unit, reference range or None)
EXTRACTABLE_LOINC = {
    "38483-4": ("Creatinine (whole blood)", "mg/dL", {"low": 0.6, "high": 1.2}),
    "2160-0": ("Creatinine", "mg/dL", {"low": 0.6, "high": 1.2}),
    "33914-3": ("eGFR", "mL/min/{1.73_m2}", {"low": 60.0, "high": None}),
    "6299-2": ("BUN", "mg/dL", {"low": 7.0, "high": 20.0}),
    "6298-4": ("Potassium", "mmol/L", {"low": 3.5, "high": 5.1}),
    "2951-2": ("Sodium", "mmol/L", {"low": 135.0, "high": 145.0}),
    "14959-1": ("Urine albumin/creatinine ratio", "mg/g", {"low": 0.0, "high": 30.0}),
    "4548-4": ("Hemoglobin A1c", "%", {"low": 4.0, "high": 5.6}),
    "2339-0": ("Glucose", "mg/dL", {"low": 70.0, "high": 99.0}),
    "33762-6": ("NT-proBNP", "pg/mL", {"low": 0.0, "high": 125.0}),
    "29463-7": ("Body weight", "kg", None),
    "8480-6": ("Systolic blood pressure", "mm[Hg]", {"low": 90.0, "high": 120.0}),
    "8462-4": ("Diastolic blood pressure", "mm[Hg]", {"low": 60.0, "high": 80.0}),
    "8867-4": ("Heart rate", "/min", {"low": 60.0, "high": 100.0}),
    "718-7": ("Hemoglobin", "g/dL", {"low": 13.0, "high": 17.0}),
}


def loinc_menu() -> str:
    """One line per code, for the extraction prompt."""
    return "\n".join(f"  {code}  {name} ({unit})" for code, (name, unit, _) in EXTRACTABLE_LOINC.items())
