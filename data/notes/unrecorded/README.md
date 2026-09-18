# Notes with no recording yet

`v2/api.py::_attach_note` globs `data/notes/*.json` and takes the newest note by encounter time as "the note that
arrived with this visit". A note dated after 15 Sep 2026 would therefore become the demo's note — and with no
`*.raw.json` beside it, **Start the visit** would try to call the model and fail on a machine with no key.

The glob is not recursive, so anything in this directory is invisible to the app. A note graduates to `data/notes/`
once it has been extracted live and its recording is committed:

```bash
python3 -m ehr.extract data/notes/unrecorded/note_demo_103.json --patient pt_002   # writes the queue + the recording
git mv data/notes/unrecorded/note_demo_103.json data/notes/
```

## note_demo_103 — the four-week visit

Written to exercise `_origin` (`v3/api.py`, `tests/test_origin.py`) on phrasing the demo note does not contain:

- **a cause the clinician asserts with no cue word from the list** — "I think this is the lisinopril"
- **a cause the clinician denies** — "Not from the metformin, though I checked a B12 anyway"
- **a cause the patient raises, not the clinician** — "She wondered about the new blood pressure tablet"
- **a problem stated in a sentence that negates something else** — "Dry cough ... no fever, no sputum"
- **a new problem with a hedged cause** — "almost certainly diabetic"

Hand-classified, it should come out around 12 stated / 6 inferred. Anything the extractor marks
`provenance.asserted: true` in the denial cases is a bug worth knowing about.
