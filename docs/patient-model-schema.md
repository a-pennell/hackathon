# Patient Model Schema — Hackathon Build Spec

One shared data model for all three workstreams. FHIR gets flattened *into* this; NLP extracts *into* this; the UI renders *from* this; reasoning consumes *from* this. Nobody builds against raw FHIR.

**Conventions**
- All timestamps ISO 8601 with timezone.
- IDs are prefixed strings: `pt_`, `prob_`, `obs_`, `med_`, `enc_`, `note_`, `lnk_`, `ins_`.
- Anything written by AI enters as `status: "proposed"` and only renders in the canonical chart after a human sets it to `"accepted"`. Proposed items live in the review queue.
- Storage: one JSON file (or SQLite) per patient is fine. No FHIR server.

---

## 1. Patient

```json
{
  "id": "pt_001",
  "name": "Marta Alvarez",
  "dob": "1954-03-17",
  "sex": "F"
}
```

Keep it minimal. Demographics beyond this add nothing to the demo.

## 2. Problem

The organizing unit of the whole chart.

```json
{
  "id": "prob_ckd",
  "patient_id": "pt_001",
  "name": "Chronic kidney disease, stage 3",
  "code": { "system": "ICD-10", "value": "N18.3" },
  "status": "active",
  "onset_date": "2021-06-01",
  "resolved_date": null,
  "provenance": { "source": "fhir_import" }
}
```

- `status`: `active` | `resolved` | `proposed` (NLP suggested a new problem, not yet accepted).
- `code` optional — don't burn hackathon time on coding accuracy.

## 3. Observation (labs + vitals)

Point-in-time, always timestamped. This is the raw material for trends.

```json
{
  "id": "obs_0042",
  "patient_id": "pt_001",
  "code": { "system": "LOINC", "value": "2160-0" },
  "name": "Creatinine",
  "value": 1.8,
  "unit": "mg/dL",
  "reference_range": { "low": 0.6, "high": 1.2 },
  "effective_time": "2026-08-30T09:15:00-04:00",
  "status": "accepted",
  "provenance": { "source": "fhir_import" }
}
```

An NLP-extracted observation differs only in provenance and status:

```json
{
  "status": "proposed",
  "provenance": {
    "source": "nlp_extraction",
    "note_id": "note_0007",
    "quote": "Cr today 1.8, up from 1.3 last month",
    "model": "extractor-v1",
    "confidence": 0.94
  }
}
```

**Rule:** every extracted item carries `note_id` + verbatim `quote`. This is what makes suggestions trustworthy and reviewable.

## 4. MedicationCourse — intervals, not list entries

One course per drug, made of dose segments. This is what lets meds render as horizontal bands under a lab curve.

```json
{
  "id": "med_lisinopril",
  "patient_id": "pt_001",
  "name": "Lisinopril",
  "code": { "system": "RxNorm", "value": "29046" },
  "segments": [
    { "start": "2022-01-10", "end": "2024-03-02", "dose": "10 mg", "route": "PO", "frequency": "daily" },
    { "start": "2024-03-02", "end": null, "dose": "20 mg", "route": "PO", "frequency": "daily" }
  ],
  "status": "accepted",
  "provenance": { "source": "fhir_import" }
}
```

- `end: null` = ongoing.
- A dose change = close one segment, open the next (same timestamp).
- A stopped med = last segment has an `end`. The course itself never gets deleted — history is the point.
- Synthea emits `MedicationRequest` resources; merge them by RxNorm code into one course and infer segments from authoredOn/status (see §8).

## 5. Encounter

```json
{
  "id": "enc_0012",
  "patient_id": "pt_001",
  "time": "2026-08-30T09:00:00-04:00",
  "type": "office visit",
  "summary": "Follow-up, CKD and HTN"
}
```

Renders as markers on the timeline. Keep it thin.

## 6. Note

```json
{
  "id": "note_0007",
  "patient_id": "pt_001",
  "encounter_id": "enc_0012",
  "time": "2026-08-30T09:40:00-04:00",
  "author": "Dr. Chen",
  "text": "...free text..."
}
```

Input to the NLP pipeline; anchor for all extraction provenance.

## 7. Link — the core primitive

Relationships are first-class rows, not foreign keys. This is deliberate: one lab can be relevant to two problems, and each link carries its own provenance and review status.

```json
{
  "id": "lnk_0301",
  "from": "obs_0042",
  "to": "prob_ckd",
  "type": "relevant_to",
  "status": "accepted",
  "provenance": { "source": "nlp_extraction", "note_id": "note_0007", "confidence": 0.91 },
  "created_at": "2026-08-30T09:41:12-04:00"
}
```

**Link types (keep to five):**

| type | from → to | meaning |
|---|---|---|
| `relevant_to` | observation → problem | this result bears on this problem |
| `treats` | medication → problem | why this drug is on board |
| `evidence_for` | observation/note → problem | supports the problem's existence (esp. proposed problems) |
| `suspected_cause` | medication/problem → observation/problem | the reasoning layer's money link |
| `monitors` | observation-code → problem | "creatinine is a tracked series for CKD" — drives which curves the problem timeline shows |

The problem-scoped timeline view = "give me everything linked to `prob_ckd`, plotted on one axis."

## 8. FHIR → model mapping (import script)

| Synthea FHIR resource | maps to |
|---|---|
| `Patient` | Patient |
| `Condition` | Problem (+ auto-link `monitors` for common problem→lab pairs, hardcoded table is fine) |
| `Observation` | Observation |
| `MedicationRequest` | MedicationCourse (group by RxNorm; each request opens/extends a segment; `stopped`/`completed` closes it) |
| `Encounter` | Encounter |
| `DocumentReference` / `DiagnosticReport` | Note (Synthea's notes are sparse — you'll write the demo notes by hand) |

Import everything as `status: "accepted"` with `provenance.source: "fhir_import"`.

## 9. TrendSummary — what the reasoning layer consumes

Computed on demand from observations + med segments. **Not stored.** One function: `trend(patient_id, loinc_code, window)`.

```json
{
  "patient_id": "pt_001",
  "code": "2160-0",
  "name": "Creatinine",
  "window": { "start": "2026-05-01", "end": "2026-08-30" },
  "n_points": 5,
  "latest": { "value": 1.8, "time": "2026-08-30" },
  "baseline": { "value": 1.3, "time": "2026-05-14" },
  "delta_abs": 0.5,
  "delta_pct": 38.5,
  "slope_per_week": 0.031,
  "direction": "rising",
  "ref_range_crossing": { "crossed": "high", "at": "2026-07-02" },
  "events_in_window": [
    { "kind": "med_segment_start", "med_id": "med_ibuprofen", "name": "Ibuprofen 600 mg", "time": "2026-06-20" }
  ]
}
```

`events_in_window` is the co-registration payload: every med start/stop/dose-change inside the window. Feed the reasoning prompt TrendSummaries — never raw value lists — and you get outputs like *"creatinine up 38% over 3 months; rise begins after ibuprofen start"* instead of *"creatinine is elevated."*

## 10. Insight — reasoning output

```json
{
  "id": "ins_0005",
  "patient_id": "pt_001",
  "problem_id": "prob_ckd",
  "statement": "Creatinine has risen 38% over 3 months. The rise begins shortly after ibuprofen was started. NSAID use in CKD may be contributing; metformin dosing may also need review at this eGFR.",
  "evidence": ["obs_0042", "obs_0038", "med_ibuprofen", "med_metformin"],
  "suggested_action": "Consider discontinuing ibuprofen; reassess metformin dose.",
  "status": "proposed",
  "provenance": { "source": "reasoning", "model": "reasoner-v1", "trend_codes": ["2160-0"] },
  "created_at": "2026-08-30T09:42:00-04:00"
}
```

Every id in `evidence` must exist — the UI renders them as tap-through citations. An insight with no inspectable evidence doesn't ship.

---

## Saturday-morning definition of done

1. This file agreed on (argue now, not Sunday).
2. Import script turns one Synthea bundle into one patient JSON in this shape.
3. One golden patient loaded whose history actually tells a story (multimorbid, 3+ years, a lab series with real movement).
4. Two hand-written demo notes ready for the extraction pipeline.
