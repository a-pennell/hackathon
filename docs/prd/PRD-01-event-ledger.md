# PRD-01 — The event ledger and the chart as a projection

**Stage:** 1 of the platform sequence (ledger before edges, edges before write path). Nothing after
this is worth much without it (`ontology-evolution.md` §1: "Stages 1 and 2 are load-bearing").
**Depends on:** nothing. **Unblocks:** PRD-02, 03, 04, 06, 08, 09.
**Schema:** `docs/roadmap/schema-v2-proposal.md` §1, §2, §12 (flagged; needs team sign-off).

## Why

The hackathon chart is a mutable JSON file edited in place by `accept_item`, with decisions living
in queue files beside the model recordings. `docs/ui-critique.md` already lists the consequences
(reset by filename pattern, decisions outside the chart, no point-in-time answer). The target
architecture makes one commitment above all others: **facts and beliefs live in separate layers,
the fact layer is an append-only ledger, and everything else is derived from it** (paper §6.2,
Lesson 4; ADR 0001 "derive the rest"; `cpor-migration-and-ia.md` §2 "the ledger, not a generic
read model"). Undo, audit, amendment, "what did the record believe on March 3rd," drift detection
and reversibility of the problem graph all fall out of this one decision for free (paper B.2).

## Goal

Every write in the system becomes an event. The v1 chart shape that every module reads today is a
**fold** over those events, cached, never edited. `pt_001` round-trips through the ledger with no
field changes.

## Scope

**In**
1. `ehr/ledger.py`: SQLite `events` table (schema §1), insert-only; `append(event) -> id`;
   `read(patient_id, until=None, kinds=None)`; `fold(patient_id, until=None) -> chart` producing the
   v1 envelope plus v2 fields; JSONL export/import per patient (`data/ledger/<pt>.jsonl`) so
   fixtures stay in git.
2. Bi-temporal timestamps on every event; `supersedes` for corrections; `caused_by` for
   verb → proposal lineage; optional hash chain (on for the demo).
3. `scripts/migrate_v1_to_events.py` (schema §12): chart, queues and recordings → events.
   Acceptance is byte equality on v1 fields.
4. `ehr/projection.py`: the fold, plus a cache keyed on (patient, last_event_id). All existing
   readers (`trend`, `brief`, `billing`, `review.ledger_for_problem`, `backend/main.py`) switch to
   reading the projection. No module reads the chart file after this ships.
5. Point-in-time reads: `GET /api/patients/{pid}?as_of=<iso>` folds to that instant. This is what
   makes the decision trail and the signed-note snapshot honest.
6. Reset becomes "fold up to the marker event recorded at server start"; no `.pristine` snapshot.
7. Recompilation audit job: `python3 -m ehr.ledger --audit pt_001` refolds from zero and diffs
   against the cached projection; any difference is a bug and fails CI.

**Out**
- A different datastore than SQLite (the docs deliberately leave this open; SQLite is the obvious
  first fit for one file per deployment).
- Multi-tenant partitioning, replication, legal hold (documented in PRD-12 as later).

## Event vocabulary

The initial list in schema §1. Rule: **one event kind per verb output**, named `object.verb_past`.
Adding a kind requires adding it to `ehr/ledger.py::KINDS` and a fold handler; the fold rejects
unknown kinds loudly rather than ignoring them.

## Design rules (binding)

- Only verbs write (PRD-02). Until PRD-02 lands, the only writer is the migration script and a
  thin `append` used by the existing modules; that thin path is deleted in PRD-02.
- The projection is a cache. Deleting it loses nothing. The audit proves it weekly.
- Narrative is stored verbatim as `narrative.received`; extraction never rewrites it.
- No event is ever updated or deleted. Entered-in-error is `observation.corrected` with `supersedes`.
- Every event has an `actor`. "system" is a real actor with a real id.

## API

```
GET  /api/patients/{pid}?as_of=…                 folded chart (v1 shape + v2 fields)
GET  /api/patients/{pid}/events?since=&kinds=    raw events (paged)
GET  /api/objects/{id}/biography                 events touching one object, newest last
```

## Acceptance

1. `migrate_v1_to_events pt_001` then `fold()` equals `pt_001.json` on every v1 field (test).
2. Sign an item through today's UI; the projection updates; `--audit` reports zero diff.
3. `?as_of=` before and after a signature returns the two chart states.
4. Reset restores the start-of-server state without any file snapshot.
5. All 33 existing tests pass unchanged against the projection.

## Metrics

Fold time for pt_001 (≈3,800 observations) under 200 ms cold, under 20 ms cached. Audit diff = 0.

## Estimate

Two to three days for one engineer. The migration script is half a day; switching readers is
mechanical because `backend/main.py` already funnels reads through a few loaders.
