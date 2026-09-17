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

## One signature

Providers sign notes. Nothing else here is called a signature. A proposal from the reading is **accepted**
or **rejected**; an insight is **agreed** or **dismissed**; a change the rules detected is **noted**; a
plan line is **added**. All of it is accepted into the visit, and the visit note is the one place a
signature happens. Above its text the note lists exactly what that signature attests, by kind, with every
item, and the text is compiled from that list; on signing, every accepted item is stamped with the note
that attested it, and the gate shows what is accepted and not yet attested.

One button in the header names the next thing owed: read the note, review it (decisions one at a
time, the rest signs with the note), sign it, assemble the visit note, sign it.

## Three kinds of suggestion, kept apart

Under *what should happen next* a suggestion says where it comes from:

- **Best practice** (`v2/guidelines.py`): rules checked against the chart, each with its source (ACC/AHA 2017,
  ADA Standards of Care 2024, KDIGO), marked *covered by the plan* or *not on the plan*, with an **Add** that puts
  the recommended line on the plan. The gate counts the gaps per problem.
- **Reasoning**: what the model reads from this patient's trends and courses, agreed or dismissed.
- **Projection** (`v2/simulate.py`): for each candidate action, what it is projected to do to the monitored value,
  as a range with the date of full effect and whether it reaches goal, from a small table of published average
  effects (Law 2009, Johnson 1994, DASH-Sodium, Hirst 2012, ADA). Options already on the plan are combined into
  *the current plan's* projection, which is drawn as the corridor on the trajectory, stated under *what would make
  us change course*, and summarised on the gate ("on the current plan, projected under 140 by about 13 Oct").
  When the next value lands it is compared with the band: within, better, or missed.

A projection is computed on demand and never stored, like a TrendSummary. It is a range, not a probability, and not
specific to the patient until the patient's own responses say how well it held. Choosing an option is an ordinary
plan line.

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
