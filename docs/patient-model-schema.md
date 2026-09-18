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

### 4.1 Extraction shape — a course is a name and a segment

What the extractor is asked to emit for a medication mirrors §4 rather than flattening it: `{ref, quote, name,
segment: {dose, route, frequency, start, end}, existing_med_id, change, treats_problem_refs}`. This is not only
tidiness. A strict output schema compiles to a grammar whose cost is dominated by the object with the most
properties — roughly `2^n` for an object whose properties may arrive in any order — and twelve flat properties on one
course was large enough for the API to refuse the request outright (*"the compiled grammar is too large"*). Nesting
turns one `2^12` into a `2^7` plus a `2^5`.

Readers accept both shapes: every extraction recorded before this change is flat
(`ehr/extract.py::_flatten_segment`).

### 7.1 `provenance.asserted` — did the passage say it, or did we?

An extracted item's provenance may carry `"asserted": true | false`: the extractor's own answer, given while it had the
passage in front of it, to whether that passage *itself* makes the claim. It applies to the two kinds that assert
something a clinician would otherwise have to check — a `suspected_cause` link, and a proposed Problem (with its
`evidence_for` link) — and is absent everywhere else.

```json
"provenance": { "source": "nlp_extraction", "note_id": "note_0007", "quote": "Daily NSAID use since May, likely contributing.",
                "asserted": true, "confidence": 0.91 }
```

`true` means a clinician reading that passage alone would agree it says so. `false` means the extractor drew the line
itself, or the passage hedges, or the patient rather than the clinician raised it, or — most importantly — the passage
*denies* it. A denial is always `false`.

It is a judgement, not a fact about the text, so it is written where judgements go: provenance, beside `confidence`,
never on the item. It is optional; a reader that does not find it must fall back to its own rule, because every
extraction recorded before this field exists lacks it.

**Why it matters.** Consumers may use it to decide what a clinician never has to look at — `v3` accepts an `asserted`
cause under the visit's signature with no review — so a wrong `true` is attested without anyone seeing it, while a
wrong `false` costs one click. Readers should therefore treat absence and uncertainty as `false`, and should keep a
check for outright denial even when the field says `true` (`v3/api.py::DENIAL`).

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

## 11. Signed Corrections And Amendments

The provider correction workflow adds these optional fields. Existing charts need no migration.

- `corrections`: append-only signed events with a `correction_` ID, item ID and kind, action,
  reason, author (`by`), signature time (`at`), effective date, complete `before`/`after`
  snapshots, archived dependent entries, and related entries retained for separate review.
- `archived_items`: `{kind, item, correction_id}` rows retaining the complete original entry
  and signature. Entries marked in error, canceled orders, and ended plans leave current
  chart collections but remain in this archive and the record. Medication stops instead
  close a segment in place; they do not archive a valid course.
- `amendments` on signed notes/documents: signed `{id, by, at, reason, text}` additions.
  Original text and signatures remain unchanged. Amendment text does not mutate clinical
  chart entries or orders.
- `medication_effect` on signed medication-change orders, note changes, and clinician plans:
  `{med_id, before, after}`, where before/after are complete segment arrays. Reversal requires
  that the current segments still match `after`. Legacy changes without snapshots cannot
  be automatically reversed.
- Corrected queue entries retain their original review stamp and gain `correction_id` and
  terminal status `entered_in_error`, `cancel`, `end_plan`, or `superseded`. They cannot be
  re-signed. Dependent links/insights leave current reasoning when evidence is marked in
  error; related orders and documents require separate provider decisions.

Every correction requires a matching chart/queue revision from a prior preview. The local
JSON prototype does not dispatch cancellations to outside pharmacies or laboratories.

## 12. Draft Synchronization

Visit-note queues retain `source_sections`, the last chart-generated sections reviewed
by the provider. Each section has a stable `key` built from its source, problem, and
section role. Provider wording is stored separately in the document's sections.
Reopening or recompiling an existing draft never replaces that wording.

Draft reads return a computed `updates_count` and `draft_revision`. Update previews
compare the current chart with `source_sections`, preserving edits to other sections.
Changes to a provider-edited section require an explicit keep, replace, or manually
merged resolution. Applying updates advances the source baseline and saves the draft;
it does not change the chart. Saves and update applications check revisions, and signing
rejects unreviewed chart updates. Signed documents remain immutable except for amendments.

Explicitly accepted workspace representations and signed clinician assessments are stored
as accepted Insights with optional `kind: representation | assessment`, clinician provenance,
the full statement, an empty suggested action, evidence IDs, and an encounter-scoped review
stamp. Updates append a new signed version. The visit draft uses the latest clinician
assessment for that encounter, falling back to its latest accepted representation, and
preserves the full authored text rather than truncating it to a generated summary.

## 13. Plan Destinations

Clinician intent accepts `destination: note | treatment_plan | both`. The form defaults to
`note`; legacy API/CLI callers without a destination retain `both` behavior.

- `note`: an unsigned authoring source in `note_plan_items`, with ID, patient/problem/
  encounter IDs, kind, text, clinician provenance, and creation time. It is not a signed
  Plan, order, or medication change. It appears only in that encounter's Note: Plan.
- `treatment_plan`: an accepted Plan with the selected destination and encounter review
  stamp. Diagnostic/referral items create orders; explicitly selected medication changes
  apply to the chart. None of these actions is added to Note: Plan by the compiler.
- `both`: the same signed treatment action, also selected for Note: Plan once. The note
  text remains unsigned until the provider signs the visit note.

Orders inherit their originating Plan's destination. Medication event compilation excludes
the before/after event delta of treatment-only changes without hiding unrelated changes.
Plans without a destination retain their existing note inclusion behavior.

The API creates a draft if needed. Existing drafts expose additions through the reviewed
update workflow, preserving provider edits and removals. Note-only source records are
authoring history, not standalone chart assertions; the signed document is the final text.
Removing text from a draft does not remove a treatment plan or order. Note/both additions
to an already signed visit note are rejected before any chart action; use an amendment
or explicitly choose treatment-plan-only instead.

The UI sends the active encounter ID explicitly. An encounter not yet ingested is rejected
instead of silently routing new text or treatment decisions to an older visit.

## Saturday-morning definition of done

1. This file agreed on (argue now, not Sunday).
2. Import script turns one Synthea bundle into one patient JSON in this shape.
3. One golden patient loaded whose history actually tells a story (multimorbid, 3+ years, a lab series with real movement).
4. Two hand-written demo notes ready for the extraction pipeline.
