# PRD-05 — Evidence capture: transcripts, extraction, and the eval harness

**Stage:** the slice-1 loop (`slice-1-spec.md`): typed entry born-attested → narrative in the log
→ one extraction pass → review → note projection. **Depends on:** PRD-01, 02, 04.
**Schema:** v2 §1 (`narrative.received`), §2 (evidence spans).

## Why

The hackathon extractor already does the hard part: verbatim quotes, allowed-code validation,
dedupe against the chart, refill-chain reasoning, stop-by-name. What it lacks is what the docs
call structural: **stable spans into a verbatim narrative event** (not just a quote string), the
rule that it **never re-proposes what the model already holds with human provenance**, an
**adversarial second pass** on the four known failure modes (negation, dose deltas, temporality,
speaker attribution), the **tripwire pre-pass** that runs rules before any model, and an **eval
harness** that measures precision *and* miss rate before any clinician trusts the queue
(`slice-1-spec.md` "Open decisions"; `cpor-qa.md` Q16; paper B.2 maintenance pipeline; evaluation
digest "recall instrument"). Ambient capture is the flagship input for the first market and the
transcript, not the vendor's note, is the evidence (`sully-transcript-pm-brief.md`).

## Goal

One extraction pipeline with two front-ends (typed note, diarised transcript), emitting proposals
with spans and the three-part anatomy, measured by a harness the kill conditions read.

## Scope

**In**
1. **Narrative events.** Demo notes and transcripts enter as `narrative.received` with
   `payload: {text, format: note | transcript, utterances: [{speaker, start, end, text}]}`.
   Character offsets are stable for the life of the event. The two hand-written demo notes stay
   as they are; a third fixture is a diarised transcript of visit 2 (`data/notes/transcript_demo_002.json`)
   with clinician/patient/family speakers.
2. **Spans.** Every proposal's `evidence[]` carries `{event_id, span}`; the validator rejects a
   proposal whose span does not contain its quote. "No cited span, no proposal."
3. **Never re-propose.** Before emitting, the pipeline diffs candidates against the projection: a
   candidate matching a claim with `tier ∈ {entered, attested}` (same code, same value ± tolerance,
   same date ± window, or same medication course) is dropped and logged as `suppressed:already_held`.
   Typed vitals at rooming are never re-proposed from the transcript (slice-1 acceptance test).
4. **Tripwires first.** Every new observation event is evaluated against every active focus's
   surveillance spec (PRD-03) by rules, before any model call; hits raise a rule-suggested proposal
   or WorkItem. The demo's "creatinine up 25 % in 90 days" becomes a rule hit, and the model is
   asked only for the attribution.
5. **Adversarial check.** A second, cheaper structured call re-reads each consequential proposal
   against its span and answers four yes/no questions (negation flipped? dose delta wrong?
   temporality wrong? speaker misattributed?). A "yes" lowers confidence below the surfacing
   threshold and attaches the reason. Recorded and replayable like every model call.
6. **Three-part anatomy.** Reasoning output (`ehr/reason.py`) is reshaped: `observation`
   (rule-computed where possible: "creatinine 1.62 → 5.7 over 12 months"), `attribution`
   (model: "consistent with NSAID contribution"), `confidence` on each. Rules produce the
   observation; the model never touches a numeric value (`cpor-qa.md` Q12/Q16).
7. **Tiered resolver** for entity identity (paper B.2): tier 1 code match with synonym/hierarchy
   expansion (stdlib table for the demo), tier 2 lexical match against focus titles and one-liners,
   tier 3 model adjudication with rationale, `match | no_match | uncertain`. Uncertain creates a new
   node plus a proposed `manifestation_of`/`relevant_to` link, never a silent guess. Merges are
   never automatic.
8. **Eval harness.** `python3 -m ehr.eval --gold data/eval/` runs the pipeline over held-out
   narratives with a gold proposal set and reports precision, recall, miss rate on consequential
   deltas, per-failure-mode counts, and suppression correctness. Gold set: the two demo notes plus
   the transcript, hand-labelled (~40 items). The harness output feeds kill condition 3/4.
9. **Ambient integration contract** (`docs/integrations/ambient-capture.md`): verbatim transcript,
   speaker diarisation, stable offsets or utterance ids, retention rights, and whether the vendor's
   structured outputs enter our queue (if so, wrapped by the adversarial check, low trust tier).
   Vendor note-only is the "degraded mode, honestly labelled": corpus import with machine
   provenance.
10. **Born-attested typed entry** UI: a vitals/instrument form (BP, weight, creatinine, PHQ-9,
    GAD-7) that calls `recordObservation` directly (PRD-02). Instrument scores are series-first.

**Out**
- Audio capture and ASR (the partner's job; a JSON transcript is the interface).
- Extraction of orders, care plans, goals (slice 1 entity set: problem, observation, medication
  statement, allergy). Allergy is a new v2 object; add it to the schema proposal when scheduled.

## Acceptance (the slice-1 test, transposed)

1. Vitals + PHQ-9 typed at rooming appear `tier: entered` with no queue item.
2. Transcript in → at least one proposal per entity type with span + confidence; **zero
   re-proposals** of the typed observations.
3. Steward modifies one, rejects one; both visible in the biography; the note regenerates citing the
   typed observations rather than restating them (PRD-06).
4. "What did the model assert at time T?" answers from the ledger (`?as_of=`).
5. Harness reports precision ≥ 0.9 and consequential miss rate ≤ 10 % on the gold set, or the
   pipeline is not enabled for live mode.
6. A negation-flipped probe ("no chest pain" → chest pain) is caught by the adversarial pass.

## Estimate

Six days: one for narrative events and spans, one for suppression and tripwires, one for the
adversarial pass, one for the resolver, two for the harness and gold set.
