"""NLP extraction: free-text note -> proposed chart items (schema §3, §4, §7).

    python3 -m ehr.extract data/notes/note_demo_002.json [--patient pt_001]
        [--model claude-opus-5] [--dry-run] [--replay data/proposed/pt_001/note_demo_002.raw.json]

Pipeline:
  1. ingest   - upsert the (human-written) encounter + note into the patient file
  2. extract  - one structured-output call to Claude with the chart context + note text
  3. validate - deterministic checks: every quote verbatim in the note, codes from the
               allowed table, every ref resolves; anything failing is *rejected with a
               reason*, never silently dropped
  4. queue    - write data/proposed/<patient>/<note_id>.json (the review queue). Nothing
               touches the canonical chart; every item is status "proposed" with
               provenance {source, note_id, quote, model, confidence}.

`--dry-run` builds and prints the prompt without calling the API. `--replay` re-validates a
saved raw model response (written next to every real run) so the demo doesn't depend on a
live call.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from ehr.codes import EXTRACTABLE_LOINC, loinc_menu
from ehr.trend import DATA_DIR, load_patient

DEFAULT_MODEL = "claude-opus-5"
EXTRACTOR_VERSION = "extractor-v1"
PROPOSED_DIR = DATA_DIR.parent / "proposed"

LINK_TYPES = {"relevant_to", "treats", "evidence_for", "suspected_cause", "monitors"}

# Codes that name the same analyte (Synthea emits both). A note saying "creatinine 5.7" matches a
# charted 5.7 under either code; without this the extractor would chart a duplicate point.
CODE_GROUPS = {"2160-0": "creatinine", "38483-4": "creatinine", "2339-0": "glucose", "2345-7": "glucose"}
DEDUPE_DAYS = 45      # a restated historical value ("3.69 in May") matches a charted value this close in time
DEDUPE_TOLERANCE = 0.02  # ...and this close in value (2%)
PLAN_KINDS = ("diagnostic", "therapeutic", "monitoring", "referral", "education", "follow_up")

# ----------------------------------------------------------------------------- prompt

SYSTEM_PROMPT = """You are the extraction step of a problem-oriented electronic health record.
You read ONE clinical note and return structured items for a human reviewer. Nothing you return
is written to the chart until a clinician accepts it, so precision matters more than recall.

Rules
- Every item carries a `quote`: a verbatim, contiguous substring of the note text (exact
  characters, including numbers and units). Items whose quote is not verbatim are discarded.
- Only extract what the note states. Do not infer values, dates, or diagnoses the note does not
  contain. Do not restate chart data that the note does not mention.
- Numeric results go in `observations`, using ONLY the LOINC codes listed below.
  Blood pressure "84/52" is two observations (systolic 8480-6, diastolic 8462-4). Values the
  note attributes to an earlier date (e.g. "labs from 8/19") get that date in `date`; values
  from this visit get `date: null` (the note date is used).
- Symptoms, exam findings and other non-numeric facts go in `findings`, each linked to the
  problem(s) it bears on.
- `problem_refs` / `treats_problem_refs` contain existing problem ids from the chart context
  (e.g. "prob_0057") or `ref` values of problems you propose in `problems` (e.g. "new_1").
- Propose a new problem only when the note names a condition that is not already on the
  problem list. If the note says an existing problem has progressed (e.g. a new CKD stage),
  propose the new stage as a new problem and set `supersedes_problem_id`.
- Medications: `change` is "new" (not in the chart), "confirm" (chart med the note says the
  patient is still taking), "stop", "dose_change" or "frequency_change" (existing med, set
  `existing_med_id`). Give dose/route/frequency as written. Dates: absolute YYYY-MM-DD when the
  note gives one; for phrases like "since around April" use the first of that month relative to
  the note date; otherwise null.
- `suspected_causes`: only when the note itself raises the causal link (e.g. NSAID use and
  kidney function). `cause_ref` is a medication or problem id (existing or new_N); `effect_ref`
  is a problem id or "LOINC:<code>".
- `plans`: each thing the assessment/plan section says will be done, one item each, linked to
  the problem it addresses: a medication decision, a test, monitoring, a referral, education, or
  a follow-up. `text` is the action in a few words as the note states it (no advice of your own);
  `kind` is one of diagnostic, therapeutic, monitoring, referral, education, follow_up. A
  medication decision is BOTH a plan item and a `medications` entry.
- `confidence` is your 0-1 estimate that a clinician will accept the item as written.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["observations", "findings", "problems", "medications", "suspected_causes", "plans"],
    "properties": {
        "observations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["quote", "loinc", "value", "unit", "date", "problem_refs", "confidence"],
            "properties": {
                "quote": {"type": "string"},
                "loinc": {"type": "string"},
                "value": {"type": "number"},
                "unit": {"type": ["string", "null"]},
                "date": {"type": ["string", "null"], "description": "YYYY-MM-DD or null for the note date"},
                "problem_refs": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            }}},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["quote", "summary", "problem_refs", "confidence"],
            "properties": {
                "quote": {"type": "string"},
                "summary": {"type": "string"},
                "problem_refs": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            }}},
        "problems": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["ref", "quote", "name", "status", "onset_date", "supersedes_problem_id", "confidence"],
            "properties": {
                "ref": {"type": "string", "description": "new_1, new_2, ..."},
                "quote": {"type": "string"},
                "name": {"type": "string"},
                "status": {"type": "string", "enum": ["active", "resolved"]},
                "onset_date": {"type": ["string", "null"]},
                "supersedes_problem_id": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
            }}},
        "medications": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["ref", "quote", "name", "dose", "route", "frequency", "start", "end",
                         "existing_med_id", "change", "treats_problem_refs", "confidence"],
            "properties": {
                "ref": {"type": "string"},
                "quote": {"type": "string"},
                "name": {"type": "string"},
                "dose": {"type": ["string", "null"]},
                "route": {"type": ["string", "null"]},
                "frequency": {"type": ["string", "null"]},
                "start": {"type": ["string", "null"]},
                "end": {"type": ["string", "null"]},
                "existing_med_id": {"type": ["string", "null"]},
                "change": {"type": "string", "enum": ["new", "confirm", "stop", "dose_change", "frequency_change"]},
                "treats_problem_refs": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            }}},
        "plans": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["quote", "kind", "text", "problem_refs", "confidence"],
            "properties": {
                "quote": {"type": "string"},
                "kind": {"type": "string", "enum": ["diagnostic", "therapeutic", "monitoring", "referral", "education", "follow_up"]},
                "text": {"type": "string"},
                "problem_refs": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            }}},
        "suspected_causes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["quote", "cause_ref", "effect_ref", "rationale", "confidence"],
            "properties": {
                "quote": {"type": "string"},
                "cause_ref": {"type": "string"},
                "effect_ref": {"type": "string"},
                "rationale": {"type": "string"},
                "confidence": {"type": "number"},
            }}},
    },
}


def chart_context(patient: dict) -> dict:
    """The slice of the chart the model needs to link against. Small on purpose."""
    problems = [
        {"id": p["id"], "name": p["name"], "status": p["status"], "onset": p.get("onset_date")}
        for p in patient.get("problems", []) if p.get("status") in ("active", "resolved")
    ]
    meds = []
    for m in patient.get("medications", []):
        if m.get("status") != "accepted":
            continue
        seg = m["segments"][-1]
        meds.append({"id": m["id"], "name": m["name"], "dose": seg.get("dose"), "route": seg.get("route"),
                     "frequency": seg.get("frequency"), "since": seg.get("start"),
                     "ongoing": seg.get("end") is None})
    return {"patient": patient["patient"], "problems": problems, "medications": meds}


def build_messages(patient: dict, note: dict) -> tuple[list[dict], list[dict]]:
    """Returns (system_blocks, messages). The stable chart context is cached; the note is not."""
    ctx = chart_context(patient)
    system_blocks = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text",
         "text": "Allowed LOINC codes for observations:\n" + loinc_menu()
                 + "\n\nCurrent chart context (JSON):\n" + json.dumps(ctx, indent=1, sort_keys=True),
         "cache_control": {"type": "ephemeral"}},
    ]
    user = (f"Note id: {note['id']}\nNote date: {note['time'][:10]}\nAuthor: {note.get('author')}\n"
            f"Encounter: {note.get('encounter_id')}\n\n--- NOTE TEXT ---\n{note['text']}\n--- END NOTE ---")
    return system_blocks, [{"role": "user", "content": user}]


# ------------------------------------------------------------------------------ model

def call_model(system_blocks, messages, model: str = DEFAULT_MODEL) -> dict:
    """One structured-output request (see ehr.llm.call_structured)."""
    from ehr.llm import call_structured
    return call_structured(system_blocks, messages, OUTPUT_SCHEMA, model=model)


# --------------------------------------------------------------------------- validate

WS_RE = re.compile(r"\s+")


def verbatim_quote(quote: str, text: str) -> str | None:
    """Return the exact substring of `text` matching `quote`, tolerating whitespace/case
    differences in the model's copy; None if it cannot be located."""
    if not quote:
        return None
    if quote in text:
        return quote
    pattern = r"\s+".join(re.escape(w) for w in WS_RE.split(quote.strip()) if w)
    m = re.search(pattern, text, flags=re.I)
    return m.group(0) if m else None


def _date_to_time(date_str: str | None, note_time: str) -> str | None:
    """'YYYY-MM-DD' -> ISO time at 00:00 in the note's UTC offset; None -> note time."""
    if not date_str:
        return note_time
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return None
    tz = re.search(r"(Z|[+-]\d{2}:\d{2})$", note_time)
    return f"{date_str}T00:00:00{tz.group(1) if tz else '+00:00'}"


def _iso_date_or_none(s: str | None) -> str | None:
    return s if s and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def _conf(x) -> float:
    try:
        return round(min(1.0, max(0.0, float(x))), 2)
    except (TypeError, ValueError):
        return 0.5


class Validator:
    """Turns raw model output into schema entities, rejecting anything unverifiable."""

    def __init__(self, patient: dict, note: dict, model: str):
        self.patient, self.note, self.model = patient, note, model
        self.text = note["text"]
        self.tag = re.sub(r"^note_", "", note["id"])
        self.now = datetime.now().astimezone().isoformat(timespec="seconds")
        self.prob_ids = {p["id"] for p in patient.get("problems", [])}
        self.med_ids = {m["id"] for m in patient.get("medications", [])}
        self.existing_obs = {  # (code, date, value) -> obs id, for exact dedupe
            (o["code"]["value"], o["effective_time"][:10], round(float(o["value"]), 3)): o["id"]
            for o in patient.get("observations", []) if isinstance(o.get("value"), (int, float))
        }
        self.obs_by_group: dict[str, list[tuple[str, float, str]]] = {}  # group -> [(date, value, id)] for fuzzy dedupe
        for o in patient.get("observations", []):
            if isinstance(o.get("value"), (int, float)) and o.get("status") == "accepted":
                g = CODE_GROUPS.get(o["code"]["value"], o["code"]["value"])
                self.obs_by_group.setdefault(g, []).append((o["effective_time"][:10], float(o["value"]), o["id"]))
        self.new_med_by_name: dict[str, dict] = {}
        self.existing_links = {(l["from"], l["to"], l["type"]) for l in patient.get("links", [])}
        self.out = {"problems": [], "observations": [], "medications": [], "links": [], "plans": []}
        self.confirmed_medications: list[dict] = []
        self.medication_changes: list[dict] = []
        self.review_hints: dict[str, str] = {}
        self.rejected: list[dict] = []
        self.ref_map: dict[str, str] = {}  # new_N -> proposed id
        self.counters = {"prob": 0, "obs": 0, "med": 0, "lnk": 0, "plan": 0}

    # -- helpers
    def new_id(self, prefix: str) -> str:
        self.counters[prefix] += 1
        return f"{prefix}_{self.tag}_{self.counters[prefix]:02d}"

    def provenance(self, quote: str, confidence) -> dict:
        return {"source": "nlp_extraction", "note_id": self.note["id"], "quote": quote,
                "model": f"{EXTRACTOR_VERSION}/{self.model}", "confidence": _conf(confidence)}

    def reject(self, kind: str, item: dict, reason: str):
        self.rejected.append({"kind": kind, "reason": reason, "item": item})

    def quote_of(self, kind: str, item: dict) -> str | None:
        q = verbatim_quote(item.get("quote", ""), self.text)
        if q is None:
            self.reject(kind, item, f"quote not found verbatim in note: {item.get('quote')!r}")
        return q

    def fuzzy_existing(self, code: str, day: str, value: float) -> str | None:
        """Charted observation of the same analyte within DEDUPE_DAYS and DEDUPE_TOLERANCE, else None."""
        from datetime import date as _date
        try:
            d0 = _date.fromisoformat(day)
        except ValueError:
            return None
        best = None
        for d, v, oid in self.obs_by_group.get(CODE_GROUPS.get(code, code), []):
            if abs(v - value) > DEDUPE_TOLERANCE * max(abs(value), 1e-9):
                continue
            gap = abs((_date.fromisoformat(d) - d0).days)
            if gap <= DEDUPE_DAYS and (best is None or gap < best[0]):
                best = (gap, oid)
        return best[1] if best else None

    def resolve_problem(self, ref: str) -> str | None:
        if ref in self.prob_ids:
            return ref
        return self.ref_map.get(ref)

    def resolve_med(self, ref: str) -> str | None:
        if ref in self.med_ids:
            return ref
        return self.ref_map.get(ref)

    def add_link(self, frm: str, to: str, ltype: str, quote: str, confidence) -> str | None:
        assert ltype in LINK_TYPES
        if (frm, to, ltype) in self.existing_links:
            return None
        self.existing_links.add((frm, to, ltype))
        lid = self.new_id("lnk")
        self.out["links"].append({"id": lid, "from": frm, "to": to, "type": ltype, "status": "proposed",
                                  "provenance": self.provenance(quote, confidence), "created_at": self.now})
        return lid

    # -- passes (problems first so refs resolve)
    def problems(self, items: list[dict]):
        for it in items:
            q = self.quote_of("problem", it)
            if q is None:
                continue
            pid = self.new_id("prob")
            self.ref_map[it.get("ref", "")] = pid
            self.out["problems"].append({
                "id": pid, "patient_id": self.patient["patient"]["id"], "name": it["name"].strip(),
                "code": None, "status": "proposed",
                "onset_date": _iso_date_or_none(it.get("onset_date")), "resolved_date": None,
                "provenance": self.provenance(q, it.get("confidence")),
            })
            self.add_link(self.note["id"], pid, "evidence_for", q, it.get("confidence"))
            sup = it.get("supersedes_problem_id")
            if sup:
                if sup in self.prob_ids:
                    self.review_hints[pid] = f"supersedes {sup}; on accept, consider resolving it"
                else:
                    self.review_hints[pid] = f"model referenced unknown problem {sup} as superseded"

    def observations(self, items: list[dict]):
        pid_of_patient = self.patient["patient"]["id"]
        for it in items:
            q = self.quote_of("observation", it)
            if q is None:
                continue
            code = str(it.get("loinc", "")).strip()
            if code not in EXTRACTABLE_LOINC:
                self.reject("observation", it, f"LOINC {code!r} not in the extractable table")
                continue
            name, unit, rr = EXTRACTABLE_LOINC[code]
            t = _date_to_time(it.get("date"), self.note["time"])
            if t is None:
                self.reject("observation", it, f"bad date {it.get('date')!r}")
                continue
            try:
                value = float(it["value"])
            except (TypeError, ValueError, KeyError):
                self.reject("observation", it, "value is not numeric")
                continue
            existing = self.existing_obs.get((code, t[:10], round(value, 3)))
            if not existing and it.get("date"):
                # Only a value the note attributes to an earlier date can be a restatement of a charted result;
                # a measurement taken at this visit is new data even if the number matches a recent one.
                existing = self.fuzzy_existing(code, t[:10], value)
            if existing:
                oid = existing
                self.review_hints[oid] = f"already in chart; note restates it ({q!r})"
            else:
                oid = self.new_id("obs")
                self.out["observations"].append({
                    "id": oid, "patient_id": pid_of_patient, "code": {"system": "LOINC", "value": code},
                    "name": name, "value": value, "unit": it.get("unit") or unit, "reference_range": rr,
                    "effective_time": t, "status": "proposed",
                    "provenance": self.provenance(q, it.get("confidence")),
                })
            for ref in it.get("problem_refs") or []:
                target = self.resolve_problem(ref)
                if target:
                    self.add_link(oid, target, "relevant_to", q, it.get("confidence"))
                else:
                    self.reject("link", {"from": oid, "to": ref}, "problem ref does not resolve")

    def findings(self, items: list[dict]):
        for it in items:
            q = self.quote_of("finding", it)
            if q is None:
                continue
            linked = False
            for ref in it.get("problem_refs") or []:
                target = self.resolve_problem(ref)
                if target:
                    lid = self.add_link(self.note["id"], target, "evidence_for", q, it.get("confidence"))
                    if lid:
                        self.review_hints[lid] = it.get("summary", "")
                    linked = True
                else:
                    self.reject("link", {"finding": it.get("summary"), "to": ref}, "problem ref does not resolve")
            if not linked:
                self.reject("finding", it, "no resolvable problem to link the finding to")

    def medications(self, items: list[dict]):
        pid_of_patient = self.patient["patient"]["id"]
        for it in items:
            q = self.quote_of("medication", it)
            if q is None:
                continue
            change = it.get("change")
            existing = it.get("existing_med_id")
            if change == "new":
                mid = self.new_id("med")
                self.ref_map[it.get("ref", "")] = mid
                self.out["medications"].append({
                    "id": mid, "patient_id": pid_of_patient, "name": it["name"].strip(), "code": None,
                    "segments": [{"start": _iso_date_or_none(it.get("start")), "end": _iso_date_or_none(it.get("end")),
                                  "dose": it.get("dose"), "route": it.get("route"), "frequency": it.get("frequency")}],
                    "status": "proposed", "provenance": self.provenance(q, it.get("confidence")),
                })
                self.new_med_by_name[it["name"].strip().lower()] = self.out["medications"][-1]
                if not _iso_date_or_none(it.get("start")):
                    self.review_hints[mid] = "start date unknown; set it on accept"
                for ref in it.get("treats_problem_refs") or []:
                    target = self.resolve_problem(ref)
                    if target:
                        self.add_link(mid, target, "treats", q, it.get("confidence"))
                    else:
                        self.reject("link", {"from": mid, "to": ref}, "problem ref does not resolve")
            elif existing in self.med_ids:
                self.ref_map[it.get("ref", "")] = existing
                if change == "confirm":
                    self.confirmed_medications.append({"med_id": existing, "quote": q, "confidence": _conf(it.get("confidence"))})
                else:
                    dose, freq = it.get("dose"), it.get("frequency")
                    hint = None
                    if change == "dose_change" and not dose:
                        dose, hint = q, "no numeric dose in the note; its instruction is kept as the dose string - set a numeric dose on accept"
                    if change == "frequency_change" and not freq:
                        freq, hint = q, "no explicit frequency in the note; its instruction is kept as the frequency string"
                    self.medication_changes.append({
                        "med_id": existing, "change": change, "effective": _iso_date_or_none(it.get("end") or it.get("start")) or self.note["time"][:10],
                        "dose": dose, "route": it.get("route"), "frequency": freq,
                        "status": "proposed", "provenance": self.provenance(q, it.get("confidence")),
                        **({"hint": hint} if hint else {}),
                    })
                for ref in it.get("treats_problem_refs") or []:
                    target = self.resolve_problem(ref)
                    if target:
                        self.add_link(existing, target, "treats", q, it.get("confidence"))
            elif change in ("stop", "dose_change", "frequency_change") and it.get("name", "").strip().lower() in self.new_med_by_name:
                # "Counseled to stop naproxen today" about a course this same note introduced: close that course.
                course = self.new_med_by_name[it["name"].strip().lower()]
                seg = course["segments"][-1]
                eff = _iso_date_or_none(it.get("end") or it.get("start")) or self.note["time"][:10]
                if change == "stop":
                    seg["end"] = eff
                    self.review_hints[course["id"]] = f"course closed {eff} by the same note ({q!r})"
                else:
                    seg["end"] = eff
                    course["segments"].append({"start": eff, "end": None, "dose": it.get("dose") or seg["dose"],
                                               "route": it.get("route") or seg["route"], "frequency": it.get("frequency") or seg["frequency"]})
            else:
                self.reject("medication", it, f"change {change!r} needs an existing_med_id that exists in the chart")

    def suspected_causes(self, items: list[dict]):
        for it in items:
            q = self.quote_of("suspected_cause", it)
            if q is None:
                continue
            cause = self.resolve_med(it.get("cause_ref", "")) or self.resolve_problem(it.get("cause_ref", ""))
            eff = it.get("effect_ref", "")
            effect = self.resolve_problem(eff) or (eff if eff.startswith("LOINC:") and eff[6:] in EXTRACTABLE_LOINC else None)
            if not cause or not effect:
                self.reject("suspected_cause", it, "cause or effect ref does not resolve")
                continue
            lid = self.add_link(cause, effect, "suspected_cause", q, it.get("confidence"))
            if lid:
                self.review_hints[lid] = it.get("rationale", "")

    def plans(self, items: list[dict]):
        """Plan items: what the note says will be done, each tied to the problem it addresses.
        FLAGGED schema addition (not in docs/patient-model-schema.md): a Plan entity, `plan_` prefix."""
        for it in items:
            q = self.quote_of("plan", it)
            if q is None:
                continue
            kind = it.get("kind")
            if kind not in PLAN_KINDS:
                self.reject("plan", it, f"unknown plan kind {kind!r}")
                continue
            targets = [t for t in (self.resolve_problem(r) for r in it.get("problem_refs") or []) if t]
            if not targets:
                self.reject("plan", it, "no resolvable problem for the plan item")
                continue
            pid = self.new_id("plan")
            self.out["plans"].append({
                "id": pid, "patient_id": self.patient["patient"]["id"], "problem_id": targets[0],
                "kind": kind, "text": (it.get("text") or "").strip() or q,
                "status": "proposed", "provenance": self.provenance(q, it.get("confidence")), "created_at": self.now,
            })
            for extra in targets[1:]:
                self.add_link(pid, extra, "relevant_to", q, it.get("confidence"))

    def run(self, raw: dict) -> dict:
        self.problems(raw.get("problems") or [])
        self.observations(raw.get("observations") or [])
        self.findings(raw.get("findings") or [])
        self.medications(raw.get("medications") or [])
        self.suspected_causes(raw.get("suspected_causes") or [])
        self.plans(raw.get("plans") or [])
        return {
            "patient_id": self.patient["patient"]["id"], "note_id": self.note["id"],
            "model": f"{EXTRACTOR_VERSION}/{self.model}", "extracted_at": self.now,
            "proposed": self.out,
            "confirmed_medications": self.confirmed_medications,
            "medication_changes": self.medication_changes,
            "review_hints": self.review_hints,
            "rejected": self.rejected,
        }


def validate(patient: dict, note: dict, raw: dict, model: str) -> dict:
    return Validator(patient, note, model).run(raw)


# ----------------------------------------------------------------------------- ingest

def load_note_file(path: str | Path) -> tuple[dict, dict | None]:
    """data/notes/*.json is {"encounter": ..., "note": ...}; a bare Note object is also accepted."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if "note" in d:
        return d["note"], d.get("encounter")
    return d, None


def ingest(patient: dict, note: dict, encounter: dict | None) -> list[str]:
    """Upsert the human-written encounter and note into the loaded patient. Idempotent."""
    changed = []
    if encounter:
        encs = patient.setdefault("encounters", [])
        idx = next((i for i, e in enumerate(encs) if e["id"] == encounter["id"]), None)
        if idx is None:
            encs.append(encounter); changed.append(f"encounter {encounter['id']} added")
        elif encs[idx] != encounter:
            encs[idx] = encounter; changed.append(f"encounter {encounter['id']} updated")
    notes = patient.setdefault("notes", [])
    idx = next((i for i, n in enumerate(notes) if n["id"] == note["id"]), None)
    if idx is None:
        notes.append(note); changed.append(f"note {note['id']} added")
    elif notes[idx] != note:
        notes[idx] = note; changed.append(f"note {note['id']} updated")
    if note.get("encounter_id") and not any(e["id"] == note["encounter_id"] for e in patient.get("encounters", [])):
        raise ValueError(f"note {note['id']} references unknown encounter {note['encounter_id']}")
    return changed


def save_patient(patient: dict, data_dir: Path = DATA_DIR):
    path = data_dir / f"{patient['patient']['id']}.json"
    path.write_text(json.dumps(patient, indent=2, ensure_ascii=False))


def queue_path(patient_id: str, note_id: str, proposed_dir: Path = PROPOSED_DIR) -> Path:
    return proposed_dir / patient_id / f"{note_id}.json"


# --------------------------------------------------------------------------- pipeline

def extract_note(patient: dict, note: dict, *, model: str = DEFAULT_MODEL, raw: dict | None = None) -> tuple[dict, dict]:
    """Run extraction (or validate a replayed raw response). Returns (batch, raw_response)."""
    if raw is None:
        system_blocks, messages = build_messages(patient, note)
        raw = call_model(system_blocks, messages, model=model)
    batch = validate(patient, note, raw["parsed"], raw.get("model", model))
    batch["usage"] = raw.get("usage")
    return batch, raw


def run_extraction(patient_id: str, note_file: str | Path, *, model: str = DEFAULT_MODEL,
                   replay: str | Path | None = None, data_dir: Path = DATA_DIR, save: bool = True) -> dict:
    """Ingest + extract + queue in one call (used by the CLI and the API). Returns the batch."""
    data_dir = Path(data_dir)
    note, encounter = load_note_file(note_file)
    patient = load_patient(patient_id, data_dir)
    changes = ingest(patient, note, encounter)
    if changes and save:
        save_patient(patient, data_dir)
    raw = json.loads(Path(replay).read_text()) if replay else None
    batch, raw = extract_note(patient, note, model=model, raw=raw)
    batch["ingest"] = changes
    qp = queue_path(patient_id, note["id"], data_dir.parent / "proposed")
    if save:
        qp.parent.mkdir(parents=True, exist_ok=True)
        qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
        if not replay:
            record_response(qp, raw)
    batch["queue_path"] = str(qp)
    return batch


def record_response(queue_path: Path, raw: dict) -> Path:
    """Save a live model response twice: a timestamped copy that is never overwritten, and
    `<stem>.raw.json`, the 'latest' pointer that replay uses. Roll back by copying an older
    timestamped file over the pointer."""
    stamped = queue_path.with_name(f"{queue_path.stem}.{datetime.now().strftime('%Y%m%dT%H%M%S')}.raw.json")
    text = json.dumps(raw, indent=2, ensure_ascii=False)
    stamped.write_text(text)
    queue_path.with_suffix(".raw.json").write_text(text)
    return stamped


def summarize(batch: dict) -> str:
    p = batch["proposed"]
    lines = [f"=== extraction for {batch['note_id']} ({batch['model']}) ===",
             f"proposed: problems={len(p['problems'])} observations={len(p['observations'])} "
             f"medications={len(p['medications'])} links={len(p['links'])}; "
             f"confirmed meds={len(batch['confirmed_medications'])} med changes={len(batch['medication_changes'])}; "
             f"rejected={len(batch['rejected'])}"]
    for x in p["problems"]:
        lines.append(f"  + problem {x['id']}: {x['name']}  <- {x['provenance']['quote']!r}")
    for x in p["observations"]:
        lines.append(f"  + obs {x['id']}: {x['name']} = {x['value']} {x['unit']} @ {x['effective_time'][:10]}  <- {x['provenance']['quote']!r}")
    for x in p["medications"]:
        s = x["segments"][0]
        lines.append(f"  + med {x['id']}: {x['name']} {s['dose']} {s['frequency']} {s['start']}..{s['end']}  <- {x['provenance']['quote']!r}")
    for x in batch["medication_changes"]:
        lines.append(f"  ~ med change {x['med_id']}: {x['change']} effective {x['effective']}  <- {x['provenance']['quote']!r}")
    for x in p["links"]:
        lines.append(f"  + link {x['id']}: {x['from']} -{x['type']}-> {x['to']}  (conf {x['provenance']['confidence']})")
    for r in batch["rejected"]:
        lines.append(f"  x rejected {r['kind']}: {r['reason']}")
    if batch.get("usage"):
        lines.append(f"usage: {batch['usage']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note_file")
    ap.add_argument("--patient", help="patient id (default: the note's patient_id)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--dry-run", action="store_true", help="ingest + print the prompt; no API call")
    ap.add_argument("--replay", help="path to a saved *.raw.json model response to validate instead of calling the API")
    ap.add_argument("--no-ingest", action="store_true", help="do not write the note/encounter into the patient file")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    note, encounter = load_note_file(args.note_file)
    pid = args.patient or note["patient_id"]
    patient = load_patient(pid, data_dir)

    changes = ingest(patient, note, encounter)
    if changes and not args.no_ingest:
        save_patient(patient, data_dir)
        print("ingest:", "; ".join(changes))
    elif changes:
        print("ingest (not saved, --no-ingest):", "; ".join(changes))
    else:
        print("ingest: note and encounter already in chart")

    if args.dry_run:
        system_blocks, messages = build_messages(patient, note)
        print("\n--- system ---")
        for b in system_blocks:
            print(b["text"])
        print("\n--- user ---")
        print(messages[0]["content"])
        return 0

    raw = None
    if args.replay:
        raw = json.loads(Path(args.replay).read_text())
    try:
        batch, raw = extract_note(patient, note, model=args.model, raw=raw)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    qp = queue_path(pid, note["id"], data_dir.parent / "proposed")
    qp.parent.mkdir(parents=True, exist_ok=True)
    qp.write_text(json.dumps(batch, indent=2, ensure_ascii=False))
    if not args.replay:
        qp.with_suffix(".raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False))
    print(summarize(batch))
    print(f"\nreview queue: {qp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
