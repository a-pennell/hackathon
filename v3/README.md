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

The real fix is not a longer word list. The model has already read the passage and should say whether it asserts the
relation, with the rule kept as the fallback for anything that does not carry the field — **flagged as a schema
addition**, not applied.
