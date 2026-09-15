# PRD-08 — The compiler: `compileContext` and views as data

**Stage:** 3 (derived views). Worth exactly what Stage 1 made it worth (`ontology-evolution.md` §7.1).
**Depends on:** PRD-01, 03; PRD-07 for rollups; PRD-09 for open loops.
**Schema:** v2 §0 (views are a kind), §9 (documents carry `view_spec_id`).

## Why

The hackathon already has five compiled views (brief, referral, orders context, coding, trail) and
each builds its own context ad hoc. The docs name this as one function under different arguments:
`compileContext(patient, task, actor, purpose, permissions, horizon, budget)` → consequential
state, courses and therapies, findings and trajectories, what changed, goals/plans/open work,
unresolved uncertainty, source objects with provenance, scoped to what this actor may see. It is a
**view**: recomputed, never edited, no id, deletable without loss; "the compiled summary is not the
patient model" (`ontology-evolution.md` §7.1; paper §6.4, B.3; site "What Becomes an Entity"). View
definitions are data; adding a view means authoring a spec (paper B.3). The rival-architecture
analysis makes the compiler the part that is safe to build under every future.

## Goal

One compiler, a registry of view specs, summary stacks with invalidation, prompt-cache-stable
packets, and citations on every line. `brief.py`, `compose.py`, the orders context and the coding
panel become specs.

## Scope

**In**
1. `ehr/compiler.py::compile_context(patient_id, task, actor, purpose, permissions, horizon, budget)`
   returning a structured packet: sections (state, courses, therapies, findings, changes, goals,
   open_work, uncertainty), each line `{text, cites: [{object_id, event_id, span?}]}`, plus
   `version` (last event id + spec hash) so any proposal can say what it looked at.
2. **Graph walk selection** (B.3): anchors from the task (named problems, meds → indications,
   message topics); weighted frontier by edge type (causal/contraindication decay slowly,
   incidental fast); per node the deepest summary stratum that fits the remaining budget; raw
   events only where recency or precision demands (last three BPs, exact doses); positional
   ordering (task + key context at start and end, background mid-packet); stable-prefix-first with
   content-hashed strata for cache hits.
3. **Permissions applied inside the compiler**: a packet never contains what its actor may not see;
   the private-process section (PRD-06) and Part 2 material (PRD-12) are excluded by storage class,
   and a bounded-search report says what was *not* searched.
4. **View spec registry** (`ehr/views/*.json`): `{id, audience, purpose, budget, register, sections,
   ordering, renderer}`. Ship: `clinician_glance` (the cold-open brief: active focuses by acuity,
   deltas since this reader last looked, open loops, pending results, stale risks; "under ten
   seconds"), `what_changed(since)`, `problem_arc`, `referral_letter`, `discharge_summary`,
   `patient_summary` (plain language), `billing_artifact` (template, no model), `legacy_soap`,
   `context_packet` (machine-facing), `encounter_agenda` (multi-context visit as one agenda).
5. **Summary stacks** (PRD-03): regeneration jobs consume the stale queue, prompt with the
   script-shaped template (predisposing context → presentation → trajectory → current state), must
   emit inline citations to event ids; a sentence without a resolvable citation fails validation
   and stays uncommitted. Dependency map problem → strata → cached views drives invalidation.
6. **Two rendering paths per spec**: deterministic (rules + templates; billing artifact, glance,
   agenda) and model-written (referral, patient summary, narrative stratum), both recorded and
   replayable like today. Unattested state is never cited in billing, referral or order views.
7. **Consumption index** (derived): which views, orders and documents consumed which claim, so a
   retraction can recall them (WF·07). Recall re-runs affected checks and flags affected documents
   as WorkItems.
8. **Ask the record** (WF·02, bounded): a narrative search over `narrative.received` events with a
   bounded-search report (documents searched, span of years, sources not searched); results are
   evidence, never claims; RAG is the fallback for "where was this discussed", not the index.
9. APIs: `GET /api/patients/{pid}/views/{spec}?…`, `GET /api/patients/{pid}/changes?since=`,
   `POST /api/patients/{pid}/ask`.

**Out**
- Learned relevance weights; edge weights are a table.
- Population views (PRD-11 later).

## Design rules (binding)

- A view never gets an id a user returns to, a URL of its own, an edit, or a claim the graph does
  not already support. Documents are views frozen by a sign event.
- Every line cites. The UI shows the stamp and opens evidence in one tap; no hover-only provenance.
- Each spec carries a budget as a design target; the compiler earns every included line.
- Staleness is localised: a stale stratum is flagged on screen, not hidden.

## Acceptance

1. `clinician_glance` for pt_001 renders in under 200 ms deterministic, cites every line, fits its
   budget, and lists open loops first.
2. `what_changed(since=last visit)` shows the creatinine delta, the naproxen start, and the pending
   proposal count, nothing else.
3. The referral letter is produced from the `referral_letter` spec and matches today's recorded
   output on section headings and citations.
4. Retracting the naproxen `caused_by` edge flags the referral document and the orders that cited it.
5. A packet compiled for a `staff` actor omits the risk object and the private-process section and
   says so.
6. The billing artifact is generated with zero model calls.

## Estimate

Six days: two for the compiler core and walk, one for specs and registry, one for summary stacks,
one for consumption/recall, one for ask-the-record.
