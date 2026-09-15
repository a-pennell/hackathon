# PRD-10 — The shell and the patient workspace

**Stage:** 0 (canvas/mount contract) and 4 (shelving). Ships on the back of surfaces that are
already better (`cpor-migration-and-ia.md` §4 "navigation changes ship only on the back of a
surface that is already better").
**Depends on:** PRD-08 (glance, what-changed), PRD-09 (Work), PRD-03/07 for Care contents; PRD-12
for multi-patient.

## Why

The hackathon UI is one patient on one chart desk. The decided IA is a stable shell of **spaces as
scopes of work** and a patient workspace of **Overview · Timeline · Care · Chart** with a persistent
patient header, six user-shaped Chart groups, the loop rule, one object one home many lenses, the
object drawer with a biography, and a documentation canvas that composes per occasion with at most
two auto-opened panels (`cpor-migration-and-ia.md` §3; `patient-ia-v2-proposal.md`;
`ontology-evolution.md` §0 surfaces/modules/routes/badges; migration site "Stable outside.
Adaptive inside."). The existing chart desk survives intact as the **problem workspace** inside
Care; it is the hero view and nothing here sands it off.

## Goal

A shell with spaces, routes, per-tab patient context and durable drafts; a patient workspace whose
four tabs answer four jobs; every object with one URL and a drawer; the chart desk mounted as the
focus workspace.

## Scope

**In**
1. **Shell.** Left rail of spaces: `Today | Work | Patients | Schedule | Messages | Practice |
   Revenue | Reports`, permissioned by role (a clinician sees four). Patient tab strip across the
   top: one tab per open patient with active-encounter state and elapsed time; **patient context is
   per tab, never per session**; patient identity in the window title. `+ Create` menu.
2. **Routes** (real, deep-linkable, back/forward safe):
   ```
   /today  /work  /patients  /schedule  /messages  /practice  /revenue  /reports
   /patients/:pid            (Overview)
   /patients/:pid/timeline
   /patients/:pid/care
   /patients/:pid/chart
   /patients/:pid/focuses/:fid          (the chart desk: problem workspace)
   /patients/:pid/contexts/:cid
   /patients/:pid/encounters/:eid  /…/note
   /objects/:id                          (drawer, any object; the canonical URL)
   ```
   Lenses are query-scoped (`?lens=diagnoses`), never second routes. A second module with the same
   noun is a defect; the router makes it visible.
3. **Patient header** (persistent chrome): identity, contact, emergency contact, insurance, flags
   (allergy strip never truncates), pregnancy/pertinent current facts as badges.
4. **Overview** = `clinician_glance` (PRD-08): active problems, current meds summary, active plan,
   stale risks, recent changes, open loops, next appointment; every item a deep link to its home.
   Owns "what's true now"; Chart has no "current state" group.
5. **Timeline**: events with dates, filter chips `Sessions · Messages · Results · Documents ·
   Changes`; encounter comb grouped (ticks within 3 days collapse with a count); notes reached in
   context.
6. **Care** (label test pending: "Care" vs "Treatment"): `Problems & concerns` (active view with the
   carries-forward band and computed clusters) · `Courses of care` · `Goals` · `Plans` · `Orders &
   requests` (result status inline: the loop rule) · `Referrals` (reply inline) · `Follow-ups`.
   No "care gaps" category: "Screenings due" is a state badge. Clicking a problem opens the
   **focus workspace** — today's chart desk (timeline, inbox, brief, trail, coding) scoped to it.
7. **Chart**: six groups as summarized collection cards, never a scrolling face sheet:
   `Paperwork & consents` · `Session documentation` (encounters + notes merged; "Looking for the
   treatment plan?" cross-link) · `Medical info` (meds provenance-badged, allergies pinned,
   immunizations door line "4 on record · last: flu 10/2025", **Lab results** with outstanding
   orders pinned above per the loop rule, **Diagnoses lens** onto Care) · `Questionnaires & scores`
   (series-first, due-strip) · `Correspondence` · `History & background` (grouped by why it is
   there). A "From outside providers" provenance toggle inside every group. Record tools (access
   log, disclosure accounting, export) as a utility, not a chip.
8. **Object drawer** (`/objects/:id`): current state, authority-scoped verbs, and **Changes** (the
   biography from the ledger, each transition stamped and linked to its occasion). Cross-boundary
   verbs mint intent in its home ("Request re-test" on a lab drawer creates an Order in Care whose
   status renders back in the drawer).
9. **Documentation canvas** (moments): the composer with panels beside it; occasion recipes decide
   what *starts* open (max two): return/mid-course → Last note · Plan; intake → forms · consents;
   outside med change → Meds · Last note; risk disclosure → Safety plan · emergency contact;
   message-anchored → the thread; ambient draft review → Meds · Last note plus the draft-vs-chart
   diff. Personal pin overrides; "no panels" respected; never rearrange mid-typing.
10. **Orientation labels** always visible: Patient · Encounter · Timeline · Chart · Current ·
    Signed · Proposed. Provenance badges: `entered · proposed · acknowledged · attested ·
    auto-applied · imported, unverified · contested · stale`.
11. **Mount contract** for modules: a module receives (patient context, scope object, actor, events)
    and renders on any of three surfaces (page, pane, drawer) without assuming placement; the chart
    desk is the first module refactored to it.
12. **Reset-snapshot warning in the UI** and the busy state near the thing being acted on
    (remaining items from `docs/ui-critique.md`).

**Out**
- Practice, Revenue, Reports interiors beyond a placeholder (PRD-11 adds thin versions).
- Mobile/tablet layouts (desktop 1280+).

## Design rules (binding)

- One object, one home, many lenses. Every other appearance is a filtered lens, never a copy.
- Stable outside, adaptive inside: spaces, URLs and landmarks are fixed; the canvas composes within
  a scope and never replaces navigation.
- States are flags, never places; provenance is a badge, never a folder.
- Collapse rule: a door line states its contents or answers the common question, never just a count.
- The loop rule: any loop the Care/Chart boundary cuts in half shows its other half on both sides.
- The Care/Chart boundary ("Care holds intent; Chart holds knowledge") never appears in UI copy.

## Acceptance

1. Two patients open in two browser tabs never share context; each title carries the patient name;
   an action in one cannot land on the other (test with the verbs' `patient_id` check).
2. `/patients/pt_001` cold-open shows the glance with open loops first; time-to-orientation task
   (current status of CKD, what changed, what is pending) completes without opening a note.
3. Clicking CKD opens the existing chart desk at `/patients/pt_001/focuses/prob_0057` with all
   current behaviour intact (replay demo passes).
4. Ordering a creatinine from the Chart lab drawer creates an order in Care and shows "requested,
   awaiting result" in the drawer and above results.
5. A consult letter appears under Correspondence and under Paperwork with the same object id.
6. On a risk-disclosure occasion the canvas opens Safety plan and the header's emergency contact and
   nothing else.

## Estimate

Ten days: three for shell, routes and header; three for Overview/Timeline/Care/Chart; two for the
drawer and mount contract; two for the canvas recipes.
