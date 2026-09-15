# Schema v2 proposal — flagged, not applied

**Status:** proposal for team agreement. `docs/patient-model-schema.md` (v1) is unchanged and still
governs the code. Nothing in this file is adopted until the team signs off; every PRD in `docs/prd/`
that needs a v2 shape says so and names the section here.

**Source of the target model:** the NDE documentation set (`~/Projects/NDE/docs`): `data-model.md`,
ADR 0001–0003, `ontology-evolution.md`, `beyond-the-pomr.md` Appendix A/B, `longitudinal-capabilities.md`
§0 and §4, `cpor-migration-and-ia.md` §3, `patient-ia-v2-proposal.md`, `slice-1-spec.md`.

**Design rule for v2:** v1 entities keep their ids, prefixes and file shapes. v2 adds an event layer
underneath them and a small number of new entity kinds beside them. Every v1 chart must round-trip:
import v1 → events → fold → v1-shaped chart, byte-for-byte on the fields v1 defines.

---

## 0. The ten kinds (taxonomy legend)

Every noun in every PR must be one of these ten (`ontology-evolution.md` §0). Nothing else gets added.

| Stratum | Kind | Rule |
|---|---|---|
| Stored | **Object** | has identity: one id, one URL, one home, a biography. Only objects get ids users return to. |
| Stored | **Composite object** | an object whose body is mostly references (the encounter+note). |
| Stored | **Event** | append-only, provenance-stamped fact about one object. Only events get written. |
| Stored | **Edge** | typed, provenance-stamped link between two objects (v1's `Link`). |
| Derived | **View** | recomputed from storage; no identity; never edited (TrendSummary, brief, coding, trail, Overview, Work queue, context packet). |
| Shown | **Surface** | page, pane, drawer, canvas slot; owns no data. |
| Shown | **Module** | code that renders objects onto a surface under the mount contract. |
| Shown | **Route** | any path to an object's URL; creates and copies nothing. |
| Shown | **Badge** | rendering of a **flag** (computed: unsigned, overdue, stale) or an **attribute** (authored: tier). Never a place. |
| Done | **Verb** | authority-scoped operation that produces events; the only thing that writes. |

Deliberately *not* kinds: the knowledge/policy plane (guidelines, formularies, payer rules), actors
(callers), and context compilation (a view).

---

## 1. Event (new; Layer 1, the ledger)

The chart file stops being the source of truth. An append-only, bi-temporal event log is. The v1
chart becomes a **projection**: fold the events and you get `{patient, problems, observations, …}`.

```json
{
  "id": "evt_000123",
  "patient_id": "pt_001",
  "kind": "observation.recorded",
  "occurred_at": "2026-08-19T09:15:00-04:00",
  "recorded_at": "2026-08-19T09:16:02-04:00",
  "actor": { "kind": "clinician", "id": "usr_chen", "name": "Dr. Chen" },
  "source": "fhir_import | manual_entry | nlp_extraction | reasoning | composition | ordering | ambient | review | system",
  "subject": "obs_7f3ce7a6",
  "payload": { "...": "the v1 entity, or the delta, verbatim" },
  "supersedes": null,
  "caused_by": "evt_000122",
  "schema_version": 2,
  "hash": "sha256:…",
  "prev_hash": "sha256:…"
}
```

- `occurred_at` vs `recorded_at` is load-bearing (late results, amendments). v1 has one timestamp.
- `supersedes` implements corrections; nothing is deleted. Entered-in-error is an event.
- `caused_by` links a verb's output to the proposal or review event that triggered it.
- Narrative enters verbatim as `narrative.received` events (a note, a transcript). The extraction
  pipeline reads them and never replaces them.
- Hash chain is optional per deployment; the demo turns it on so "hash-linked note" is real.
- Storage: SQLite table `events`, insert-only (UPDATE/DELETE revoked), one file per deployment,
  `patient_id` indexed. JSONL export per patient for git-friendly fixtures.

**Event kinds (initial vocabulary, one per verb output):** `patient.registered`, `problem.raised`,
`problem.status_changed`, `problem.recoded`, `problem.merged`, `problem.steward_transferred`,
`observation.recorded`, `observation.corrected`, `medication.segment_opened`,
`medication.segment_closed`, `medication.discontinued`, `encounter.opened`, `encounter.signed`,
`encounter.amended`, `narrative.received`, `edge.asserted`, `edge.retracted`, `proposal.raised`,
`proposal.decided`, `insight.raised`, `order.placed`, `order.fulfilled`, `order.cancelled`,
`document.composed`, `document.signed`, `workitem.raised`, `workitem.assigned`, `workitem.deferred`,
`workitem.completed`, `risk.assessed`, `goal.set`, `goal.progress_overridden`,
`context.opened`, `context.closed`, `context.discharged`, `impression.recorded`, `review.dwelled`.

---

## 2. Claim anatomy (new fields on every belief-layer entity)

Every problem, observation, medication, edge, insight, order, document, goal, risk is a **claim**
(`data-model.md` §1). v2 adds four fields to each; v1's `status`/`provenance` stay and map onto them.

```json
{
  "tier": "proposed | acknowledged | attested | entered | auto_applied",
  "asserted_by": { "kind": "clinician | patient | reconciliation_engine | rule | import", "id": "…" },
  "version": 3,
  "evidence": [ { "event_id": "evt_000098", "span": { "start": 412, "end": 471 } } ]
}
```

- **Tier ladder.** `proposed` (machine, unreviewed) → `acknowledged` (seen, not signed) →
  `attested` (signed by the steward). `entered` = born-attested typed entry (vitals, PHQ-9).
  `auto_applied` = low-stakes batchable mutation (summary refresh, harvested edge) that is
  spot-audited, never individually signed. v1 `status: proposed` ⇒ `tier: proposed`;
  v1 `status: accepted` with `provenance.source: fhir_import` ⇒ `tier: entered` (badged
  "imported, unverified" until a clinician touches it: `eng-faq.md` "How would migration work").
- **Evidence spans** generalise v1's `note_id + quote`: the quote stays (human-readable) and gains
  a stable offset into the narrative event. "No cited span, no proposal" is enforced by the validator.
- **Version** increments on every event that touches the entity; the biography is the event list.
- **Consumption** (which views/orders/documents read this claim, when) is a derived index, not stored
  on the claim; needed for claim recall (PRD-08).

---

## 3. Problem → ClinicalFocus (extended, not renamed in files)

v1 `Problem` keeps its `prob_` prefix and its file key `problems`. It gains:

```json
{
  "kind": "problem | concern | symptom_cluster | goal | risk | watch_item | question",
  "status": "active | recurrence | relapse | remission | inactive | resolved | refuted",
  "carries_forward": { "value": true, "by": "usr_chen", "at": "…", "reason": "post-mastectomy, no left-arm BP" },
  "lifecycle": "suspected | working | established | resolved",
  "certainty": "low | moderate | high",
  "steward": { "id": "usr_chen", "since": "…" },
  "concern_state": "open | matured | dissolved | re_attested",
  "surveillance": {
    "parameters": [ { "code": "38483-4", "threshold": { "delta_pct": 25, "window": "90d" } } ],
    "review_horizon": "P90D",
    "notify": "steward"
  },
  "codings": [
    { "system": "SNOMED-CT | ICD-10 | patient_friendly", "value": "N18.4",
      "verification": "working | confirmed | refuted", "purpose": "clinical | billing | patient",
      "asserted_in": "enc_0093", "tier": "attested" }
  ],
  "summary_stack": { "one_liner": "…", "paragraph": "…", "narrative": "…", "stale": false, "as_of_event": "evt_…" }
}
```

- **Diagnosis is not a table.** v1's single `code` becomes `codings[]`; re-coding edits identity in
  place (`problem.recoded`), a status change appends (`problem.status_changed`).
- **Hierarchy is an edge (`manifestation_of`), never a `parent_id`.** Clusters are computed per view.
  This is the fix for the four-CKD-stage-problems symptom flagged in `docs/ui-critique.md`.
- **Recurrence is a status, not a new entity.** The importer's "one Problem per Synthea Condition"
  decision (flagged decision 7) becomes a merge proposal, individually attested.
- **Exactly one steward** per focus, always; transfers are events; orphans raise a WorkItem.
- **Concern** is where medicine starts; a concern must mature, dissolve with a rationale, or be
  re-attested. `kind: risk` carries `RiskAssessment` history (§7).
- **Surveillance spec** is the forward-looking half: the reasoning layer evaluates tripwires before
  any model runs.
- `summary_stack` is cached view output stored *with* the object for invalidation bookkeeping; it is
  never authoritative and is regenerated from events (Appendix B.2 of the paper).

---

## 4. Link → Edge (extended)

v1 `Link` keeps `lnk_` and the file key `links`. v2 widens the vocabulary and adds edge provenance.

| v1 type | keeps | v2 additions |
|---|---|---|
| `relevant_to` | yes | `valence: for | against` |
| `treats` | yes | `addresses` alias for orders/plans |
| `evidence_for` | yes | `valence` |
| `suspected_cause` | yes | rename target `caused_by` (direction: effect → cause) with `confidence` |
| `monitors` | yes | unchanged; `from` = `"LOINC:<code>"` (flagged decision 2, now adopted) |
| — | new | `manifestation_of` (problem → problem), `complicates`, `rules_out`, `affects` |
| — | new | `fulfills` (result → order, letter → referral) |
| — | new | `documented_in` (anything → encounter) |
| — | new | `anchored_to` (workitem → object) |
| — | new | `addresses` (care context / goal / order → focus) |

```json
{ "id": "lnk_0301", "from": "obs_0042", "to": "prob_0057", "type": "relevant_to", "valence": "for",
  "edge_provenance": "harvested | asserted | ai_proposed | confirmed",
  "proposal": { "observed": "…", "inferred": "…", "model": "claude-opus-5@2026-09", "reasoned_over": ["evt_…"],
                "disposition": { "decision": "confirmed | amended | rejected", "by": "…", "at": "…" } },
  "tier": "attested", "created_by_event": "evt_000140" }
```

The `proposal` block is the **proposal-with-disposition** pattern (`ontology-evolution.md` §5). It is
one pattern for edges, status changes, orders and work items; v1's `review` record is its
disposition half and is kept verbatim inside it.

---

## 5. Encounter + Note → one composite (extended)

v1 `Encounter` and `Note` keep their ids. v2 makes the note the encounter's body and adds what
ADR 0003 needs:

```json
{
  "id": "enc_0093", "patient_id": "pt_001", "time": "…", "type": "office visit", "summary": "…",
  "occasion": "visit | phone | message | results_review | care_coordination | no_show",
  "modality": "in_person | telehealth", "visit_type": "problem | preventive | procedure",
  "provider": "usr_chen",
  "care_contexts": ["ctx_0002"],
  "diagnosis": [ { "focus_id": "prob_0057", "rank": 1, "inferred": true } ],
  "note": {
    "id": "note_0011", "status": "draft | signed | amended",
    "sections": [ { "heading": "Assessment", "body": "…prose with {{chip:obs_7f3ce7a6}} references…" } ],
    "references": ["obs_7f3ce7a6", "med_naproxen", "ins_0004"],
    "snapshot": { "at_sign": { "obs_7f3ce7a6": { "value": 5.7 }, "prob_0057": { "status": "active" } } },
    "signed_at": null, "signed_by": null, "hash": null, "amends": null
  }
}
```

- **References, not copies.** Chips in the body point at objects; the object stays home.
- **Copy-on-sign snapshot** of every referenced value. A signed note that read "rising" never later
  renders "falling." Amendments append a new note version with `amends`.
- `diagnosis[]` ("problems addressed today") is **inferred and correctable** (G6), never a checklist.
  `ehr/billing.py` reads it instead of re-deriving from the trail.
- v1's `notes[]` list (hand-written demo notes) continues to exist as `narrative.received` events
  whose `payload.text` is the verbatim note; a v2 note is authored *in* an encounter.
- **A blank note, typed and signed, is a complete legal document.** Extraction is never a signing gate.

---

## 6. CareContext (new, `ctx_`)

```json
{ "id": "ctx_0002", "patient_id": "pt_001",
  "type": "PRIMARY_CARE_FOCUSED | CHRONIC_CARE_PROGRAM | PT_REHAB | MENTAL_HEALTH_CASE | POST_ACUTE_TRANSITION | PREGNANCY",
  "kind": "course | acute_episode", "parent_id": null,
  "status": "open | assess | plan | treat | monitor | revise | closed",
  "start": "…", "end": null, "discharged_on": null, "discharge_summary": null,
  "managing_provider": "usr_chen", "addresses": ["prob_0057"],
  "care_plan": { "label": "Plan of care", "items": [], "goals": ["goal_0001"], "review_due": "…" },
  "risk_history": ["risk_0001"], "compliance": { "profile": "CHRONIC_CARE_PROGRAM" } }
```

- **Never forced (G1).** No-context encounters are complete. The importer creates none; a
  clinician or a proposal opens one.
- **Nesting is inferred/retrospective (G2)**; `parent_id` is the one permitted nesting because the
  rollup rule needs it: an `active` acute sub-episode ⇒ parent reads "not currently controlled."
- **Discharge ≠ lapse (G8).**
- Type behaviour lives in a **profile registry** (compliance rules, note pack, closure criteria),
  not in the object.

## 7. Goal (`goal_`), RiskAssessment (`risk_`), MedicationStatement

```json
{ "id": "goal_0001", "focus_id": "prob_0057", "statement": "keep eGFR above 20 through 2026",
  "measure": "33914-3", "target": 20, "direction": "above",
  "progress": "derived: met | improving | stalled | regressed", "manual_state": null }
{ "id": "risk_0001", "context_id": "ctx_0004", "level": "low | elevated | high", "as_of": "…",
  "assessed_by": "…", "safety_plan": "…", "stale_after": "P30D", "confidentiality": "part2 | none" }
```

- Goal progress is **derived** from the linked measure (G3); override is a provenance-bearing event.
- Risk carries as-of + attribution and surfaces **staleness**; `confidentiality` is a real gate in v2
  (PRD-12), not a stub.
- v1 `MedicationCourse` is what was *prescribed*. v2 adds `taken` segments (patient-reported, tier
  `proposed` until confirmed) so "taken vs prescribed" is a visible gap, not a silent overwrite.

## 8. Order (`ord_`) and Task/WorkItem (`wi_`)

`Order` (already flagged in README) is adopted with two additions: `fulfills` edges to results, and
`status: draft | signed | transmitted | fulfilled | cancelled` with each transition an event.

```json
{ "id": "wi_0007", "patient_id": "pt_001", "kind": "result_review | message | refill | referral | unsigned_note | proposal | charge | follow_up | risk_review | steward_orphan",
  "anchor": "ord_0003", "reason": "creatinine result back, 5.7", "status": "open | assigned | in_progress | waiting | done | cancelled",
  "owner": { "kind": "user | pool", "id": "usr_chen" }, "priority": "routine | soon | urgent", "due_at": "…",
  "depends_on": [], "suggested_by": "rule:tripwire | model:… | user:…", "completion": "acknowledged", "outcome": null }
```

- A **flag** (result overdue) is derived; a **WorkItem** is an obligation with identity and a
  biography. Not every flag instantiates an item.
- `suggested_by` and provenance are mandatory; a queue that mixes rule-raised, model-proposed and
  colleague-assigned items is unauditable without them.

## 9. Document (`doc_`) — adopted as flagged, plus view spec

README flagged shape adopted; add `view_spec_id` (which compiled view produced it), `budget`,
and `citations[]` as `{event_id, span}` pairs. Documents are compiled views frozen by a sign event.

## 10. Actor, permissions, disclosure

Not a kind. `actor` on every event; a `roles` table (clinician, staff, biller, patient, rule,
model, integration) with **verb allow-lists**; permissions are evaluated per entity, sensitivity,
consent and purpose of use, and the compiler applies them (a compiled view never leaks what its
reader may not see). Disclosure boundaries (export, records release, patient view) carry tier and
purpose on every focus ("concern — monitoring", "provisional, billed").

---

## 10a. Objects introduced by later PRDs (listed so the ten kinds stay ten)

| Object | Prefix | Introduced by | Note |
|---|---|---|---|
| Allergy | `alg_` | PRD-05 (slice-1 entity set) | pinned safety strip; entered-in-error is an event |
| Appointment | `appt_` | PRD-11 | encounter `fulfills` appointment |
| Thread / Message | `thr_` / events | PRD-11 | one URL; Work and Correspondence are lenses |
| Charge / Claim | `chg_` / `clm_` | PRD-11 | captured at sign from `ehr/billing.py`; attested-for-claim is its own event |
| Consent | `cons_` | PRD-12 | scope, expiry; Part 2 disclosure requires one |
| User / Role / Pool | `usr_` / config | PRD-12 | actors are callers, not a kind; stored as config |

## 11. What breaks, module by module

| Module | v1 assumption | v2 change |
|---|---|---|
| `scripts/import_patient.py` | writes the chart file | writes `*.registered/recorded` events with `source: fhir_import`, `tier: entered`; chart is folded |
| `ehr/review.py::accept_item` | mutates chart JSON | becomes the `decideProposal` verb; emits `proposal.decided` + the entity event; fold updates the projection |
| `ehr/extract.py` | queue file per note | proposals are `proposal.raised` events in the ledger with spans; queue = view over undecided proposals |
| `ehr/reason.py` | insight with `evidence: [ids]` | insight decomposed into observation / attribution / confidence, each separately decidable; tripwires evaluated first |
| `ehr/trend.py` | reads observations list | unchanged (reads the projection) |
| `ehr/brief.py`, `ehr/compose.py` | ad hoc context builders | both become view specs over `compileContext` |
| `ehr/orders.py` | signed insights → orders | unchanged logic; orders get `fulfills` and status events |
| `ehr/billing.py` | derives "addressed" from trail | reads `encounter.diagnosis[]` |
| `backend/main.py` reset | restores a file snapshot | truncates events after a marker id (a fold to a point in time) |
| frontend | one patient, one chart desk | multi-patient shell; chart desk becomes the *problem workspace* inside Care |

## 12. Migration of pt_001

`scripts/migrate_v1_to_events.py`: read `pt_001.json`, emit one event per entity and per medication
segment with `occurred_at` = the entity's time, `recorded_at` = migration time, `source` = the v1
provenance source, `tier` = `entered` (imported) or `attested` (v1 `review.decision == accepted`)
or `proposed`. Recordings (`*.raw.json`) become `narrative.received` + `proposal.raised` events with
`source: nlp_extraction | reasoning | composition`. Acceptance: fold(events) equals the v1 chart on
every v1 field.
