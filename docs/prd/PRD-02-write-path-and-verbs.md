# PRD-02 — One write path: verbs, authority, provenance

**Stage:** 2 of the platform sequence. "The stage worth defending" (`ontology-evolution.md` §7.3).
**Depends on:** PRD-01. **Unblocks:** PRD-04, 05, 06, 09, 11, 12.
**Schema:** v2 §0 (verbs are a kind), §2 (tiers), §4 (proposal-with-disposition), §10 (actors).

## Why

The hackathon has the right invariant, "nothing AI-generated writes without human acceptance," but it
is enforced by one function and a convention. The target generalises it: **intelligence proposes;
authority acts.** Every caller (the UI, the extraction pipeline, the reasoning layer, a rule, an
integration, an outside agent) writes through the same enumerable list of verbs, distinguishable
only by provenance; anything that cannot satisfy the same authorisation and validation does not
write (`ontology-evolution.md` §6 "one write path, for every caller", §7.3; ADR 0001 invariant;
eng-faq "Why can't the AI write to the chart?"). The verb list is also the half of the product that
"is not commoditising": knowing what actions exist, who may perform each, what must be validated,
what needs confirmation and what counts as done.

## Goal

A registry of verbs is the only door to the ledger. `accept_item` becomes one verb among thirty.
Proposals are inert records until an authorised verb executes them.

## Scope

**In**
1. `ehr/verbs.py`: a registry. Each verb declares `name`, `inputs` (validated), `requires`
   (role/authority), `confirm` (needs explicit human confirmation: yes/no), `emits` (event kinds),
   `side_effects` (other verbs it calls), `done_when`. Illustrative first list:
   `registerPatient`, `raiseProblem`, `updateProblemStatus`, `recodeProblem`, `mergeProblems`,
   `transferSteward`, `recordObservation`, `correctObservation`, `recordMedicationChange`,
   `discontinueMedication`, `openEncounter`, `signEncounter`, `amendEncounter`, `receiveNarrative`,
   `assertEdge`, `retractEdge`, `raiseProposal`, `decideProposal`, `raiseInsight`, `placeOrder`,
   `fulfillOrder`, `cancelOrder`, `composeDocument`, `signDocument`, `raiseWorkItem`,
   `assignWorkItem`, `deferWorkItem`, `completeWorkItem`, `assessRisk`, `setGoal`,
   `overrideGoalProgress`, `openCareContext`, `closeCareContext`, `dischargeCareContext`,
   `recordImpression`.
2. **Actors and authority.** `ehr/actors.py`: roles `clinician | staff | biller | patient | rule |
   model | integration`, each with a verb allow-list. A `model` actor may call only `raiseProposal`,
   `raiseInsight`, `raiseWorkItem(suggested)` and `composeDocument(draft)`. A `rule` actor adds
   `raiseWorkItem`. Nothing else. This is the ADR 0001 invariant made structural.
3. **Proposal with disposition.** `raiseProposal` stores what was observed, what was inferred,
   which model/rule at which version, and what it reasoned over; `decideProposal(confirmed |
   amended | rejected, reason_code, reason)` records the ruling and, on confirm, calls the target
   verb with `caused_by` set. The proposal and its ruling both persist (retention policy: PRD-04).
   v1's `review` record is the disposition half, kept verbatim.
4. **Born-attested typed entry.** `recordObservation` called by a clinician actor writes
   `tier: entered` directly, no queue (slice-1 §"structured manual entry"). Both write paths exist
   from day one: typed data enters at birth, extracted data enters as a proposal.
5. **Confirmation contract.** Verbs marked `confirm: true` (sign, discharge, merge, discontinue,
   transmit order) refuse to run without an explicit `confirmation` token issued by the UI step
   that showed the consequence. This is where "consequential mutations are never bulk-accepted"
   is enforced, not in the frontend.
6. Every verb call is itself logged (`verb.invoked` with args hash, actor, outcome) so the
   telemetry PRD-04 needs exists without a separate project.
7. `POST /api/verbs/{name}` as the single write endpoint; existing `review`, `extract`, `reason`,
   `compose`, `orders`, `undo`, `reset` endpoints become thin wrappers that call verbs. `undo` is
   `decideProposal(reverted)` plus compensating events, never deletion.

**Out**
- A permissions UI. Roles are a table; PRD-12 adds administration.
- Cross-patient verbs. Every verb validates `patient_id` on every object it touches and refuses
  writes that cross a patient boundary (ADR 0003 write-back contract).

## Design rules (binding)

- The verb list is enumerable, documented, and the same for every caller. `GET /api/verbs`
  returns it with each verb's authority and confirmation requirements.
- A verb may call other verbs; it may not append events directly except its own declared kinds.
- Validation happens in the verb, once. The frontend never re-implements a rule the verb enforces.
- A model actor never holds a session; its provenance names the model and version.

## Acceptance

1. Replaying the demo (extract → decide → reason → decide → orders → compose → sign) writes only
   through verbs; a test asserts no code path calls `ledger.append` outside `ehr/verbs.py`.
2. A `model` actor calling `updateProblemStatus` is refused with a readable error.
3. `decideProposal(confirmed)` on a naproxen `caused_by` edge writes `proposal.decided` then
   `edge.asserted` with `caused_by` pointing at the decision.
4. `signEncounter` without a confirmation token is refused; with it, it emits the snapshot (PRD-06).
5. `recordObservation` by a clinician writes `tier: entered` with no proposal record.

## Metrics

Verb latency p95 under 50 ms. Zero writes outside the registry (CI grep + runtime assertion).

## Estimate

Three days. Most of it is moving existing logic from `review.py`, `orders.py`, `compose.py` into
named verbs and deleting the chart-mutation helpers.
