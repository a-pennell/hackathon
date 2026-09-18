# CLAUDE.md — Problem-Oriented EHR (Hackathon)

## What we're building

A patient-modeled, problem-oriented EHR where the chart monitors itself and the note is assembled from
what the chart already knows.

The demo patient is **Jeane Casandra Lueilwitz (`pt_002`)**, 55F, three active problems: essential
hypertension (`prob_0007`), type 2 diabetes (`prob_0009`), hypertriglyceridemia (`prob_0011`), on
hydrochlorothiazide 25 mg and metformin 500 mg since 2022. The visit is a dictated follow-up on
15 Sep 2026 (`enc_c002`, `data/notes/note_demo_102.json`, Dr. Chen).

The arc: the dictation is read, findings land on the problems they touch, and one decision moment comes
up — daily over-the-counter ibuprofen since May, with a new urine albumin/creatinine of 48 (up from 18)
and BP above goal on HCTZ alone. The NSAID is a suspected cause; the plan stops it, starts lisinopril,
switches metformin to extended-release. Albuminuria and low back pain enter as new problems. The hero
views are the standing gate (which problems are off course before you open one), the problem's seven
questions with labs and medication courses on one axis, and the visit note compiled from the record.

`pt_001` (Willie Klocko) is the Synthea-imported patient; it stays for import and extraction-replay
tests, not for the demo.

Optimize for the 3-minute demo, not generality.

## Stack

Python 3.11+ + FastAPI backend (reads per-patient JSON from /data); React + Vite frontend; import/analysis
scripts in /scripts are stdlib-only Python. No FHIR server, no database.

One server runs all three fronts: `python3 -m uvicorn backend.main:app --reload --port 8000`.

- `/` — v1, the full workbench (`frontend/`). Queue, timeline, notes.
- `/v2/?patient=pt_002` — **the demo** (`v2/`). Gate, seven questions, one signature. See `v2/README.md`.
- `/v3/?patient=pt_002` — the visit as one surface (`v3/`): the dictation plays, findings land, the note
  grows, one signature closes it. See `v3/README.md`.

Each front's `dist` is committed; rebuild with `npm run build` in its own directory (v2/v3 `node_modules`
are symlinks to `frontend/node_modules`). Model calls are recorded — the demo runs offline from
`data/proposed/**/*.raw.json`; live calls need `ANTHROPIC_API_KEY` exported in the terminal that starts
uvicorn.

## The data model is law

**Read `docs/patient-model-schema.md` before writing any code that touches patient data.** All entities,
IDs, link types, and provenance shapes are defined there. Do not invent fields or alternate shapes; if the
schema needs to change, stop and flag it — schema changes require team agreement, not a unilateral edit.
Proposed additions are listed under "Schema additions proposed" in `README.md` and wait for sign-off.

## Non-negotiables

1. **Nothing AI-generated writes directly to the chart.** Every NLP-extracted or reasoned item enters with
   `status: "proposed"` and only renders in the canonical chart after a human accepts it. Proposed items go
   to the review queue.
2. **Provenance always.** Every extracted item carries `note_id` + the verbatim `quote` it came from. Every
   Insight's `evidence` array contains only IDs that actually exist.
3. **Medications are interval courses, not list entries.** Dose changes close one segment and open the next.
   Never delete a course; stopped meds keep their history.
4. **TrendSummary is computed on demand, never stored.** The reasoning layer consumes TrendSummaries (deltas,
   slopes, events_in_window), never raw value arrays.
5. **All timestamps ISO 8601 with timezone. All IDs prefixed** (`pt_`, `prob_`, `obs_`, `med_`, `enc_`,
   `note_`, `lnk_`, `ins_`).
6. **Only the visit note is signed.** Everything else has its own verb: proposals are accepted or rejected,
   insights agreed or dismissed, detected changes noted, plan lines added. The signature attests them, and
   what it attests is listed before it is given.

## Working conventions

- Small, frequent commits; one work chunk per Claude Code task.
- Golden patient bundles live in `/data`. Don't regenerate them mid-hackathon without telling the team —
  everyone's demos depend on the same data.
- Hand-written demo notes live in `/data/notes/`. These are curated demo assets; don't overwrite them.
- **Never commit `data/patients/*.json` or non-raw queue files.** They are the live chart; a demo run dirties
  them and the reset snapshot is taken from the clean state. Recorded model responses (`*.raw.json`) are the
  exception — those are assets and belong in git.
- Tests never read the live chart: `tests/conftest.py` builds a clean copy and points `EHR_DATA_DIR` at it.
- Other sessions share this working tree. Commit only the files you touched, and leave the chart as you
  found it.
- No FHIR server. The import script flattens Synthea FHIR bundles into our schema once; everything downstream
  reads our JSON.
- Prefer boring, working code over clever abstractions. This ships Sunday.
