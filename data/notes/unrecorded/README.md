# Notes with no recording yet

`v2/api.py::_attach_note` globs `data/notes/*.json` and takes the newest note by encounter time as "the note that
arrived with this visit". A note dated after 15 Sep 2026 would therefore become the demo's note — and with no
`*.raw.json` beside it, **Start the visit** would try to call the model and fail on a machine with no key.

The glob is not recursive, so anything in this directory is invisible to the app. A note graduates to `data/notes/`
once it has been extracted live, its recording is committed, **and the demo no longer depends on an earlier note being
the current visit** — `note_demo_103` is recorded but stays here for that second reason: it is dated after 15 Sep, so
moving it would make the four-week visit the demo's visit:

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

## What the live run found (17 Sep 2026)

Extracted for real against a clean chart: 3 problems, 6 observations, 2 medications, 19 links, 10 plans, 5 rejected.
The recording is committed as `data/proposed/pt_002/note_demo_103.raw.json`; replay it with `--replay` rather than
spending another call.

`provenance.asserted`, on its first real outing, was right on all five judgements — including the two the rule gets
wrong:

| passage | extractor | rule alone |
|---|---|---|
| "Not from the metformin, though I checked a B12 anyway." | `false` | inferred ✓ |
| "Cough. I think this is the lisinopril." | `true` | inferred ✗ (no cue word) |
| "...almost certainly diabetic." (as a cause) | `true` | inferred ✗ (no cue word) |
| "Albuminuria. Awaiting the repeat ACR." | `true` | stated ✓ |
| "New peripheral neuropathy, distal and symmetric..." | `true` | stated ✓ |

The denial is the one that matters: the extractor marked it `false` unprompted, and the clinician is asked rather than
having a cause they rejected attested under their signature.

**A caveat on the 5 rejections.** The run was made against a chart where the 15 Sep visit had *not* been signed, so
lisinopril, ibuprofen and acetaminophen are not on board and "Stop lisinopril" has no course to stop. The validator
refused them correctly. A truer run would follow a signed visit 102; the rejections say more about the fixture than
about the extractor.
