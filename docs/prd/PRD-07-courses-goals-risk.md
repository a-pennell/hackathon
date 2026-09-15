# PRD-07 — Courses of care, goals, risk, and the derived agenda

**Depends on:** PRD-01, 02, 03. **Unblocks:** PRD-06 (context panel in the composer), PRD-08 (brief
reads rollups), PRD-11 (compliance agenda in Today).
**Schema:** v2 §6 (CareContext), §7 (Goal, RiskAssessment).

## Why

The hackathon has problems and encounters but nothing between them: no bounded arc of management,
no goal that reports its own progress, no risk object with an as-of date, no computed "what needs
attention." Those are the capabilities an encounter-based system structurally cannot provide
(`longitudinal-capabilities.md` §2.6–2.8, 2.10) and the ones ADR 0002/0003 specify most precisely,
with eight binding guardrails. The first market (non-prescribing mental health) makes the risk
object the flagship, and PT is the second proven profile.

## Goal

One canonical CareContext with type variants, a profile registry that owns per-type behaviour, goals
with derived progress, an append-only risk history with staleness, and a compliance agenda computed
from structured state.

## Scope

**In**
1. **CareContext** object and verbs (`openCareContext`, `closeCareContext`, `dischargeCareContext`)
   with `kind: course | acute_episode`, optional `parent_id`, `addresses[] → focus`.
2. **Profile registry** (`ehr/context_profiles.py`): per type, compliance rules (functions over
   structured state), note pack sections, closure criteria, billing flag, display labels ("Plan of
   care" vs "Treatment plan"). Ship `PRIMARY_CARE_FOCUSED`, `CHRONIC_CARE_PROGRAM` (pt_001's CKD/CHF/
   T2DM arc), `MENTAL_HEALTH_CASE` (risk + treatment-plan review), `PT_REHAB` (visits used, recert
   window, progress report due, KX threshold). Lifecycle for all: open → assess → plan → treat →
   monitor → revise → close.
3. **Rollup rule.** `current_status(focus)` reads "not currently controlled" when any linked acute
   sub-episode is active, regardless of baseline (ADR 0003 decision 1). Never reads note prose.
4. **Goals** with measure linkage (`goal.measure` = LOINC or instrument), target, direction;
   `progress` derived (`met | improving | stalled | regressed`) from `trend()`; `manual_state`
   override is a provenance event (G3).
5. **RiskAssessment** history on the context: level, as_of, assessed_by, safety plan,
   `stale_after`; staleness is a flag rendered loudly ("assessed 41 days ago, stale"). A stale
   low-risk reads as a warning, never as reassurance. Confidentiality field present; enforcement is
   PRD-12 and is a **launch gate for the MH profile**, not a later phase (G5).
6. **Discharge vs lapse** (G8): discharge is an event with a derived closure summary; a course with
   visits/auth remaining and no activity past its horizon is flagged `lapsed`, never auto-closed.
7. **Compliance agenda** (view): per context, the profile's rule outputs (recert due, progress
   report due, treatment-plan review overdue, authorisation burn-down) as flags; consequential ones
   instantiate WorkItems (PRD-09).
8. **Preventive agenda** (view, patient-level, not a context): screening and immunisation
   forecasting from a small USPSTF/ACIP table against age/sex/history, plus surveillance of chronic
   focuses. "Screenings due" is a state, never a category. A finding during a preventive visit
   raises a problem in place.
9. **Encounter ↔ context linking is inferred and offered, never required** (G1): the composer
   proposes likely contexts from the visit reason and recent activity and shows the consequence of
   linking (which sections, which billing) before the clinician confirms.
10. **Correction modes** (from the evaluations): re-code, mark refuted, split, merge, reopen,
    retract, each a verb with a required assessment where consequential.

**Out**
- Pregnancy and post-acute profiles (registry entries, no fixtures).
- Care-plan items as first-class tasks beyond goals (kept as a field per G7 until PRD-09 lands, then
  promoted).

## Design rules (binding)

- G1–G8 from ADR 0003 are acceptance criteria, not guidance.
- Nesting is designated by the system or retrospectively; the composer never asks "parent or
  child?"
- No global "active episode" selector; the encounter composes 1..N contexts.
- Billing derives from clinical interventions (charges link to the problem that justifies them);
  the KX guardrail fires at capture, not at claim.

## Fixtures

Extend the golden set with three patients (see PRD-12 for the patients directory): `pt_002`
knee-pain PT course over the KX cap; `pt_003` MH anxiety case with elevated, stale risk; `pt_004`
concurrent PT + MH (multi-context). Synthea can seed the demographics and encounters; the courses,
goals and risk history are hand-written fixtures like the demo notes.

## Acceptance

1. pt_001: a `CHRONIC_CARE_PROGRAM` context addressing CKD/CHF/T2DM; opening an acute AKI
   sub-episode flips CKD's current status to "not currently controlled" without any note edit.
2. pt_002: recert alert fires from visits/cert dates; Recertify resets the window; Discharge
   produces a summary; a course left idle past horizon shows `lapsed`, not closed.
3. pt_003: risk pill shows level, as-of, assessor and a stale marker; "Record risk today" appends,
   never overwrites; the safety-plan-review alert clears on record.
4. pt_004: the encounter links both contexts; the note composes both packs; billing scopes to PT.
5. A preventive visit on pt_001 shows the computed agenda with no linked problem, and an elevated BP
   entry raises a problem in place.
6. Goal "eGFR above 20" reports `regressed` from the trend; a manual override is a provenance event.

## Estimate

Six days including fixtures.
