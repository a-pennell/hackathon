# v3 · the visit as one surface

v2 runs the visit as a relay: dictation, then reading, then a review list, then the problem, then the note. v3 keeps
everything in v2 (it is a fork of `v2/frontend`, served at `/v3/?patient=pt_002`, with v2 untouched at `/v2/`) and
replaces the relay with one screen, the **Visit**:

- **The transcript plays** on the left, at speaking pace (pause, skip to end, 1× to 4×). The recorded reading is not
  rerun; each of its findings already carries the verbatim passage it came from, so it is revealed the moment the
  transcript reaches that passage. Utterances show how many findings they carry.
- **Findings land on the problem they touch.** The gate strip across the top lights the problems the conversation has
  reached; a problem the note raises appears as a dashed "new" chip. The chosen problem shows "Heard at this visit"
  above its seven questions: what was said about it, with the passage.
- **Only decisions wait.** A problem raised, a cause asserted, a course changed: these sit as chips with Accept and
  Reject (with a reason, inline). Everything else is marked "accepted at close".
- **The note grows the whole time.** The right pane counts what is accepted, what is heard and not yet accepted, and
  what is to attest. **Close the visit** accepts what is left; **Sign the visit note** is then the one signature.

## Two acts: dictate, sign

Providers dictate and are done, and this keeps that. Every finding the reading takes from the dictation is marked
**stated** when its passage makes the claim ("daily NSAID use since May, likely contributing" states the cause;
"with new albuminuria" states the problem) or **inferred** when the reading added a relation the passage does not
say (metformin as a cause of the diabetes, inferred from "adherence the main driver"). Stated findings need no
click: the signature accepts them. Inferred ones, usually none or one, take a yes or a no with a reason. Anything
inferred and unanswered is set aside as unconfirmed, on the record and undoable, not taken into the note.

**Sign the visit note** is then the one act: it accepts what was stated, takes what was said yes to, closes the
dictated note, compiles the visit note from the record as it now stands, adds the clinician's own words, and
signs. On Jeane that is 45 items attested by one signature and two clicks after the dictation. The problem page,
the reasoning and the projections are there to think with, and none of them is owed.

`POST /v3/api/patients/{pid}/visit/sign` does all of it. The visit's working state (where the transcript is, the
answers given, the clinician's words) survives navigating to Problems and back within the session.

**Review the note** shows the same note first. `POST /v3/api/patients/{pid}/visit/preview` runs the signature on a
copy of the chart and the queue — the same decisions, the same compile — and returns the document and the manifest
without writing anything. The dictated sections are shown as dictated; the compiled sections are editable there,
and an edit travels with the signature as `sections`, so what the provider reads is what gets signed. Signing is
available from the panel, so reading the note first costs one extra click and no second pass.

API: `GET /v3/api/patients/{pid}/visit` returns the utterances with character offsets and every proposal of the
visit's note positioned in the transcript (`v3/api.py`). All actions reuse the v1 review endpoints and the v2
note endpoints; no new model call is made.

## Signing ends the visit, not the problem

The visit used to stop at *signed · open the visit note*, which is a filing-cabinet ending for a system whose claim is
that it keeps watching. The signature is really the moment the chart starts waiting for something, so that is what the
screen now says: `GET /v3/api/patients/{pid}/commitments` returns the promises the visit just made, each with a date
and something that answers it.

On Jeane, nine of them: the two expectations the lisinopril sets (creatinine at or under 1.04 mg/dL, potassium under
5.5, both tested by the BMP), the projections for systolic pressure and A1c, the plan lines that say when ("BMP in 2
weeks" → 29 Sep, "Repeat A1c in 3 months" → 14 Dec), and the one inferred finding left unanswered, still undoable and
still off the note. The projection is read from the same `problem_view` the problem page renders, so the watch list
and the problem card cannot disagree.

**Two weeks later · let the results land** sits in that panel. The BMP comes back at creatinine 0.9 and potassium 4.4:
both expectations answer *within*, the systolic lands at 138 against a projected 133.2–139.6 and reads *better*, the
"BMP in 2 weeks" line stops being owed and reads *resulted*, and the count falls from nine to four. Each line links to
its problem, which is the seam into the rest of the chart.

## What "stated" is worth, and what it is not

A finding marked **stated** is accepted by the signature without a click, so the classifier decides what a clinician
never has to look at. Its two errors are not comparable: a stated thing called inferred costs one click; an inferred —
or *denied* — thing called stated attests a claim the clinician did not make.

Tested against eighteen passages written as dictation, the first version got ten wrong, and five of those were the
dangerous kind. `"I doubt the ibuprofen is contributing"` was read as **stated**, because the sentence contains
"ibuprofen" and "contribut": the chart would have recorded the suspected cause the clinician had just rejected.
`"Ruled out albuminuria"` would have added the problem. The cue list is a closed vocabulary over open language and
had no notion of a sentence saying *no*.

Two changes (`v3/api.py`, `tests/test_origin.py`): a passage carrying any negation is never read as asserting a
relation, and the cue list covers the causal verbs a clinician actually dictates ("explains", "aggravated by",
"on the back of"). Seventeen of eighteen now, and the one miss asks instead of assuming.

Run against a **second dictation** — the four-week visit, where the lisinopril has caused a cough and a new
neuropathy appears — the split is **12 stated / 6 inferred**, not the 30 / 1 of the first note. That ratio was an
artifact of one note's phrasing. Zero unsafe errors; three misses, all in the direction of asking:
`"I think this is the lisinopril"` asserts a cause with no verb the list carries, and `"no fever, no sputum"` costs
the cough a click because sentence-level negation cannot tell which clause it belongs to.

The real fix is not a longer word list, and it is now built: `provenance.asserted` (schema §7.1). The extractor
answers, while it has the passage in front of it, whether that passage itself makes the claim, and `_origin` prefers
that answer to anything recoverable from cue words afterwards. One veto is kept over it — a passage that denies the
relation outright is never read as asserting it, however the extractor answered — because a wrong `true` is attested
without anyone seeing it while a wrong `false` costs one click.

**The demo still runs on the rule.** Every recording in `data/proposed` was made before the field existed, and the
reader falls back when it is absent. Re-recording the extractions with a live key is what turns it on; nothing else
has to change.

## The flowsheet fills in as it is spoken

The chart the reading writes to is the same one on screen, so it should show the writing happen. Every proposal the
transcript has reached is passed into the problem's chart (`revealed`, `v3/frontend/src/Timeline.tsx`), and only those
are drawn — so a value lands in its row at the moment it is said, not in a batch when the note was read.

When "BP 154 over 94 sitting, repeat 150 over 92" goes past, the systolic row's headline becomes **150** in the amber
of something unsigned, labelled *heard at this visit*, with *was 154 · 2026-08* kept underneath rather than replaced:
the clinician can see both the number they just said and the one the chart has been carrying. The point appears on the
plot at the visit's date in the same pass. Later, when "stop ibuprofen" and "start lisinopril" are dictated, their
courses draw as pencil bands under the series they affect — the NSAID's band closing at this visit, the ACE inhibitor's
opening — which is the linked-entities claim made while it is being said rather than asserted afterwards.

Nothing here is on the chart. It is the same pencil convention the review queue uses, and the signature is still what
writes it. Outside a visit `revealed` is omitted and every proposal shows at once, which is what the problem page
wants, so v2 is unchanged.

The motion is 260ms, decelerating, from 5px below the line the value will occupy, and is dropped entirely under
`prefers-reduced-motion`.

## Runbook — the three-minute demo

Rehearsed end to end at 1024×768 on a clean chart, last on 17 Sep 2026. Every number below was read off that
run, not estimated; the clock is the machine time plus room to talk.

**Before you start.** Server up (`python3 -m uvicorn backend.main:app --reload --port 8000`), **Reset demo** clicked,
window at least 1100px wide if you want the note pane pinned on the right — below that it drops to the bar at the foot,
which also works. Open `http://localhost:8000/` and take **The visit** from the chooser, or go straight to
`http://localhost:8000/v3/?patient=pt_002`. No API key is needed: the reading is replayed.

| | beat | says | clock |
|---|---|---|---|
| 1 | The gate, before anything | Three problems, two of them off course. This is what she looks like walking in. | 0:00 |
| 2 | **Start the visit**, set the speed to **2×**, open **Essential hypertension** | The dictation plays. Watch the flowsheet: when the pressures are read out they land in their rows, amber, with what the chart held kept underneath. The NSAID and the ACE inhibitor draw themselves as bands when they are dictated. | 0:10 |
| 3 | Let it run, then **Skip to end** | Thirty findings placed, and the gate has grown from three problems to five: albuminuria and the back pain were never on the list. | 0:50 |
| 4 | The one chip that asks | Everything the dictation *said* is accepted by the signature — no clicks. This one the reading inferred; the passage does not say it. **No**, "Non-adherence is the cause, not the drug." | 1:05 |
| 5 | **Review the note** | This is the note, exactly as the signature would write it. Nothing is on the chart yet. The rejection I just gave is already in the assessment, with my reason. | 1:25 |
| 6 | **Sign the visit note** | One signature. Forty-five items attested. | 1:40 |
| 7 | The watch list | Signing ended the visit, not the problem — eight things now have a date and something that answers them. Creatinine is expected to rise, up to 1.04, which is *inside* the lab's range, so the range would never flag it. The BMP already on the plan is what answers it. | 1:50 |
| 8 | **Two weeks later** | Creatinine 0.9, within. Potassium 4.4, within. Pressure 138, better than projected. The BMP stops being owed. Eight open items, now four. | 2:25 |

**Pacing.** The transcript is 34 utterances at 2.2s each: **75s at 1×, 37s at 2×, 19s at 4×**. At 1× it eats forty
percent of the three minutes, so run it at 2× and talk over it, or 4× if you are short. **Skip to end** is always safe.

**If you are asked the hard question** — *"how do you know what the clinician said versus what you inferred?"* — the
answer is `tests/test_origin.py` and the section above it: badly, at first. A denial read as an assertion was the bug,
it is fixed, and the classifier now errs towards asking. The honest version of this demo says the split is 12/6 on a
second dictation, not 30/1.

**Recovering mid-demo.** **Reset demo** in the header puts the chart back to its server-start state and clears the
visit's working state. It is safe at any point.

**If a screen looks like the wrong app.** Index documents are served `no-store`, so this should not happen any more —
but a browser that visited these URLs before that was added may still hold an old entry, and `/v3/` can render v1 from
it. One reload fixes it for good. Worth doing once on the demo machine before you start, along with **Reset demo**.
