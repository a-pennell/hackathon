# PRD-11 — Operations: Today, Schedule, Messages, Revenue, Reports

**Depends on:** PRD-09 (Work), PRD-10 (shell), PRD-12 (multi-patient, roles), PRD-06 (charges from
encounters).

## Why

"More or less operational" needs the clinic day, appointments, conversations and money, or the
patient workspace has no way to be reached and nothing to close. The docs are deliberate about
keeping these thin: Practice is "deliberately boring and page-like, spend no innovation budget";
Revenue is first-class because its actors, permissions and state machines differ; Messages is a
communication object and ledger evidence whose *obligations* surface in Work; Today is the temporal
landing surface; Reports is a limited destination and most analytics are lenses
(`cpor-migration-and-ia.md` §3 spaces table; migration site role table). Billing is "generated to
payer spec with citations so the clinical layers stay clean" (paper §6.4) and derives from problems
addressed (PRD-06), which `ehr/billing.py` already does.

## Goal

Enough of each space that a clinic day runs end to end on the fixtures: arrive, room, visit, sign,
charge, message, follow up; each object with one home and lenses elsewhere.

## Scope

**In**
1. **Schedule**: Appointment object (`appt_`) with patient, provider, start/end, type, status
   (`booked | arrived | roomed | in_visit | done | no_show | cancelled`); day/week views; creating
   an appointment is a verb; arriving/rooming are events; an appointment opens an encounter.
   Scheduling → encounter edge is one of the unmapped legacy pieces named in `ontology-evolution.md`
   §8; this PRD maps it as `fulfills` (encounter → appointment).
2. **Today** (`/today`): the clinic day for the signed-in role: visits with readiness (forms,
   eligibility placeholder, rooming vitals entered), arrivals, no-shows, same-day changes, visit
   prep (glance link per visit), encounters needing attention (unsigned), escalations, appointment-
   linked messages. Composed from Schedule + Work + flags; owns no data.
3. **Messages** (`/messages`): Thread object (`thr_`) and Message events (`msg.received`,
   `msg.sent`), portal and internal, with assignment, pools, delivery state; the authoritative home
   for conversation threads. Actionable threads project into Work (unread patient messages,
   assigned threads, waiting-on-staff); the thread has one URL and appears under the patient's
   Correspondence and Timeline as lenses. A message can anchor an occasion (open a note from the
   thread; PRD-06).
4. **Revenue** (`/revenue`): Charge object (`chg_`) captured in the encounter at sign from
   `ehr/billing.py` (CPT/E-M + ICD-10 with citations), then a queue of charges by state
   (`draft | ready | held | submitted | paid | denied`); claim as a thin object (`clm_`) with
   status; attested-for-claim recorded as a distinct event from clinical conviction (PRD-03).
   PT charge capture (8-minute rule, units, performer, KX attestation) lives in the PT profile
   (PRD-07) and lands here. No payer connectivity; export is a file.
5. **Practice** (`/practice`): users, roles, pools, templates, the profile registry as read-only
   config, the attestation metrics dashboard (PRD-04), quality lenses (a few HEDIS-style measures
   computed over the patients directory once PRD-12 lands). Deliberately page-like.
6. **Reports** (`/reports`): cross-patient queries over the projections: registry ("patients with
   last eGFR below 30"), care-gap rollup, panel counts. Read-only, exportable CSV.
7. Every space's contents are projections; Today and Reports store nothing; Schedule, Messages and
   Revenue own their objects and nothing else.

**Out**
- Real eligibility, clearinghouse, e-prescribing transmission, fax, portal auth, telehealth video.
  Each is named as an integration boundary with a stub adapter behind the BFF.
- Patient-facing portal UI (a patient-facing summary view exists in PRD-08; the portal is later).

## Acceptance

1. Book pt_001 for tomorrow, arrive, room (vitals typed, born-attested), open the encounter from
   Today, sign, and the charge appears in Revenue as `ready` with cited codes; Work shows nothing
   dropped.
2. A portal message from pt_003 appears in Messages, projects into Work under Messages, opens the
   patient's Correspondence lens with the same thread id, and closes when replied.
3. Marking an appointment no-show creates an occasion row in Session documentation and a follow-up
   flag; nothing is written to the chart body.
4. Reports lists the two patients whose last eGFR is below 30 and links to their focus workspaces.
5. A biller role sees Work, Patients (chart lens permissioned), Revenue and nothing else.

## Estimate

Ten days total, two per space, with Practice and Reports the thinnest.
