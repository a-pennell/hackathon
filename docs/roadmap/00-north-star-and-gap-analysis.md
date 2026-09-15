# From the hackathon prototype to an operational problem-oriented EHR

**Status:** plan for team discussion, 15 September 2026. Nothing here is built. The schema in
`docs/patient-model-schema.md` is unchanged; every change it would need is flagged in
`schema-v2-proposal.md`.

**Source:** the NDE documentation set at `~/Projects/NDE/docs` (22 specs, 3 ADRs, the CPOR paper,
three independent evaluations, the IA studies) and the four site pages at `~/Projects/NDE`
(`index.html` the architecture, `migration.html`, `strategy.html` the North Star, `paper.html`).
The NDE React prototype is ignored on purpose: its own engineering FAQ says "there is no live or
reusable production code; a real implementation starts from scratch. What carries forward are the
decisions."

## 1. What the target is, in one paragraph

The record is not a document; it is a model of the patient exposed to correction. Three layers:
an **append-only, bi-temporal event ledger** of everything that happened (the legal record, never
edited); a small **belief layer** of attributed, tiered, versioned, evidence-linked claims,
organised around **clinical focuses** (problems, concerns, goals, risks) with typed edges, one
steward each, and a forward-looking surveillance spec; and a **compiler** that renders every
document (note, brief, referral, bill, patient summary, AI context packet) for an audience, a
purpose and a budget, citing its sources. **Intelligence proposes; authority acts**: one write
path of enumerable, authority-scoped verbs for every caller; nothing machine-made touches
confirmed state without a human signature; attestation is a measured economy with kill
conditions. The product IA is stable outside and adaptive inside: spaces as scopes of work
(`Today | Work | Patients | Schedule | Messages | Practice | Revenue | Reports`), a patient
workspace of `Overview · Timeline · Care · Chart`, one object one home many lenses, and a canvas
that composes per occasion. First market: non-prescribing mental health with ambient capture as
the flagship input; ONC certification eventually.

## 2. What the hackathon already satisfies

The weekend build is further along the target than its size suggests, because it made the same
three commitments the docs treat as the spine:

| Target commitment | Hackathon status |
|---|---|
| AI proposes, humans attest; nothing AI-written reaches the chart unsigned | **Built.** `status: proposed` → review queue → `accept_item`; the only path to the chart is a human decision |
| Provenance on every claim; evidence ids must exist | **Built.** `note_id + quote` on every extracted item; insights validated against the chart; citations tap through |
| Views computed, never stored | **Built** for trend, brief, decision trail, visit coding |
| Medications as interval courses | **Built** (v1 §4), matches the docs' medication-statement shape |
| Links as first-class rows with provenance and review status | **Built** (five types); this is the seed of the edge table |
| Reasons on rejection as the clinician's judgment made explicit | **Built** (`review_record` with reason codes); the docs' "proposal with disposition" |
| Recorded, replayable model calls; single call site | **Built**; the docs' "every model call recorded and auditable" |
| Referral letter, orders, MDM coding compiled from signed state with citations | **Built**; three of the compiler's view specs already exist ad hoc |
| Design principles judged against the literature | **Built** (`docs/clinical-decision-principles.md`), overlapping the paper's Part V–VI |

## 3. The gaps, ranked by how much they unlock

| # | Gap | Docs that decide it | PRD |
|---|---|---|---|
| 1 | The chart is a mutable file; no ledger, no point-in-time, decisions live in queue files | paper §6.2/B.1, ADR 0001, ontology §1 | PRD-01 |
| 2 | One function enforces the invariant; no verb registry, no actor model, no confirmation contract | ontology §6–7, strategy invariants 3–4 | PRD-02 |
| 3 | Problems are flat imports: no kinds, codings, steward, surveillance, carries-forward; four CKD problems; links capped at five types with no edge provenance | paper §6.3/A.2, longitudinal §0, migration §3 "problems and PMH" | PRD-03 |
| 4 | Inbox has no consequence classes, steward routing, evidence-before-interpretation, telemetry, kill conditions, probes, retention policy | paper A.3/A.6/B.4, all three evaluations | PRD-04 |
| 5 | Extraction lacks spans, never-re-propose, adversarial check, tripwire pre-pass, eval harness; no transcript input | slice-1 spec, cpor-qa Q16, paper B.2 | PRD-05 |
| 6 | No encounter as change context, no composer, no sign/snapshot/amend, no problems-addressed join | ADR 0003, Note Patterns PAT·01–08 | PRD-06 |
| 7 | No course of care, goal, risk object, rollup, compliance or preventive agenda | ADR 0002/0003 G1–G8, longitudinal §2.6–2.10 | PRD-07 |
| 8 | Five ad hoc context builders instead of one compiler with view specs, budgets, summary stacks, consumption/recall | ontology §7.1, paper §6.4/B.3 | PRD-08 |
| 9 | No Work: no flags vs obligations, no ownership, no cross-patient queue | ontology §2, migration §3, every evaluation's top gap | PRD-09 |
| 10 | One chart desk, not a shell; no spaces, routes, header, four tabs, drawer, canvas recipes | migration §3, patient-ia-v2 | PRD-10 |
| 11 | No day, schedule, messages, charges, reports | migration spaces table | PRD-11 |
| 12 | One patient, no actors, no permissions, no Part 2 boundary, no FHIR export | ADR 0003 G5, eng-faq, evaluations "production gate" | PRD-12 |

## 4. Sequencing

The docs give an explicit order and a reason for it: **ledger first, edges second, write path
third; derived views, shelving, recipes and the deep model after** (`ontology-evolution.md` §1:
"sequence them first even where a later stage would demo better"). Transposed to a greenfield
codebase with no legacy writers, that is:

```
Stage 1  PRD-01 ledger  ──►  PRD-02 verbs  ──►  PRD-03 focus + edges        (substrate, ~10 days)
                                  │
Stage 2  PRD-04 attestation ◄─────┴────► PRD-05 evidence + harness            (the loop, ~11 days)
                                  │
Stage 3  PRD-07 courses/goals/risk ──► PRD-06 encounter + composer            (clinical depth, ~14 days)
         PRD-08 compiler (glance, what-changed, agenda first)                  (~6 days, parallel)
         PRD-12 patients + permissions (fixtures early; Part 2 gate before MH) (~7 days, parallel)
                                  │
Stage 4  PRD-09 Work  ──►  PRD-10 shell + patient workspace                   (the product, ~14 days)
                                  │
Stage 5  PRD-11 operations                                                   (~10 days)
```

Roughly twelve engineer-weeks of focused work for one person, or five to six calendar weeks for a
team of three with the substrate serialised and Stages 3–5 parallel. Two rules from the migration
doc apply even without a legacy system: **navigation changes ship only on the back of a surface
that is already better** (the shell lands after the glance, Work and the drawer exist), and
**no graph-derived surface reaches a clinician before its gate** (the harness in PRD-05 and the
kill-condition dashboard in PRD-04 exist before live extraction is on by default).

## 5. Demo arcs the plan makes possible

Each act of `demo-script-longitudinal.md` maps onto a stage:

| Act | Capability | Needs |
|---|---|---|
| "What's true now, what changed" | glance, per-problem diff, scale trend, rollup | PRD-03, 07, 08 |
| "A course of care, not a pile of visits" | discharge vs lapse, recert, charge capture + KX, pre-sign gate | PRD-06, 07, 11 |
| "Risk that carries forward and tells you when it's stale" | risk object, staleness, confidentiality | PRD-07, 12 |
| "One patient, two specialties, one chart" | multi-context encounter, composed note, scoped billing | PRD-06, 07 |
| "A visit with no problem at all" | preventive agenda, finding raises a problem in place | PRD-07 |
| Today's hackathon arc (note → proposals → sign → insight → orders → referral) | unchanged, now as the focus workspace | keeps working through every stage (PRD-01 acceptance) |

## 6. Decisions the team has to make (not the engineer)

1. **Adopt schema v2** as flagged, or a subset. Minimum viable subset for Stage 1: §1 events,
   §2 tiers/spans, §4 edge provenance. The rest can wait for its PRD.
2. **Naming.** The docs still carry four names for one concept (episode / Episode / CareContext /
   course of care). Proposal: internal `CareContext`, clinician-facing "course of care", never
   "episode" in UI.
3. **Care tab label** ("Care" vs "Treatment") and **problems label** ("Problems & concerns" vs
   "Problems"): the IA study says a live label test decides; the deciding task is "you're tracking
   a client's drinking without diagnosing anything, where do you record it?"
4. **Retention of rejected machine belief.** PRD-04 proposes a 90-day full-fidelity window then
   aggregation; the trilemma (liability / spoliation / safety learning) has no policy that satisfies
   all three, so this is a governance call with a revisit date.
5. **Kill-condition thresholds.** PRD-04 proposes numbers (modification rate < 5 %, dwell < 3 s,
   15 min/day, miss rate > 10 %); the North Star says ~95 % acceptance with < 2 s dwell. Pick and
   write them into config before Stage 2 ships.
6. **Ambient partner contract.** The four asks (verbatim transcript, diarisation, stable offsets,
   retention rights) are a partnership decision point; PRD-05 works from a JSON transcript fixture
   either way.
7. **Part 2 enforcement before any MH fixture is shown** to anyone outside the team. PRD-12 is a
   gate, not a phase.
8. **The rival architecture revisit date.** The graph is built as a fold over the ledger so it can
   thin to a cache if compute-on-read wins; put a date on the benchmark.

## 7. Proposed additions to `CLAUDE.md` non-negotiables (for team agreement)

6. Only verbs write. Every state change is an event with an actor and provenance; the chart is a
   fold over events and is never edited.
7. Consequential changes (new problem, status transition, merge, causal edge, medication change,
   order, sign) are reviewed one at a time by the focus's steward. Bulk accept exists only for
   batchable items.
8. Every compiled view cites; unattested state is never cited in a bill, a referral or an order.
9. One object, one home, one URL, many lenses. A second module with the same noun is a defect.
10. Permissions live below the document and govern the compiler and search too.

## 8. Immediate next steps

1. Team reads `schema-v2-proposal.md` §1, §2, §4 and decides item 1 above.
2. Start PRD-01 on a branch; the acceptance test is byte equality of the folded chart with
   `pt_001.json`, so the demo keeps working from day one.
3. Write the gold set for the eval harness (PRD-05) in parallel; it needs a clinician, not an
   engineer.
4. Before the server is started for any demo: `git checkout data/patients/pt_001.json` and remove
   the derived queue files, as today.

## 9. What this plan deliberately does not do

- It does not migrate a legacy EHR; there is none. The migration doc's shell/strangler/BFF
  machinery is transposed to "ledger first, verbs second" and the one rule that survives: one
  authoritative writer per capability.
- It does not build a module registry, a service mesh, or a database beyond SQLite. The docs
  defer all three until measured need.
- It does not structure the assessment. Prose assessment linked to structured evidence is the
  equilibrium (paper §6.3).
- It does not pursue certification, e-prescribing transmission, clearinghouse or portal auth;
  each is named as an integration boundary with a stub adapter.
