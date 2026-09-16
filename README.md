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
| `data/patients/pt_002.json` | the demo chart: Jeane Lueilwitz, diabetes and hypertension, curated by `scripts/curate_pt_002.py` |
| `data/patients/pt_001.json` | the first golden chart (Willie Klocko, CKD + CHF + T2DM), still runnable with `?patient=pt_001` |
| `data/notes/` | hand-written demo notes (curated, don't overwrite) |
| `data/proposed/<pt>/` | review queues: `<note_id>.json` from extraction, `reason_<problem_id>.json` from reasoning |
| `ehr/trend.py` | `trend(patient_id, loinc_code, window)` -> TrendSummary (§9) |
| `ehr/extract.py` | note -> proposed observations / problems / medications / links (§3, §4, §7) |
| `ehr/reason.py` | TrendSummaries + chart context -> proposed Insights (§10) |
| `ehr/review.py` | accept / reject queue items into the chart, recording who, when and why; `sign_note` attests a note and everything it proposed |
| `ehr/compose.py` | chart state + signed insights + review decisions -> a generated referral letter with citations |
| `ehr/brief.py` | pre-visit brief per problem: computed on open (no model), or Claude-written over the same evidence |
| `ehr/orders.py` | signed insights -> proposed orders (labs, medication changes, referrals); signing a medication change edits the course |
| `ehr/record.py` | the record as events, read off provenance and review stamps: what a note, a signature or a model run wrote. Computed on demand |
| `ehr/overview.py` | the patient overview: what changed since the last routine visit, ranked by clinical meaning; active concerns by what they need; open loops. Computed on demand |
| `ehr/card.py` | the problem card: representation, supporting and doesn't-fit evidence, plan, expected trajectory and what changed, computed from the chart on demand (never stored) |
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

The screen is framed like a record: session tabs for the open patients, the practice bar, a
patient header with the visit and the note's status, and five patient tabs, **Overview ·
Timeline · Care · Chart · Notes**. The header carries one button, the next thing owed, computed
from the chart: read the note, review it, sign it, ask what changed on the concern that is moving,
sign the insights, draft and sign the orders, and finally "nothing owed", which opens the notes.
The visit chip in the header ("office visit · 15 Sep · note in progress") opens them too.

- **Overview** is orientation: what changed since you last looked, ranked by clinical meaning;
  the active concerns by what they need; the open loops. "Since" is the signed-in clinician's
  last visit with a note of their own, not a global last visit: a visit by someone else in
  between is news to them, not a baseline.
- **Timeline** is the record on one list, newest first, in five lanes a chip can hide: sessions
  (visits, with the note that documented them), results (one row per day, the monitored series
  called out, out-of-range counted), documents (notes and letters: signed, unsigned, imported),
  changes (courses opened, changed and closed on their clinical dates; problems raised; plan
  items; orders) and reasoning (insights, causes asserted, rejections with their reasons). The
  first lane alone is the old visit log; all five are the record. `ehr/timeline.py` computes it.
- **Care** is what we are doing: one card per concern with its plan, its measures and its open
  loops, chips that pivot the same objects by kind (plans, orders and requests, referrals,
  follow-ups, measures), and a due strip for monitored measures past their interval. Opening a
  card lands in the **problem workspace**: an evidence spine of the record read for that problem,
  a banner for each consequential proposal, the summary stack (one line, the cited assessment
  paragraph to accept or edit, the full history), the clinician's assessment in prose, a
  surveillance card (each monitored series with its threshold and state, the expectation and
  what to reassess on, the next review), a linked card, supporting and doesn't-fit evidence,
  insights, plan, the trajectory with the expectation drawn as a corridor.
- **Notes** lists every note on file for the patient by state: in progress (read, with decisions
  or a signature still owed, and how many), waiting to be read, signed (by whom, when). Each row's
  button is the next thing owed on that note.
- **The note** is the encounter canvas, reached from the header, the overview or Notes: the text with
  every passage the reading used marked, the clinical diff (each proposal in diff notation),
  consequential items first, each reviewed one at a time in a **drawer** (what the system saw,
  what it concluded, its confidence, each part separately signable; what changes on the chart if
  you sign; sign, or reject with a reason), the batchable rest under the problems they touch,
  a panel rail (plan, last note, medications, results) and charge capture. **Sign note** unlocks
  once the consequential items are decided and commits the rest; the record under the note lists
  what the reading and the signature wrote.
- **Timeline** is the patient's visits and record events; **Chart** is medications, results by
  series and problems.

Every screen has an "About this screen" door at its foot, and the Demo menu at the top right
holds the Claude live/saved switch, an About page on the record's architecture, and Reset.
Everything AI-proposed is drawn in *pencil* (dashed, amber) until a clinician signs it; signed
items become ink.

The chart opens on `pt_002`; `http://localhost:8000/?patient=pt_001` opens the first golden
patient, whose recorded demo (CKD, naproxen, metformin) still plays through the same views.

## Demo runbook

Every Claude call in the demo (extraction, reasoning, orders, referral, brief) is run live once
(`claude-opus-5`) and the responses are saved as `data/proposed/<patient>/*.raw.json`, so the demo
replays them offline and byte-for-byte. Live mode needs `ANTHROPIC_API_KEY` exported in the shell
that starts the server. The header has a **Claude: live / saved** switch.

The patient is Jeane Lueilwitz, 55, type 2 diabetes and hypertension on metformin and
hydrochlorothiazide. Over twelve months her A1c drifts 6.4 → 7.1 → 7.9 and her blood pressure
climbs 128/80 → 142/88 → 154/94, with new albuminuria. The note that arrives reveals why: she has
been skipping metformin for stomach upset, and taking ibuprofen daily for her back since May.

1. **Overview** opens cold: "here for: office visit, 15 Sep" with the note waiting, both concerns
   marked *worsening* with the blood pressure and glucose moves since January, nothing pending.
2. **Read the note** (the header button). The note view shows the text with every passage the
   reading used marked, the clinical diff, and the consequential items first: the ibuprofen
   course as a suspected cause of the blood pressure, the metformin switch, lisinopril, the new
   concern, low back pain. **Review** each in the drawer: sign it, or reject it with a reason.
   The batchable rest, results and plan items, sit under the problems they touch.
3. **Sign note** unlocks once the consequential items are decided. One signature commits the
   rest and attests the note; the **record** under the note lists what it wrote: results
   recorded, courses opened and changed, links asserted, plan items set, your rejections with
   their reasons, the signature.
4. Back on **Overview**: the medication changes lead the ranked list; open the hypertension row.
5. **The card.** Representation (proposed), your assessment, supporting evidence with the ibuprofen
   course as a suspected cause, the plan items from the note under *Plan*, and once ibuprofen is
   stopped an **Expected** line: systolic falling within two weeks, drawn as a corridor on the
   trajectory. **What's changed?** brings the insights; sign them. **Draft orders** turns the
   signed actions into orders; sign them.
6. **Add to plan**, on a Care card or in the workspace's plan slot: your own decision on a problem,
   one typed line (treat, test, monitor, refer, follow up, educate). It is signed as you add it and
   stamped with the visit; a test or referral also places the order, and a treat line can stop or
   re-dose a course on the chart, on the visit day. It shows on the card as "your decision, this
   visit", on the Timeline's changes lane, and in the visit note's plan (`ehr/intent.py`).
7. **Draft the visit note.** Once the transcript is signed and the concerns are settled, the button
   compiles the visit note from what you did: the transcript verbatim, the results recorded and
   reviewed, and per problem addressed an assessment and a plan rendered from the causes asserted,
   the rejections with their reasons, the signed insights, the plan items, the course changes and
   the orders. Every section carries the ids it came from. Edit the prose, **sign the visit note**;
   it lands on the record as a document of the visit, under Notes and on the Timeline. The chart
   writes the note; nothing reaches the chart before the signature (`ehr/draft.py`).
8. **Reset demo** restores the chart to its server-start state and clears the queues.
   (Start the server from a clean chart, since that is the state it snapshots.)

### The three-minute script

Twenty-nine proposals, six insights and nine orders is more than three minutes holds. Two beats
carry the demo; everything else is signed quickly. Start on `?patient=pt_002` from a clean chart,
Claude on **saved**.

| When | Do | Say |
|---|---|---|
| 0:00 | Overview | "Jeane, 55, diabetes and hypertension. Since Dr. Chen last saw her in January: systolic 142 to 154, glucose 142 to 168. Both concerns worsening. Nothing pending. A note from this morning is waiting." |
| 0:20 | **Read the note** | "The system reads it. Every passage it used is marked. The clinical diff lists what it proposes, in diff notation: two new problems, three courses, two suspected causes, nine plan items. Nothing has touched the chart." |
| 0:45 | **Review** the first item, ibuprofen | "The consequential items come first, one at a time, and the causal one leads: ibuprofen, 400 mg, since May, stopped today, as a suspected cause of the hypertension. Observation and attribution are separately signable. What changes if I sign is spelled out. This is beat one." **Sign.** |
| 1:15 | **Review** the metformin item | "The second cause it proposes is wrong: metformin as a cause of the diabetes. The note says adherence is the driver. **Reject**, disagree, one line: *non-adherence is the cause, not the drug*. The rejection is on the record with its reason. Beat two." |
| 1:40 | Review and sign the other five, fast | "Albuminuria raised, back pain raised, acetaminophen, lisinopril, the metformin switch." |
| 2:00 | **Sign note** | "One signature commits the rest and attests the note. The record under it lists what it wrote: courses opened, links asserted, plan items set, my rejection with its reason." |
| 2:15 | **Ask what changed on hypertension** | "The reasoning runs over the trends and the course events. Three insights, the second names the ibuprofen and expects a fall. The card shows the expectation as a corridor on the trajectory." |
| 2:40 | **Sign 3 insights** · **Draft orders** · **Sign 5 orders** | "Signed actions become orders. Button says the next thing owed each time." |
| 2:45 | **+ Add to plan** on the hypertension card | "My own line: home BP log, review in two weeks. Signed as I add it." |
| 2:50 | **Draft the visit note** | "The chart writes the note. The transcript is the first section, verbatim. Every other section is compiled from what I just did, and every sentence cites the record: the cause I asserted, the one I rejected and why, the insights, the plan, the orders. I edit one line." **Sign the visit note.** |
| 2:58 | Header | "Two unsigned notes on other patients: the button says so. Reset demo." |

If time is short, skip 1:40 and let **Sign note** wait: the button reads "Sign note · 5 to review
first", which makes the point that consequential items gate the signature.

Same flow from the shell:

```bash
python3 -m ehr.extract data/notes/note_demo_102.json --patient pt_002 --replay data/proposed/pt_002/note_demo_102.raw.json
python3 -m ehr.review pt_002 note_demo_102 --list
python3 -m ehr.record pt_002 --note note_demo_102
python3 -m ehr.reason pt_002 --problem prob_0007 --replay data/proposed/pt_002/reason_prob_0007.raw.json
python3 -m ehr.overview pt_002
python3 -m ehr.card pt_002 --problem prob_0007
python3 -m ehr.intent pt_002 --problem prob_0007 --kind monitoring --text "Home BP log, review in two weeks"
python3 -m ehr.draft pt_002 --encounter enc_c002          # the visit note, compiled; --sign to sign it as it stands
```

Drop `--replay` to call Claude live (each call is roughly 10-15k tokens). Every live run writes a
timestamped copy (`note_demo_102.20260915T091200.raw.json`, never overwritten) and updates the
`<stem>.raw.json` pointer that replay uses. To roll back a bad live run, copy an older timestamped
file over the pointer. Reset from the shell:
`git checkout data/patients/pt_002.json && rm data/proposed/pt_002/*[^w].json` (everything but
the recordings).

The first golden patient's runbook (Willie Klocko, creatinine 1.6 → 5.7, naproxen since October,
metformin at eGFR 15.6) still works at `?patient=pt_001` with its recordings under
`data/proposed/pt_001/`.

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
4. **Plan item** (`ehr/extract.py` plans, `ehr/review.py`): `plan_` prefix, `{patient_id, problem_id, kind: diagnostic |
   therapeutic | monitoring | referral | education | follow_up, text, status, provenance (note_id + quote), created_at}`;
   signed plan items live under a new top-level `plans` list. What the note's assessment and plan says will be done,
   one item each, tied to the problem it addresses.
5. **Note status** (`ehr/review.py::sign_note`): a note gains `status: "received" | "signed"` and a `review` record
   when the clinician signs it; signing commits every proposal from that note that was not rejected.
6. **Curated provenance** (`scripts/curate_pt_002.py`): `provenance.source: "curated"` marks values written for the
   demo story, distinct from `fhir_import`.
7. **Visit coding** (`ehr/billing.py`) is computed on demand and never stored, like a TrendSummary: the
   E/M level follows the 2021 MDM rule (level met by two of three elements) over what was signed that
   day, and the ICD-10 codes come from a small demo table. Nothing is ever generated to justify a code.

7. **`encounter_id` on the review record** (`ehr/review.py`): the visit a signature happened in, stamped on
   every accept and reject. It is what lets the visit note be compiled from one encounter's decisions.
8. **Visit note as a Document** (`ehr/draft.py`): `kind: "encounter_note"`, `encounter_id`,
   `problems_addressed[]`, `problem_id: null`; sections carry `source` (`transcript` | `compiled`) and
   `edited`. Queued as `visitnote_<encounter_id>`, signed into `documents` like the referral letter.
9. **Clinician provenance** (`ehr/intent.py`): `provenance.source: "clinician"` with `by`, on plan items, orders
   (`from_plan` names the intent) and medication changes the clinician makes directly. Signed as made; the
   review record carries the encounter.

## Things the team should know

- The chart's creatinine story is under `38483-4` (whole blood, diabetes-care visits); `2160-0`
  (serum, CHF panels) is flat for this patient. Both are `monitors` series for CKD.
- Schema interpretations that the schema doc leaves open are listed in `FLAGGED_DECISIONS` in
  `scripts/import_patient.py` and echoed in `data/patients/pt_001.import-report.json`.
- Regenerating Synthea output needs OpenJDK 21 (`brew install openjdk@21`) and the jar in
  `tools/synthea/` (see `scripts/gen_synthea.sh`). Don't regenerate mid-hackathon.
