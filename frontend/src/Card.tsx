import { useMemo, useState } from "react";
import type { ReviewBody } from "./api";
import { buildGroups, decideIdsOf, GroupCard, type Group } from "./Inbox";
import Timeline from "./Timeline";
import Trail from "./Trail";
import Coding from "./Coding";
import type { Card as CardT, Coding as CodingT, Document, Insight, QueueBatch, Timeline as TL, TrailEntry } from "./types";

type Props = {
  card: CardT;
  tl: TL | null;
  queues: QueueBatch[];
  chartInsights: Insight[];
  chartDocuments: Document[];
  labels: Record<string, string>;
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onReview: (stem: string, body: ReviewBody) => Promise<void>;
  onReadDocument: (doc: Document) => void;
  onOpenNote: (noteId: string) => void;
  busy: string | null;
  mode: "live" | "replay";
  window_: string;
  setWindow: (w: string) => void;
  windows: string[];
  actions: { reason: () => void; orders: () => void; compose: () => void; readNote: () => void };
  trail: TrailEntry[];
  coding: CodingT | null;
};

type Slot = "header" | "supporting" | "insights" | "plan" | "documents" | "other" | "routine";
type Placed = { g: Group; b: QueueBatch };

const dmy = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })}`;
};
const REVIEWER = "Dr. Chen";

export default function Card({ card, tl, queues, chartInsights, chartDocuments, labels, highlight, onHover, onReview, onReadDocument, onOpenNote, busy, mode, window_, setWindow, windows, actions, trail, coding }: Props) {
  const name = (id: string) => labels[id] ?? id;
  const focusIds = useMemo(() => new Set([card.problem_id, ...(tl?.series.map((s) => `LOINC:${s.code}`) ?? [])]), [card.problem_id, tl]);
  const chartMedIds = useMemo(() => new Set((tl?.medications ?? []).map((m) => m.id)), [tl]);

  // Proposals go to the slot they would fill on the card. Nothing waits in a separate inbox.
  const slots = useMemo(() => {
    const out: Record<Slot, Placed[]> = { header: [], supporting: [], insights: [], plan: [], documents: [], other: [], routine: [] };
    const changes: { c: NonNullable<QueueBatch["medication_changes"]>[number]; b: QueueBatch; here: boolean }[] = [];
    for (const b of queues) {
      for (const g of buildGroups(b, name, chartMedIds)) {
        // A rejected subject leaves its links stranded as proposed; they cannot be signed, so the group is decided.
        if (g.status !== "proposed" || g.subject?.status === "rejected") continue;
        const supersedes = g.kind === "problem" && (b.review_hints?.[g.subjectId] ?? "").includes(card.problem_id);
        const touches = supersedes || focusIds.has(g.subjectId) || g.hoverIds.some((id) => focusIds.has(id)) ||
          (g.subject && "problem_id" in g.subject && focusIds.has((g.subject as Insight).problem_id)) || false;
        const slot: Slot = g.routine ? "routine" : !touches ? "other" : g.kind === "problem" ? "header" : g.kind === "insight" ? "insights" : g.kind === "order" ? "plan" : g.kind === "document" ? "documents" : "supporting";
        out[slot].push({ g, b });
      }
      for (const c of b.medication_changes ?? []) if (c.status === "proposed") changes.push({ c, b, here: chartMedIds.has(c.med_id) });
    }
    return { ...out, changes };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queues, focusIds, chartMedIds, labels, card.problem_id]);

  const [rep, setRep] = useState<{ status: "proposed" | "accepted" | "rejected"; text: string; editing: boolean }>({ status: "proposed", text: card.representation.text, editing: false });
  const [assessment, setAssessment] = useState<{ text: string; editing: boolean; at: string | null }>({ text: "", editing: false, at: null });
  const [showTrajectory, setShowTrajectory] = useState(true);
  const [showOther, setShowOther] = useState(false);
  const [showTrail, setShowTrail] = useState(false);
  const [openConsider, setOpenConsider] = useState<Set<string>>(new Set());

  const signedInsights = chartInsights.filter((i) => i.problem_id === card.problem_id);
  const signedDocs = chartDocuments.filter((d) => d.problem_id === card.problem_id);
  const otherCount = slots.other.length + slots.routine.length + slots.changes.filter((x) => !x.here).length;
  const signAllOther = () => {
    const byStem = new Map<string, string[]>();
    for (const { g, b } of [...slots.other, ...slots.routine]) byStem.set(b.stem, [...(byStem.get(b.stem) ?? []), ...decideIdsOf(g)]);
    const stems = new Set([...byStem.keys(), ...slots.changes.filter((x) => !x.here).map((x) => x.b.stem)]);
    return Promise.all([...stems].map((stem) => onReview(stem, { accept: byStem.get(stem) ?? [], accept_changes: slots.changes.some((x) => !x.here && x.b.stem === stem) })));
  };
  const cardProps = { name, highlight, onHover, onReview, onReadDocument, busy };
  const ev = (x: { ids: string[] }) => ({ onMouseEnter: () => onHover(x.ids), onMouseLeave: () => onHover(null), className: x.ids.some((id) => highlight.has(id)) ? "hi" : "" });
  const pendingHere = slots.header.length + slots.supporting.length + slots.insights.length + slots.plan.length + slots.documents.length + slots.changes.filter((x) => x.here).length;

  return (
    <div className="cardpage">
      <section className="explain top">
        <h2>The problem card</h2>
        <p>
          One screen for one concern, organised around what the clinician thinks is happening rather than around the note. Everything in ink below is on the chart; everything in
          pencil is proposed and waits for a signature in the slot it would fill. The card is computed from the chart each time it opens, like a trend summary: nothing on it is stored.
        </p>
        <p className="qs">
          <b>Q1</b> what is happening · <b>Q2</b> what we think it means · <b>Q3</b> what changed · <b>Q4</b> what we are doing · <b>Q5</b> what we are unsure of · <b>Q6</b> what should happen next · <b>Q7</b> what would change our mind
        </p>
      </section>

      <article className="pcard">
        <header className="ptitle">
          <h1>{card.problem.name}</h1>
          <span className="tag ep" title={card.epistemic.why}>{card.epistemic.value}</span>
          <span className="tag">{card.problem.status}</span>
          {card.qualifiers.map((q) => (
            <span key={q.label} className={`tag ${q.label === "worsening" || q.label === "unexpected" ? "warn" : "soft"}`} title={q.why}>
              {q.label}{q.computed ? " · computed" : ""}
            </span>
          ))}
          <span className="stamp">
            {card.kind} · {card.problem.onset_date ? `since ${card.problem.onset_date.slice(0, 4)}` : "no onset"} · {card.decisions} decisions
            {pendingHere > 0 ? ` · ${pendingHere} waiting here` : ""}
          </span>
        </header>
        {slots.header.map(({ g, b }) => (
          <div key={g.key} className="slot header-slot">
            <div className="slot-label">Proposed change to this problem</div>
            <GroupCard g={g} b={b} {...cardProps} />
          </div>
        ))}

        <div className="pgrid">
          <section>
            <h3>
              Representation <span className="cnt">{rep.status === "accepted" ? `accepted by ${REVIEWER} · not written in this demo` : rep.status === "rejected" ? "rejected" : "proposed by rules from the chart"}</span>
            </h3>
            {rep.editing ? (
              <div className="pencil-box">
                <textarea value={rep.text} onChange={(e) => setRep({ ...rep, text: e.target.value })} rows={4} />
                <div className="row">
                  <span className="spacer" />
                  <button className="btn small ghost" onClick={() => setRep({ ...rep, editing: false, text: card.representation.text })}>Cancel</button>
                  <button className="btn small primary" onClick={() => setRep({ status: "accepted", text: rep.text, editing: false })}>Accept as edited</button>
                </div>
              </div>
            ) : rep.status === "accepted" ? (
              <div className="ink-box serif">{rep.text}</div>
            ) : rep.status === "rejected" ? (
              <div className="quiet">Representation rejected. <button className="link" onClick={() => setRep({ status: "proposed", text: card.representation.text, editing: false })}>Show the proposal again</button></div>
            ) : (
              <div className="pencil-box">
                <div className="serif" onMouseEnter={() => onHover(card.representation.cites)} onMouseLeave={() => onHover(null)}>{rep.text}</div>
                <div className="chips" onMouseLeave={() => onHover(null)}>
                  {card.representation.cites.slice(0, 8).map((id) => (
                    <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={id} onMouseEnter={() => onHover([id])}>{name(id)}</span>
                  ))}
                  {card.representation.cites.length > 8 && <span className="hint">+{card.representation.cites.length - 8} more</span>}
                </div>
                <div className="row">
                  <span className="hint">every clause cites; edits keep the citations that survive</span>
                  <span className="spacer" />
                  <button className="btn small ghost" onClick={() => setRep({ ...rep, status: "rejected" })}>Reject</button>
                  <button className="btn small" onClick={() => setRep({ ...rep, editing: true })}>Edit</button>
                  <button className="btn small primary" onClick={() => setRep({ ...rep, status: "accepted" })}>Accept</button>
                </div>
              </div>
            )}
          </section>
          <section>
            <h3>
              Assessment <span className="cnt">{assessment.at ? `${REVIEWER} · ${assessment.at} · not written in this demo` : "prose, in your words"}</span>
            </h3>
            {assessment.editing ? (
              <div className="ink-box">
                <textarea autoFocus value={assessment.text} rows={4} placeholder="What you think is happening, with as much hedging as it deserves." onChange={(e) => setAssessment({ ...assessment, text: e.target.value })} />
                <div className="row">
                  <span className="spacer" />
                  <button className="btn small ghost" onClick={() => setAssessment({ ...assessment, editing: false })}>Cancel</button>
                  <button className="btn small primary" onClick={() => setAssessment({ text: assessment.text, editing: false, at: new Date().toISOString().slice(0, 10) })}>Sign</button>
                </div>
              </div>
            ) : assessment.text ? (
              <div className="ink-box serif">{assessment.text}</div>
            ) : (
              <div className="quiet">No assessment recorded on this concern. The system never writes one.</div>
            )}
          </section>
        </div>

        <div className="pgrid">
          <section>
            <h3>Supporting <span className="cnt">{card.supporting.length}{slots.supporting.length ? ` · ${slots.supporting.length} proposed` : ""}</span></h3>
            <ul className="ev">
              {card.supporting.map((x) => (
                <li key={x.id} {...ev(x)}>
                  <span className="v for">+</span>
                  <span className="txt">{x.text}<span className="detail">{x.detail}</span></span>
                  <span className="src">{x.source}</span>
                </li>
              ))}
              {card.supporting.length === 0 && <li className="quiet">Nothing on the chart is linked to this problem yet.</li>}
            </ul>
            {slots.supporting.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
          </section>
          <section>
            <h3>Doesn't fit <span className="cnt">{card.doesnt_fit.length}</span></h3>
            <ul className="ev">
              {card.doesnt_fit.map((x, i) => (
                <li key={i} {...ev(x)}>
                  <span className={`v ${x.valence === "unexplained" ? "unx" : "against"}`}>{x.valence === "unexplained" ? "○" : "−"}</span>
                  <span className="txt">{x.text}<span className="detail">{x.detail}</span></span>
                  <span className="src">{x.kind.replace("_", " ")}</span>
                </li>
              ))}
              {card.doesnt_fit.length === 0 && <li className="quiet">Nothing on the chart argues against the current reading. Quiet is a valid output.</li>}
            </ul>
          </section>
        </div>

        <section className="full">
          <h3>Insights <span className="cnt">{signedInsights.length} signed{slots.insights.length ? ` · ${slots.insights.length} proposed` : ""}</span></h3>
          {signedInsights.length + slots.insights.length === 0 && (
            <div className="quiet">No reasoning has run on this problem. <button className="link" disabled={!!busy} onClick={actions.reason}>What's changed?</button> asks for it; an empty answer is a normal answer.</div>
          )}
          {signedInsights.map((i) => (
            <div key={i.id} className="insight ink" onMouseEnter={() => onHover(i.evidence)} onMouseLeave={() => onHover(null)}>
              <div className="statement serif">{i.statement}</div>
              <div className="chips" onMouseLeave={() => onHover(null)}>
                {i.evidence.map((id) => <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={id} onMouseEnter={() => onHover([id])}>{name(id)}</span>)}
              </div>
              <button className="link" onClick={() => setOpenConsider((s) => { const n = new Set(s); n.has(i.id) ? n.delete(i.id) : n.add(i.id); return n; })}>
                {openConsider.has(i.id) ? "▾" : "▸"} suggestion
              </button>
              {openConsider.has(i.id) && <div className="action">{i.suggested_action}</div>}
              <div className="stamp">{i.provenance.model} · signed by {i.review?.by ?? REVIEWER} · {i.review?.at.slice(0, 10)}</div>
            </div>
          ))}
          {slots.insights.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
        </section>

        <section className="full">
          <h3>Plan <span className="cnt">{card.plan.length} signed{slots.plan.length + slots.changes.filter((x) => x.here).length ? ` · ${slots.plan.length + slots.changes.filter((x) => x.here).length} proposed` : ""}</span></h3>
          <div className="plan">
            {card.plan.map((p) => (
              <div key={p.id} {...ev(p)} title={p.detail}>
                <span className="k">{p.plan_kind}</span>
                <span>{p.text}</span>
                <span className="tag ok">signed</span>
              </div>
            ))}
            {card.plan.length === 0 && <div className="quiet">Nothing ordered on this problem yet. Signed insights become orders with <button className="link" disabled={!!busy} onClick={actions.orders}>Draft orders</button>.</div>}
          </div>
          {slots.plan.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
          {slots.changes.filter((x) => x.here).map(({ c, b }, i) => (
            <div key={i} className="card pencil">
              <span className="kind">med change</span>
              <div className="what"><b>{name(c.med_id)}</b>: {c.change.replace("_", " ")} effective {c.effective}{c.dose && c.change === "dose_change" ? ` → ${c.dose}` : ""}</div>
              <div className="quote">{c.provenance.quote}</div>
              <div className="row"><span className="spacer" /><button className="btn small primary" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept_changes: true })}>Sign</button></div>
            </div>
          ))}
        </section>

        <section className="full exp">
          <div className="k">Expected</div>
          <div>
            {card.expected ? (
              <span className="pencil-inline" onMouseEnter={() => onHover(card.expected!.ids)} onMouseLeave={() => onHover(null)}>
                {card.expected.statement}. <span className="stamp">watching {card.expected.code} · {card.expected.direction} · by {dmy(card.expected.by)} · {card.expected.status.replace("_", " ")} · proposed by rules</span>
              </span>
            ) : (
              <span className="quiet">Nothing has been changed on this problem yet, so there is nothing to expect. When a suspected cause is stopped, the card proposes what should happen next.</span>
            )}
          </div>
          <div className="k">Reassess if</div>
          <div>
            {card.expected ? card.expected.reconsider_if.map((r, i) => <span key={i} className="pencil-inline">{r.trigger} → {r.then}. </span>) : <span className="quiet">—</span>}
          </div>
          <div className="k">Changed</div>
          <div className="changed">
            {card.changed.length === 0 && <span className="quiet">Nothing has changed on this problem in the last 90 days.</span>}
            {card.changed.map((l, i) => (
              <span key={i} className={`line ${l.kind} ${l.ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(l.ids)} onMouseLeave={() => onHover(null)}>{l.text} </span>
            ))}
          </div>
        </section>

        {(signedDocs.length > 0 || slots.documents.length > 0) && (
          <section className="full">
            <h3>Documents <span className="cnt">{signedDocs.length} signed{slots.documents.length ? ` · ${slots.documents.length} proposed` : ""}</span></h3>
            {signedDocs.map((d) => (
              <div key={d.id} className="plan"><div><span className="k">{d.kind}</span><span>{d.title}</span><button className="btn small" onClick={() => onReadDocument(d)}>Read</button><span className="tag ok">signed</span></div></div>
            ))}
            {slots.documents.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
          </section>
        )}

        <div className="pactions">
          <button className="btn" disabled={!!busy} onClick={actions.readNote}>Read a note</button>
          <button className="btn primary" disabled={!!busy} onClick={actions.reason}>What's changed?</button>
          <button className="btn" disabled={!!busy} onClick={actions.orders}>Draft orders</button>
          <button className="btn" disabled={!!busy} onClick={actions.compose}>Draft referral</button>
          <button className="btn" onClick={() => setAssessment({ ...assessment, editing: true })}>Update assessment</button>
          <button className="btn ghost" onClick={() => setShowTrajectory((v) => !v)}>{showTrajectory ? "Hide" : "View"} trajectory</button>
          <span className="spacer" />
          <span className="hint">Claude: {mode === "live" ? "live" : "saved"}</span>
        </div>

        {showTrajectory && (
          <section className="full trajectory">
            <h3>
              Trajectory <span className="cnt">{tl?.series.length ?? 0} series · {tl?.medications.length ?? 0} courses</span>
              <span className="seg">
                {windows.map((w) => <button key={w} className={w === window_ ? "on" : ""} onClick={() => setWindow(w)}>{w}</button>)}
              </span>
            </h3>
            {tl && tl.series.length > 0 ? (
              <Timeline data={tl} highlight={highlight} onHover={(id) => onHover(id ? [id] : null)} onOpenNote={onOpenNote} corridor={card.expected} />
            ) : (
              <div className="quiet">No monitored series in this window.</div>
            )}
          </section>
        )}

        {otherCount > 0 && (
          <section className="full other">
            <button className="fold" onClick={() => setShowOther((v) => !v)}>
              {showOther ? "▾" : "▸"} {otherCount} proposal{otherCount > 1 ? "s" : ""} on other problems from the same note
            </button>
            <button className="btn small ghost" disabled={!!busy} onClick={signAllOther}>Sign all {otherCount}</button>
            {showOther && (
              <div className="other-list">
                {slots.other.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
                {slots.changes.filter((x) => !x.here).map(({ c, b }, i) => (
                  <div key={i} className="card pencil">
                    <span className="kind">med change</span>
                    <div className="what"><b>{name(c.med_id)}</b>: {c.change.replace("_", " ")} effective {c.effective}{c.dose && c.change === "dose_change" ? ` → ${c.dose}` : ""}</div>
                    <div className="quote">{c.provenance.quote}</div>
                    <div className="row"><span className="spacer" /><button className="btn small primary" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept_changes: true })}>Sign</button></div>
                  </div>
                ))}
                {slots.routine.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
              </div>
            )}
          </section>
        )}

        <section className="full doors">
          <button className="fold" onClick={() => setShowTrail((v) => !v)}>{showTrail ? "▾" : "▸"} Decision trail · {trail.filter((e) => e.decision !== "pending").length} decided</button>
          {showTrail && <Trail entries={trail} labels={labels} highlight={highlight} onHover={onHover} />}
          {coding && coding.signed_today > 0 && <Coding coding={coding} highlight={highlight} onHover={onHover} />}
        </section>
      </article>

      <section className="explain bottom">
        <h2>What you are looking at</h2>
        <ul>
          <li><b>Representation</b> is the compressed problem statement, in illness-script order: context, presentation, trajectory, current state. Rules propose it with a citation per clause. It renders in pencil until you accept or edit it, and the compiler would never cite an unaccepted one.</li>
          <li><b>Assessment</b> stays prose and is only ever yours. The card asks for it at checkpoints, not per visit.</li>
          <li><b>Supporting</b> and <b>Doesn't fit</b> keep the recorded value (mono), its provenance (measured, note, patient-reported) and its interpretation (the valence mark) as three separate things. The <span className="v against">−</span> and <span className="v unx">○</span> lines are rule checks over the chart: two assays disagreeing on one day, a counter-trend move while a suspected cause continued, a medication that contradicts the problem state, a missed expectation.</li>
          <li><b>Insights</b> show the statement and the evidence first; the suggestion is folded until asked for, so the judgment forms before the recommendation arrives.</li>
          <li><b>Expected</b> and <b>Reassess if</b> are one object read two ways. When a suspected cause is stopped, the card proposes which series should move, which way and by when, and evaluates it against every result that arrives afterwards. A missed expectation becomes an <span className="tag warn">unexpected</span> qualifier, a <span className="v against">−</span> line, and the first item under Changed.</li>
          <li><b>Proposals sit in the slot they would fill.</b> A finding from a note lands under Supporting, an order under Plan, a superseding problem under the title. Proposals about other problems fold at the bottom and can be signed in one gesture; consequential items on this problem are signed one at a time.</li>
          <li><b>The trajectory</b> draws the expectation as a corridor on its series: from the value at the stop toward a quarter's move, until the due date, with the axis extended past today. A result inside it is quiet; one outside it after the due date is ringed as a mismatch, and the corridor turns vermilion.</li>
          <li><b>Not in this slice:</b> alternatives with discriminators, and persistence of what you accept or write here. Those are the schema additions flagged in the design document's appendix.</li>
        </ul>
      </section>
    </div>
  );
}
