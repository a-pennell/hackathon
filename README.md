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

In the UI, from a fresh chart (CKD stage 3 selected). The header has a **Claude: live / saved**
switch: *saved* replays the recorded responses (no network), *live* calls the API. The sheet opens
with a **pre-visit brief** (what moved, what changed on the medication list, what is waiting, what
you decided last time) and closes with the **decision trail** and **visit coding**, all of which
update as you sign and reject.

1. **Read a note** → pick note 2 → **Read (saved)**. Findings land in **To sign** in pencil,
   about a dozen cards, each carrying the links it proposes; the naproxen course appears dashed
   on the sheet with a "cause?" tag.
2. Reject "Chronic kidney disease stage 4" with a reason; **sign all** the rest. Every decision
   shows a 10-second **Undo**. Signed items move into a collapsed "signed" strip.
3. **What's changed?** Four insights, each citing real ids: restage CKD; naproxen as contributor;
   **stop metformin at eGFR 15.6**; the two creatinine assays disagree. Hover the chips; sign.
4. **Draft orders** (needs one live run to record): the signed actions become orders; a signed
   medication change edits the course on the sheet.
5. **Draft referral**: a letter rendered from the chart, the signed insights and your decisions,
   every section carrying tap-through citations. **Read** it, then **Sign referral**. The
   **Visit coding** panel updates with each signature.
6. **Reset demo** restores the chart to its server-start state and clears the queues.
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

## Where this goes next

`docs/roadmap/00-north-star-and-gap-analysis.md` maps the prototype onto the target architecture
in the NDE documentation set (`~/Projects/NDE/docs`) and sequences twelve PRDs in `docs/prd/`
(ledger → verbs → focus and edges → attestation → evidence → courses → composer → compiler → Work →
shell → operations → permissions). `docs/roadmap/schema-v2-proposal.md` lists every schema change
those PRDs need, flagged for team agreement; `docs/patient-model-schema.md` is unchanged.

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
5. **Clinician chart edits** carry `provenance: {source: "clinician", evidence: [ids]}` plus a review
   record. Used when restaging CKD: the stage 1-3 problems were set `resolved` (with `resolved_date`
   and a review record naming the signed restage insight) and the `monitors` links for the creatinine,
   eGFR and BUN series were re-pointed at the stage 4 problem. Nothing is deleted; the old problems
   keep their links and history. Visit coding only lets a problem that is active on the coded day own
   a monitored series, so a resolved stage no longer counts as "progressing". The four signed insights
   (and the reasoning / referral queue batches they came from) were re-pointed from the stage 3 id to
   the stage 4 id so the decision ledger follows the restaged problem; ids and provenance are unchanged,
   and the `*.raw.json` recordings keep their `prob_0057` stems.

## Things the team should know

- `data/patients/pt_001.json` is the **fresh** chart the demo starts from (nothing extracted, nothing
  signed); the server snapshots it at start for "Reset demo". One curation on top of the import: CKD
  stages 1 and 2 are `resolved` at the onset of the stage that superseded them (2021-01-20 and
  2025-11-26), and "Disorder of kidney due to diabetes mellitus" is `resolved` at stage 3 onset
  (2025-11-26) since the kidney disease is tracked under the CKD stage from then on. So the visit
  coding shows one CKD line, not four. The chart as it
  looks after the whole arc has been walked (note 2 signed, insights signed, stages restaged to 4)
  is in git history at commit `55e2e5f` if you need it.
- The chart's creatinine story is under `38483-4` (whole blood, diabetes-care visits); `2160-0`
  (serum, CHF panels) is flat for this patient. Both are `monitors` series for CKD.
- Schema interpretations that the schema doc leaves open are listed in `FLAGGED_DECISIONS` in
  `scripts/import_patient.py` and echoed in `data/patients/pt_001.import-report.json`.
- Regenerating Synthea output needs OpenJDK 21 (`brew install openjdk@21`) and the jar in
  `tools/synthea/` (see `scripts/gen_synthea.sh`). Don't regenerate mid-hackathon.
