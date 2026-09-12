#!/usr/bin/env python3
"""Flatten one Synthea FHIR R4 bundle into a per-patient JSON in our schema.

    python3 scripts/import_patient.py data/synthea/fhir/<bundle>.json [--id pt_001]
        [--out data/patients] [--keep-findings] [--merge-creatinine-codes]

Writes data/patients/<id>.json and data/patients/<id>.import-report.json and
prints a validation summary. Everything imported gets status "accepted" and
provenance.source "fhir_import" (docs/patient-model-schema.md §8).

Schema interpretations that are NOT settled by the schema doc are listed in
FLAGGED_DECISIONS below and echoed in the report.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fhir_common import (  # noqa: E402
    CREATININE_CANONICAL, FRIENDLY_NAMES, MONITORS_TABLE, REFERENCE_RANGES, clean_person_name, code_of,
    condition_category, date_only, display_of, first_coding, frequency_text, fullurl_map,
    is_social_history_condition, load_bundle, parse_dt, parse_rx_display, patient_display_name, resources,
    route_for_form, slugify,
)

# Synthea re-issues chronic meds as a new MedicationRequest at every visit (annual wellness,
# monthly insulin). Same-code requests closer together than this are one continuous segment.
REFILL_GAP_DAYS = 400

FLAGGED_DECISIONS = [
    "File envelope is {patient, problems, observations, medications, encounters, notes, links, insights}; the schema defines entities, not the wrapper.",
    "'monitors' links use from='LOINC:<code>' because §7 says 'observation-code' without defining the shape.",
    "Medication courses are grouped by ingredient + route parsed from the RxNorm display (strength-specific RxNorm codes would never yield a dose-change segment; IV furosemide is a separate course from oral); course.code is the latest segment's RxNorm.",
    "Synthea re-issues chronic meds as a new completed MedicationRequest at every visit; same-RxNorm requests <= 400 days apart are merged into one segment.",
    "Medication segment end dates are inferred (Synthea emits none): a different-strength request closes the previous segment at its start; a completed refill chain (>=2 requests) lapses one median refill interval after its last request; a single completed request ends at the next encounter; an inferred end past the last encounter is left open (end=null) rather than faked. (Synthea notes list every drug ever prescribed, so they carry no stop signal.)",
    "Non-numeric Observations (valueCodeableConcept/valueString/valueBoolean) are not imported; schema value is numeric.",
    "Conditions ending in '(finding)'/'(situation)' (Synthea social history) are filtered unless --keep-findings.",
    "reference_range comes from a hardcoded table (Synthea emits none); null for other codes.",
    "Synthea emits each CKD stage as its own Condition; one Problem per Condition is kept (earlier stages resolved). Merging into a single CKD problem is a team call.",
    "Creatinine stays under both Synthea codes (2160-0 serum, 38483-4 whole blood; different generators, different baselines); both are 'monitors' series for CKD. --merge-creatinine-codes re-codes 38483-4 to 2160-0.",
    "eGFR (33914-3) values that share a DiagnosticReport panel with serum creatinine 2160-0 are excluded (counted in the report): Synthea derives them from the flat serum series, so under one code they interleave with the CKD-tracking eGFR and plot as noise. --keep-panel-egfr disables this.",
    "'treats' links come only from MedicationRequest.reasonReference (explicit in FHIR), nothing inferred.",
]

TZ_RE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")
TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")  # "(disorder)", "(procedure)", "(environment)" ...

ENCOUNTER_CLASS = {"AMB": "ambulatory", "EMER": "emergency", "IMP": "inpatient", "HH": "home health",
                   "VR": "virtual", "OBSENC": "observation", "SS": "short stay"}

NOTE_LOINC = {"34117-2", "51847-2"}

CODE_SYSTEMS = {
    "http://loinc.org": "LOINC",
    "http://snomed.info/sct": "SNOMED-CT",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_tz(ts: str | None, label: str, report: dict) -> str | None:
    if ts is None:
        return None
    if not TZ_RE.search(ts):
        report["warnings"].append(f"{label}: timestamp without timezone: {ts}")
    return ts


class Importer:
    def __init__(self, bundle: dict, patient_id: str, keep_findings: bool, merge_creatinine_codes: bool,
                 keep_panel_egfr: bool = False):
        self.bundle = bundle
        self.pid = patient_id
        self.keep_findings = keep_findings
        self.merge_creatinine_codes = merge_creatinine_codes
        self.keep_panel_egfr = keep_panel_egfr
        self.refmap = fullurl_map(bundle)
        self.report: dict = {
            "patient_id": patient_id,
            "imported_at": now_iso(),
            "counts": {},
            "date_range": {},
            "monitors": {},
            "medications": {"courses": 0, "segments": 0, "requests_merged_into_segments": 0,
                            "end_inference": Counter(), "multi_segment_courses": []},
            "filtered_conditions": [],
            "unmapped_resources": {},
            "unmapped_observations": Counter(),
            "duplicate_notes": 0,
            "lab_panel_reports": 0,
            "creatinine_recoded": 0,
            "excluded_observations": Counter(),
            "warnings": [],
            "flagged_decisions": FLAGGED_DECISIONS,
        }
        # FHIR ref -> our id
        self.enc_ids: dict[str, str] = {}
        self.prob_ids: dict[str, str] = {}
        self.out = {
            "patient": None, "problems": [], "observations": [], "medications": [],
            "encounters": [], "notes": [], "links": [], "insights": [],
        }

    # ----------------------------------------------------------------- utils
    def resolve(self, ref: dict | None) -> dict | None:
        if not ref or not ref.get("reference"):
            return None
        return self.refmap.get(ref["reference"])

    def refkey(self, ref: dict | None) -> str | None:
        return ref.get("reference") if ref else None

    def practitioner_name(self, ref: dict | None) -> str | None:
        if ref and ref.get("display"):
            return clean_person_name(ref["display"])
        r = self.resolve(ref)
        if not r:
            return None
        if r.get("resourceType") == "Practitioner":
            names = r.get("name") or []
            if names:
                n = names[0]
                given = " ".join(n.get("given", []))
                prefix = " ".join(n.get("prefix", []))
                return clean_person_name(" ".join(x for x in (prefix, given, n.get("family", "")) if x))
        return clean_person_name(r.get("name"))

    # --------------------------------------------------------------- patient
    def import_patient(self):
        p = next(resources(self.bundle, "Patient"))
        self.fhir_patient = p
        sex = {"female": "F", "male": "M"}.get(p.get("gender"), "U")
        self.out["patient"] = {
            "id": self.pid,
            "name": patient_display_name(p),
            "dob": p.get("birthDate"),
            "sex": sex,
        }
        if p.get("deceasedDateTime"):
            self.report["warnings"].append(f"patient is deceased ({date_only(p['deceasedDateTime'])})")

    # ------------------------------------------------------------ encounters
    def import_encounters(self):
        encs = []
        for e in resources(self.bundle, "Encounter"):
            start = (e.get("period") or {}).get("start")
            encs.append((parse_dt(start), e))
        encs.sort(key=lambda x: (x[0] is None, x[0]))
        for i, (_, e) in enumerate(encs, 1):
            eid = f"enc_{i:04d}"
            self.enc_ids[f"urn:uuid:{e['id']}"] = eid
            self.enc_ids[f"Encounter/{e['id']}"] = eid
            types = e.get("type") or []
            type_disp = display_of(types[0]) if types else ""
            cls = (e.get("class") or {}).get("code")
            etype = type_disp.lower() if type_disp else ENCOUNTER_CLASS.get(cls, (cls or "unknown").lower())
            reasons = e.get("reasonCode") or []
            summary = display_of(reasons[0]) if reasons else (type_disp or etype)
            summary = TRAILING_PAREN_RE.sub("", summary)
            self.out["encounters"].append({
                "id": eid,
                "patient_id": self.pid,
                "time": ensure_tz((e.get("period") or {}).get("start"), eid, self.report),
                "type": TRAILING_PAREN_RE.sub("", etype),
                "summary": summary,
            })

    # -------------------------------------------------------------- problems
    def import_problems(self):
        conds = []
        for c in resources(self.bundle, "Condition"):
            if not self.keep_findings and is_social_history_condition(c):
                self.report["filtered_conditions"].append(display_of(c.get("code")))
                continue
            conds.append((parse_dt(c.get("onsetDateTime")), c))
        conds.sort(key=lambda x: (x[0] is None, x[0]))
        self.problem_categories: dict[str, str] = {}  # prob_id -> category
        for i, (_, c) in enumerate(conds, 1):
            pid = f"prob_{i:04d}"
            self.prob_ids[f"urn:uuid:{c['id']}"] = pid
            self.prob_ids[f"Condition/{c['id']}"] = pid
            coding = first_coding(c.get("code"))
            name = re.sub(r"\s*\((disorder|finding|situation)\)\s*$", "", display_of(c.get("code")))
            abated = c.get("abatementDateTime")
            clinical = code_of(c.get("clinicalStatus")) or ("resolved" if abated else "active")
            status = "resolved" if (abated or clinical in ("resolved", "inactive", "remission")) else "active"
            prob = {
                "id": pid,
                "patient_id": self.pid,
                "name": name,
                "code": {"system": "SNOMED-CT", "value": coding.get("code")} if coding.get("code") else None,
                "status": status,
                "onset_date": date_only(c.get("onsetDateTime")),
                "resolved_date": date_only(abated),
                "provenance": {"source": "fhir_import"},
            }
            self.out["problems"].append(prob)
            cat = condition_category(c)
            if cat:
                self.problem_categories[pid] = cat

    # ---------------------------------------------------------- observations
    def panel_codes(self) -> dict[str, set[str]]:
        """Observation fullUrl -> the set of LOINC codes in the DiagnosticReport panel it belongs to."""
        members: dict[str, set[str]] = {}
        for r in resources(self.bundle, "DiagnosticReport"):
            refs = [self.refkey(x) for x in (r.get("result") or [])]
            codes = {code_of((self.refmap.get(ref) or {}).get("code")) for ref in refs}
            for ref in refs:
                if ref:
                    members.setdefault(ref, set()).update(codes)
        return members

    def import_observations(self):
        rows = []
        panels = self.panel_codes()
        for o in resources(self.bundle, "Observation"):
            t = o.get("effectiveDateTime") or o.get("issued")
            comps = o.get("component") or []
            if (not self.keep_panel_egfr and code_of(o.get("code")) == "33914-3"
                    and "2160-0" in panels.get(f"urn:uuid:{o.get('id')}", set())):
                self.report["excluded_observations"]["33914-3 eGFR derived from a serum-creatinine panel (dual-generator duplicate)"] += 1
                continue
            # Ids come from a hash of the FHIR resource id, not a running counter, so they survive
            # re-imports (an exclusion rule that drops 93 observations must not renumber the other 3800).
            # Synthea uuids share their leading segments, hence the hash rather than a prefix.
            stem = "obs_" + hashlib.sha1(str(o.get("id", "")).encode()).hexdigest()[:8]
            if "valueQuantity" in o:
                rows.append((t, o.get("code"), o["valueQuantity"], stem))
            elif comps and any("valueQuantity" in cp for cp in comps):
                for k, cp in enumerate(comps, 1):
                    if "valueQuantity" in cp:
                        rows.append((t, cp.get("code"), cp["valueQuantity"], f"{stem}_{k}"))
            elif comps:
                self.report["unmapped_observations"][f"{code_of(o.get('code'))} {display_of(o.get('code'))} [non-numeric components]"] += 1
            else:
                kind = next((k for k in o if k.startswith("value")), "no value")
                self.report["unmapped_observations"][f"{code_of(o.get('code'))} {display_of(o.get('code'))} [{kind}]"] += 1
        rows.sort(key=lambda r: (parse_dt(r[0]) is None, parse_dt(r[0]) or datetime.min.replace(tzinfo=timezone.utc)))
        seen_ids: set[str] = set()
        for t, code_cc, vq, oid in rows:
            while oid in seen_ids:  # uuid prefix collision: vanishingly unlikely, handled anyway
                oid += "x"
            seen_ids.add(oid)
            code = code_of(code_cc)
            if code == "38483-4" and self.merge_creatinine_codes:
                code = CREATININE_CANONICAL
                self.report["creatinine_recoded"] += 1
            name = FRIENDLY_NAMES.get(code) or display_of(code_cc)
            val = vq.get("value")
            self.out["observations"].append({
                "id": oid,
                "patient_id": self.pid,
                "code": {"system": CODE_SYSTEMS.get(first_coding(code_cc).get("system"), "LOINC"), "value": code},
                "name": name,
                "value": float(val) if isinstance(val, (int, float)) else val,
                "unit": vq.get("unit") or vq.get("code"),
                "reference_range": REFERENCE_RANGES.get(code),
                "effective_time": ensure_tz(t, oid, self.report),
                "status": "accepted",
                "provenance": {"source": "fhir_import"},
            })

    # ------------------------------------------------------------------ notes
    def import_notes(self):
        notes = []
        for d in resources(self.bundle, "DocumentReference"):
            content = (d.get("content") or [{}])[0].get("attachment") or {}
            data = content.get("data")
            if not data:
                self.report["warnings"].append(f"DocumentReference {d.get('id')} has no attachment data")
                continue
            text = base64.b64decode(data).decode("utf-8", errors="replace")
            enc_ref = ((d.get("context") or {}).get("encounter") or [None])[0]
            authors = d.get("author") or []
            author = self.practitioner_name(authors[0]) if authors else None
            t = d.get("date") or ((d.get("context") or {}).get("period") or {}).get("start")
            notes.append((t, self.enc_ids.get(self.refkey(enc_ref)), author, text))
        notes.sort(key=lambda n: (parse_dt(n[0]) is None, parse_dt(n[0]) or datetime.min.replace(tzinfo=timezone.utc)))
        self.note_text_by_enc: dict[str, str] = {}
        for i, (t, eid, author, text) in enumerate(notes, 1):
            nid = f"note_{i:04d}"
            self.out["notes"].append({
                "id": nid,
                "patient_id": self.pid,
                "encounter_id": eid,
                "time": ensure_tz(t, nid, self.report),
                "author": author or "Synthea",
                "text": text,
            })
            if eid:
                self.note_text_by_enc[eid] = text
        # DiagnosticReports: notes duplicate DocumentReference text; lab panels are containers.
        for r in resources(self.bundle, "DiagnosticReport"):
            if any(code_of(cc) in NOTE_LOINC for cc in [r.get("code")] + (r.get("category") or [])) or r.get("presentedForm"):
                self.report["duplicate_notes"] += 1
            else:
                self.report["lab_panel_reports"] += 1

    # ------------------------------------------------------------ medications
    def import_medications(self):
        by_ingredient: dict[str, list[dict]] = defaultdict(list)
        for mr in resources(self.bundle, "MedicationRequest"):
            cc = mr.get("medicationCodeableConcept")
            if not cc:
                med = self.resolve(mr.get("medicationReference"))
                cc = (med or {}).get("code")
            parsed = parse_rx_display(display_of(cc))
            t = parse_dt(mr.get("authoredOn"))
            if t is None:
                self.report["warnings"].append(f"MedicationRequest {mr.get('id')} has no authoredOn; skipped")
                continue
            route = route_for_form(parsed["form"])
            key = (parsed["ingredient"], route)  # same drug by a different route is a different course
            by_ingredient[key].append({"mr": mr, "cc": cc, "parsed": parsed, "t": t, "route": route})

        self.enc_timeline = sorted(
            (parse_dt(e["time"]), e["time"], e["id"]) for e in self.out["encounters"] if e["time"]
        )
        last_enc_iso = self.enc_timeline[-1][1] if self.enc_timeline else None
        end_rule = self.report["medications"]["end_inference"]

        used_ids: set[str] = set()
        courses = []
        for (ingredient, route), reqs in by_ingredient.items():
            reqs.sort(key=lambda r: r["t"])
            route_suffix = {"INJ": " (injectable)", "SC": " (injectable)", "INH": " (inhaled)", "TD": " (patch)",
                            "OPH": " (ophthalmic)", "TOP": " (topical)", "NASAL": " (nasal)"}.get(route, "")
            display_name = ingredient[:1].upper() + ingredient[1:] + route_suffix
            # Collapse refill chains: consecutive same-RxNorm requests <= REFILL_GAP_DAYS apart.
            runs: list[list[dict]] = []
            for r in reqs:
                if runs and code_of(runs[-1][-1]["cc"]) == code_of(r["cc"]) \
                        and (r["t"] - runs[-1][-1]["t"]).days <= REFILL_GAP_DAYS:
                    runs[-1].append(r)
                else:
                    runs.append([r])
            self.report["medications"]["requests_merged_into_segments"] += len(reqs) - len(runs)

            segments = []
            for idx, run in enumerate(runs):
                first, last = run[0], run[-1]
                start_iso = first["mr"].get("authoredOn")
                next_run_start = runs[idx + 1][0]["t"] if idx + 1 < len(runs) else None
                if last["mr"].get("status") == "active":
                    end_dt, rule = None, "active_ongoing"
                elif len(run) >= 2:
                    gaps = sorted((b["t"] - a["t"]).days for a, b in zip(run, run[1:]))
                    median_gap = gaps[len(gaps) // 2]
                    end_dt, rule = last["t"] + timedelta(days=median_gap), "refill_chain_lapsed"
                else:
                    nxt_enc = next((t for t, _iso, _eid in self.enc_timeline if t > last["t"]), None)
                    end_dt, rule = nxt_enc, "single_request_next_encounter"
                # a new run for the same ingredient always closes the previous one at its start
                if next_run_start is not None and (end_dt is None or end_dt > next_run_start):
                    end_dt, rule = next_run_start, "next_request_different_strength"
                # An inferred end beyond the end of the record is indistinguishable from "still on it":
                # leave it open rather than invent a stop on the last encounter date.
                if last["mr"].get("status") != "active" and self.enc_timeline and \
                        (end_dt is None or end_dt > self.enc_timeline[-1][0]):
                    end_dt, rule = None, "completed_but_lapse_beyond_record_left_open"
                end_rule[rule] += 1
                dosage = (last["mr"].get("dosageInstruction") or [None])[0]
                parsed = last["parsed"]
                segments.append({
                    "start": date_only(start_iso),
                    "end": date_only(end_dt.isoformat()) if end_dt else None,
                    "dose": parsed["dose"],
                    "route": route_for_form(parsed["form"]),
                    "frequency": frequency_text(dosage),
                    "_rx": code_of(last["cc"]),
                    "_reason": [self.refkey(x) for r in run for x in (r["mr"].get("reasonReference") or [])],
                })
            base = f"med_{slugify(ingredient)}" + ({"INJ": "_inj", "SC": "_inj", "INH": "_inh", "TD": "_td",
                                                     "OPH": "_oph", "TOP": "_top", "NASAL": "_nasal"}.get(route, ""))
            mid = base
            n = 2
            while mid in used_ids:
                mid = f"{base}_{n}"
                n += 1
            used_ids.add(mid)
            reasons = sorted({rr for sg in segments for rr in sg["_reason"] if rr})
            latest_rx = segments[-1]["_rx"]
            for sg in segments:
                sg.pop("_rx"); sg.pop("_reason")
            courses.append({
                "id": mid,
                "patient_id": self.pid,
                "name": display_name,
                "code": {"system": "RxNorm", "value": latest_rx} if latest_rx else None,
                "segments": segments,
                "status": "accepted",
                "provenance": {"source": "fhir_import"},
                "_reasons": reasons,
            })
            if len(segments) > 1:
                self.report["medications"]["multi_segment_courses"].append(
                    f"{mid}: " + " -> ".join(f"{sg['dose']} ({sg['start']}..{sg['end'] or 'ongoing'})" for sg in segments))
        courses.sort(key=lambda c: c["segments"][0]["start"] or "")
        self.med_reasons = {c["id"]: c.pop("_reasons") for c in courses}
        self.out["medications"] = courses
        self.report["medications"]["courses"] = len(courses)
        self.report["medications"]["segments"] = sum(len(c["segments"]) for c in courses)

    # ------------------------------------------------------------------ links
    def import_links(self):
        n = 0
        created = now_iso()

        def add(frm, to, ltype):
            nonlocal n
            n += 1
            self.out["links"].append({
                "id": f"lnk_{n:04d}", "from": frm, "to": to, "type": ltype, "status": "accepted",
                "provenance": {"source": "fhir_import"}, "created_at": created,
            })

        obs_codes = Counter(o["code"]["value"] for o in self.out["observations"] if o["code"]["system"] == "LOINC")
        mon_report = {"created": [], "missing_series": []}
        for pid, cat in self.problem_categories.items():
            for code in MONITORS_TABLE.get(cat, []):
                if obs_codes.get(code):
                    add(f"LOINC:{code}", pid, "monitors")
                    mon_report["created"].append(f"LOINC:{code} ({FRIENDLY_NAMES.get(code, code)}, n={obs_codes[code]}) -> {pid} [{cat}]")
                else:
                    mon_report["missing_series"].append(f"{pid} [{cat}] has no observations for {code} ({FRIENDLY_NAMES.get(code, code)})")
        self.report["monitors"] = mon_report

        treats = 0
        for mid, reasons in self.med_reasons.items():
            for ref in reasons:
                pid = self.prob_ids.get(ref)
                if pid:
                    add(mid, pid, "treats")
                    treats += 1
                else:
                    self.report["warnings"].append(f"{mid} reasonReference {ref} is not an imported problem (filtered or missing)")
        self.report["treats_links"] = treats

    # -------------------------------------------------------------- unmapped
    def count_unmapped(self):
        mapped = {"Patient", "Encounter", "Condition", "Observation", "MedicationRequest", "DocumentReference", "DiagnosticReport"}
        c = Counter(r["resourceType"] for r in resources(self.bundle))
        self.report["unmapped_resources"] = {k: v for k, v in sorted(c.items()) if k not in mapped}
        self.report["source_resource_counts"] = dict(sorted(c.items()))

    # ------------------------------------------------------------ self-check
    def self_check(self):
        ids = set()
        for key in ("problems", "observations", "medications", "encounters", "notes", "links"):
            for e in self.out[key]:
                if e["id"] in ids:
                    self.report["warnings"].append(f"duplicate id {e['id']}")
                ids.add(e["id"])
        obs_codes = {o["code"]["value"] for o in self.out["observations"]}
        for l in self.out["links"]:
            frm = l["from"]
            if frm.startswith("LOINC:"):
                if frm[6:] not in obs_codes:
                    self.report["warnings"].append(f"{l['id']} from {frm} has no observations")
            elif frm not in ids:
                self.report["warnings"].append(f"{l['id']} from {frm} does not exist")
            if l["to"] not in ids:
                self.report["warnings"].append(f"{l['id']} to {l['to']} does not exist")
        for c in self.out["medications"]:
            segs = c["segments"]
            for a, b in zip(segs, segs[1:]):
                if a["end"] is None or (b["start"] and a["end"] > b["start"]):
                    self.report["warnings"].append(f"{c['id']} segments overlap: {a} / {b}")
        for n in self.out["notes"]:
            if n["encounter_id"] and n["encounter_id"] not in ids:
                self.report["warnings"].append(f"{n['id']} encounter {n['encounter_id']} missing")

    # ---------------------------------------------------------------- report
    def finalize(self):
        o = self.out
        self.report["counts"] = {
            "patient": 1, "problems": len(o["problems"]), "observations": len(o["observations"]),
            "medications": len(o["medications"]), "encounters": len(o["encounters"]), "notes": len(o["notes"]),
            "links": len(o["links"]), "insights": 0,
        }
        enc_t = sorted(e["time"] for e in o["encounters"] if e["time"])
        obs_t = sorted(x["effective_time"] for x in o["observations"] if x["effective_time"])
        self.report["date_range"] = {
            "encounters": [date_only(enc_t[0]), date_only(enc_t[-1])] if enc_t else None,
            "observations": [date_only(obs_t[0]), date_only(obs_t[-1])] if obs_t else None,
        }
        self.report["problems"] = [
            f"{p['id']} {p['name']} [{p['status']}] {p['onset_date']}..{p['resolved_date'] or ''}"
            + (f" <{self.problem_categories[p['id']]}>" if p["id"] in self.problem_categories else "")
            for p in o["problems"]
        ]
        self.report["observation_codes"] = {
            f"{sysname}:{code} {FRIENDLY_NAMES.get(code) or name}": n
            for (sysname, code, name), n in sorted(
                Counter((x["code"]["system"], x["code"]["value"], x["name"]) for x in o["observations"]).items())
        }
        self.report["medications"]["end_inference"] = dict(self.report["medications"]["end_inference"])
        self.report["unmapped_observations"] = dict(self.report["unmapped_observations"])
        self.report["excluded_observations"] = dict(self.report["excluded_observations"])

    def run(self):
        self.import_patient()
        self.import_encounters()
        self.import_problems()
        self.import_observations()
        self.import_notes()
        self.import_medications()
        self.import_links()
        self.count_unmapped()
        self.self_check()
        self.finalize()
        return self.out, self.report


def print_summary(report: dict):
    p = print
    p(f"\n=== Import summary for {report['patient_id']} ===")
    p("Entity counts: " + ", ".join(f"{k}={v}" for k, v in report["counts"].items()))
    dr = report["date_range"]
    p(f"Date range: encounters {dr['encounters']}, observations {dr['observations']}")
    p("\nProblems:")
    for line in report["problems"]:
        p("  " + line)
    p("\nMonitors links created:")
    for line in report["monitors"]["created"] or ["  (none)"]:
        p("  " + line)
    if report["monitors"]["missing_series"]:
        p("Monitors table codes with no observations (no link made):")
        for line in report["monitors"]["missing_series"]:
            p("  " + line)
    p(f"'treats' links from reasonReference: {report.get('treats_links', 0)}")
    m = report["medications"]
    p(f"\nMedications: {m['courses']} courses, {m['segments']} segments "
      f"({m['requests_merged_into_segments']} refill requests merged); end-date inference: {m['end_inference']}")
    for line in m["multi_segment_courses"]:
        p("  multi-segment: " + line)
    p(f"\nObservations by code ({len(report['observation_codes'])} distinct):")
    for k, v in report["observation_codes"].items():
        p(f"  {k}: {v}")
    p(f"Creatinine 38483-4 values re-coded to 2160-0: {report['creatinine_recoded']} (opt-in via --merge-creatinine-codes)")
    p(f"\nNotes: {report['counts']['notes']} imported from DocumentReference; "
      f"{report['duplicate_notes']} DiagnosticReport note copies skipped; "
      f"{report['lab_panel_reports']} lab-panel DiagnosticReports covered by member observations")
    p(f"\nFiltered Conditions (social history, {len(report['filtered_conditions'])}): "
      + ", ".join(sorted(set(report["filtered_conditions"]))))
    if report.get("excluded_observations"):
        p("\nObservations excluded on purpose (see flagged decisions):")
        for k, v in report["excluded_observations"].items():
            p(f"  {k}: {v}")
    p("\nObservations NOT imported (non-numeric value):")
    for k, v in report["unmapped_observations"].items() or {"(none)": ""}.items():
        p(f"  {k}: {v}")
    p("\nFHIR resource types with no schema mapping (counted, not imported):")
    for k, v in report["unmapped_resources"].items():
        p(f"  {k}: {v}")
    if report["warnings"]:
        p(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"][:30]:
            p("  " + w)
        if len(report["warnings"]) > 30:
            p(f"  ... {len(report['warnings']) - 30} more in the report file")
    p("\nFlagged schema interpretations (need team agreement):")
    for i, d in enumerate(report["flagged_decisions"], 1):
        p(f"  {i}. {d}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle")
    ap.add_argument("--id", help="patient id (default pt_<first 8 hex of Synthea uuid>)")
    ap.add_argument("--out", default="data/patients")
    ap.add_argument("--keep-findings", action="store_true", help="import '(finding)'/'(situation)' Conditions too")
    ap.add_argument("--merge-creatinine-codes", action="store_true", help="re-code whole-blood creatinine 38483-4 to 2160-0")
    ap.add_argument("--keep-panel-egfr", action="store_true", help="keep eGFR values from serum-creatinine panels (default: excluded)")
    args = ap.parse_args()

    bundle = load_bundle(args.bundle)
    fhir_patient = next(resources(bundle, "Patient"))
    pid = args.id or f"pt_{fhir_patient['id'].replace('-', '')[:8]}"
    if not pid.startswith("pt_"):
        print("--id must start with pt_", file=sys.stderr)
        return 2

    out, report = Importer(bundle, pid, args.keep_findings, args.merge_creatinine_codes, args.keep_panel_egfr).run()
    report["source_bundle"] = str(args.bundle)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{pid}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    (out_dir / f"{pid}.import-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print_summary(report)
    print(f"\nWrote {out_dir / (pid + '.json')} and {out_dir / (pid + '.import-report.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
