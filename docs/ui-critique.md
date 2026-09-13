# Chart desk: systems and cognitive-load critique

13 September 2026. Measured at 1440×900 on pt_001 in two states: **A**, note 2 extracted and
nothing signed; **B**, decisions made, two insights signed, referral pending. Numbers are from
the DOM, not estimates. Severity uses the 0–4 usability scale (4 = prevents task completion).

## 1. The system as a system

The build is a pipeline with one human gate:

```
chart (fhir_import) ──► extract ──► queue ──► sign/reject ──► chart (accepted)
                             ▲                     │
                     recordings (replay)           ▼
                                           reason ──► queue ──► sign ──► chart.insights
                                                        │
                                           orders ◄─────┘──► compose (referral) ──► chart.documents
                                                        ▼
                                  brief / trail / coding  (projections, never stored)
```

**What holds.** Every state change to the chart goes through one function (`accept_item`) with one
invariant (nothing AI-produced is on the chart without a review record). Every model call is
recorded and replayable, so the system is deterministic after the first live run. Reset returns
to a snapshot of a clean chart. Projections (trend, brief, trail, coding) are pure functions of
chart + queue and never persist, so they cannot drift.

**Coupling that will bite.**

| Issue | Where | Severity | Why it matters |
|---|---|---|---|
| Queue files are the source of truth for decisions, and they live beside the recordings in one folder. Reset deletes by filename pattern. | `data/proposed/` | 2 | A second patient or a renamed queue silently breaks reset and the ledger. Decisions belong in the chart (as a `reviews` list) or a dedicated store, not in the proposal files. |
| Every frontend refresh refetches everything: summary, queues, timeline, brief, trail, coding. Signing one link triggers six requests and re-renders the sheet. | `App.tsx` `refresh()` | 2 | Fine at 3,800 observations; visible lag at 10× that. Also causes the timeline to flash during the fetch. |
| The snapshot for reset is taken at server start and only when the chart is clean. A server started mid-demo has no snapshot. | `backend/main.py` | 2 | Already caught once. The warning goes to stdout, which the presenter won't see. Should surface in the UI. |
| Problem identity is fragmented: four CKD-stage problems share monitored series, so signing one creatinine link "addresses" four problems in the coding panel. | import, `billing.py` | 3 | Inflates the problems element and confuses the audience. Root cause is the one-problem-per-FHIR-condition import decision (flagged, but now it has consequences). |
| Order → course mutation happens inside `accept_item` as a side effect. | `review.py` | 1 | Correct but invisible; a signed order silently rewrites a medication band. Needs an "ordered" event on the trail. |
| Live runs overwrite the replay pointer. Timestamped copies exist, but rollback is a manual copy. | `record_response` | 1 | Acceptable for the demo; needs a "make this the replay" action later. |

## 2. Cognitive load, measured

| Measure | State A | State B | Reading |
|---|---|---|---|
| Header actions | 10 (4 buttons, 3 of them menus hiding 9 actions, plus 6 window segments) | same | Two of the menus (Reason, Compose) are the demo's whole narrative and are visually equal to "Reset demo". |
| Brief | 7 sentences, 607 chars | 11 sentences, 1,051 chars | The brief grows with every signature and pushes the timeline to y = 396 px of 843. In state B the hero view starts below the midpoint of the screen. |
| Sheet scroll height | 1,616 px (1.9 screens) | 3,042 px (3.6 screens) | Trail starts at 1,234 px, coding at 2,336 px. The two panels that justify the pitch are two and three screens down. |
| Inbox | 38 cards, 76 buttons, 6,210 px (7.4 screens), 784 words | 44 cards, 8,682 px (10.3 screens), 34 of them already signed | The queue never empties: signed cards stay in the inbox, so the "review" surface is 77 % history by state B. |
| Decisions per note | 38 sign/reject pairs + 1 "sign all" | | Two-thirds of the cards are links. A clinician signs *findings*, not links. |
| Encounter row | 82 ticks in one year | | Daily telemedicine ticks in spring 2026 form a comb; the two ticks that matter are indistinguishable at a glance. |
| Problem list | 19 rows, names wrapping to 3 lines once the ✎ tag appears | | Wrapping breaks scanning; the tag competes with the name. |

Against Sweller's three loads: intrinsic load is genuinely high (multimorbid patient, four series,
thirteen medications) and that is fine. **Extraneous load is where the build now fails**: the
inbox asks for 38 decisions where the clinical content is about eight; the brief repeats what the
lanes show beneath it; signed history sits in the queue. Germane load is protected in the right
places (evidence-first cards, reasons on rejection) and undercut in one (the suggested action sits
beside the evidence, so the conclusion arrives before the judgment forms).

## 3. Heuristic findings

Nielsen's ten, scored 0–4 severity; only findings with severity ≥ 2 are listed.

| # | Heuristic | Finding | Sev |
|---|---|---|---|
| 8 | Aesthetic and minimalist | Inbox: 38 cards for one note; signed cards remain; links shown as first-class cards. Signal-to-noise is the single biggest problem. | 3 |
| 6 | Recognition over recall | Link cards read `obs_7f3ce7a6 relevant_to prob_0057` in the trail and as raw ids in chips. Names exist in the labels map but aren't used everywhere. | 2 |
| 1 | Visibility of system status | "Signing…" appears in the header, far from the card being signed; the timeline flashes stale data during refetch; no confirmation that a signature landed beyond the badge change. | 2 |
| 2 | Match with the real world | "Compose", "Reason about this problem", "Replay last Claude run", "rules only" are system vocabulary. A clinician would say "Draft orders", "What changed?", "Referral letter". | 2 |
| 3 | User control and freedom | No undo after sign. Reject has a reason row, sign is instant and irreversible in the UI (the data model would allow un-signing). | 3 |
| 4 | Consistency | Three different affordances mean "run the model": a header menu (Reason), a header menu (Compose), and inline text buttons on the brief ("Ask Claude", "replay"). | 2 |
| 7 | Flexibility and efficiency | No keyboard path through the queue; every decision is a mouse click on a 22 px button. A reviewer signing 38 items needs J/K plus S/R. | 2 |
| 5 | Error prevention | "Sign all 44" is one click with a native confirm only on Reset. Sign-all skipping links into rejected items is correct but reported only in the API response, not on screen. | 2 |
| 10 | Help | None, and the affordances that need it most (pencil vs ink, what "cause?" means, what a chip does) have no explanation anywhere in the UI. | 2 |

Trunk test: passes. Patient, problem, and section are always visible; the selected problem is
marked; the sheet header says what you are looking at.

Krug's "half the words": the brief and the inbox both fail it. The brief says "across 4 results"
four times; the inbox repeats the verbatim quote on every link card that shares one.

## 4. What the hero view does well

Worth stating so the fixes don't sand it off. The co-registered sheet is right: one axis, bands
under curves, out-of-range flagged, the moving series first, latest-plus-delta in the margin.
Pencil-versus-ink is legible without explanation once seen. Chips that light up the sheet are the
best interaction in the product; they make the citation rule tangible. Reasons on rejection are a
genuine advance over any chart the audience has used. The trail and coding panels make the
argument of the whole project visible in the product, not in a slide.

## 5. Fixes, ranked by load removed per hour of work

1. **Collapse links into their findings.** A finding card carries its links as a footer ("→ CKD
   stage 3, → HTN") and signing the finding signs its links. Note 2 drops from 38 cards to about
   12. Removes the most extraneous load of anything on the list. ~2 h.
2. **Signed items leave the queue.** Move them to a collapsed "Signed today (34)" strip under the
   queue; the review surface shows only what still needs a decision. Queue height falls from 10
   screens to under 2. ~1 h.
3. **Brief: cap and don't repeat the lanes.** Three sentences: what changed most, what is waiting,
   what you decided last time. Series detail belongs in the margin of each lane, which already
   shows it. Timeline returns to the top third of the screen. ~1 h.
4. **Undo after sign.** A 10-second "Signed · undo" toast per decision; un-sign removes the chart
   copy and restores the queue status. Removes the fear tax on every click. ~2 h.
5. **Rename the actions in the clinician's language.** "A note arrives" → "Read a note"; "Reason
   about this problem" → "What's changed?"; "Compose" → "Draft orders / Draft referral"; "Replay
   last Claude run" → "Use saved draft". The live/replay distinction is ours, not theirs, and can
   live in a small mode switch in the header. ~30 min.
6. **Keyboard review.** J/K to move, S to sign, R to reject, Enter to confirm a reason. ~1 h.
7. **Group the encounter comb.** Ticks within 3 days collapse to one marker with a count; the two
   note-bearing ticks stay distinct. ~1 h.
8. **Names, not ids, everywhere.** Chips show `obs_7f3ce7a6` on hover and the name inline; the
   trail already resolves names, the inbox link cards should too. ~30 min.
9. **Reset snapshot warning in the UI**, not stdout. ~15 min.
10. **Move decisions out of the queue files** into the chart. Not for today; the first thing to
    do when a second patient exists.

Doing 1–3 before the demo changes the product more than anything built this week; they are also
the three that the principles document already predicted (P7, P8) and scored at 2.

## 6. Score

Against the heuristic framework's 0–10: **6/10** today. The hero view and the provenance model
are at 9; the queue and the header drag the whole down. Fixes 1–5 would put it at 8; they cost an
afternoon.

## 7. After fixes 1–5 (same day, measured the same way)

| Measure | Before (state A) | After |
|---|---|---|
| Inbox cards for note 2 | 38 | 22, each carrying its links as a footer |
| Inbox buttons | 76 | 46 |
| Inbox height | 6,210 px (7.4 screens) | 3,970 px (4.7 screens); signed items leave into a strip |
| Brief | 7 sentences, 607 chars | 2 sentences, 162 chars |
| Timeline top | ~330 px | 222 px |
| Header actions | 3 menus hiding 9 actions | 4 direct buttons + a live/saved switch |
| Undo after sign | none | 10-second undo on every decision, reversing chart copies and auto-signed links |
| Raw ids on cards | frequent | none (queue carries a labels map) |

Two design rules fell out of doing it: a link into a proposed problem belongs to the problem's
card, not the item's, because it cannot be signed before the problem exists; and any card whose
links would sign another proposed item says so ("signs it too") rather than doing it silently.

Remaining from the list: keyboard review, the encounter comb, and moving decisions out of the
queue files. Score after fixes: **8/10**.
