# CLAUDE.md — Problem-Oriented EHR (Hackathon)

## What we're building

A weekend hackathon prototype: a patient-modeled, problem-oriented EHR. Demo arc: a clinician opens a multimorbid synthetic patient (CHF + CKD + T2DM), a new free-text note arrives, the system extracts findings, links each to an existing problem or proposes a new one, and surfaces one decision moment (e.g., rising creatinine → reconsider metformin, NSAID as suspected cause). The hero view is a problem-scoped co-registered timeline: labs plotted with medication intervals as bands and encounters as markers, filtered to one problem.

Optimize for the 3-minute demo, not generality.

## Stack

Python 3.11+ + FastAPI backend (reads per-patient JSON from /data); React + Vite frontend; import/analysis scripts in /scripts are stdlib-only Python. No FHIR server, no database.

## The data model is law

**Read `docs/patient-model-schema.md` before writing any code that touches patient data.** All entities, IDs, link types, and provenance shapes are defined there. Do not invent fields or alternate shapes; if the schema needs to change, stop and flag it — schema changes require team agreement, not a unilateral edit.

## Non-negotiables

1. **Nothing AI-generated writes directly to the chart.** Every NLP-extracted or reasoned item enters with `status: "proposed"` and only renders in the canonical chart after a human accepts it. Proposed items go to the review queue.
2. **Provenance always.** Every extracted item carries `note_id` + the verbatim `quote` it came from. Every Insight's `evidence` array contains only IDs that actually exist.
3. **Medications are interval courses, not list entries.** Dose changes close one segment and open the next. Never delete a course; stopped meds keep their history.
4. **TrendSummary is computed on demand, never stored.** The reasoning layer consumes TrendSummaries (deltas, slopes, events_in_window), never raw value arrays.
5. **All timestamps ISO 8601 with timezone. All IDs prefixed** (`pt_`, `prob_`, `obs_`, `med_`, `enc_`, `note_`, `lnk_`, `ins_`).

## Working conventions

- Small, frequent commits; one work chunk per Claude Code task.
- Golden patient bundles live in `/data`. Don't regenerate them mid-hackathon without telling the team — everyone's demos depend on the same data.
- Hand-written demo notes live in `/data/notes/`. These are curated demo assets; don't overwrite them.
- No FHIR server. The import script flattens Synthea FHIR bundles into our schema once; everything downstream reads our JSON.
- Prefer boring, working code over clever abstractions. This ships Sunday.
