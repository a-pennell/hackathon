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
| `ehr/review.py` | accept / reject queue items into the chart, recording who, when and why |
| `ehr/compose.py` | chart state + signed insights + review decisions -> a generated referral letter with citations |
| `ehr/brief.py` | pre-visit brief per problem: computed on open (no model), or Claude-written over the same evidence |
| `ehr/orders.py` | signed insights -> proposed orders (labs, medication changes, referrals); signing a medication change edits the course |
| `ehr/billing.py` | visit coding computed from what was signed today: diagnosis codes (demo ICD-10 map) and the E/M level by medical decision making, every element justified by ids |
| `ehr/llm.py` | the single Claude API call site (`claude-opus-5`, structured output) |
| `tests/` | `python3 -m pytest tests -q` |

Stdlib-only except `anthropic` (needed only for live extraction / reasoning). Python 3.11+.

## Run the app

```bash
python3 -m uvicorn backend.main:app --reload --port 8000     # API + serves frontend/dist at /
```

Open http://localhost:8000. The built frontend is committed in `frontend/dist`; after editing
`frontend/src`, rebuild with `cd frontend && npm install && npm run build` (Node 22). For live
frontend reloads use `npm run dev` (port 5173, proxies `/api` to 8000).

The screen is a chart desk: the problem list (left, newest monitored problem first), the
problem-scoped timeline (centre: monitored lab series with reference bands, medication courses
as bands on the same axis, encounters as ticks), and the review queue (right). Everything
AI-proposed is drawn in *pencil* (dashed, amber) until a clinician signs it; signed items become
ink. "A note arrives" opens a demo note and extracts it (live, or replaying a saved response);
"Reason about this problem" runs the reasoning layer (live, replay, or rules-only).

## Demo runbook

The two Claude calls have been run live once (`claude-opus-5`) and their responses are saved as
`data/proposed/pt_001/*.raw.json`, so the demo replays them offline and byte-for-byte. Live mode
needs `ANTHROPIC_API_KEY` exported in the shell that starts the server.

In the UI, from a fresh chart (CKD stage 3 selected). The sheet opens with a **pre-visit brief**
(what moved, what changed on the medication list, what is waiting, what was decided last time)
and closes with the **decision trail** (every proposal that touched the problem, with who decided
what and why). Both update as you sign and reject.

1. **A note arrives** → pick note 2 → **Extract (replay)**. 42 pencil items land in the queue:
   the naproxen course (dashed, "cause?"), a stage-4 problem, hypotension, the HCTZ hold.
2. **sign all** on the note queue. Pencil turns to ink; naproxen appears under the creatinine curve.
3. **Reason about this problem** → **Replay last Claude run**. Four insights, each citing real ids:
   restage CKD; naproxen as contributor (with lisinopril + furosemide); **stop metformin at eGFR
   15.6**; the two creatinine assays disagree, repeat the lab.
4. Hover the evidence chips to light up the cited points and bands; **Sign** the insight. Reject
   something with a reason (the stage-4 restaging, say: "repeat serum creatinine first"). That
   reason is the reasoning ledger, and it shows up in the referral.
5. **Compose** → **Orders from signed insights** (Claude, or replay once recorded): the signed
   actions become orders to sign; a signed medication change edits the course on the sheet.
   Then **Compose** → **Nephrology referral** (or replay): a letter rendered from the chart, the
   signed insight and your decisions, every section carrying tap-through citations. **Read** it,
   then **Sign referral**. The **Visit coding** panel at the bottom of the sheet updates with each
   signature: the E/M level and its justification, and the diagnosis codes.
6. **Reset demo** (header) restores the chart to its server-start state and clears the queues.
   (Start the server from a clean chart, since that is the state it snapshots.)

Same flow from the shell:

```bash
python3 -m ehr.extract data/notes/note_demo_002.json --replay data/proposed/pt_001/note_demo_002.raw.json
python3 -m ehr.review pt_001 note_demo_002 --accept-all --accept-changes
python3 -m ehr.reason pt_001 --problem prob_0057 --replay data/proposed/pt_001/reason_prob_0057.raw.json
python3 -m ehr.review pt_001 reason_prob_0057 --list
python3 -m ehr.review pt_001 note_demo_002 --reject prob_demo_002_01 --reason-code needs_confirmation --reason "repeat serum creatinine first"
python3 -m ehr.compose pt_001 --problem prob_0057 --kind referral --audience nephrology   # or --replay <raw.json>
```

Drop `--replay` to call Claude live (each call is roughly 10-15k tokens). Every live run writes a
timestamped copy (`note_demo_002.20260912T084512.raw.json`, never overwritten) and updates the
`<stem>.raw.json` pointer that replay uses. To roll back a bad live run, copy an older timestamped
file over the pointer. Reset from the shell:
`git checkout data/patients/pt_001.json && rm data/proposed/pt_001/note_demo_002.json data/proposed/pt_001/reason_prob_0057.json`.

The decision moment: creatinine (LOINC `38483-4`) rises from 1.6 to 5.7 over the year, eGFR falls
to 15.6, the note reveals daily naproxen since April, and metformin 500 mg is still on board.

## Schema additions proposed (not yet in docs/patient-model-schema.md)

Two shapes the build needs that the schema doc does not define. Both are additive; flag for team sign-off.

1. **Review record** on any proposed item once decided (`ehr/review.py`):
   `"review": {"by", "at", "decision": "accepted"|"rejected", "reason_code", "reason"}`. Reason codes:
   `already_known`, `not_relevant`, `disagree`, `needs_confirmation`, `other`. A rejection with a reason
   is the clinician's judgment made explicit; the composer reads these as the reasoning ledger.
2. **Document entity** (`ehr/compose.py`): `doc_` prefix, `{patient_id, problem_id, kind, audience, title,
   sections: [{heading, text, cites}], questions, status, provenance: {source: "composition", model,
   evidence, confidence}, created_at}`; signed documents live under a new top-level `documents` list.
3. **Order entity** (`ehr/orders.py`): `ord_` prefix, `{patient_id, problem_id, kind: lab | medication_change |
   referral | imaging, name, detail, code, med_id, change, dose, audience, status, provenance: {source:
   "ordering", model, from_insight, evidence, confidence}, created_at, ordered_at}`; signed orders live under
   a new top-level `orders` list. Orders derive only from signed insights.
4. **Visit coding** (`ehr/billing.py`) is computed on demand and never stored, like a TrendSummary: the
   E/M level follows the 2021 MDM rule (level met by two of three elements) over what was signed that
   day, and the ICD-10 codes come from a small demo table. Nothing is ever generated to justify a code.

## Things the team should know

- The chart's creatinine story is under `38483-4` (whole blood, diabetes-care visits); `2160-0`
  (serum, CHF panels) is flat for this patient. Both are `monitors` series for CKD.
- Schema interpretations that the schema doc leaves open are listed in `FLAGGED_DECISIONS` in
  `scripts/import_patient.py` and echoed in `data/patients/pt_001.import-report.json`.
- Regenerating Synthea output needs OpenJDK 21 (`brew install openjdk@21`) and the jar in
  `tools/synthea/` (see `scripts/gen_synthea.sh`). Don't regenerate mid-hackathon.
