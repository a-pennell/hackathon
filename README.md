# Problem-Oriented EHR (hackathon)

Patient-modeled, problem-oriented EHR prototype. One data model (`docs/patient-model-schema.md`), one
golden patient (`data/patients/pt_001.json`), and a pipeline that turns a free-text note into
reviewable chart proposals and a reasoned Insight. Nothing AI-generated reaches the chart until a
human accepts it.

## Layout

| Path | What |
|---|---|
| `scripts/gen_synthea.sh`, `find_golden.py`, `import_patient.py` | Synthea generation, golden-patient ranking, FHIR -> our JSON |
| `data/golden/` | the golden patient's raw Synthea bundle (committed) |
| `data/patients/pt_001.json` | the chart: patient, problems, observations, medications, encounters, notes, links, insights |
| `data/notes/` | hand-written demo notes (curated, don't overwrite) |
| `data/proposed/<pt>/` | review queues: `<note_id>.json` from extraction, `reason_<problem_id>.json` from reasoning |
| `ehr/trend.py` | `trend(patient_id, loinc_code, window)` -> TrendSummary (§9) |
| `ehr/extract.py` | note -> proposed observations / problems / medications / links (§3, §4, §7) |
| `ehr/reason.py` | TrendSummaries + chart context -> proposed Insights (§10) |
| `ehr/review.py` | accept / reject queue items into the chart |
| `ehr/llm.py` | the single Claude API call site (`claude-opus-5`, structured output) |
| `tests/` | `python3 -m pytest tests -q` |

Stdlib-only except `anthropic` (needed only for live extraction / reasoning). Python 3.11+.

## Demo runbook

Live steps need `ANTHROPIC_API_KEY` exported in your shell. Every step that calls the API also
has an offline path (`--replay <saved raw response>`, or `--rules-only` for reasoning).

```bash
# 0. baseline: the chart as imported, plus the trend the reasoning layer will see
python3 -m ehr.trend pt_001 38483-4 1y

# 1. the note arrives -> extraction -> review queue
python3 -m ehr.extract data/notes/note_demo_002.json
python3 -m ehr.review pt_001 note_demo_002 --list

# 2. the clinician accepts (all, or by id) -> items enter the chart as accepted, provenance kept
python3 -m ehr.review pt_001 note_demo_002 --accept-all --accept-changes

# 3. reasoning on the CKD problem -> proposed Insight citing real ids
python3 -m ehr.reason pt_001 --problem prob_0057            # or --rules-only without a key
python3 -m ehr.review pt_001 reason_prob_0057 --list
python3 -m ehr.review pt_001 reason_prob_0057 --accept-all
```

The decision moment: creatinine (LOINC `38483-4`) rises from 1.6 to 5.7 over the year, eGFR falls
to 15.6, the note reveals daily naproxen since April, and metformin 500 mg is still on board.

## Reset the demo

`git checkout data/patients/pt_001.json && rm -rf data/proposed/pt_001/note_demo_002*` restores the
chart to the committed state (both demo notes ingested, nothing accepted).

## Things the team should know

- The chart's creatinine story is under `38483-4` (whole blood, diabetes-care visits); `2160-0`
  (serum, CHF panels) is flat for this patient. Both are `monitors` series for CKD.
- Schema interpretations that the schema doc leaves open are listed in `FLAGGED_DECISIONS` in
  `scripts/import_patient.py` and echoed in `data/patients/pt_001.import-report.json`.
- Regenerating Synthea output needs OpenJDK 21 (`brew install openjdk@21`) and the jar in
  `tools/synthea/` (see `scripts/gen_synthea.sh`). Don't regenerate mid-hackathon.
