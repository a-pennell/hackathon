# Hand-written demo notes

Curated demo assets for `pt_002` (Jeane Lueilwitz, the demo) and `pt_001` (Willie Klocko, the first golden patient). **Do not overwrite or regenerate.** Every number in
these notes matches the chart in `data/patients/pt_001.json` (creatinine under LOINC `38483-4`,
eGFR `33914-3`, BP, weight, ACR, med list), so the timeline, the extraction output and the trend
summaries line up during the demo.

## File shape

One JSON file per note: `{"encounter": <Encounter §5>, "note": <Note §6>}`. The encounter is
included so the ingest step can upsert it before the note (the note "arrives" with its visit).
For `note_demo_001` the encounter is `enc_0253`, already in the chart (identical copy, no-op upsert).
For `note_demo_002` the encounter `enc_0262` is **new** and dated after the last imported visit.

Nothing in these files is pre-extracted. Findings, links and insights must come out of the pipeline
with `status: "proposed"` and a verbatim `quote` (non-negotiables 1 and 2).

## Demo arc

1. **`note_demo_001`** (2026-05-20, routine follow-up). Creatinine has *dipped* to 3.69, so the
   reasoning layer should stay quiet. The note plants the seed: knee pain, "takes Aleve from the
   pharmacy when it's bad".
2. **`note_demo_002`** (2026-09-11, the note that arrives live). Creatinine 5.7, eGFR 15.6, uremic
   symptoms, and the patient admits to naproxen 500 mg twice daily since last October. Metformin 500 mg
   twice daily is still on the list. This is the decision moment: rising creatinine, NSAID as
   suspected cause, metformin needs review at this eGFR. The note deliberately leaves that decision
   "pending" so the system, not the author, surfaces it.

## Extraction answer key (what a good run should propose)

### note_demo_001 → existing problems + one new problem + one new medication

| Quote (verbatim) | Proposed item | Link |
|---|---|---|
| "creatinine 3.69, down from 5.57 in April" | Observation 38483-4 = 3.69 (2026-05-20) | relevant_to → CKD (prob_0057) |
| "eGFR 24" | Observation 33914-3 = 24 | relevant_to → CKD |
| "K 4.73" | Observation 6298-4 = 4.73 | relevant_to → CKD |
| "BP 80/48" | Observations 8480-6 = 80, 8462-4 = 48 | relevant_to → HTN (prob_0002) |
| "Trace bilateral ankle edema" | finding | relevant_to → CHF (prob_0036) |
| "one low of 62 last week" | Observation glucose = 62 (approx. date) | relevant_to → T2DM (prob_0004) |
| "Both knees have been aching since last fall" / "likely osteoarthritis" | **new Problem** Bilateral knee osteoarthritis (status proposed) | evidence_for ← note |
| "He takes Aleve from the pharmacy when it's bad, maybe a few times a week" | **new MedicationCourse** Naproxen (OTC, prn, start ~2025-10) | treats → knee OA (proposed) |
| "Uses furosemide 40 mg only when his ankles swell" | confirms existing med_furosemide prn | treats → CHF |

### note_demo_002 → the decision moment

| Quote (verbatim) | Proposed item | Link |
|---|---|---|
| "creatinine 5.7, up from 3.69 in May and 4.4 in late July" | Observation 38483-4 = 5.7 (2026-08-19, already in chart: dedupe or attach) | relevant_to → CKD |
| "eGFR 15.6" | Observation 33914-3 = 15.6 | relevant_to → CKD |
| "taking naproxen 500 mg twice a day most days since around last October, over the counter" | **MedicationCourse** Naproxen 500 mg PO bid, start ~2025-10, end 2026-09-11 ("Counseled to stop naproxen today") | suspected_cause → CKD progression / creatinine series |
| "Still on metformin 500 mg twice daily" | confirms existing med_metformin_hydrochloride | treats → T2DM |
| "fatigue, poor appetite, and nausea most mornings" / "metallic taste" | findings | evidence_for → CKD (uremic symptoms) |
| "1+ bilateral pitting edema to the ankles" / "uses furosemide about every other day now" | finding + med frequency change | relevant_to → CHF |
| "BP 84/52" / "Hold HCTZ starting today" | Observations 84/52; **med_hydrochlorothiazide segment end 2026-09-11** | relevant_to → HTN |
| "Reduce evening 70/30 insulin by 4 units" | insulin dose change (new segment) | treats → T2DM |
| "CKD progressing" / "eGFR is now under 20" | **Problem update**: CKD stage 4 (or 5) proposed, stage 3 to resolve | — |
| "Bilateral knee osteoarthritis" | confirms proposed problem from note 1 | — |

### Expected Insight (reasoning layer, from `trend("pt_001", "38483-4", "1y")` + events)

Statement along the lines of: *creatinine up ~250% over 12 months (1.62 → 5.7), eGFR 15.6; daily
naproxen since last October is a likely contributor; metformin is on board at an eGFR where it is
contraindicated.* `evidence` must cite real ids: the creatinine observations, `med_metformin_hydrochloride`,
and the proposed naproxen course once accepted. `suggested_action`: stop naproxen (done in note), stop
metformin, nephrology (already referred).


---

## pt_002 · Jeane Lueilwitz (the demo)

Chart curated by `scripts/curate_pt_002.py`; every number below is on it.

1. **`note_demo_101`** (2026-01-25, check-up). A1c 7.1 up from 6.4, BP 142/88, fasting glucose 142.
   Plants the seeds: stomach upset with metformin, "takes Advil when it's bad", home BP in the 140s.
2. **`note_demo_102`** (2026-09-15, the note that arrives). A1c 7.9, BP 154/94, ACR 48 up from 18.
   Skipping metformin most days for three months; ibuprofen 400 mg two or three times a day since
   around May. The plan: switch metformin to extended-release, stop ibuprofen, start lisinopril,
   BMP in two weeks, home BP log with a goal, physical therapy referral, A1c in three months.

### Extraction answer key for note_demo_102

| Quote (verbatim) | Proposed item | Link |
|---|---|---|
| "BP 154/94 sitting" | Observations 8480-6 = 154, 8462-4 = 94 (2026-09-15) | relevant_to → HTN (prob_0007) |
| "A1c 7.9" / "Fasting glucose 168" / "Urine albumin/creatinine 48 mg/g" | already on the chart (2026-08-02): dedupe or attach | relevant_to → T2DM (prob_0009) |
| "skipping metformin most days for about three months because of the stomach upset" | finding | evidence_for → T2DM |
| "taking ibuprofen 400 mg two or three times a day most days since around May, over the counter" | **new MedicationCourse** Ibuprofen 400 mg, start 2026-05-01, end 2026-09-15 ("Stop ibuprofen") | suspected_cause → HTN |
| "Daily NSAID use since May, likely contributing." | suspected_cause | ibuprofen → HTN |
| "Switch metformin to extended-release 1000 mg daily with dinner." | metformin dose_change + **plan** (therapeutic) | treats → T2DM |
| "Start lisinopril 10 mg daily." | **new MedicationCourse** Lisinopril 10 mg + **plan** (therapeutic) | treats → HTN |
| "Repeat A1c in 3 months." / "BMP in 2 weeks." / "Home BP log, goal under 140/90 in 4 weeks." | **plans** (monitoring) | T2DM / HTN |
| "Physical therapy referral." | **plan** (referral) | new problem |
| "Low back pain, mechanical." | **new Problem** Low back pain (status proposed) | evidence_for ← note |

### Expected insights (reasoning, prob_0007 and prob_0009)

Blood pressure above goal and rising on hydrochlorothiazide alone with daily NSAID use since May
and new albuminuria; the stop and the ACE inhibitor start are recorded, the expectation is a fall
within weeks. A1c rising with documented non-adherence rather than treatment failure; the
extended-release switch addresses the cause; recheck in three months.
