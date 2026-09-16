# v2 · the gate, the seven answers, the assembled note

A simpler front on the same chart, data model and pipelines. Served at `/v2/?patient=pt_002` by the
same server; its API lives under `/v2/api`. Nothing in `ehr/` was rewritten: `v2/monitor.py` arranges
what `ehr/card.py`, `ehr/overview.py` and `ehr/draft.py` already compute.

## The three views

1. **Problems**, the gate. Every problem, sorted by standing, computed by rules over the chart and
   never stored: *off course* (an expectation missed, or a monitored value outside its range and
   still moving the wrong way), *watch* (outside range but steady, a change made and not yet answered,
   an unexplained finding, an answer still owed), *in good standing* (monitored, in range, steady),
   *not monitored*. One line says why; one line says what is next.
2. **A problem**, as seven answers, in order: what is happening (the monitored series with the
   courses drawn under them, so a medication's effect on a value is read off one axis); what we think
   it means (the working summary, the causes signed and rejected, the reasoning); what changed (what
   the rules detected, each with an **Acknowledge** that signs it into the record); what we are doing
   (plan, courses, loops, and **Add to plan** for the clinician's own line); what we are uncertain
   about; what should happen next; what would make us change course (the expectation and the
   tripwires).
3. **Visit note**, assembled. The dictated history verbatim, the dictated assessment and plan folded,
   then per problem an assessment and a plan compiled from what was decided at this visit, every
   sentence citing the record. A box for the clinician's own words. Sign to freeze it.

One button in the header names the next thing owed: read the note, review it (decisions one at a
time, the rest signs with the note), sign it, assemble the visit note, sign it.

## The three claims the demo makes

- **The system watches every problem all the time.** The gate is recomputed on every request from
  thresholds, expectations and loops. Nothing in it is written by hand.
- **Entities are linked, so effects are visible.** A course is drawn as a band under the series it is
  linked to; a cause asserted from a note becomes an edge; the trajectory shows the value against the
  course, and the expectation set when the course closed is a corridor on the same axis.
- **Documentation is assembly.** Changes are detected by rules and signed by the clinician; decisions
  on the note are signed; the visit note is compiled from those signatures. The clinician can still
  type anything, and largely does not have to.

## Run

```bash
cd v2/frontend && npm run build     # node_modules is a symlink to ../../frontend/node_modules
uvicorn backend.main:app --reload --reload-dir backend --reload-dir ehr --reload-dir v2
```

Then open `http://localhost:8000/v2/?patient=pt_002`. Reset from the header. Tests: `tests/test_v2.py`.
