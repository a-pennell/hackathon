# PRD-04 — Attestation surface: the clinical diff, v2

**Stage:** rides on PRD-02 (proposals are verbs' inputs). Designed before the graph fills it
(`cpor-migration-and-ia.md` Phase 2: "its interaction grammar is designed now, before proposals
exist").
**Depends on:** PRD-01, PRD-02. Informs PRD-05 (what the pipeline must emit), PRD-09 (Proposal lane
in Work).
**Schema:** v2 §2 (tiers), §4 (proposal-with-disposition).

## Why

"Attestation is the wager" (`cpor-qa.md` Part 4 §1; paper §6.5 Assumption 2). Every evaluation
ranked rubber-stamping and silent omission as the top two failure modes. The hackathon inbox is a
good first draft (evidence-first cards, reasons on rejection, undo, links folded into findings), but
it has no steward routing, no consequential/batchable split, no evidence-before-interpretation
gate, no telemetry, and a bulk "sign all" that can attest consequential changes. The target commits
to a specific **review economy**: who reviews what, when, under what liability, with what measured
burden, and what happens when the burden exceeds budget (paper A.3, A.6).

## Goal

The review queue becomes a steward's changeset: consequence-ranked, individually attested where it
matters, batch-acknowledged where it does not, instrumented from the first click, with kill
conditions computed from its own telemetry.

## Scope

**In**
1. **Proposal anatomy.** Every proposal renders three separable claims: *observation* (what the
   evidence shows), *attribution* (the proposed reading), *confidence* on each. A steward can
   accept the observation and reject the attribution. Insights from `ehr/reason.py` are re-shaped
   to emit this triple (PRD-05).
2. **Consequence classes.** `consequential` = new problem, status transition, merge, `caused_by`
   edge, medication change, order, document sign, risk level. `batchable` = `relevant_to` /
   `monitors` edges, summary refreshes, harvested edges. Consequential items are reviewed one at a
   time; **bulk-accept is unavailable for them** (enforced by the `confirm` contract in PRD-02,
   not by hiding a button). Batchable items land as `acknowledged` in one gesture and are
   spot-audited (5 % sample surfaced weekly as a WorkItem).
3. **Steward routing.** Proposals route to the focus's steward, never to whoever opened the chart.
   The queue is per user; a covering clinician sees "Dr. Chen's queue" as read-only unless
   stewardship is transferred.
4. **Evidence before interpretation.** For diagnostically consequential proposals (new problem,
   status transition, `caused_by`), the card first shows the evidence panel and a one-line
   impression field; the machine's framing is revealed after the impression is recorded
   (`recordImpression` event). Impression vs proposal disagreement is the calibration signal.
5. **Authored assessment checkpoints.** Raising a problem, changing a diagnosis, closing a course
   require a typed assessment (prose; no structured reasoning fields). Trainee mode withholds the
   machine's interpretation until the learner commits.
6. **Telemetry on every interaction** (emitted by the verbs, no separate project): dwell per item,
   evidence-span opened (yes/no), decision, modification-on-review, time-to-attestation for
   consequential items, queue depth per steward per day, attestation minutes per clinician per day.
7. **Kill conditions as a dashboard** (`GET /api/metrics/attestation`), thresholds stated in the
   config, four of them: (1) rubber-stamp: modification rate on consequential items below 5 % over
   two weeks, or median dwell under 3 s; (2) queue burden: attestation minutes/clinician/day above
   budget (default 15); (3) recall floor: withheld-mention audit finds missed consequential deltas
   above 10 % (PRD-05); (4) silent-omission rate (the "fourth kill condition" every evaluation
   asked for). When a condition trips, the system **raises proposal thresholds** (proposes less)
   rather than normalising the queue, and says so on screen.
8. **Seeded probes.** A small library of wrong proposals (dose off by 10×, negation flipped,
   wrong speaker, wrong problem) injected at a configurable rate in demo/pilot mode; catch rate is
   the gaming-resistant rubber-stamp metric.
9. **Retention tiers** for rejected machine belief (the trilemma: liability / spoliation /
   safety learning): rejected consequential proposals kept at full fidelity for a bounded window
   (default 90 days) then aggregated to accuracy statistics; sub-threshold proposals never enter
   the retained record. Documented as a policy knob, default set, revisit date recorded.
10. **Keyboard review** (J/K move, S sign, R reject, E open evidence, Enter confirm reason), the
    remaining item from `docs/ui-critique.md`.
11. **Contested state.** A steward can mark a proposal or claim `disputed`, recording both
    positions; disputed claims render loudly (not as an error) and never support a bill or referral.

**Out**
- Multi-steward co-signature workflows.
- A learned threshold model; thresholds are configuration.

## Design rules (binding)

- Unattested machine state is visibly provisional (pencil) and supports no billing, referral or
  order (the compiler refuses to cite it in those views; PRD-08).
- "Sign all" exists only for batchable items and says "acknowledge 14 links".
- Every rejection carries a reason code (existing), and rejections are data the pipeline reads
  (never re-propose the same claim with the same evidence).
- No hover-only provenance: stamp visible, evidence on demand, one tap.

## UI

Extends `Inbox.tsx`: consequence lane on top (one card at a time, evidence → impression →
proposal reveal), batchable strip below with one acknowledge action, steward chip on the queue
header, metrics drawer, probe indicator in demo mode. Card vocabulary from `cpor-design-notes.md`:
"suggested change", "linked findings", "review and sign", "possible explanations".

## Acceptance

1. Replaying note 2: the four consequential items (stage-4 problem, naproxen `caused_by`, stop
   metformin, restage) cannot be bulk-signed; the 18 batchable links acknowledge in one gesture.
2. Opening the naproxen card shows evidence and an impression box; the proposal text is hidden
   until an impression is recorded; the disagreement is logged.
3. Signing 20 consequential items in under 60 s with zero modifications trips kill condition 1 on
   the dashboard.
4. A seeded 10× dose probe that is signed is counted as a miss and shown in the metrics drawer.
5. Every queue action produces a `verb.invoked` event with dwell and evidence-opened fields.

## Estimate

Five days: two for proposal anatomy and consequence classes through the verbs, two for the UI
sequence and keyboard path, one for telemetry, dashboard and probes.
