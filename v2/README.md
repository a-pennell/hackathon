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

## What a change is expected to break

A projection is about a value we are trying to improve. The other kind matters more at the bedside: a value the plan
is expected to push the **wrong** way, where the clinical question is how far is too far.

Starting lisinopril is expected to raise creatinine — it lowers pressure inside the glomerulus. A rise of up to 30%
that settles within four weeks is acceptable and the drug is continued (Bakris & Weir 2000; KDIGO 2012 §3.1). On
Jeane that threshold is **1.04 mg/dL, from her own baseline of 0.8** — and 1.04 is *inside* the lab's reference range
of 0.6–1.2. The range cannot flag it. The same rule works the other way for potassium: the threshold is 5.5 mmol/L,
*above* the range high of 5.1, so a result the lab flags high is still expected here.

Three things follow, and each is visible in question 7:

- The expectation names the test that will answer it. Here the plan already says "BMP in 2 weeks"; if it did not, the
  line reads *nothing on the plan tests this*.
- While an expectation is live it **replaces** the standing tripwire for that series. The generic rule watches for a
  ±25% move and would have fired on the very rise the plan predicts; the threshold now reads "above 1.04 mg/dL, or
  still rising after 4 weeks · set by Lisinopril 10 mg started 15 Sep 2026, not the standing rule".
- Stopping the ibuprofen pushes creatinine the other way, so the card says a smaller rise, or none, is just as
  consistent. Two changes at one visit, in opposite directions, on one value.

Then **Two weeks later** lands the BMP: creatinine 0.9, potassium 4.4, both within. The expectation set at the visit
is answered by the result, and the card says so.

Rules, not a model (`v2/simulate.py`, `expectations`). Computed on demand, never stored.

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

## Two weeks later

The header offers **Two weeks later** once the visit is documented. It writes a curated follow-up
(`data/followups/pt_002.json`: a home blood pressure log and the basic metabolic panel) as accepted results and reads
the chart as of 30 Sep. The projection is then tested rather than asserted: "projected 133 to 140 by 13 Oct; observed
138 on 29 Sep: better than projected", the expectation reads *met*, and hypertension moves from off course to watch.
Reset removes the follow-up with everything else.

A problem raised from a note has results linked to it and nothing watching them, so the view treats the series of
those results as what it is watched by (albuminuria is watched by the albumin/creatinine ratio). Computed for the
view; the merge into a real monitoring link stays a steward's decision.

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
cd frontend && npm install          # once: v2 and v3 symlink their node_modules into this one
cd v2/frontend && npm run build     # node_modules is a symlink to ../../frontend/node_modules
uvicorn backend.main:app --reload --reload-dir backend --reload-dir ehr --reload-dir v2
```

Then open `http://localhost:8000/v2/?patient=pt_002`. Reset from the header. Tests: `tests/test_v2.py`.
