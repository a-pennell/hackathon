# A clinical-reasoning-centred EHR: design

**Status:** design for team discussion, 15 September 2026. Nothing here is built. It extends the
target architecture already chosen (`docs/roadmap/00-north-star-and-gap-analysis.md`, the twelve
PRDs, `docs/roadmap/schema-v2-proposal.md`) rather than replacing it. Every schema change it
needs is listed in the appendix and flagged; `docs/patient-model-schema.md` is unchanged.

**Companion:** the screen mockups, drawn on pt_001's real values, are published as the
"Reasoning Chart" artifact and referenced by frame number below.

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

A concern is a `ClinicalFocus` (v2 §3). It may begin as "fatigue" or "declining kidney function"
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
`carries_forward`. So "Declining kidney function" can be `kind: concern, epistemic: syndrome,
status: active` and later become `kind: problem, epistemic: working` with the title
"CKD progression, NSAID-accelerated", as a recorded transition with a rationale, never an
overwrite (paper §6.3). The UI renders `epistemic` as one chip beside the name and never asks
for it at creation; a raised concern starts at `finding` or `syndrome`.

No numeric probabilities on hypotheses. The paper's argument (§6.3, A.2) holds: clinicians will
not author them, a versioned probability register is the most discoverable artifact, and the
machine reads hedged prose perfectly well. Certainty is the ladder position plus the assessment.

### 2.2 Hypotheses and discriminators

A differential is not a list. Each alternative is a small focus:

```json
{ "id": "prob_h_0057_02", "kind": "hypothesis", "name": "Assay or specimen discrepancy",
  "standing": "competing | leading | unlikely | dismissed",
  "epistemic": "possible", "steward": {...},
  "discriminators": [ { "code": "2160-0", "label": "Repeat serum creatinine, single lab",
                        "would_show": "concordant value near 5.7 confirms; near 2.0 reopens",
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
    { "statement": "Creatinine falls within two weeks off naproxen if the hemodynamic component is real",
      "parameters": [ { "code": "38483-4", "direction": "falling", "by": "2026-09-25" } ],
      "set_by": "usr_chen", "at": "2026-09-11T…", "from_insight": "ins_0057_02" } ],
  "reconsider_if": [
    { "trigger": "no fall in creatinine by 2026-09-25", "then": "renal ultrasound; nephrology now, not routine",
      "parameters": [ { "code": "38483-4", "test": "not_falling", "by": "2026-09-25" } ] },
    { "trigger": "potassium above 5.5", "then": "same-day review", "parameters": [ { "code": "2823-3", "test": "gt", "value": 5.5 } ] } ],
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
  "text": "59M with T2DM, HFrEF and CKD 3, creatinine 1.6 → 5.7 over twelve months with eGFR now 15.6, rising from the month daily naproxen began, October 2025; three weeks of fatigue, nausea and poor appetite. Still on metformin 500 mg.",
  "qualifiers": ["chronic", "progressive", "worsening", "unexpected_rate"],
  "tier": "proposed | attested", "asserted_by": {...}, "as_of_event": "evt_…",
  "cites": ["obs_243df5cd", "obs_7f3ce7a6", "med_demo_002_01", "note_demo_002"]
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

| Layer | Object | Example on pt_001 | Provenance vocabulary |
|---|---|---|---|
| Source finding | Observation event | Creatinine (whole blood) 5.7 mg/dL, 19 Aug | `measured`, `patient_reported`, `clinician_documented`, `imported` (outside record), `historical` |
| Interpretation | Edge with valence, or a representation qualifier | `relevant_to` CKD, valence `for`; "worsening" | `asserted` (clinician), `ai_proposed`, `harvested` (rule) |
| Clinical inference | Insight, hypothesis, `caused_by` edge | "Naproxen is a suspected contributor" | `inferred_by_ai`, `inferred_by_clinician`, with model or user id |

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

The two creatinine series on pt_001 (whole-blood 38483-4 at 5.7, serum 2160-0 at 1.94, same
date) plot as two series with a discordance mark, never averaged (P9). That discordance is
exactly the kind of "doesn't fit" the card must show.

---

## 11. Decision support that interrogates the model

CDS is not an alert layer. It is four kinds of insight, each a `proposal.raised` with the
observation / attribution / confidence anatomy (PRD-04 §1), each attached to the focus it
concerns, each quiet until the clinician turns to it:

| Kind | Question it asks | Trigger | pt_001 example |
|---|---|---|---|
| `mismatch` | What does not fit the current explanation? | `expectation.evaluated: missed`; new `valence: unexplained` finding | whole-blood creatinine fell to 3.69 in May while naproxen continued daily; serum creatinine flat at 1.9 while whole-blood reads 5.7 |
| `discriminator` | Which evidence would separate the competing hypotheses? | two or more hypotheses with `standing: competing` and no resolved discriminator | a repeat serum creatinine and BUN from one lab separates "true stage 5" from "assay discrepancy" |
| `missing` | What information would materially change the decision? | a plan or hypothesis whose discriminator is `not_ordered` or `unavailable` | no renal imaging on record; no urine albumin since November |
| `contradiction` | What in the record disagrees with itself? | rule checks across diagnosis ↔ findings, medication ↔ problem state, plan ↔ goals, expected ↔ observed, steward ↔ steward | metformin 500 mg active with eGFR 15.6; CKD labelled stage 3 with eGFR 15.6 |

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

One object, one home, many lenses (PRD-10). Nothing is duplicated between views; a card on the
Overview is a lens on the same focus that Care shows. The four tabs and the Care/Chart boundary
are unchanged from `patient-ia-v2-proposal.md`; this design fills the Care tab's problem card and
the Overview's top half.

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

## 18. The example card, on pt_001 (frame 2)

```
Declining kidney function                      working · active · worsening · unexpected rate
Concern, steward Dr. Chen · onset Nov 2025 · chronic care programme (CKD, HFrEF, T2DM)

Representation  (proposed by the system, 11 Sep · Accept · Edit)
  59M with T2DM, HFrEF and CKD 3, creatinine 1.6 → 5.7 over twelve months with eGFR now 15.6,
  rising from the month daily naproxen began, October 2025; three weeks of fatigue, nausea and
  poor appetite. Still on metformin 500 mg.

Assessment  (Dr. Chen, 11 Sep)
  Most consistent with NSAID-accelerated progression of established CKD, now in the stage 5
  range, with early uremic symptoms. I am not ready to restage until the two creatinine assays
  agree.

Supporting                                      Doesn't fit
  + creatinine (whole blood) 1.62 → 5.7, 12 mo     − serum creatinine 1.94, flat over the year
  + eGFR 15.6 (19 Aug), from 55.45                 − BUN 17.3, flat; unusual beside a true 5.7
  + naproxen daily since Oct 2025 (note, 11 Sep)   ○ fell to 3.69 in May while still on daily
  + fatigue, nausea, poor appetite × 3 wk              naproxen

Alternatives
  competing  Assay or specimen discrepancy · discriminator: repeat serum creatinine + BUN, one lab · ordered
  competing  Hemodynamic AKI on CKD (lisinopril + furosemide + NSAID) · discriminator: response to stopping naproxen · pending
  unlikely   Obstruction · discriminator: renal ultrasound · not ordered

Plan
  therapeutic  stop naproxen (signed)              diagnostic  creatinine + BUN, single lab (signed)
  therapeutic  stop metformin (signed)             referral    nephrology, urgent (signed)
  monitoring   creatinine, potassium every 2 weeks

Expected     creatinine falls within two weeks off naproxen if the hemodynamic component is real
Reassess if  no fall by 25 Sep → renal ultrasound, nephrology now · potassium above 5.5 → same day

Changed since 29 Jul
  creatinine (whole blood) 4.38 → 5.7 ▲   naproxen revealed, daily since last October   symptoms new: fatigue, nausea

[Review evidence] [Update assessment] [View trajectory] [Add to plan] [Alternatives · 3]
```

Every value is a real one from `data/patients/pt_001.json` or `data/notes/note_demo_002.json`.
The two "doesn't fit" lines marked `−` and the `○` line are the contradiction and mismatch checks
from §11, and they are the most important lines on the card: they are what a reader of four
encounter notes would miss.

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
that needs no substrate work is the **card-first workspace over the current JSON chart**: the
representation and assessment as fields on the existing problem, `expected` as a field on the
`monitors` link, proposals rendered into the card's slots from the existing queues, the timeline
mounted as the card's trajectory section. The current three-pane desk is not extended; it is
replaced by the card, and the recorded demo flow (note → proposals → sign → insight → orders →
referral) plays through the card unchanged.

---

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
