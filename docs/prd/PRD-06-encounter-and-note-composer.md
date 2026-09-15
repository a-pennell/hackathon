# PRD-06 — The encounter and the note composer

**Depends on:** PRD-01, 02, 03; PRD-05 for extraction into the composer; PRD-07 for the context panel.
**Schema:** v2 §5 (Encounter + Note composite).

## Why

ADR 0003 is the most fully specified document in the NDE set and the hackathon has none of it:
encounters are thin markers, the demo notes are inputs only, there is no composer, no sign, no
snapshot, no amendment, and "problems addressed today" is inferred from the review trail for
billing. The target: **the encounter is the change context, the note is a composition that
references objects and never owns them, it is frozen at sign with a copy-on-sign snapshot, and a
blank note typed and signed is a complete legal document** (ADR 0003 decisions 3–4, G4, G6;
`cpor-migration-and-ia.md` "Compositions are not atoms"; Note Patterns PAT·01–08). The first
market's flagship pattern is the deliberately unread psychotherapy note (PAT·08).

## Goal

A clinician opens an occasion, sees live context, writes or accepts, and signs. Signing snapshots
what the note referenced, appends attributed entity updates, computes problems addressed today, and
produces a legacy-format SOAP rendering for the billing pipeline.

## Scope

**In**
1. **Encounter object** with `occasion`, `modality`, `visit_type`, `care_contexts[]`,
   `diagnosis[]` (inferred, correctable), and the note as its body. `openEncounter` from Today,
   Schedule, a message thread, or a results review; a phone contact and a results review are
   occasions too.
2. **Composer** (`/patients/:pid/encounters/:eid/note`): one contenteditable narrative surface per
   section with **chips** that reference objects (`{{chip:obs_…}}`), a `/` menu to insert an
   order, lab, referral or follow-up intent (typed intents executed at sign), and an `@` menu to
   pull a chart value as a reference. Chips are references, never copies. Section plan comes from
   the profile packs of the linked contexts (PRD-07) plus fixed sections; no pack ⇒ Assessment and
   per-problem Plan only.
3. **Per-problem A/P with diff** (PAT·04): for each problem addressed, the prior assessment/plan
   beside today's; carry-forward re-asserts a claim (recorded as such, never pasted prose);
   plan items are typed intents.
4. **Live context panel** at the top (PRD-07): status, goals, risk, compliance, last plan,
   trends, with the linked contexts inferred and offered, consequence shown before linking.
5. **Suggestions tray** (PRD-05): proposals fire from the narrative as it is typed or transcribed,
   with spans; accepting lands them as `acknowledged` in the encounter's changeset; the sign gate
   attests them.
6. **ROS pattern** (PAT·02): symptom-category observations with present/absent/unasked and source,
   context-scoped systems, patient pre-fill, no "all systems negative" button, prose projection.
7. **Pre-sign reconciliation gate**: lists uncaptured free text with unreviewed proposals,
   carried-forward problems not reviewed, open compliance/billing items, and asks for per-item
   Capture/Ignore; per-problem Confirm is the only way a problem becomes "addressed today".
   Signing never silently attests an unopened problem (the canonical violation in the North Star).
8. **Sign** (`signEncounter`, confirm-gated): copy-on-sign snapshot of every referenced value,
   `encounter.signed` with hash of the ledger state, attributed `PROBLEM_UPDATE` events per
   addressed problem, executed intents → orders/WorkItems, note immutable. **Amend** appends a new
   version with `amends`; prior versions render unchanged.
9. **Write-back contract** implemented per object (ADR 0003 table): problem A/P snapshot + update;
   goal progress derived; care-plan item on explicit change; order/task create/complete; outcome
   observation reads only; context status on explicit change or rollup; risk updates the object,
   never owns it.
10. **Legacy SOAP view** (PRD-08 view spec): a conventional note rendered from the encounter for
    billing/legal continuity, with citations. The "compatibility shim" as a template.
11. **Deliberately unread space** (PAT·08): a section flagged `storage_class: private_process` that
    the extraction pipeline and the compiler are excluded from, with permissions below the document
    (PRD-12).
12. **Drafts are durable**: autosave as `encounter.draft_saved` events (drafts are just events);
    interruption recovery restores the composer and the changeset exactly.

**Out**
- Voice capture; dictation arrives as a transcript event (PRD-05).
- Multi-author concurrent editing (single author per draft; documented gap).

## Design rules (binding)

- The narration layer never depends on the entity layer: extraction is progressive enhancement,
  never a signing gate.
- A signed note that read "improving" never later renders "worsening" (G4).
- Never interrupt the telling (PAT·03): proposals surface after a pause or at sign, not mid-sentence.
- Copy-forward is inert: pasting prose claims nothing; only chips and typed intents write.

## Acceptance

1. Open visit 2 for pt_001, link the chronic-care context (offered, not required), type the
   assessment with two chips, accept the naproxen proposal, sign: the note snapshot holds
   creatinine 5.7 and CKD `active`; `diagnosis[]` lists CKD, HTN; billing (`ehr/billing.py`) reads it.
2. Later correcting creatinine (supersede) changes the projection but not the signed note.
3. A blank note signed on a no-context encounter is valid and appears in Timeline and Record.
4. Amending appends `note v2` with `amends: v1`; v1 renders byte-identical.
5. The pre-sign gate blocks signing while an unreviewed carried-forward problem exists and shows it.
6. Text in the private-process section never appears in proposals, briefs, or the SOAP view.
7. Killing the tab mid-note and reopening restores the draft and the changeset.

## Estimate

Eight days. The composer surface (chips, menus, sections) is the bulk; sign/snapshot/amend are
verbs on top of PRD-02.
