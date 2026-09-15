# PRD-12 — Many patients, actors, permissions, confidentiality, interop

**Depends on:** PRD-01, 02. **Gates:** the MH profile (PRD-07), risk rendering anywhere, Work across
patients (PRD-09), the shell (PRD-10), Reports (PRD-11).
**Schema:** v2 §10.

## Why

Everything cross-patient (Work, Today, registries) needs a patients directory, and the docs are
unambiguous that **permissions live below the document, by entity, sensitivity, consent and
purpose of use, that they govern the inference path too, and that 42 CFR Part 2 / ROI is a
prerequisite for queryable risk state, not a later phase** (ADR 0003 G5; eng-faq "Where do
permissions live?"; every evaluation's "BH confidentiality as production gate"). FHIR is the
exchange contract and never the UI model; the log and model must stay exportable in standard form
or "this becomes another proprietary silo" (eng-faq). The hackathon has one patient, no users, and
a stubbed nothing.

## Goal

A patients directory with several golden fixtures, real actors and roles, permission evaluation on
every read and write including the compiler, storage classes with Part 2 segmentation, an access
log, disclosure accounting, and FHIR export of ledger and projection.

## Scope

**In**
1. **Patients directory**: `data/ledger/<pid>.jsonl` per patient, `GET /api/patients` with search
   (name, DOB, MRN); fixtures pt_001 (existing), pt_002 PT knee, pt_003 MH anxiety, pt_004 PT+MH,
   pt_005 new patient blank, pt_006 preventive visit (PRD-07 fixtures). Synthea seeds demographics
   and encounters; courses, goals, risk and transcripts are hand-written.
2. **Actors and sessions**: a users fixture (clinician, therapist, MA, front desk, biller, practice
   lead, patient), a trivial local sign-in that sets the actor (no real auth; the boundary is the
   verb registry, not the login), `actor` stamped on every event and every read.
3. **Permission model**: `can(actor, verb | read, object, purpose)` evaluated by role allow-lists
   (PRD-02) × object sensitivity × consent × purpose of use. Sensitivity classes: `standard`,
   `behavioral_health`, `part2_substance_use`, `private_process` (PRD-06). Visibility states for
   restricted objects: `visible | restricted_with_reason | redacted_but_known_to_exist |
   unavailable` (the four states the evaluations asked for), rendered distinctly. Break-glass is a
   verb with a reason, logged loudly, and a WorkItem for review.
4. **Compiler and inference respect permissions**: `compile_context` and ask-the-record take the
   actor and never include what the actor may not read; a corpus query is not a side door.
5. **Consent objects** (`cons_`): ROI, telehealth, treatment, financial, with scope and expiry;
   Part 2 disclosure requires a matching consent; disclosure accounting records every export and
   release with tier and purpose on every focus ("concern — monitoring", "provisional, billed").
6. **Access log**: every read of a restricted object is an event; the patient's record tools show
   the log.
7. **FHIR export**: `GET /api/patients/{pid}/fhir` produces a Bundle from the projection
   (Patient, Condition with clinicalStatus/verificationStatus, Observation, MedicationStatement /
   MedicationRequest, Encounter, Composition, EpisodeOfCare, Goal, ServiceRequest, Task,
   Provenance); the ledger exports as `Provenance` + `AuditEvent`. Import path stays the existing
   Synthea importer, now emitting events. Deviations (parent_id nesting, tiers, edges) map per the
   ADR 0003 table; edges export as `Condition` extensions where FHIR has them.
8. **Schema versioning**: every event carries `schema_version`; a migration is a fold with an
   upgrader per version; the recompilation audit runs after every migration.
9. **Retention and legal hold** (documented, minimal): the ledger is never pruned; rejected
   proposals follow PRD-04's tiered retention; a `legal_hold` flag on a patient suspends aggregation.

**Out**
- Real identity provider, SSO, MFA.
- HL7v2 interfaces, real HIE; adapters are stubs behind the BFF.
- Certification work (ONC is assumed eventually; the hedges are the FHIR export and the day-one
  provenance fields).

## Acceptance

1. A front-desk actor opening pt_003 sees the header and schedule and a `redacted_but_known_to_exist`
   marker where the risk object would be; the therapist sees the risk object; the access log
   records both.
2. `compile_context` for the PCP on pt_003 omits Part 2 material absent a consent and states it in
   the bounded-search report; adding the ROI consent includes it.
3. An `integration` actor attempting `updateProblemStatus` is refused; `raiseProposal` succeeds and
   the proposal shows `source: integration:<name>`.
4. The FHIR bundle for pt_001 validates against R4 resource shapes for the resources above and
   round-trips through the importer to an equal projection.
5. Work for the MA shows only items the MA may act on.

## Estimate

Seven days, of which two are fixtures.
