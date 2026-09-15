# PRD-03 — Clinical focus and typed edges: the record's index

**Stage:** 1 (edges) plus problem-list phases P1–P3 (`ontology-evolution.md` §2 "Diagnosis / problem").
**Depends on:** PRD-01 (events), PRD-02 (verbs) for anything that writes.
**Schema:** v2 §3 (ClinicalFocus), §4 (edges).

## Why

The hackathon problem list is a flat import of Synthea Conditions: four CKD-stage problems, one
`code`, one `status`, no owner, no forward-looking half. The consequences are already visible
(`docs/ui-critique.md`: signing one creatinine link "addresses" four problems). The target model
says a problem is a **versioned hypothesis-object with a lifecycle, a steward and a surveillance
spec**; diagnosis is a coded facet, not a thing; hierarchy is an edge computed at read time, never
a stored parent; ambiguity gets a first-class home as a **concern**; and the problem list and the
past medical history are **two views over one store** distinguished by status and carries-forward
(paper §6.3, A.2; `longitudinal-capabilities.md` §0; `cpor-migration-and-ia.md` §3 "Problems and
past medical history"; NDE commits `e2e28f7`, `796eacc`). The edges are what make the record
traversable: "a graph with no edges compiles into a pile of documents" (`ontology-evolution.md` §1).

## Goal

Problems become clinical focuses with codings, status, carries-forward, steward, concern lifecycle
and surveillance. Links become typed, provenance-bearing edges with a capped vocabulary. Clusters
and history are computed views. The four CKD problems become one problem with a status history.

## Scope

**In**
1. **Focus kinds.** `kind: problem | concern | symptom_cluster | goal | risk | watch_item | question`.
   UI labels stay "Problem", "Concern", "Goal", "Risk", "Watch item" (`cpor-design-notes.md` term
   table). Concern entry is one field of friction; promotion to problem carries an attestation
   ceremony (`patient-ia-v2-proposal.md` §2 "friction placement is policy").
2. **Status and carries-forward.** `status: active | recurrence | relapse | remission | inactive |
   resolved | refuted`; `carries_forward` is an explicit, human-set, provenance-bearing attribute.
   Three prohibitions enforced by the verbs: no independent write path into history, no free-text
   PMH block, recurrence is a status not a new entity.
3. **Codings as facets.** `codings[]` with system, verification, purpose, tier. `recodeProblem`
   edits in place; `updateProblemStatus` appends. Purpose-qualified attestation: attested-for-claim
   (at the pre-sign gate, PRD-06) is a different act from attested-as-clinical-conviction, and the
   biography records which. Billed and clinical codes may diverge and no surface renders that as an
   error.
4. **Steward.** Exactly one per focus; default = importing clinician for imported, author for
   raised; `transferSteward` is an event; an orphan raises a `steward_orphan` WorkItem (PRD-09).
5. **Surveillance spec.** Per focus: parameters (LOINC), thresholds (delta %, absolute, ref-range
   crossing), review horizon, notify. Seeded from `MONITORS_TABLE` for imported problems. The
   reasoning layer (PRD-05/08) evaluates tripwires against every new observation event *before*
   any model runs; a tripwire hit raises a proposal or a WorkItem with `suggested_by: rule:tripwire`.
6. **Edges.** Vocabulary from schema §4, capped; a new type needs a written argument. Edge
   provenance `harvested | asserted | ai_proposed | confirmed`; `ai_proposed` carries the proposal
   block. Importer harvests `treats` (from `reasonReference`), `monitors` (table), `documented_in`
   (encounter membership), `fulfills` (DiagnosticReport → order where present).
7. **Derived structure.** `ehr/focus_views.py`: `active_list(patient, lens)`, `history_view(patient)`
   grouped by *why* an item is there (resolved, remission, procedural, ended), `clusters(patient,
   lens)` from `manifestation_of` edges one level deep with member counts, `current_status(focus)`
   including the care-context rollup (PRD-07). Which problem leads a cluster is a per-view argument.
8. **Merge as a proposal.** `mergeProblems` is consequential, individually attested, never
   automatic; the importer emits merge *proposals* for Synthea's stage-per-Condition CKD entries
   instead of four problems. Uncertain resolution creates a new node plus a proposed link, never a
   silent guess (paper B.2 entity resolution).
9. **Summary stack** per focus (one-liner, paragraph, narrative), script-shaped, cached with
   `as_of_event`, invalidated when an event touches the focus or its edges; regeneration in PRD-08.

**Out**
- Body-system grouping (a derived facet with 58.7 % specificity; not worth a lane now).
- Automatic promotion of symptoms to problems (system-assisted prompt only: "coded at 3 visits,
  add to the list?").

## Design rules (binding)

- No focus stores a `parent_id`. `manifestation_of` is a DAG; indentation is one level deep.
- A collapsed cluster always shows its member count.
- Every problem in a cluster is independently addressable: its own route, steward, courses.
- Structure is not comprehension: Timeline and Chart views stay first-class beside the
  problem-ordered view (Bossen's fragmentation finding, cited in the paper §6.3).

## UI (in the existing chart desk, before the IA lands)

- Problem list gains: kind chip, status, steward initials, carries-forward band under the active
  list, cluster indent with count, "raise a concern" affordance (one field).
- Problem header gains the one-liner from the summary stack and the surveillance line ("watching
  creatinine, eGFR; review by 15 Dec").
- Edge chips show valence and provenance (harvested vs proposed vs confirmed) using the existing
  pencil-vs-ink grammar.

## Acceptance

1. Re-import pt_001: one CKD problem with a status history and a proposed merge for the four
   Synthea entries; `active_list` shows CKD once; coding panel counts one problem addressed.
2. Raise a concern in one field; it appears with `kind: concern`; promoting it to a problem requires
   the attestation step and records both events.
3. A creatinine observation crossing the CKD tripwire raises a rule-suggested WorkItem before any
   model call.
4. `history_view` shows a resolved condition with `carries_forward: true` in the subordinate band of
   the active list and in the grouped history, from one store.
5. Adding a sixth edge type without a registry entry fails validation.

## Estimate

Four days: two for the model and verbs, one for the importer changes, one for the list/cluster
views and chart-desk UI.
