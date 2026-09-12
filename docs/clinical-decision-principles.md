# Principles for Deciding in the Chart

Twelve principles for judging an interface that sits between a clinician and a decision, drawn
from the research on how clinicians actually decide, what the electronic record did to that,
what decision support did, and what AI changes. Each principle carries the evidence it rests on,
three checks you can apply to any screen, and an honest score for the chart desk in this repo.

Score any screen 0-3 per principle. Anything at 0 or 1 is the next thing to build.

---

## 1. What the research says

### How clinicians decide

**Recognition first, analysis second.** Croskerry's universal model: a presentation the clinician
recognizes engages fast, pattern-based System 1; an unrecognized one engages slower analytical
System 2; either can override the other, and both feed a calibrator that learns from outcomes
[2]. Most diagnostic error comes from failed heuristics in System 1 (anchoring, premature
closure), and the countermeasures Croskerry proposes are *cognitive forcing strategies*:
deliberate checks placed at the moment of decision, not general exhortations to be careful [2].

**Experts do not compare options.** Klein's recognition-primed decision studies found that in
fewer than 12 percent of decision points did expert fireground commanders weigh alternatives.
They recognized the situation as typical and mentally simulated the first plausible action [3].
The same holds in medicine: an interface that presents a menu of options to an expert is
answering a question they are not asking. What they need is the pattern, presented so
recognition can fire.

**Situation awareness has three levels.** Endsley: perceiving the elements, comprehending what
they mean, projecting what happens next [4]. A 2023 review of nineteen studies concluded that
electronic records mostly serve the first level and "do not support the development of higher
levels of SA" among primary care physicians [4]. A value on a screen is perception. A trend with
a baseline is comprehension. A trend with the medication that changed it is the beginning of
projection.

**Load has three kinds, and only one is worth paying.** Sweller's cognitive load theory
distinguishes intrinsic load (the task itself), extraneous load (imposed by how information is
presented), and germane load (the effort that builds understanding) [5]. Disorganized,
redundant, or incomplete presentation in the record raises extraneous load and is now a
recognized contributor to burnout [5]. The design goal is not to minimize load. It is to remove
the extraneous kind and protect the germane kind.

### What the record did to deciding

**The record was meant to expose reasoning.** Weed's problem-oriented medical record organized
the chart around a numbered problem list, with plans and progress tied to each problem, so that
the record itself would display and discipline the physician's logic [1]. That intent did not
survive contact with billing.

**Time went to the screen.** Sinsky's time-and-motion study: 27 percent of the clinic day on
direct face time, 49 percent on the record and desk work, and for every hour with a patient
nearly two more on the record [6]. Downing and colleagues argue the cause is regulation and
billing rather than the software as such, citing that notes in the United States run nearly four
times longer than notes elsewhere on the same product [17].

**Information chaos.** Beasley named five failure modes of the primary-care record: overload,
underload, scatter, conflict, and erroneous information [7]. All five are design failures before
they are data failures.

**Diagnosis is where it goes wrong.** The National Academies concluded that most people will
experience at least one diagnostic error in their lifetime, and asked that health IT for the
diagnostic process demonstrate usability, fit workflow, and be independently evaluated [12].
Sittig and Singh's sociotechnical model names eight interdependent dimensions of any health IT
deployment, of which the interface is only one [13].

### What decision support did

**The five rights.** Right information, to the right person, in the right format, through the
right channel, at the right time in the workflow [8]. Most decision support fails on the last
two.

**Alerts get overridden.** Roughly half of outpatient medication alerts are overridden, and about
half of those overrides are appropriate [9]; across studies the override rate runs from 49 to 96
percent [9]. Phansalkar's review distilled eleven human-factors principles for alert design,
including false-alarm rate, prioritization, habituation, and proximity of task components [15].

**Unvalidated models make it worse.** The external validation of a widely deployed sepsis model
found sensitivity of 33 percent and positive predictive value of 12 percent at the vendor's
threshold, while 18 percent of hospitalizations triggered an alert [11]. The model missed two
thirds of cases and alarmed on nearly one in five patients.

**Automation bias is real and has known mitigators.** Goddard's systematic review of 74 studies
found automation bias mediated by trust, workload, time pressure, and task complexity, and
mitigated by emphasizing user accountability, displaying confidence levels, positioning advice
carefully, and giving information rather than recommendations [10]. Parasuraman's model gives
the vocabulary: automation can be applied to information acquisition, analysis, decision
selection, or action, each on a ten-level scale from manual to fully automatic [18]. The level
should be chosen per function, not once for the product.

### What AI changes

**Ambient capture reduces documentation time.** The Permanente pilot: 3,442 physicians, 303,266
encounters, less time in documentation and favorable clinician and patient feedback [14]; the
2025 follow-up across 7,260 physicians reported 15,791 hours saved [14]. This is a real gain.
But the output is still a note, and the note is still an artifact of what was said, not of what
was reasoned.

**Drafting shifts the work; it does not remove it.** When clinicians were given AI-drafted
replies to patient messages, reply time did not change, but task load fell by 13.9 points and
work exhaustion fell [16]. Twenty percent of drafts were used. Reviewing became the work. That
is the shape of everything that follows: the leverage is in what the clinician reviews and
decides, and in what the record keeps of that decision.

---

## 2. The principles

Each principle: the statement, what it rests on, three checks, and the chart desk's score today
(0 = absent, 1 = gestured at, 2 = present with gaps, 3 = done).

### P1. The problem is the unit, not the document

Everything about one problem is visible in one place without opening a note. Documents are
projections of the problem's state, never the primary record. *Rests on:* Weed [1]; Beasley's
scatter and overload [7].

- Can a clinician answer "what is happening with this problem" from one screen?
- Is every result, medication, and finding linked to the problem it bears on?
- Are notes reachable from the problem rather than the other way round?

**Chart desk: 2.** The timeline is problem-scoped and links are first-class, but CKD appears as
four stage-problems because the import keeps one problem per FHIR condition. The unit is right;
the instance is fragmented.

### P2. Show the trajectory, not the value

A number is perception. The interface's job is comprehension and projection: baseline, delta,
direction, and the events that changed the line, on one time axis. *Rests on:* Endsley [4];
Klein's pattern recognition [3].

- Do labs, medication intervals, and encounters share one axis?
- Does every value appear with its baseline, delta, and direction, not alone?
- Are medication starts, stops, and dose changes visible as events on that axis?

**Chart desk: 3.** Co-registered lanes, reference bands, flagged out-of-range points, medication
bands with dose-change ticks, and the flowsheet margin showing latest, delta, and direction.

### P3. Meet the decision where it lives

Proposals attach to the problem they concern and wait there. Nothing interrupts. *Rests on:* the
five rights, especially channel and time [8]; Phansalkar's proximity principle [15]; the
override literature [9].

- Do proposals appear on the problem they are about, not in a global list?
- Are there zero modal interruptions in the decision path?
- Does the queue accumulate quietly until the clinician turns to it?

**Chart desk: 3.** The inbox groups items under the selected problem, the sheet draws them in
place, and nothing pops up.

### P4. Propose in pencil, sign in ink

Nothing the machine produces reaches the record without a human act. The two states look
different everywhere. Rejecting costs no more than accepting. *Rests on:* Parasuraman's levels
applied per function [18]; Goddard's accountability mitigator [10]; the Academies' call for
human-factors design [12].

- Is every AI-produced item visibly distinct until signed?
- Is signing an act, never a default or a timeout?
- Is reject as available and as fast as accept?

**Chart desk: 3.** Pencil-versus-ink is enforced in the data and drawn on the sheet, cards, and
list; links cannot be signed into a rejected or missing endpoint.

### P5. Every claim is a citation

A proposal without inspectable evidence does not ship. Quotes are verbatim; ids exist; the reader
can tap through. *Rests on:* Goddard's finding that information beats recommendation and that
shown confidence mitigates bias [10]; the Academies on evaluable IT [12].

- Does every extracted item carry the verbatim text it came from?
- Does every insight and generated document cite only ids that exist?
- Can the reader reach the cited thing in one action?

**Chart desk: 3.** Verbatim quotes are enforced at validation, evidence is filtered to existing
ids, and chips highlight the cited points and bands.

### P6. Capture judgment where it deviates

The clinician's disagreement with the machine is the most valuable thing the record can hold.
Ask why on rejection, keep it, and read it downstream. *Rests on:* Croskerry's calibrator [2];
Weed's intent that the record show reasoning [1].

- Does rejecting invite a reason, in the clinician's words?
- Do reasons persist on the item, attributed and dated?
- Are they consumed by later steps rather than filed away?

**Chart desk: 2.** Reasons are captured with a code and free text and flow into the generated
referral as the reasoning ledger. There is no decision-trail view per problem yet.

### P7. Cut extraneous load, protect germane load

Never make a clinician re-enter what the chart already knows. Generate documents from state. But
keep the reasoning act: evidence before conclusion, so the judgment is formed, not received.
*Rests on:* Sweller [5]; Sinsky [6]; Garcia's finding that drafting moves burden rather than
removing it [16].

- Is any fact typed twice?
- Are audience-specific documents rendered from the record rather than written?
- Does the interface present evidence before the suggested action?

**Chart desk: 2.** The referral is generated with citations, and nothing is re-typed. The
insight card still shows the suggested action beside the evidence rather than after it, and a
single note produces around forty cards to review.

### P8. Quiet is a valid output

A system that always has something to say is a system that will be ignored. Empty is an
acceptable result; low confidence recedes; nothing alerts without a change. *Rests on:* override
rates [9]; the sepsis model's alert burden [11]; Phansalkar on false alarms and habituation [15].

- Can the reasoning step return nothing, and does the interface treat that as normal?
- Do low-confidence items recede rather than compete?
- Is there any alert that fires without something having changed?

**Chart desk: 2.** The live model is instructed that an empty list is correct and the UI shows
it calmly; items under 0.6 confidence recede. The rules-only fallback fires on any movement.

### P9. Reconcile before you show

Restated values match the charted result instead of duplicating it. One series per analyte.
Conflicts are surfaced as conflicts, not averaged away. *Rests on:* Beasley's scatter, conflict,
and erroneous information [7].

- Is a value restated in a note linked to the existing result rather than charted again?
- Does each analyte plot as one series?
- When two sources disagree, does the interface say so?

**Chart desk: 3.** Restated labs dedupe against the chart within a date window, the eGFR panel
rule collapses two generators to one series, and the live reasoning surfaced the discordant
creatinine assays as its own insight.

### P10. Calibrate trust in the open

Confidence and model version on every item. Rejections counted. Performance measured against a
known answer, not assumed. *Rests on:* Goddard's confidence-display mitigator [10]; the sepsis
validation [11]; the Academies' recommendation for independent evaluation [12].

- Does every AI item show its confidence and which model produced it?
- Is the rate of rejection and validator rejection visible somewhere?
- Is there a measured accuracy against a gold set?

**Chart desk: 2.** Confidence and model are on every item and the validator reports what it
dropped. The answer key exists for the demo notes but nothing scores against it automatically.

### P11. Reversible, auditable, replayable

No course is deleted; provenance is always present; every decision is recorded; every model run
can be reproduced. *Rests on:* Sittig and Singh's measurement dimension [13]; the Academies'
call for evaluable systems [12].

- Can any state be traced to the note, import, or model run that produced it?
- Can a model run be replayed byte-for-byte?
- Can the record be returned to a known state?

**Chart desk: 3.** Provenance on everything, review records, timestamped recordings with a
replay pointer, and a reset to a clean snapshot.

### P12. The visit is for deciding

The system does the synthesis before the visit and the documentation after it, so the time in
the room is spent on the decision. *Rests on:* ambient capture's gains [14]; Garcia's shift
from writing to reviewing [16]; Weed's plans tied to problems [1].

- Is there a synthesis ready before the clinician opens the chart?
- Is the clinician's in-visit work deciding, not typing?
- Are all outward documents produced from the record after the decisions are made?

**Chart desk: 1.** Reasoning runs on demand, not ahead of the visit, and the referral is the only
generated document. The extraction assumes a written note rather than ambient capture.

---

## 3. Scorecard

| Principle | Score | Next move |
|---|---|---|
| P1 Problem is the unit | 2 | merge CKD stages into one problem with stage history (schema decision) |
| P2 Trajectory over value | 3 | pin signed insights onto the axis at their date |
| P3 Meet the decision where it lives | 3 | |
| P4 Pencil then ink | 3 | |
| P5 Every claim is a citation | 3 | |
| P6 Capture deviating judgment | 2 | decision-trail panel per problem |
| P7 Extraneous out, germane kept | 2 | collapse the suggested action by default; fewer cards per note |
| P8 Quiet is valid | 2 | make the rules fallback threshold-based |
| P9 Reconcile before showing | 3 | |
| P10 Calibrate in the open | 2 | score extraction against the answer key on every run |
| P11 Reversible and replayable | 3 | |
| P12 The visit is for deciding | 1 | pre-visit brief; ambient-capture input; generated visit note |

29 of 36. The gaps cluster on two things: the pre-visit and post-visit ends of the encounter
(P12), and keeping the clinician's own reasoning in the loop (P6, P7, P8).

---

## Sources

1. Weed LL. Medical Records That Guide and Teach. *N Engl J Med* 1968;278:593-600, 652-657.
2. Croskerry P. The importance of cognitive errors in diagnosis and strategies to minimize them. *Acad Med* 2003;78:775-780. Croskerry P. Cognitive forcing strategies in clinical decisionmaking. *Ann Emerg Med* 2003;41:110-120. Croskerry P. A universal model of diagnostic reasoning. *Acad Med* 2009;84:1022-1028.
3. Klein GA, Calderwood R, Clinton-Cirocco A. Rapid decision making on the fire ground. *Proc Hum Factors Soc* 1986;30:576-580. Klein GA. *Sources of Power.* MIT Press, 1998.
4. Endsley MR. Toward a theory of situation awareness in dynamic systems. *Hum Factors* 1995;37:32-64. Savoy A et al. Electronic health records' support for primary care physicians' situation awareness: a metanarrative review. *Hum Factors* 2023;65:237-259.
5. Sweller J. Cognitive load during problem solving. *Cogn Sci* 1988;12:257-285. Sweller J, van Merriënboer JJG, Paas F. Cognitive architecture and instructional design. *Educ Psychol Rev* 1998;10:251-296. Asgari E et al. Impact of EHR use on cognitive load and burnout among clinicians. *JMIR Med Inform* 2024;12:e55499.
6. Sinsky C et al. Allocation of physician time in ambulatory practice: a time and motion study in 4 specialties. *Ann Intern Med* 2016;165:753-760.
7. Beasley JW et al. Information chaos in primary care. *J Am Board Fam Med* 2011;24:745-751.
8. Osheroff JA et al. *Improving Outcomes with Clinical Decision Support: An Implementer's Guide,* 2nd ed. HIMSS, 2012.
9. Nanji KC et al. Overrides of medication-related clinical decision support alerts in outpatients. *J Am Med Inform Assoc* 2014;21:487-491. van der Sijs H et al. Overriding of drug safety alerts in computerized physician order entry. *J Am Med Inform Assoc* 2006;13:138-147.
10. Goddard K, Roudsari A, Wyatt JC. Automation bias: a systematic review of frequency, effect mediators, and mitigators. *J Am Med Inform Assoc* 2012;19:121-127.
11. Wong A et al. External validation of a widely implemented proprietary sepsis prediction model in hospitalized patients. *JAMA Intern Med* 2021;181:1065-1070.
12. National Academies of Sciences, Engineering, and Medicine. *Improving Diagnosis in Health Care.* National Academies Press, 2015.
13. Sittig DF, Singh H. A new sociotechnical model for studying health information technology in complex adaptive healthcare systems. *Qual Saf Health Care* 2010;19(Suppl 3):i68-i74.
14. Tierney AA et al. Ambient artificial intelligence scribes to alleviate the burden of clinical documentation. *NEJM Catalyst* 2024;5(3):CAT.23.0404; follow-up 2025, CAT.25.0040.
15. Phansalkar S et al. A review of human factors principles for the design and implementation of medication safety alerts in clinical information systems. *J Am Med Inform Assoc* 2010;17:493-501.
16. Garcia P et al. Artificial intelligence-generated draft replies to patient inbox messages. *JAMA Netw Open* 2024;7(3):e243201.
17. Downing NL, Bates DW, Longhurst CA. Physician burnout in the electronic health record era: are we ignoring the real cause? *Ann Intern Med* 2018;169:50-51. Erickson SM et al. Putting patients first by reducing administrative tasks in health care. *Ann Intern Med* 2017;166:659-661.
18. Parasuraman R, Sheridan TB, Wickens CD. A model for types and levels of human interaction with automation. *IEEE Trans Syst Man Cybern A* 2000;30:286-297.
