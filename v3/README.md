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

API: `GET /v3/api/patients/{pid}/visit` returns the utterances with character offsets and every proposal of the
visit's note positioned in the transcript (`v3/api.py`). All actions reuse the v1 review endpoints and the v2
note endpoints; no new model call is made.
