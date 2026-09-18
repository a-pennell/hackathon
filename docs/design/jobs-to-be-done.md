# Jobs to be done

**Status:** design input, 16 September 2026. Companion to `docs/design/clinical-reasoning-ehr.md`
and the twelve PRDs. Describes what people come to the record to get done, not what the screens are.

## What a job is here

A job is a situation, a motivation, and the outcome that says it is done. Jobs are stable;
screens are not. The prototype commits to one rule this document depends on: **the patient header
carries one button, the next thing owed, computed from the chart** (`frontend/src/next.ts`). That
button must always resolve to one of the jobs below for the person signed in, in their role. Today
it resolves only for a primary care clinician on one patient whose note has already arrived.

Marks: **built** (with where it lives), **partly**, **not built**. Built means in this prototype,
not in the NDE north-star. The worked patient is Jeane Lueilwitz, 55, type 2 diabetes and
hypertension, whose 15 September note reveals daily ibuprofen since May and skipped metformin.

## Primary care clinician

1. When a note has arrived on the patient in front of me, I want to see what it changes on the
   chart before I sign, so I can attest what is true and refuse what is not. **Built**: the note
   view's clinical diff and review drawer; the ibuprofen course as suspected cause of the blood
   pressure is the first consequential item.
2. When I open a patient I have not seen in months, I want to know what moved and why, so I walk
   in oriented. **Built**: Overview's "what changed since the last routine visit" (A1c 6.4 → 7.9,
   BP 128/80 → 154/94); `ehr/brief.py`.
3. When a concern is worsening, I want the record to say what it thinks is happening and what
   does not fit, so I can decide whether to change course. **Built**: the Care card
   (representation, supporting, doesn't fit, expected trajectory) and "What's changed?" insights.
4. When I have decided, I want the decisions to become orders and course changes without
   re-typing, so I can close the visit. **Built**: `ehr/orders.py`; signing the metformin change
   edits the course.
5. When I have several patients in a day, I want every unsigned note and unacknowledged result in
   one place, so nothing is left owed at day's end. **Partly**: the Notes tab lists one patient's
   notes by state; nothing crosses patients (PRD-09).
6. When I am in the room, I want to write the note against live context and have the record read
   it as I go, so documentation is one act. **Not built**: notes are files that arrive; no
   composer (PRD-06).

## Behavioral / mental health clinician

1. When I finish a session, I want to write the note type it calls for (intake, progress,
   crisis, termination) with today's risk assessment recorded on the patient, dated and never
   buried in prose, so a stale low-risk note cannot read as current. **Not built**: no note
   types, no risk object (ADR 0003 G5, PRD-07).
2. When a patient is in front of me, I want PHQ-9 and GAD-7 as a series with today's score
   entered, so I can see whether treatment is working. **Not built**; Chart's series-first results
   view is the shape, but no instruments exist.
3. When I write process notes, I want a section the system will not read, extract from or
   compile, so my working notes stay private. **Not built** (PAT·08, PRD-06 §11); extraction
   reads the whole note today.
4. When a treatment plan is due for review, I want its goals with measured progress in front of
   me, so the review is a judgment, not a re-typing. **Not built**; Care plan items are the nearest
   shape.
5. When a primary care colleague opens a shared patient, I want them to see that a behavioral
   health course exists without its content, so confidentiality holds below the document. **Not
   built**: no permissions.

## Front desk / scheduling

1. When a patient calls or arrives, I want to find them by name, date of birth or record
   number, so I open the right chart. **Not built**: the practice bar's search is disabled.
2. When I am running the day, I want to see who is booked, arrived, roomed, in visit and done, so
   I can move people and answer "how long". **Not built** (PRD-11 Today, Schedule).
3. When someone needs to be seen, I want to book, move or cancel a visit and have it become the
   encounter the clinician documents in, so front and back share one object. **Not built**;
   encounters are chart markers only.
4. When a patient no-shows, I want it recorded and the follow-up raised without touching the
   clinical chart. **Not built**.
5. When forms, consent or insurance need checking before a visit, I want a readiness state per
   visit. **Not built**.

## Medical assistant / rooming

1. When I room a patient, I want to enter vitals and the reason for visit so they land as
   recorded values the clinician's view reads at once. **Not built**: the demo's 154/94 arrives
   inside the clinician's note.
2. When I room a patient, I want to reconcile the medication list with what they actually take,
   so the clinician learns metformin is skipped before, not during, the visit. **Partly**:
   medications are courses in Chart; no reconciliation surface.
3. When a monitored measure is due, I want to see it while the patient is here, so I collect it.
   **Partly**: the Care tab's due strip.
4. When the clinician has signed orders, I want the ones I execute as a list I can complete.
   **Partly**: signed orders exist; no completion state or assignment.
5. When a patient message is routine, I want to answer within protocol and route the rest. **Not
   built** (PRD-11 Messages).

## Care coordinator / nurse triage

1. When results land, I want the abnormal ones across my patients in one queue with what was
   expected on each, so I route what needs a clinician and close what does not. **Not built**
   cross-patient; per patient the surveillance card shows thresholds.
2. When a patient calls with a symptom, I want concerns, courses and last plan in one glance, so
   I triage against the real picture. **Partly**: Overview, for one patient; no triage occasion.
3. When a referral has gone out, I want to know it was received and answered, so it does not
   silently die. **Not built**: referrals are orders with no reply state.
4. When a follow-up was promised (BMP in two weeks, home BP log in four), I want it owed on the
   day, to someone. **Partly**: plan items of kind `follow_up` are signed; no owner, no date-driven
   queue (PRD-09).
5. When a high-risk patient is in a transition, I want a bounded course with a checklist, so the
   work has an end. **Not built** (PRD-07).

## Billing and coding

1. When a note is signed, I want diagnosis codes and the E/M level derived from what was
   signed, each element justified, so I submit what the record supports. **Built**:
   `ehr/billing.py`, Charge capture in the note view after signing.
2. When a charge is captured, I want it to move through ready, held, submitted, paid and denied
   on one object, so I never re-key it. **Not built** (PRD-11 Revenue).
3. When a claim is denied, I want the encounter it came from and its signed evidence, so the
   appeal writes itself. **Partly**: the record under the note lists what the signature wrote; no
   claim object.
4. When I review a day, I want every signed encounter with no charge, so nothing goes unbilled.
   **Not built**.
5. When a diagnosis is claimed but not clinically held, I want that recorded as a distinct
   attestation. **Not built** (PRD-03).

## Patient (portal, brief)

1. When my visit is over, I want what was decided in plain words, what I do and what happens
   next, so I leave with a plan I understand: stop the ibuprofen, metformin extended-release with
   dinner, start lisinopril, log blood pressure, BMP in two weeks. **Not built**; the patient
   summary view is named in PRD-08 only.
2. When a result comes back, I want it with what it means for me, so I am not waiting on a call.
   **Not built**.
3. When I have a question, I want to send it and know who has it. **Not built** (Messages).
4. When my medication list is wrong, I want a way to say so, so "skipping metformin" reaches the
   chart before the visit. **Not built**.
5. When I am asked for a questionnaire or a home BP log, I want to enter it before the visit and
   have it land as a measure. **Not built**.

## Note drafts as a first-class job

Every clinician role shares a job: **see my notes in progress and completed for the day, resume
a draft, and know which are unsigned.** Half is built. The **Notes** tab (`frontend/src/NotesTab.tsx`)
lists one patient's notes as *In progress* (read, decisions or signature owed, with the count),
*Waiting to be read* and *Signed* (by whom, when); each row's button is the next thing owed on
that note: *Read*, *Review · n*, *Sign*, *Open*. "Visit signed" opens it. Missing: notes are never
written here (`received` or `signed` only; no composer, PRD-06), so there is no draft to resume;
notes have an author but no *mine*; and the list is per patient, so the clinician's day is invisible.

**Note states** the full job needs: `draft` (in a composer, autosaved as `encounter.draft_saved`),
`awaiting signature` (today's *in progress*), `signed` (frozen, snapshotted), `amended` (a later
version with `amends`). Draft and awaiting signature are unsigned.

**The header button, per state, for the signed-in clinician on the open patient:**

| Situation | Button says | Opens |
|---|---|---|
| Visit open, no note started | *Start the note* (not built) | composer on the encounter |
| Draft exists by me | *Resume the note* (not built) | composer, restored exactly |
| Note arrived, unread | *Read the note* (built) | note view |
| Proposals undecided | *Review the note · n* (built) | note view, drawer on the first consequential item |
| Everything decided | *Sign the note* (built) | sign gate |
| Signed; concern moving | *Ask what changed on hypertension* (built) | card |
| Nothing owed here, unsigned notes elsewhere | *Unsigned notes · n* (not built) | the notes list, mine, across patients |
| Nothing owed anywhere | *Visit signed* (built; was "Nothing owed") | this patient's Notes tab |

The change to the built machine is the second-to-last row: **"Visit signed" must not be reachable
while the same clinician has unsigned notes on other patients.** The button's idle state is the
clinician's documentation debt, not the patient's.

**The notes list across patients** is the Notes tab's three sections as a Work lens, filtered to
mine or my team, each row a deep link carrying the verb the header would show on that patient.
Nothing is worked in the list. Mental health notes appear with their type, never their content.

## Where the primary call-to-action should default

| Role | The one job the header button defaults to | Secondary jobs a tab or panel serves |
|---|---|---|
| Primary care clinician | Sign what is owed on this patient's note; when nothing is, my unsigned notes across patients | Overview (what moved), Care card (what we think, what next), Notes, orders, referral letter |
| Behavioral health clinician | Resume or sign today's session note, with risk recorded | Measures series (PHQ-9, GAD-7), treatment plan review, private section |
| Front desk / scheduling | Find the patient; then the next arrival to check in | Today's day, booking, readiness, no-show follow-up |
| Medical assistant / rooming | Room the next patient (vitals, reason, medication reconciliation) | Due measures, orders to execute, routine messages |
| Care coordinator / nurse triage | Review the next result or follow-up owed across my patients | Referral status, triage glance, course checklists |
| Billing and coding | Capture the next uncharged signed encounter | Charge states, denials with evidence, claim-vs-conviction attestation |
| Patient | Read what was decided at my last visit and what I do next | Results with meaning, messages, medication check-in, questionnaires |

Only the first row's button exists today, and it stops one step short: its idle state opens one
patient's notes instead of the clinician's.
