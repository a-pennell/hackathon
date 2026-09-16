import { useMemo, useState } from "react";
import type { ReviewBody } from "./api";
import { buildGroups, decideIdsOf, GroupCard, type Group } from "./Inbox";
import Timeline from "./Timeline";
import Trail from "./Trail";
import Coding from "./Coding";
import type { Card as CardT, Coding as CodingT, Document, Insight, QueueBatch, RecordEvent, Timeline as TL, TrailEntry } from "./types";

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
  record: RecordEvent[];
};

type Slot = "header" | "supporting" | "insights" | "plan" | "documents" | "other" | "routine";
type Placed = { g: Group; b: QueueBatch };

const dmy = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })}`;
};
const fmtTime = (s?: string) => (s ? s.slice(0, 16).replace("T", " ") : "");
const nice = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)).replace(/\.?0+$/, "");
const REVIEWER = "Dr. Chen";
const CERTAINTY: Record<string, string> = { confirmed: "high", probable: "high", working: "moderate", suspected: "low", possible: "low", syndrome: "low", finding: "low" };
const EV_WORD: Record<string, string> = {
  "note.received": "note", "note.signed": "note signed", "observation.recorded": "result", "problem.raised": "problem", "medication.course_opened": "course",
  "medication.dose_changed": "dose", "medication.segment_closed": "stopped", "edge.asserted": "link", "plan.set": "plan", "insight.raised": "insight",
  "order.placed": "order", "document.signed": "document", "proposal.rejected": "rejected",
};

export default function Card({ card, tl, queues, chartInsights, chartDocuments, labels, highlight, onHover, onReview, onReadDocument, onOpenNote, busy, window_, setWindow, windows, actions, trail, coding, record }: Props) {
  const name = (id: string) => labels[id] ?? id;
  const focusIds = useMemo(() => new Set([card.problem_id, ...card.members.map((m) => m.id), ...(tl?.series.map((s) => `LOINC:${s.code}`) ?? [])]), [card.problem_id, card.members, tl]);
  // Courses linked to this problem (treats or suspected cause); a change on one of these is consequential here.
  const chartMedIds = useMemo(() => new Set((tl?.medications ?? []).filter((m) => m.relation && m.relation !== "on_board").map((m) => m.id)), [tl]);

  // Proposals go to the slot they would fill on the card. Nothing waits in a separate inbox.
  const slots = useMemo(() => {
    const out: Record<Slot, Placed[]> = { header: [], supporting: [], insights: [], plan: [], documents: [], other: [], routine: [] };
    const changes: { c: NonNullable<QueueBatch["medication_changes"]>[number]; b: QueueBatch; here: boolean }[] = [];
    for (const b of queues) {
      for (const g of buildGroups(b, name, chartMedIds)) {
        if (g.status !== "proposed" || g.subject?.status === "rejected") continue;
        const supersedes = g.kind === "problem" && (b.review_hints?.[g.subjectId] ?? "").includes(card.problem_id);
        const touches = supersedes || focusIds.has(g.subjectId) || g.hoverIds.some((id) => focusIds.has(id)) ||
          (g.subject && "problem_id" in g.subject && focusIds.has((g.subject as Insight).problem_id)) || false;
        const slot: Slot = g.routine ? "routine" : !touches ? "other" : g.kind === "problem" ? "header" : g.kind === "insight" ? "insights" : g.kind === "order" || g.kind === "plan" ? "plan" : g.kind === "document" ? "documents" : "supporting";
        out[slot].push({ g, b });
      }
      for (const c of b.medication_changes ?? []) if (c.status === "proposed") changes.push({ c, b, here: chartMedIds.has(c.med_id) });
    }
    return { ...out, changes };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queues, focusIds, chartMedIds, labels, card.problem_id]);

  // Consequential proposals get a banner: a superseding problem, a suspected cause, a course opened, stopped or changed.
  const consequential = useMemo(() => {
    const out: { key: string; kind: string; title: string; text: string; anchor: string }[] = [];
    for (const { g } of slots.header) out.push({ key: g.key, kind: "new problem", title: `${name(g.subjectId)} proposed in place of ${card.problem.name}`, text: g.quote ?? "", anchor: "slot-header" });
    for (const { g } of slots.supporting) {
      if (g.kind === "medication" && g.subject) out.push({ key: g.key, kind: "course", title: `${name(g.subjectId)}: a course to open on the chart`, text: g.quote ?? "", anchor: "slot-supporting" });
      else if (g.links.some((l) => l.type === "suspected_cause")) out.push({ key: g.key, kind: "suspected cause", title: `${name(g.subjectId)} as a suspected cause`, text: g.quote ?? "", anchor: "slot-supporting" });
    }
    for (const { c } of slots.changes.filter((x) => x.here)) out.push({ key: `chg-${c.med_id}`, kind: c.change === "stop" ? "course stopped" : "dose change", title: `${name(c.med_id)}: ${c.change.replace("_", " ")} effective ${c.effective}`, text: c.provenance.quote ?? "", anchor: "slot-plan" });
    return out;
  }, [slots, labels]); // eslint-disable-line react-hooks/exhaustive-deps

  const [rep, setRep] = useState<{ status: "proposed" | "accepted" | "rejected"; text: string; editing: boolean }>({ status: "proposed", text: card.representation.text, editing: false });
  const [assessment, setAssessment] = useState<{ text: string; editing: boolean; at: string | null }>({ text: "", editing: false, at: null });
  const [stratum, setStratum] = useState<"line" | "assessment" | "history">("assessment");
  const [showTrajectory, setShowTrajectory] = useState(true);
  const [showOther, setShowOther] = useState(false);
  const [showSupporting, setShowSupporting] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
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
  const oneLiner = card.representation.text.replace(/^[^.]*?\.\s+(?=[A-Z])/, "").split(/\.\s+(?=[A-Z])/)[0].replace(/\.?$/, ".");
  const evidenceLines = card.supporting.length + card.doesnt_fit.length;
  const supportingShown = showSupporting ? card.supporting : card.supporting.slice(0, 4);
  const jump = (anchor: string) => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div className="pwork">
      <aside className="spine" aria-label="Evidence spine">
        <span className="eyebrow">Evidence spine</span>
        <h2>Record events linked to this problem</h2>
        <p className="note">Every line is a dated, signed fact. The card reads them; it never stores them.</p>
        <div className="thread">
          {record.length === 0 && <div className="quiet">Nothing has been written to this problem yet.</div>}
          {record.map((e, i) => {
            const state = ["problem.raised", "note.signed", "plan.set", "medication.segment_closed", "medication.dose_changed", "medication.course_opened"].includes(e.kind);
            return (
              <div key={i} className={`ev ${state ? "state" : ""} ${e.ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(e.ids)} onMouseLeave={() => onHover(null)}>
                <span className="when">{fmtTime(e.at)}</span>
                <span className="what">{e.text}</span>
                <span className="src">{EV_WORD[e.kind] ?? e.kind} · {e.source}{e.by ? ` · ${e.by}` : ""}</span>
              </div>
            );
          })}
          {pendingHere > 0 && (
            <div className="ev pending" onClick={() => jump(slots.header.length ? "slot-header" : slots.insights.length ? "slot-insights" : "slot-supporting")}>
              <span className="when">now</span>
              <span className="what">{pendingHere} proposal{pendingHere > 1 ? "s" : ""} awaiting your signature</span>
              <span className="src">unsigned · in the slots below</span>
            </div>
          )}
        </div>
      </aside>

      <article className="pcard pmain">
        {consequential.filter((c) => !dismissed.has(c.key)).map((c) => (
          <div key={c.key} className="banner" role="status">
            <div className="grow">
              <span className="flag">Machine proposal · {c.kind} · unsigned</span>
              <h3>{c.title}</h3>
              {c.text && <p className="serif">“{c.text}”</p>}
              <p className="why">Consequential changes are reviewed one at a time. Review before anything changes.</p>
            </div>
            <div className="bactions">
              <button className="btn primary" onClick={() => jump(c.anchor)}>Review</button>
              <button className="btn ghost" onClick={() => setDismissed((s) => new Set(s).add(c.key))}>Not now</button>
            </div>
          </div>
        ))}

        <header className="phead">
          <span className="pid">{card.kind} · {card.problem.id} · since {card.problem.onset_date?.slice(0, 4) ?? "?"} · {card.decisions} decisions on the record</span>
          <h1>{card.problem.name}</h1>
          <div className="chips">
            <span className="tag ep" title={card.epistemic.why}>{card.epistemic.value}</span>
            <span className="tag">certainty <b>{CERTAINTY[card.epistemic.value] ?? "moderate"}</b></span>
            <span className="tag steward">steward <b>{card.steward.name} ({card.steward.role})</b></span>
            <span className="tag soft">onset <b>{card.problem.onset_date ?? "unknown"}</b></span>
            <span className="tag soft">{evidenceLines} evidence lines</span>
            {card.members.length > 0 && <span className="tag soft" title={card.members.map((m) => m.name).join(" · ")}>+{card.members.length} related entr{card.members.length > 1 ? "ies" : "y"}</span>}
            {card.qualifiers.map((q) => (
              <span key={q.label} className={`tag ${q.label === "worsening" || q.label === "unexpected" ? "warn" : "soft"}`} title={q.why}>{q.label}{q.computed ? " · computed" : ""}</span>
            ))}
            {pendingHere > 0 && <span className="tag pend">{pendingHere} waiting here</span>}
          </div>
        </header>

        {slots.header.length > 0 && (
          <div id="slot-header" className="slot header-slot">
            <div className="slot-label">Proposed change to this problem</div>
            {slots.header.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
          </div>
        )}

        <section className="stack">
          <span className="eyebrow">Summary stack</span>
          <div className="stackbar" role="tablist" aria-label="Summary depth">
            <button className="lvl" role="tab" aria-selected={stratum === "line"} onClick={() => setStratum("line")}>one line</button>
            <button className="lvl" role="tab" aria-selected={stratum === "assessment"} onClick={() => setStratum("assessment")}>assessment</button>
            <button className="lvl" role="tab" aria-selected={stratum === "history"} onClick={() => setStratum("history")}>full history</button>
          </div>
          {stratum === "line" && <p className="machine-text lead" onMouseEnter={() => onHover(card.representation.cites)} onMouseLeave={() => onHover(null)}>{oneLiner}</p>}
          {stratum === "assessment" && (
            rep.editing ? (
              <div className="pencil-box">
                <textarea value={rep.text} onChange={(e) => setRep({ ...rep, text: e.target.value })} rows={4} />
                <div className="row"><span className="spacer" /><button className="btn small ghost" onClick={() => setRep({ ...rep, editing: false, text: card.representation.text })}>Cancel</button><button className="btn small primary" onClick={() => setRep({ status: "accepted", text: rep.text, editing: false })}>Accept as edited</button></div>
              </div>
            ) : rep.status === "accepted" ? (
              <div className="ink-box"><p className="machine-text">{rep.text}</p><span className="stamp">representation accepted by {REVIEWER} · not written in this demo</span></div>
            ) : rep.status === "rejected" ? (
              <div className="quiet">Representation rejected. <button className="link" onClick={() => setRep({ status: "proposed", text: card.representation.text, editing: false })}>Show the proposal again</button></div>
            ) : (
              <div className="pencil-box">
                <p className="machine-text" onMouseEnter={() => onHover(card.representation.cites)} onMouseLeave={() => onHover(null)}>{rep.text}</p>
                <div className="chips" onMouseLeave={() => onHover(null)}>
                  {card.representation.cites.slice(0, 8).map((id) => <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={id} onMouseEnter={() => onHover([id])}>{name(id)}</span>)}
                  {card.representation.cites.length > 8 && <span className="hint">+{card.representation.cites.length - 8} more</span>}
                </div>
                <div className="row">
                  <span className="hint">drafted by rules from the chart; every clause cites</span>
                  <span className="spacer" />
                  <button className="btn small ghost" onClick={() => setRep({ ...rep, status: "rejected" })}>Reject</button>
                  <button className="btn small" onClick={() => setRep({ ...rep, editing: true })}>Edit</button>
                  <button className="btn small primary" onClick={() => setRep({ ...rep, status: "accepted" })}>Accept</button>
                </div>
              </div>
            )
          )}
          {stratum === "history" && (
            <div className="history">
              <p className="machine-text muted">The full history compiles from the evidence spine and the decision trail; it expands each line with the source quotation and the reasoning recorded at each step.</p>
              <Trail entries={trail} labels={labels} highlight={highlight} onHover={onHover} />
            </div>
          )}
        </section>

        <section className="authored">
          <div className="authored-head">
            <span className="eyebrow">Clinician-authored assessment</span>
            <span className="spacer" />
            {!assessment.editing && <button className="btn small" onClick={() => setAssessment({ ...assessment, editing: true })}>{assessment.text ? "Update" : "Write"} assessment</button>}
          </div>
          {assessment.editing ? (
            <>
              <textarea autoFocus value={assessment.text} rows={4} placeholder="What you think is happening, with as much hedging as it deserves." onChange={(e) => setAssessment({ ...assessment, text: e.target.value })} />
              <div className="row"><span className="spacer" /><button className="btn small ghost" onClick={() => setAssessment({ ...assessment, editing: false })}>Cancel</button><button className="btn small primary" onClick={() => setAssessment({ text: assessment.text, editing: false, at: new Date().toISOString().slice(0, 16).replace("T", " ") })}>Sign</button></div>
            </>
          ) : assessment.text ? (
            <>
              <p className="body">{assessment.text}</p>
              <span className="sig">{REVIEWER} · signed {assessment.at} · not written in this demo</span>
            </>
          ) : (
            <p className="quiet">No assessment on this problem. The system never writes one; it is asked for when a problem is raised, its reading changes, or a course closes.</p>
          )}
        </section>

        <div className="cards2">
          <section className="scard watch">
            <span className="eyebrow">Surveillance</span>
            <h4>What would change this problem's status</h4>
            {card.surveillance.rows.map((r) => (
              <div key={r.code} className={`kv ${r.ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(r.ids)} onMouseLeave={() => onHover(null)}>
                <span className="k">{r.name}</span>
                <span className={`v ${r.tripped ? "tripped" : ""}`}>{nice(r.latest.value)} · {r.state}</span>
              </div>
            ))}
            {card.expected ? (
              <>
                <div className="kv"><span className="k">Expected</span><span className="v">{card.expected.statement} · <b>{card.expected.status.replace("_", " ")}</b></span></div>
                {card.expected.reconsider_if.map((r, i) => <div key={i} className="kv"><span className="k">Reassess if</span><span className="v">{r.trigger} → {r.then}</span></div>)}
              </>
            ) : (
              <div className="kv"><span className="k">Expected</span><span className="v muted">set when a cause is stopped or a course starts</span></div>
            )}
            <div className="kv"><span className="k">Next review</span><span className="v">{dmy(card.surveillance.next_review)}</span></div>
          </section>
          <section className="scard">
            <span className="eyebrow">Linked in the graph</span>
            <h4>Courses, causes, documents, related entries</h4>
            {card.linked.length === 0 && card.members.length === 0 && <p className="quiet">Nothing linked yet.</p>}
            {card.linked.map((l) => (
              <div key={l.rel + l.id} className={`linkrow ${l.ids.some((id) => highlight.has(id)) ? "hi" : ""} ${l.rel === "documented in" ? "clickable" : ""}`} onMouseEnter={() => onHover(l.ids)} onMouseLeave={() => onHover(null)} onClick={() => l.rel === "documented in" && onOpenNote(l.id)}>
                <span className={`rel ${l.rel === "suspected cause" ? "cause" : ""}`}>{l.rel}</span>
                <span className="txt">{l.text} <span className="meta">· {l.detail}</span></span>
              </div>
            ))}
            {card.members.map((m) => (
              <div key={m.id} className="linkrow"><span className="rel">related entry</span><span className="txt">{m.name} <span className="meta">· since {m.onset_date?.slice(0, 4) ?? "?"}</span></span></div>
            ))}
          </section>
        </div>

        <div className="pgrid" id="slot-supporting">
          <section>
            <h3>Supporting <span className="cnt">{card.supporting.length}{slots.supporting.length ? ` · ${slots.supporting.length} proposed` : ""}</span></h3>
            <ul className="ev">
              {supportingShown.map((x) => (
                <li key={x.id} {...ev(x)}>
                  <span className="v for">+</span>
                  <span className="txt">{x.text}<span className="detail">{x.detail}</span></span>
                  <span className="src">{x.source}</span>
                </li>
              ))}
              {card.supporting.length === 0 && <li className="quiet">Nothing on the chart is linked to this problem yet.</li>}
            </ul>
            {card.supporting.length > 4 && <button className="link" onClick={() => setShowSupporting((v) => !v)}>{showSupporting ? "show fewer" : `${card.supporting.length - 4} more`}</button>}
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

        <section className="full" id="slot-insights">
          <h3>Insights <span className="cnt">{signedInsights.length} signed{slots.insights.length ? ` · ${slots.insights.length} proposed` : ""}</span>
            <span className="spacer" />
            <button className="btn small" disabled={!!busy} onClick={actions.reason} title="Trend summaries and medication events go to the model; insights come back for your signature">What's changed?</button>
          </h3>
          {signedInsights.length + slots.insights.length === 0 && <div className="quiet">No reasoning has run on this problem. An empty answer is a normal answer.</div>}
          {signedInsights.map((i) => (
            <div key={i.id} className="insight ink" onMouseEnter={() => onHover(i.evidence)} onMouseLeave={() => onHover(null)}>
              <div className="statement serif">{i.statement}</div>
              <div className="chips" onMouseLeave={() => onHover(null)}>
                {i.evidence.map((id) => <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={id} onMouseEnter={() => onHover([id])}>{name(id)}</span>)}
              </div>
              <button className="link" onClick={() => setOpenConsider((s) => { const n = new Set(s); n.has(i.id) ? n.delete(i.id) : n.add(i.id); return n; })}>{openConsider.has(i.id) ? "▾" : "▸"} suggestion</button>
              {openConsider.has(i.id) && <div className="action">{i.suggested_action}</div>}
              <div className="stamp">{i.provenance.model} · signed by {i.review?.by ?? REVIEWER} · {i.review?.at.slice(0, 10)}</div>
            </div>
          ))}
          {slots.insights.map(({ g, b }) => <GroupCard key={g.key} g={g} b={b} {...cardProps} />)}
        </section>

        <section className="full" id="slot-plan">
          <h3>Plan <span className="cnt">{card.plan.length} signed{slots.plan.length + slots.changes.filter((x) => x.here).length ? ` · ${slots.plan.length + slots.changes.filter((x) => x.here).length} proposed` : ""}</span>
            <span className="spacer" />
            <button className="btn small" disabled={!!busy || signedInsights.length === 0} onClick={actions.orders} title="Turn the signed insights' actions into orders to sign">Draft orders</button>
            <button className="btn small" disabled={!!busy} onClick={actions.compose} title="A referral letter rendered from the chart, the signed insights and your decisions">Draft referral</button>
          </h3>
          <div className="plan">
            {card.plan.map((p) => (
              <div key={p.id} {...ev(p)} title={p.detail}><span className="k">{p.plan_kind.replace("_", " ")}</span><span>{p.text}</span><span className="tag ok">signed</span></div>
            ))}
            {card.plan.length === 0 && <div className="quiet">Nothing signed on this problem yet.</div>}
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

        <section className="full trajectory">
          <h3>
            Trajectory <span className="cnt">{tl?.series.length ?? 0} series · {tl?.medications.length ?? 0} courses</span>
            <button className="link" onClick={() => setShowTrajectory((v) => !v)}>{showTrajectory ? "hide" : "show"}</button>
            <span className="seg">{windows.map((w) => <button key={w} className={w === window_ ? "on" : ""} onClick={() => setWindow(w)}>{w}</button>)}</span>
          </h3>
          {showTrajectory && (tl && tl.series.length > 0 ? (
            <Timeline data={tl} highlight={highlight} onHover={(id) => onHover(id ? [id] : null)} onOpenNote={onOpenNote} corridor={card.expected} />
          ) : (
            <div className="quiet">No monitored series in this window.</div>
          ))}
        </section>

        {otherCount > 0 && (
          <section className="full other">
            <button className="fold" onClick={() => setShowOther((v) => !v)}>{showOther ? "▾" : "▸"} {otherCount} proposal{otherCount > 1 ? "s" : ""} on other problems from the same note</button>
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

        {coding && coding.signed_today > 0 && <section className="full doors"><Coding coding={coding} highlight={highlight} onHover={onHover} /></section>}

        <details className="explain bottom">
          <summary>About this screen</summary>
          <ul>
            <li><b>The evidence spine</b> on the left is the record read for this problem: every result, link, plan item, insight and decision that touched it, dated and signed, with proposals still waiting marked at the end.</li>
            <li><b>A banner</b> appears for anything consequential the system proposes on this problem: a new or superseding problem, a suspected cause, a course opened, stopped or changed. Consequential changes are reviewed one at a time; the batchable rest sit in the slots below.</li>
            <li><b>The summary stack</b> has three depths. The one-liner is the trajectory sentence. The assessment paragraph is drafted by rules in illness-script order (context, presentation, trajectory, current state) and cites every clause; accept, edit or reject it. The full history is the decision trail.</li>
            <li><b>Your assessment</b> stays prose and is only ever yours.</li>
            <li><b>Surveillance</b> is what would change this problem's status: each monitored series with its threshold and where it stands, the expectation set when a cause was stopped, what to reassess on, and the next review.</li>
            <li><b>Supporting</b> and <b>Doesn't fit</b> keep the recorded value, its provenance and its interpretation apart. The <span className="v against">−</span> and <span className="v unx">○</span> lines are rule checks over the chart.</li>
            <li><b>Not in this slice:</b> alternatives with discriminators, and persistence of what you accept or write here. Those are the schema additions flagged in the design document's appendix.</li>
          </ul>
        </details>
      </article>
    </div>
  );
}
