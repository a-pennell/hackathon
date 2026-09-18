# A clinical-reasoning-centred EHR: design

**Status:** design for team discussion, 15 September 2026. Nothing here is built. It extends the
target architecture already chosen (`docs/roadmap/00-north-star-and-gap-analysis.md`, the twelve
PRDs, `docs/roadmap/schema-v2-proposal.md`) rather than replacing it. Every schema change it
needs is listed in the appendix and flagged; `docs/patient-model-schema.md` is unchanged.

**Companion:** the screen mockups, published as the "Reasoning Chart" artifact and referenced
by frame number below, were drawn on the first golden patient (pt_001, Willie Klocko, CKD). The
examples in this document use the demo patient, pt_002: Jeane Lueilwitz, 55, type 2 diabetes and
hypertension on metformin and hydrochlorothiazide, A1c 6.4 → 7.9 and blood pressure 128/80 →
154/94 over twelve months, new albuminuria, and a note on 15 September 2026 that reveals skipped
metformin and daily ibuprofen since May.

**Premise.** The record is not a transcript of clinical cognition. Clinicians carry a compressed,
partly tacit model of the patient. The system's job is to externalise the clinically useful part
of that model, organised around the evolving concern, without making the clinician document every
inference. Notes, encounters, orders, observations and documents are representations of that model,
not its home.

---

## 0. The seven questions (the acceptance test for every screen)

Every surface in this design is scored against whether it lets the clinician answer, without
reading prose they did not write:

1. What is happening?
2. What do we think it means?
3. What changed?
4. What are we doing?
5. What are we uncertain about?
6. What should happen next?
7. What would make us change course?

A screen element that helps with none of these does not belong in the clinical workflow. The
existing chart desk answers 1, 3 and 4 well (`docs/clinical-decision-principles.md` scorecard);
it answers 2 only through insight text, and 5, 6 and 7 not at all. Those three are the new work.

---

## 1. Three layers, and where each already lives

| Brief | This architecture | Status |
|---|---|---|
| **Clinical reality** (observed, measured, reported, imported) | Layer 1, the event ledger: `observation.recorded`, `narrative.received`, medication segments, encounters | PRD-01; v1 chart today |
| **Clinical model** (what we think is happening) | Layer 2, the focus graph: problems and concerns with typed edges, assessment prose, goals, courses, surveillance | PRD-03, PRD-07; partly built (problems, five link types, insights) |
| **Clinical record** (what we communicate) | Layer 3, compiled views: note, brief, referral, handoff, patient summary, billing artifact | PRD-08; brief, referral, orders, coding built ad hoc |

The model sits between the data and the documents, and the note is never the canonical source
of understanding. That is already the spine of the plan. What the brief adds is a **richer
clinical model**: the concern carries an epistemic state, a problem representation, hypotheses
with discriminators, evidence with valence, an expected trajectory and contingencies. Sections 2
to 11 specify those; the rest of this document is how they are shown.

---

## 2. The concern: the primary object

A concern is a `ClinicalFocus` (v2 §3). It may begin as "fatigue" or "blood pressure above goal"
and never has to become a diagnosis to organise care. What the brief asks for, mapped field by
field:

| Brief element | Field on the focus | v2 today | Change needed |
|---|---|---|---|
| Identity: name, label, status, priority, acuity, onset, owner, linked course | `name`, `summary_stack.one_liner`, `status`, `acuity`, `onset_date`, `steward`, `addresses` edge from CareContext | mostly present | add `acuity: routine | soon | urgent | now` and `priority` (per-steward ordering) |
| **Epistemic state** | `epistemic` | `lifecycle` + `certainty` | replace both with one ladder (§2.1) |
| **Problem representation** | `representation` | `summary_stack.one_liner` | promote to its own stratum with qualifiers and a tier (§4) |
| **Evidence** with valence and relationship | edges `relevant_to` / `evidence_for` with `valence`; `caused_by`, `complicates`, `manifestation_of` | v2 §4 | add `explains`, `may_contribute_to`, `associated_with`; add `valence: unexplained` (§5) |
| **Differential / hypotheses** | focuses with `kind: hypothesis`, edge `alternative_for` | absent | new kind, one new edge, `standing` field (§2.2) |
| **Assessment** | authored prose on the focus, versioned by event | `assessment` in v2 §5 note body | keep prose; make it a focus-level event, `assessment.recorded` |
| **Goals** | `Goal` with measure, target, direction, derived progress | PRD-07 | unchanged |
| **Plan** | orders, courses, referrals, follow-ups with `addresses` → focus | orders built; `addresses` in v2 | add `plan_kind: diagnostic | therapeutic | monitoring | preventive | referral | education | follow_up | contingency` |
| **Expected trajectory** | `surveillance.expected[]` | absent | new (§2.3) |
| **Contingencies** | `surveillance.reconsider_if[]` | tripwire thresholds only | generalise (§2.3) |
| Unresolved questions | focuses with `kind: question` linked to the concern | `kind: question` exists | unchanged |

### 2.1 Epistemic state

One ladder, not a binary. `epistemic` replaces v2's `lifecycle` and `certainty`:

```
finding → syndrome → possible → suspected → working → probable → confirmed
```

`status` stays separate and orthogonal (`active | recurrence | relapse | remission | inactive |
resolved | refuted`); "ruled out" is `status: refuted`, "historical" is `status: inactive` with
`carries_forward`. So "Blood pressure above goal" can be `kind: concern, epistemic: syndrome,
status: active` and later become `kind: problem, epistemic: working` with the title
"Hypertension, uncontrolled, NSAID-aggravated", as a recorded transition with a rationale, never
an overwrite (paper §6.3). The UI renders `epistemic` as one chip beside the name and never asks
for it at creation; a raised concern starts at `finding` or `syndrome`.

No numeric probabilities on hypotheses. The paper's argument (§6.3, A.2) holds: clinicians will
not author them, a versioned probability register is the most discoverable artifact, and the
machine reads hedged prose perfectly well. Certainty is the ladder position plus the assessment.

### 2.2 Hypotheses and discriminators

A differential is not a list. Each alternative is a small focus:

```json
{ "id": "prob_h_0007_02", "kind": "hypothesis", "name": "NSAID-driven rise",
  "standing": "competing | leading | unlikely | dismissed",
  "epistemic": "suspected", "steward": {...},
  "discriminators": [ { "code": "8480-6", "label": "Home blood pressure log, four weeks off ibuprofen",
                        "would_show": "a fall toward 130s confirms; no fall points at the diuretic alone or at adherence",
                        "state": "ordered | pending | resulted | unavailable | not_ordered" } ] }
```

with an `alternative_for` edge to the concern and its own `for`/`against` edges. The card shows,
for each alternative, why it is plausible (its `for` edges), what argues against it (`against`),
what is unknown, and the discriminator with its loop state (the loop rule: the order and the result
show each other). The steward promotes an alternative with one verb, `promoteHypothesis`, which
records the pivot and demotes the previous leader to `competing`, keeping both on the record.

### 2.3 Expected trajectory and contingencies

The surveillance spec (v2 §3) is the forward-looking half of the problem. The brief's two
questions, "if we are right, what should happen next?" and "what would make us reconsider?",
are the same object read two ways:

```json
"surveillance": {
  "expected": [
    { "statement": "Systolic under 140 within four weeks off ibuprofen and on lisinopril",
      "parameters": [ { "code": "8480-6", "direction": "falling", "target": 140, "by": "2026-10-13" } ],
      "set_by": "usr_chen", "at": "2026-09-15T…", "from_insight": "ins_0007_01" } ],
  "reconsider_if": [
    { "trigger": "systolic still above 140 by 2026-10-13", "then": "adherence and home cuff first; then a second agent",
      "parameters": [ { "code": "8480-6", "test": "not_falling", "by": "2026-10-13" } ] },
    { "trigger": "potassium above 5.5 or creatinine up by more than 30% on the two-week BMP", "then": "hold lisinopril, same-day review",
      "parameters": [ { "code": "6298-4", "test": "gt", "value": 5.5 } ] } ],
  "parameters": [ ... existing tripwires ... ],
  "review_horizon": "P14D"
}
```

Both are optional and lightweight: one sentence and, where a lab is involved, a code and a
direction so the system can check it. The rules layer evaluates `expected` and `reconsider_if`
against every new observation event before any model runs (PRD-03 §5), which is what turns
"expected vs observed" into a computed state rather than a memory.

---

## 3. The reasoning loop, recorded as events

`observe → represent → hypothesise → discriminate → act → observe trajectory → revise` is not a
workflow with stages; it is the set of verbs that touch a focus. Each is already an event kind or
becomes one:

| Loop step | Verb / event |
|---|---|
| observe | `observation.recorded`, `narrative.received` |
| represent | `representation.revised` (new; proposal → attested) |
| hypothesise | `problem.raised` with `kind: hypothesis`, `hypothesis.standing_changed` (new) |
| discriminate | `order.placed` with `plan_kind: diagnostic`, `discriminator.resolved` (derived) |
| act | `order.placed`, `medication.segment_*`, `goal.set` |
| observe trajectory | `expectation.evaluated` (new, rule-emitted: `met | not_yet | missed`) |
| revise | `problem.status_changed`, `problem.epistemic_changed` (new), `assessment.recorded`, `impression.recorded` |

The **reasoning history** view (frame 5) folds these per focus into a thread: what we thought,
what arrived, what changed, why. Previous interpretations are never overwritten and never shown
by default; the current card carries a "revised 3 times · last 11 Sep" affordance that opens the
thread. Revision is made cheap: editing the representation or promoting a hypothesis is one
action with an optional one-line rationale, and the rationale is the thing the thread quotes.

---

## 4. Problem representation

The single most valuable cognitive product is the compressed, discriminating one-liner. It gets
its own stratum, distinct from the machine one-liner, because it is the clinician's
interpretation, not a summary of data:

```json
"representation": {
  "text": "55F with T2DM and hypertension on hydrochlorothiazide alone, blood pressure 128/80 → 154/94 over twelve months with new albuminuria (ACR 18 → 48), rising from the month daily ibuprofen began, May 2026; home readings in the 150s over 90s.",
  "qualifiers": ["chronic", "progressive", "worsening", "unexpected_rate"],
  "tier": "proposed | attested", "asserted_by": {...}, "as_of_event": "evt_…",
  "cites": ["obs_c0006", "obs_c0007", "med_demo_102_01", "note_demo_102"]
}
```

- **Qualifiers** are the semantic axes the brief lists (acute/chronic, progressive/stable,
  focal/diffuse, unilateral/bilateral, episodic/persistent, new/recurrent, improving/worsening,
  expected/unexpected). Where a qualifier is computable it is computed and badged as such:
  `worsening` from the trend direction, `unexpected_rate` from a missed expectation. The rest are
  authored. Qualifiers render as a short chip row under the name (frame 2) and drive filters on
  the Overview ("worsening", "unexpected").
- **AI proposes, the steward disposes.** The reasoning layer may propose a representation (it is
  a `proposal.raised` with cited spans). It renders in pencil with *Accept · Edit · Reject* and
  every clause is a citation chip; editing keeps the citations that survive. A proposed
  representation is never shown as if the clinician wrote it, and the compiler never cites an
  unattested one in a document.
- Illness-script order inside the text (context → presentation → trajectory → current state) is
  the prompt template, not a form the clinician fills.

---

## 5. Source, interpretation, inference: three objects, always

| Layer | Object | Example on pt_002 | Provenance vocabulary |
|---|---|---|---|
| Source finding | Observation event | Systolic blood pressure 154 mm[Hg], 2 Aug | `measured`, `patient_reported`, `clinician_documented`, `imported` (outside record), `historical` |
| Interpretation | Edge with valence, or a representation qualifier | `relevant_to` hypertension, valence `for`; "worsening" | `asserted` (clinician), `ai_proposed`, `harvested` (rule) |
| Clinical inference | Insight, hypothesis, `caused_by` edge | "Daily ibuprofen is a suspected contributor" | `inferred_by_ai`, `inferred_by_clinician`, with model or user id |

These are never merged into one card. On the problem card, a finding under *Supporting* shows the
value in mono type (the machine-recorded fact), the valence mark, and a small provenance stamp; the
interpretation lives in the edge; the inference is a separate line under *Assessment* or an
insight. v2's `edge_provenance` and `asserted_by` carry the vocabulary; the additions are the two
`inferred_by_*` values and `valence: unexplained` for findings that bear on the concern but fit
no current explanation (the brief's "currently unexplained", the paper's mismatch signal).

---

## 6. Tacit and compressed reasoning: what we ask for, and when

The system asks the clinician to author exactly three things, and only at checkpoints:

1. **A representation** (one sentence) when a concern is raised or its epistemic state moves.
   Usually by accepting or editing a proposal.
2. **An assessment** (prose, any length, hedging welcome) at model-formation checkpoints:
   raising a problem, a diagnostic pivot, closing a course (PRD-04 §5). Never per visit.
3. **A one-line impression** before a diagnostically consequential proposal is revealed
   (evidence before interpretation, PRD-04 §4).

Everything else is computed or proposed: qualifiers, deltas, expectation status, discriminator
state, the summary stack, the note. The goal is a model another clinician can reconstruct, not a
chain of thought. A card with representation, assessment, two supporting findings and one
expectation already answers the seven questions.

---

## 7. Progressive disclosure: the three levels

| Level | Surface | Answers | Default content |
|---|---|---|---|
| **1 Orientation** | Patient Overview (frame 1) | who, why here, major concerns, what changed, what needs attention | header; "since you last looked" deltas ranked; active concerns by acuity with the pending item as the row action; open loops |
| **2 Clinical model** | Problem card in Care (frame 2) | representation, assessment, trajectory, plan, uncertainty, major evidence | the compact card: name, chips, representation, assessment, supporting, doesn't fit, plan, expected, reassess if, changed since |
| **3 Investigation** | Drawer and workspace panels (frames 3 to 5) | full differential, evidence spine, raw data, timeline, original documents, provenance, reasoning history | on demand, one tap each, never on the default screen |

The card's collapsed state is the four lines the brief names: **problem, current state,
assessment, plan**. Each further section is a door with its contents stated on the door
("Doesn't fit · 2", "Alternatives · 3, one discriminator pending", "Revised 3 times"), per the
collapse rule in `patient-ia-v2-proposal.md`. Nobody constructs a graph by hand: edges are
harvested, proposed, or created as a side effect of an action (linking a finding while writing the
assessment, ordering a discriminator from an alternative).

### 7.1 The problem workspace, from scratch

The chart desk today is three panes: problem list, timeline, inbox. This design does not keep that
layout. The workspace is **the card**, and everything else is a section of it or a door from it:

- **Proposals live in the slot they would fill.** A proposed representation sits in the
  representation slot in pencil. A proposed `for`/`against` edge is a pencil line under
  *Supporting* or *Doesn't fit*. A proposed order is a pencil line in *Plan*. A proposed
  hypothesis is a pencil row under *Alternatives*. There is no separate inbox for problem-scoped
  items; the decision meets the reasoning it belongs to (P3). The cross-patient, cross-problem
  queue is Work (PRD-09), and it deep-links into the slot.
- **The trajectory is a section, not a pane.** *View trajectory* expands the co-registered chart
  inline under the evidence, scoped to the card's monitored parameters and the corridor. The
  full Timeline tab remains for the source- and time-oriented view Bossen's finding requires.
- **The problem list is a rail, not a pane.** Active concerns by acuity, one line each, with the
  epistemic chip and the pending-item action, collapsible to initials. The Overview (frame 1) is
  the list's full form.
- **The brief is retired.** Its four jobs (what moved, what changed on the medication list, what
  is waiting, what you decided last time) are the card's *Changed since*, *Plan*, the pending
  chips, and the thread. This removes the `docs/ui-critique.md` finding that the brief grows with
  every signature and pushes the hero view below the fold.
- **Ambient and typed narrative enter through the same door.** A note or transcript arriving on
  the patient raises proposals into the slots above; the clinician never opens an editor to start.

The four-tab patient IA (Overview · Timeline · Care · Chart) and the pencil-and-ink grammar are
kept because they are good for the clinician, not for compatibility; everything inside the Care
tab is new.

---

## 8. Longitudinal over encounter-centric

A concern persists across encounters; the encounter is the change context that stamps who and
when (v2 §5, ADR 0003). The problem thread (frame 5) is the concern's own timeline of
transitions, folded from events: raised, evidence arrived, representation revised, hypothesis
promoted, plan changed, expectation met or missed. It reads like the brief's low-back-pain
example and it is generated, not written. The encounter note is one of the things linked from a
thread entry, not the container of the thread.

---

## 9. "What changed?" as a first-class interaction

`what_changed(since)` (PRD-08 view spec) exists at patient and problem level. The brief's demand
is that it rank clinically meaningful deltas rather than list events. The ranking rule, in order:

1. **Expectation missed or contingency triggered** (`expectation.evaluated: missed`,
   `reconsider_if` hit) with the parameter that did it.
2. **Epistemic or status transition** on any active focus; hypothesis promoted or dismissed.
3. **Medication change** on a course that `treats` or is `caused_by`-linked to an active focus.
4. **Monitored parameter crossing** a tripwire, a reference range, or its goal target.
5. **Goal progress transition** (`improving → stalled`, etc.).
6. **New unexplained finding** (edge with `valence: unexplained`).
7. **Setting change**: admission, discharge, new steward, new outside record.
8. Everything else, collapsed under "14 other events".

`since` defaults to the reader's last attestation on this patient (a per-user fact, not a global
"last visit"). Each line cites and opens the object in its drawer. The Overview shows the top five
patient-wide; the problem card shows the top three for that focus under **Changed since**.

---

## 10. Trajectory: expected versus observed on one axis

The hero timeline stays (`Timeline.tsx`): monitored series with reference bands, medication
courses as bands, encounters as ticks. It gains two things (frame 3):

- **The expectation corridor.** When an `expected[]` entry names a parameter, the chart draws a
  dashed corridor from the action's date to `by`, in the direction stated. Points landing inside
  it are quiet; a point outside it after `by` is the mismatch mark, and the same mark appears on
  the card and in "what changed". This is how *problem → intervention → response → reassessment*
  becomes visible instead of inferred.
- **Reasoning marks.** Attested transitions (representation revised, hypothesis promoted,
  assessment signed) sit as small marks on the axis at their date (the remaining P2 item in the
  principles scorecard), so the reader sees when the model changed relative to when the data did.

Home and office blood pressure on pt_002 are two series (patient-reported 150s over 90s, measured
154/94) and stay two series; where they disagree the chart marks it, never averages it (P9). A
disagreement there is exactly the kind of "doesn't fit" the card must show.

---

## 11. Decision support that interrogates the model

CDS is not an alert layer. It is four kinds of insight, each a `proposal.raised` with the
observation / attribution / confidence anatomy (PRD-04 §1), each attached to the focus it
concerns, each quiet until the clinician turns to it:

| Kind | Question it asks | Trigger | pt_002 example |
|---|---|---|---|
| `mismatch` | What does not fit the current explanation? | `expectation.evaluated: missed`; new `valence: unexplained` finding | A1c rose 7.1 → 7.9 with metformin on the active list; the note attributes it to skipped doses, so treatment failure is not the reading; a home glucose log that stays high on the extended-release switch would reopen it |
| `discriminator` | Which evidence would separate the competing hypotheses? | two or more hypotheses with `standing: competing` and no resolved discriminator | a four-week home blood pressure log off ibuprofen and on lisinopril separates "NSAID-driven" from "diuretic alone is not enough" |
| `missing` | What information would materially change the decision? | a plan or hypothesis whose discriminator is `not_ordered` or `unavailable` | no home blood pressure log on the chart; no lipid panel since 2024; no repeat ACR after the first abnormal value |
| `contradiction` | What in the record disagrees with itself? | rule checks across diagnosis ↔ findings, medication ↔ problem state, plan ↔ goals, expected ↔ observed, steward ↔ steward | ibuprofen daily with hypertension above goal and new albuminuria; A1c 7.9 with metformin "active" that is not being taken |

Rules and the model both produce these. Contradiction and mismatch are rule-first (they are checks
over structured state, PRD-03 §5) and the model is asked only to phrase and to cite. The phrasing
rule from the brief is binding: name the divergence, name the competing explanation, name what
would move it. "Consider PE" is not an acceptable output; "persistent hypoxia is not explained by
the current model; PE remains competing; D-dimer or imaging would change its likelihood" is.

---

## 12. Calibrated reliance: the inspectable insight

Every insight renders the same seven parts, in this order, with the suggestion last (frame 4).
This is the evidence-before-interpretation rule made into layout:

1. **Observation** (what the evidence shows, mono, cited)
2. **Supporting** (for-valence citations)
3. **Doesn't fit** (against-valence citations; may be empty and says so)
4. **Uncertainty** (the model's stated confidence in words, and which part it is least sure of)
5. **Missing** (what it could not see: no imaging, no outside record, note older than the labs)
6. **Would change if** (the counterfactual: the observation that would retract this)
7. **Suggestion** (one sentence, with the plan kind)

plus the provenance stamp (model, version, which events it reasoned over, `reasoned_over[]`).
Numeric probability appears only if a calibrated model produced it for that specific prediction;
the reasoning model's `confidence` is shown as a word band (low / moderate / high), not a decimal.
The steward can accept the observation and reject the attribution (PRD-04 §1). Acceptance rate is
not the metric; modification rate, dwell, and probe catch rate are (PRD-04 §6 to §8).

---

## 13. Where support appears (and what is allowed to interrupt)

| Placement | Used for |
|---|---|
| Inline mark on a value or band | tripwire crossing, mismatch, discordance, stale |
| Problem-level insight, folded into the card's *Doesn't fit* / *Alternatives* | the four kinds in §11 |
| "What changed" line | anything ranked 1 to 6 in §9 |
| Optional reasoning panel (drawer) | the full anatomy, the differential, the thread |
| **Interruptive** | only: a `reconsider_if` trigger whose `then` names same-day action, a critical result, an allergy or interaction at order time |

Nothing else pops. The rules-only fallback in `reason.py` becomes threshold-based (P8) so that
quiet is a normal output.

---

## 14. Documents from the model, narrative preserved

The compiler (PRD-08) renders the note, handoff, referral, patient summary and billing artifact
from the attested model. The **assessment and plan** section of a note is the card's
representation, assessment, plan, expected and reassess-if, in prose order, each line cited; the
clinician edits the rendered text and the edit is a `document.amended` event, never a second
source of truth. Free text is kept everywhere it earns its place: the assessment, the rationale on
a transition, the reason on a rejection, the patient's own words as a `narrative.received` event.
The rule is structured relationships + concise narrative + raw evidence, and the composer never
asks for structure at the reasoning grain.

---

## 15. Views and hierarchy

| Brief view | This IA | Owns |
|---|---|---|
| Patient Overview | `/patients/:pid` Overview | Level 1: current state, what changed, needs attention |
| Care | `/patients/:pid/care` | concerns and problems (the cards), courses, goals, plans, orders, referrals, follow-ups |
| Timeline | `/patients/:pid/timeline` | events and transitions with filter chips (Sessions · Results · Documents · Changes · Reasoning) |
| Clinical | `/patients/:pid/chart` Chart | medications, labs, vitals, imaging, allergies, histories (six groups) |
| Encounter | Chart › Session documentation, and the canvas | what happened in one interaction |
| Documentation | compiled views, frozen by sign | notes, letters, summaries |
| Notes | `/patients/:pid/notes` Notes | the notes on file by state (in progress, waiting to be read, signed); scoped to the patient or to all my patients |

One object, one home, many lenses (PRD-10). Nothing is duplicated between views; a card on the
Overview is a lens on the same focus that Care shows. The four tabs and the Care/Chart boundary
are unchanged from `patient-ia-v2-proposal.md`; this design fills the Care tab's problem card and
the Overview's top half. Notes is the fifth tab, added for the job every clinician role shares
(`jobs-to-be-done.md`): see my notes in progress and completed, resume one, know which are unsigned.

---

## 16. The scanability grammar

Eight distinctions, each with exactly one encoding, applied everywhere (the existing pencil-vs-ink
grammar extended):

| Distinction | Encoding |
|---|---|
| clinician-authored vs AI-generated | ink vs pencil (solid vs dashed amber), stamp on every pencil item; serif for authored prose, sans for compiled text, mono for recorded values |
| observation vs interpretation | mono value with unit vs sans label; interpretation never in mono |
| supporting vs contradicting | `+` and `−` valence marks in green-black and vermilion; unexplained is a hollow `○` |
| certain vs uncertain | the epistemic chip, one word, always visible on the card |
| expected vs unexpected | quiet vs the mismatch mark (vermilion outline) on the point, the card and the delta line |
| stable vs changed | grey vs the delta chip with direction and magnitude; unchanged lines carry no chip |
| current vs historical | full ink vs graphite; historical never on the default card |
| active vs resolved | position (active list vs the carries-forward band) plus status chip |

No colour is used for anything else. Semantic colour (vermilion, amber, green) is separate from
the one accent (the selection blue).

---

## 17. The things not to do, and how the design prevents them

| Don't | Enforced by |
|---|---|
| design around a blank note editor | the note is a compiled view; the canvas opens on the card, not the editor |
| treat the note as the clinical state | Overview and card read structured state; the note is a door |
| treat diagnosis codes as the representation | codings are facets (v2 §3); the representation is its own stratum |
| require a diagnosis to create a concern | one-field concern entry; `epistemic: finding` is valid |
| force chain-of-thought | three authored artefacts only (§6) |
| expose AI reasoning as clinician reasoning | pencil/ink; unattested representation never cited |
| enormous mandatory differentials | hypotheses are optional focuses; a card with zero alternatives is normal |
| alerts for every deviation | §13; interruptive list is closed |
| duplicate data between modules | one home, lenses |
| hide provenance | stamp visible, evidence one tap, never hover-only |
| overwrite prior interpretations | every revision is an event; the thread shows them |
| flatten uncertainty | the epistemic ladder and `standing`, no binaries |
| bury trajectories in notes | the corridor on the hero timeline; the thread |
| assume more data is better understanding | budgets on every view; the card's collapse rule |

---

## 18. The example card, on pt_002 (frame 2)

```
Blood pressure above goal                       working · active · worsening · unexpected rate
Concern, steward Dr. Chen · onset Jan 2026 · with T2DM

Representation  (proposed by the system, 15 Sep · Accept · Edit)
  55F with T2DM and hypertension on hydrochlorothiazide alone, blood pressure 128/80 → 154/94
  over twelve months with new albuminuria (ACR 18 → 48), rising from the month daily ibuprofen
  began, May 2026; home readings in the 150s over 90s.

Assessment  (Dr. Chen, 15 Sep)
  Above goal on one agent, with a daily NSAID she did not think to mention and new albuminuria
  in a diabetic. Stop the ibuprofen, add an ACE inhibitor for the albuminuria as much as the
  pressure, and let the home log tell us how much was the NSAID.

Supporting                                      Doesn't fit
  + systolic 128 → 142 → 148 → 154, 12 mo          − no home log on the chart: the "150s" are recalled
  + ACR 18 → 48 mg/g (2 Aug)                        ○ diastolic 80 → 94 began before May, when the
  + ibuprofen daily since May (note, 15 Sep)            ibuprofen started
  + home readings 150s/90s (patient-reported)

Alternatives
  leading    NSAID-driven rise · discriminator: home log four weeks off ibuprofen · not ordered
  competing  Diuretic alone no longer enough · discriminator: response to lisinopril · pending
  unlikely   White-coat component · discriminator: home log vs office · not ordered

Plan
  therapeutic  stop ibuprofen (signed)             monitoring   home BP log, goal under 140/90 in 4 wk (signed)
  therapeutic  start lisinopril 10 mg daily (signed)  diagnostic   BMP in 2 weeks (signed)
  education    acetaminophen for the back           referral     physical therapy (signed)

Expected     systolic under 140 within four weeks off ibuprofen and on lisinopril
Reassess if  still above 140 by 13 Oct → adherence and home cuff first, then a second agent ·
             potassium above 5.5 or creatinine up 30% on the two-week BMP → hold lisinopril, same day

Changed since 11 Jul
  systolic 148 → 154 ▲   ibuprofen revealed, daily since May   ACR 18 → 48, new albuminuria

[Review evidence] [Update assessment] [View trajectory] [Add to plan] [Alternatives · 3]
```

Every value is a real one from `data/patients/pt_002.json` or `data/notes/note_demo_102.json`.
The `−` line and the `○` line are the contradiction and mismatch checks from §11, and they are
the most important lines on the card: the home readings the plan depends on are not on the chart
yet, and the diastolic was already climbing before the ibuprofen started, so the NSAID is not
the whole story.

---

## 19. Screen test

Every screen in the mockups was checked against the brief's eight questions:

| Question | Frame 1 Overview | Frame 2 Card | Frame 3 Trajectory | Frame 4 Insight | Frame 5 Thread |
|---|---|---|---|---|---|
| helps form or update the mental model | yes | yes | yes | yes | yes |
| reduces reconstruction | ranked deltas | four-line collapse | corridor | evidence first | folded events |
| preserves uncertainty | epistemic chips | ladder, standing | discordance mark | word bands | pivots kept |
| exposes relationships | row actions from loops | valence, alternatives | bands on one axis | cites | causes of revision |
| shows change, mismatch, trajectory | yes | changed since | yes | mismatch kind | yes |
| keeps evidence apart from interpretation | mono vs sans | three objects | series vs marks | anatomy order | quotes vs rationale |
| fast recognition, deeper analysis on demand | five lines | doors | zoom | drawer | drawer |
| reasoning without exhaustive explanation | none asked | one sentence + prose | none | impression only | rationale optional |

---

## 20. What this changes in the plan

Nothing in the sequencing moves. The additions land inside PRDs that already exist:

| Addition | Lands in | Size |
|---|---|---|
| `epistemic` ladder, `acuity`, `priority` | PRD-03 (focus model) | half a day |
| `representation` stratum with qualifiers, proposal + accept/edit | PRD-03 model, PRD-05 proposal, PRD-04 card | two days |
| hypotheses (`kind: hypothesis`, `alternative_for`, `standing`, discriminators) | PRD-03 | one day |
| `expected[]`, `reconsider_if[]`, `expectation.evaluated` rule | PRD-03 §5 surveillance | one day |
| new edge types and `valence: unexplained` | PRD-03 §6 edge registry | half a day |
| insight kinds and the seven-part anatomy | PRD-04 §1, PRD-05 | one day |
| `what_changed` ranking rule | PRD-08 view spec | half a day |
| expectation corridor and reasoning marks on the timeline | `Timeline.tsx`, before or after PRD-10 | one day |
| the problem card and the reasoning thread | PRD-10 Care tab, focus workspace | three days |
| Overview top half | PRD-08 `clinician_glance` + PRD-10 | two days |

Roughly twelve days on top of the existing estimates, most of it UI. The first demonstrable slice
that needs no substrate work is the **card-first workspace over the current JSON chart**, and a
first cut of it is built: `ehr/card.py` computes the card and the **Card** view renders it with
proposals in their slots; `ehr/overview.py` computes the Level 1 screen (frame 1) with the §9
ranking and the **Overview** view renders it, both with explanations around them (README, "Run
the app"); the expectation corridor of §10 is drawn on the trajectory. The **Note** view makes
the note a signed thing on the record (§14): the text with every passage the reading used marked
in it, one signature that commits what was not rejected, and `ehr/record.py` reading the ledger
of §3 back off provenance and review stamps. Plan items (§2, `plan_`) are extracted from the
assessment and plan and signed with the note. The demo patient is now Jeane Lueilwitz, diabetes
and hypertension, curated by `scripts/curate_pt_002.py`. The frame follows the NDE care
mockup (session tabs, practice bar, patient header with one computed next action, Overview ·
Timeline · Care · Chart); Care carries problem cards with plan, measures and open loops and
kind-pivot chips; the workspace follows the CPOR problem view (evidence spine, proposal
banners, summary stack, authored assessment, surveillance and linked cards); consequential
proposals open the review drawer with the three-part anatomy and the what-changes table; the
note is the encounter canvas with the clinical diff and a panel rail. The **Notes** tab lists the
notes on file by state, each row's button the next thing owed on it, scoped to the patient or to
all my patients; the header button's idle state is the clinician's documentation debt ("Unsigned
notes · n") before it is "Visit signed". `jobs-to-be-done.md` maps the jobs of seven roles onto
what is built; outside primary care almost nothing is. The **visit note** is compiled from the
encounter's decisions (`ehr/draft.py`): the transcript verbatim, then an assessment and a plan per
problem addressed, every sentence citing the record, edited and signed by the clinician (§14 the
other way round: the chart writes the note). What remains unbuilt is
persistence of the accepted representation and assessment, and alternatives, which need the
appendix's schema additions. In full: the
representation and assessment as fields on the existing problem, `expected` as a field on the
`monitors` link, proposals rendered into the card's slots from the existing queues, the timeline
mounted as the card's trajectory section. The current three-pane desk is not extended; it is
replaced by the card, and the recorded demo flow (note → proposals → sign → insight → orders →
referral) plays through the card unchanged.

---

## 21. v2: what the build taught the design (17 September 2026)

The first build followed this document screen for screen and came out heavier than a clinician would tolerate. v2
(`v2/README.md`, served at `/v2/`) keeps the model and drops most of the surface. What changed, and why:

- **The gate comes before the card.** §7's Level 1 was "what changed". In use, the first question is simpler: which
  problems are in good standing and which are not. Standing is computed by rules on every request (off course, watch,
  in good standing, not monitored), with one line of why and one of what is next. The seven questions of §19 are then
  the problem page itself, in order, rather than a test the page is scored against.
- **One signature.** §12 asked for observation and attribution to be separately signable, and the build asked for a
  signature on proposals, insights, acknowledged changes and plan lines. Providers sign notes. Everything else is now
  accepted, agreed, noted or added, and the visit note is the one signature; it lists what it attests, its text is
  compiled from that list, and each accepted item is stamped with the note that attested it (`attested_in`).
- **The chart writes the note.** §14 said documents come from the model. The visit note is compiled from the
  encounter's decisions: the dictated history verbatim, the dictated assessment and plan folded, then per problem an
  assessment and a plan, each sentence citing the record. The clinician edits, adds their own words, and signs.
- **Three kinds of suggestion, kept apart** (§11, §13): best practice as sourced rules with a gap or covered state;
  the model's reasoning; and projection, which is §2.3's expectation with a magnitude and a band, generated for
  options before one is chosen. The current plan's projection is the corridor of §10, and the next value tests it:
  within, better, or missed. Ranges from published average effects, never probabilities (§12).
- **Vocabulary is the provider's.** Problem, summary, your assessment, what we are watching, related on the chart.
  Concern, representation, epistemic state, surveillance and ledger remain the model's words in this document and do
  not appear on screen.
- **Decisions are few.** A problem raised, a cause asserted, a change to a course on the chart. Everything else the
  reading found is accepted when the review is closed.

Still not built, and still wanted: alternatives with discriminators (§2.2), the impression before the reveal (§12),
goals as first-class objects (they are constants in three places), and calibration of projections to the patient's
own responses.

---

## 22. v3: the visit in the order a clinician reasons (18 September 2026)

A follow-up visit is management reasoning more than diagnosis, and it runs in a fairly fixed order: orient (why here,
what changed, which problems, what is missing), gather (history, exam, results, testing hypotheses as they go),
represent (one line per problem), link (one cause across two problems, one decision serving two), decide, set
expectations (what should happen, by when, what would make us change course), close the loop (what was not touched).
The note should record that reasoning; the common failure is a note that records the data and leaves it out.

v3 now supports each step where it happens and has each one write its own part of the note — the table is in
`v3/README.md`. The design consequences worth keeping:

- **The note is written alongside the reasoning, not after it.** It compiles from what has been spoken so far and grows
  through the visit. A note that appears only at the end turns documentation back into a separate task.
- **Expectations belong in the note.** A drug started today that is expected to push a value the wrong way (lisinopril
  and creatinine) is reasoning the next reader needs; left on a screen, a creatinine of 1.0 next month reads as harm.
- **Silence is not a decision.** A question the clinician did not answer must not be written into the note as a
  rejection. It was, in every signed note, until walking the visit step by step made it visible.
- **Best practice is a checklist against the plan as it stands**, consulted at the moment of deciding, and never
  written into the note. What the dictation covered reads as covered; what is left is what to add before signing.
- **The signature closes a finished note.** A clinician does not sign halfway through dictating.

## Appendix: schema additions to flag (for `schema-v2-proposal.md`)

All additive. None adopted until the team agrees.

1. **ClinicalFocus**: `epistemic` (replaces `lifecycle` + `certainty`), `acuity`, `priority`,
   `representation {text, qualifiers[], tier, asserted_by, as_of_event, cites[]}`,
   `standing` and `discriminators[]` when `kind: hypothesis`,
   `surveillance.expected[]`, `surveillance.reconsider_if[]`.
2. **Focus kinds**: add `hypothesis`.
3. **Edges**: add `alternative_for` (hypothesis → focus), `explains`, `may_contribute_to`,
   `associated_with`; `valence` gains `unexplained`.
4. **Provenance**: `asserted_by.kind` gains `inferred_by_ai`, `inferred_by_clinician`;
   observation provenance vocabulary fixed to `measured | patient_reported |
   clinician_documented | imported | historical`.
5. **Insight**: `kind: mismatch | discriminator | missing | contradiction | synthesis`,
   `against[]`, `unknown[]`, `would_change_if`, `confidence_band`.
6. **Order / plan item**: `plan_kind`.
7. **Events**: `representation.revised`, `problem.epistemic_changed`,
   `hypothesis.standing_changed`, `expectation.evaluated`, `assessment.recorded`.
