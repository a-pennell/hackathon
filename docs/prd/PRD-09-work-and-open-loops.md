# PRD-09 — Work: open loops and accountable obligations

**Depends on:** PRD-01, 02, 03. Consumes PRD-04 (Proposal lane), PRD-07 (compliance flags).
**Schema:** v2 §8 (WorkItem).

## Why

Every evaluation named the same weakest object: **work ownership**. "Who owns the next action, what
remains open, what has been delegated, and how completion is verified" is the gap; "documented but
unowned follow-up" is a high-likelihood, high-severity failure (evaluation digest, files 1–3). The
docs resolve the model: a **flag** is a derived condition (result overdue) rendered as a badge; a
**WorkItem** is an obligation with identity, a biography and mandatory `suggested_by`; not every
flag instantiates an item; Work is a *projection* of objects in actionable states plus true
WorkItems, never a copy (`ontology-evolution.md` §2; `cpor-migration-and-ia.md` §3 "Work is a
projection, not a task pile"). The hackathon has a per-patient inbox and nothing across patients.

## Goal

A cross-patient Work space with one queue of open loops filtered by obligation type, backed by
WorkItem objects whose assignment, deferral, escalation and completion are events, and with the
Proposal lane present from day one.

## Scope

**In**
1. **Flags** (`ehr/flags.py`, derived, never stored): unsigned note, result awaiting review,
   order without fulfilment past expected turnaround, referral without reply, stale risk, screening
   due, steward orphan, recert/progress-report due, proposal awaiting decision, charge incomplete,
   follow-up due. Each flag names the object, the rule, and whether it *may instantiate* an item.
2. **WorkItem** object and verbs (`raiseWorkItem`, `assignWorkItem`, `deferWorkItem` with reason
   and until, `escalateWorkItem`, `blockWorkItem` on another item, `completeWorkItem` with outcome,
   `cancelWorkItem`). States `open | assigned | in_progress | waiting | done | cancelled`. Distinct
   from "verified": a completion may require verification (result acknowledged *and* patient
   notified) per the item's completion criteria.
3. **Instantiation policy.** Rules decide which flags become items (result review: always;
   screening due: only when a visit is scheduled within 60 days; proposal: never, it is its own
   lane). Documented in `ehr/flags.py::INSTANTIATES` so the policy is legible.
4. **Work space** (`/work`): one queue across patients, filter chips by obligation type with counts
   (results, documentation, refills, referrals, authorisations, charges, follow-ups, messages,
   tasks, **proposals**), grouped by patient on demand, sorted by consequence then due. Every row
   is a deep link into the patient scope with the object's drawer open; nothing is worked *in*
   Work.
5. **Per-row primary action** = the item's obligation made actionable ("Review result", "Sign
   note", "Record risk today", "Decide proposal"); a row with nothing due has no button
   (`cpor-design-notes.md`).
6. **Ownership.** Owner is a user or a pool; steward is the default owner for clinical items;
   unowned items past 24 h escalate to the pool lead; the overdue-unowned count is a first-class
   metric.
7. **Biography.** Every WorkItem row opens its drawer with "Changes": raised (by rule/model/user),
   assigned, deferred (reason), completed (outcome), each stamped and linked to the occasion.
8. **Never mint `Result → Task → Result`.** A result in `needs review` appears in Work directly
   under Results; a WorkItem exists only when the work must be independently assigned, delegated,
   scheduled or tracked.

**Out**
- Team/pool administration UI (a fixture file of users and pools).
- Messaging (PRD-11 adds the message thread object; actionable messages then appear here).

## API

```
GET  /api/work?owner=me|pool:…&kind=…&patient=…     the projection
GET  /api/patients/{pid}/flags                        flags for one patient (Overview reads this)
POST /api/verbs/raiseWorkItem | assignWorkItem | deferWorkItem | completeWorkItem | …
```

## Acceptance

1. Creatinine 5.7 lands as an event → flag `result_review` → WorkItem raised with
   `suggested_by: rule:result_review`, owner = CKD steward → appears in Work under Results with
   "Review result" → completing it records outcome and clears the flag.
2. A problem whose steward leaves (fixture) shows `steward_orphan` in Work within one fold.
3. Proposals from note 2 appear under the Proposals chip with counts and open the PRD-04 card.
4. Deferring an item requires a reason and an until-date; it disappears from the default view and
   returns on the date; the biography shows both.
5. `GET /api/work` returns no duplicated object: a result under Results is the same object id as
   the result in the patient's Chart.

## Estimate

Four days: one for flags, one for the WorkItem object and verbs, two for the space and drawer.
