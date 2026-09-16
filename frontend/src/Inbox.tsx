import { useState } from "react";
import { labelOf } from "./labels";
import type { ReviewBody } from "./api";
import type { Document, Insight, Link, Medication, Observation, Order, Plan, Problem, QueueBatch, Review } from "./types";
import { REASON_CODES } from "./types";

type Props = {
  queues: QueueBatch[];
  problemId: string | null;
  focusIds: Set<string>;       // the selected problem + its monitored series ("LOINC:<code>")
  chartMedIds: Set<string>;    // medications already on the chart (routine confirmations fold)
  chartInsights: Insight[];
  chartDocuments: Document[];
  labels: Record<string, string>;
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onReview: (stem: string, body: ReviewBody) => Promise<void>;
  onReadDocument: (doc: Document) => void;
  busy: string | null;
};

type Kind = "problem" | "result" | "medication" | "link" | "insight" | "document" | "order" | "finding" | "plan";
type AnyItem = Problem | Observation | Medication | Link | Insight | Document | Order | Plan;
type Status = "proposed" | "accepted" | "rejected" | "corrected";

/** One reviewable thing: a subject (proposed item, or a chart item / note the links hang off) plus its links. */
export type Group = {
  key: string;
  kind: Kind;
  subject: AnyItem | null;      // null when the subject already lives on the chart (a result, the note)
  subjectId: string;
  title: React.ReactNode;
  quote?: string;
  links: Link[];
  status: Status;
  confidence: number | null;
  hoverIds: string[];
  review?: Review;
  routine: boolean;
  alsoSigns?: string[];         // proposed items that signing this card's links will sign as endpoints
};

const LOW_CONFIDENCE = 0.6;
/** The ids a Sign on this card decides: its proposed subject plus its proposed links. */
export const decideIdsOf = (g: Group) => [...(g.subject && g.subject.status === "proposed" ? [g.subject.id] : []), ...g.links.filter((l) => l.status === "proposed").map((l) => l.id)];
const fmtTime = (s?: string) => (s ? s.slice(0, 16).replace("T", " ") : "");
const codeLabel = (code: string | null) => REASON_CODES.find((c) => c.code === code)?.label ?? code ?? "";
const LINK_WORD: Record<string, string> = { relevant_to: "relevant to", evidence_for: "evidence for", treats: "treats", suspected_cause: "suspected cause of", monitors: "monitors" };

export default function Inbox({ queues, problemId, focusIds, chartMedIds, chartInsights, chartDocuments, labels, highlight, onHover, onReview, onReadDocument, busy }: Props) {
  const name = (id: string) => labelOf(labels, id);
  const pending = queues.reduce(
    (n, b) => n + Object.values(b.proposed).flat().filter((it) => it && (it as { status: string }).status === "proposed").length +
      (b.medication_changes ?? []).filter((c) => c.status === "proposed").length,
    0,
  );
  const relevantInsights = chartInsights.filter((i) => !problemId || i.problem_id === problemId);
  const relevantDocs = chartDocuments.filter((d) => !problemId || d.problem_id === problemId);

  return (
    <aside className="inbox">
      <div className="section-head">
        <h2>To sign</h2>
        {pending > 0 && <span className="count">{pending} waiting</span>}
      </div>
      {queues.length === 0 && <div className="quiet">Nothing waiting. When a note is read, its findings land here in pencil until you sign them.</div>}
      {queues.map((b) => (
        <Batch key={b.stem} b={b} focusIds={focusIds} chartMedIds={chartMedIds} name={name} highlight={highlight} onHover={onHover} onReview={onReview} onReadDocument={onReadDocument} busy={busy} />
      ))}

      <div className="section-head" style={{ marginTop: 16 }}>
        <h2>Insights on chart</h2>
      </div>
      {relevantInsights.length === 0 && <div className="quiet">No signed insights for this problem.</div>}
      {relevantInsights.map((i) => (
        <div key={i.id} className="card">
          <span className="kind ok">insight</span>
          <span className="conf">{i.provenance.model?.split("/").pop()}</span>
          <div className="statement">{i.statement}</div>
          <div className="action">
            <b>Consider:</b> {i.suggested_action}
          </div>
          <Chips ids={i.evidence} name={name} highlight={highlight} onHover={onHover} />
          <ReviewLine r={i.review} />
        </div>
      ))}

      {relevantDocs.length > 0 && (
        <>
          <div className="section-head" style={{ marginTop: 16 }}>
            <h2>Documents on chart</h2>
          </div>
          {relevantDocs.map((d) => (
            <div key={d.id} className="card">
              <span className="kind ok">{d.kind} · {d.audience}</span>
              <span className="conf">{d.provenance.model?.split("/").pop()}</span>
              <div className="statement">{d.title}</div>
              <div className="row">
                <span className="hint">{d.sections.length} sections · {d.provenance.evidence?.length ?? 0} citations</span>
                <span className="spacer" />
                <button className="btn small" onClick={() => onReadDocument(d)}>Read</button>
              </div>
              <ReviewLine r={d.review} />
            </div>
          ))}
        </>
      )}
    </aside>
  );
}

function ReviewLine({ r }: { r?: Review }) {
  if (!r) return null;
  return (
    <div className="review">
      <b>{r.decision === "accepted" ? "Signed" : "Rejected"}</b> by {r.by} · {r.at.slice(0, 10)}
      {(r.reason_code || r.reason) && (
        <>
          {" · "}
          {r.reason_code && <span>{codeLabel(r.reason_code)}</span>}
          {r.reason && <span className="why">{r.reason_code ? " — " : ""}{r.reason}</span>}
        </>
      )}
    </div>
  );
}

/** Build review groups: every proposed item becomes a group carrying the links that leave it;
 *  links from things already on the chart (a note finding, a charted result) become their own groups. */
export function buildGroups(b: QueueBatch, name: (id: string) => string, chartMedIds: Set<string>): Group[] {
  const links = (b.proposed.links ?? []) as Link[];
  const groups: Group[] = [];
  const claimed = new Set<string>();
  const statusOf = (subject: AnyItem | null, ls: Link[]): Status => {
    const all = [...(subject ? [subject.status] : []), ...ls.map((l) => l.status)] as Status[];
    if (subject && !["proposed", "accepted", "rejected"].includes(subject.status)) return "corrected";
    if (all.some((s) => s === "proposed")) return "proposed";
    if (subject && subject.status === "rejected") return "rejected";
    return all.includes("accepted") ? "accepted" : all.includes("rejected") ? "rejected" : "corrected";
  };
  const add = (kind: Kind, subject: AnyItem | null, subjectId: string, title: React.ReactNode, ls: Link[], extra: Partial<Group> = {}) => {
    ls.forEach((l) => claimed.add(l.id));
    const prov = subject?.provenance ?? ls[0]?.provenance;
    const alsoSigns = [...new Set(ls.flatMap((l) => [l.from, l.to]).filter((id) => id !== subjectId && proposedIds.has(id)))];
    groups.push({
      key: subjectId, kind, subject, subjectId, title, links: ls, status: statusOf(subject, ls), alsoSigns,
      confidence: prov?.confidence ?? null, quote: (subject?.provenance as { quote?: string } | undefined)?.quote ?? ls[0]?.provenance.quote,
      hoverIds: [subjectId, ...ls.flatMap((l) => [l.from, l.to])],
      review: (subject as { review?: Review } | null)?.review ?? ls.find((l) => l.review)?.review,
      routine: false, ...extra,
    });
  };

  // A link into a proposed problem can only be signed once that problem exists, so it belongs to the
  // problem's card; a link out of a proposed item to something already on the chart belongs to the item.
  const proposedIds = new Set([...(b.proposed.problems ?? []), ...(b.proposed.medications ?? []), ...(b.proposed.observations ?? [])].map((x) => x.id));
  const own = (id: string) => links.filter((l) => !claimed.has(l.id) && (l.from === id || l.to === id));
  for (const p of b.proposed.problems ?? []) add("problem", p, p.id, <>New problem <b>{p.name}</b></>, own(p.id));
  for (const m of b.proposed.medications ?? []) {
    const s = m.segments[0];
    add("medication", m, m.id, <><b>{m.name}</b> {s.dose} {s.route} {s.frequency} · {s.start ?? "?"} → {s.end ?? "ongoing"}</>, own(m.id));
  }
  for (const o of b.proposed.observations ?? []) add("result", o, o.id, <><b>{o.name}</b> <span className="num">{o.value}</span> {o.unit} · {o.effective_time.slice(0, 10)}</>, own(o.id));
  for (const i of b.proposed.insights ?? []) add("insight", i, i.id, i.statement, [], { hoverIds: i.evidence });
  for (const d of b.proposed.documents ?? []) add("document", d, d.id, d.title, [], { hoverIds: d.provenance.evidence ?? [] });
  for (const o of b.proposed.orders ?? []) {
    const target = o.kind === "medication_change" ? ` · ${o.change === "stop" ? "stop" : "change dose of"} ${name(o.med_id!)}${o.dose ? " → " + o.dose : ""}` : o.kind === "referral" ? ` · to ${o.audience}` : o.code ? ` · ${o.code.system} ${o.code.value}` : "";
    add("order", o, o.id, <><b>{o.name}</b>{target}<div className="hint" style={{ marginTop: 2 }}>{o.detail}</div></>, [], { hoverIds: o.provenance.evidence ?? [] });
  }
  for (const p of b.proposed.plans ?? []) {
    add("plan", p, p.id, <><span className="plan-kind">{p.kind.replace("_", " ")}</span> {p.text} <span className="t">· {name(p.problem_id)}</span></>, own(p.id), { hoverIds: [p.id, p.problem_id] });
  }
  // remaining links: findings from the note (one group per quote) and results already on the chart (one group per result)
  const rest = links.filter((l) => !claimed.has(l.id));
  const byFrom = new Map<string, Link[]>();
  for (const l of rest) {
    const k = l.from.startsWith("note_") ? `${l.from}|${l.provenance.quote}` : l.from;
    byFrom.set(k, [...(byFrom.get(k) ?? []), l]);
  }
  for (const [k, ls] of byFrom) {
    const from = ls[0].from;
    if (from.startsWith("note_")) {
      add("finding", null, k, <>{b.review_hints?.[ls[0].id] ?? "Finding"}</>, ls, { hoverIds: ls.flatMap((l) => [l.to]) });
    } else if (from.startsWith("med_") && chartMedIds.has(from) && ls.every((l) => l.type === "treats")) {
      add("medication", null, from, <><b>{name(from)}</b> · already on the chart</>, ls, { routine: true });
    } else {
      add(from.startsWith("obs_") ? "result" : from.startsWith("med_") ? "medication" : "link", null, from, from.startsWith("obs_") ? <><b>{name(from)}</b> · already on the chart</> : <b>{name(from)}</b>, ls);
    }
  }
  return groups;
}

function Batch({
  b, focusIds, chartMedIds, name, highlight, onHover, onReview, onReadDocument, busy,
}: { b: QueueBatch; focusIds: Set<string>; chartMedIds: Set<string>; name: (id: string) => string; highlight: Set<string>; onHover: Props["onHover"]; onReview: Props["onReview"]; onReadDocument: Props["onReadDocument"]; busy: string | null }) {
  const [showRoutine, setShowRoutine] = useState(false);
  const [showDecided, setShowDecided] = useState(false);
  const groups = buildGroups(b, name, chartMedIds);
  const touches = (g: Group) =>
    focusIds.has(g.subjectId) || g.hoverIds.some((id) => focusIds.has(id)) ||
    (g.subject && "problem_id" in g.subject && focusIds.has((g.subject as Insight).problem_id)) || false;

  const open = groups.filter((g) => g.status === "proposed" && !g.routine);
  const routine = groups.filter((g) => g.status === "proposed" && g.routine);
  const decided = groups.filter((g) => g.status !== "proposed");
  const changes = b.medication_changes ?? [];
  const openChanges = changes.filter((c) => c.status === "proposed");
  const focused = open.filter(touches);
  const rest = open.filter((g) => !touches(g));
  const total = open.length + routine.length + openChanges.length;
  const title = b.note_id ? `Note ${b.note_id.replace("note_", "")}` : b.kind ? `${b.kind[0].toUpperCase() + b.kind.slice(1)} · ${name(b.problem_id!)}` : b.ordered_at ? `Orders · ${name(b.problem_id!)}` : `What changed · ${name(b.problem_id!)}`;

  const card = (g: Group) => <GroupCard key={g.key} g={g} b={b} name={name} highlight={highlight} onHover={onHover} onReview={onReview} onReadDocument={onReadDocument} busy={busy} />;

  return (
    <section>
      <div className="batch-title">
        <b>{title}</b> · {fmtTime(b.extracted_at ?? b.reasoned_at ?? b.composed_at ?? b.ordered_at)}
        {total > 1 && (
          <>
            {" "}·{" "}
            <button className="btn small ghost" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept_all: true, accept_changes: true })}>
              sign all {total}
            </button>
          </>
        )}
      </div>
      {total === 0 && <div className="quiet">Everything from this batch is decided.</div>}
      {focused.length > 0 && rest.length > 0 && <div className="focus-head">About this problem</div>}
      {focused.map(card)}
      {openChanges.map((c, i) => (
        <div key={i} className="card pencil">
          <span className="kind">med change</span>
          <span className="conf">{c.provenance.confidence}</span>
          <div className="what">
            <b>{name(c.med_id)}</b>: {c.change.replace("_", " ")} effective {c.effective}
            {c.dose && c.change === "dose_change" && <> → {c.dose}</>}
          </div>
          <div className="quote">{c.provenance.quote}</div>
          {c.hint && <div className="hint">{c.hint}</div>}
          <div className="row">
            <span className="spacer" />
            <button className="btn small primary" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept_changes: true })}>Sign</button>
          </div>
        </div>
      ))}
      {focused.length > 0 && rest.length > 0 && <div className="focus-head" style={{ color: "var(--graphite)" }}>Other problems</div>}
      {rest.map(card)}
      {routine.length > 0 && (
        <button className="fold" onClick={() => setShowRoutine((v) => !v)}>
          {showRoutine ? "▾" : "▸"} {routine.length} routine confirmation{routine.length > 1 ? "s" : ""} of medications already on the chart
        </button>
      )}
      {showRoutine && routine.map(card)}
      {(decided.length > 0 || changes.length > openChanges.length) && (
        <div className="strip">
          <button onClick={() => setShowDecided((v) => !v)}>
            {showDecided ? "▾" : "▸"} <span className="n">{decided.filter((g) => g.status === "accepted").length + (changes.length - openChanges.length)}</span> signed
            {decided.some((g) => g.status === "rejected") && <> · <span className="n">{decided.filter((g) => g.status === "rejected").length}</span> rejected</>}
          </button>
        </div>
      )}
      {showDecided && decided.map(card)}
      {b.rejected.length > 0 && (
        <div className="quiet">
          {b.rejected.length} item{b.rejected.length > 1 ? "s" : ""} could not be verified and {b.rejected.length > 1 ? "were" : "was"} dropped:{" "}
          {b.rejected.map((r) => r.reason).join("; ").slice(0, 240)}
        </div>
      )}
    </section>
  );
}

function Chips({ ids, name, highlight, onHover }: { ids: string[]; name: (id: string) => string; highlight: Set<string>; onHover: (ids: string[] | null) => void }) {
  return (
    <div className="chips" onMouseLeave={() => onHover(null)}>
      {ids.map((id) => (
        <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={id} onMouseEnter={() => onHover([id])}>
          {name(id)}
        </span>
      ))}
    </div>
  );
}

function ReasonRow({ onConfirm, onCancel, busy }: { onConfirm: (code: string | null, text: string) => void; onCancel: () => void; busy: boolean }) {
  const [code, setCode] = useState<string | null>(null);
  const [text, setText] = useState("");
  return (
    <div className="reason">
      <div className="codes">
        {REASON_CODES.map((c) => (
          <button key={c.code} className={`code ${code === c.code ? "on" : ""}`} onClick={() => setCode(code === c.code ? null : c.code)}>
            {c.label}
          </button>
        ))}
      </div>
      <input
        autoFocus
        placeholder="Why? One line, in your words (optional but valuable)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onConfirm(code, text);
          if (e.key === "Escape") onCancel();
        }}
      />
      <div className="row">
        <span className="spacer" />
        <button className="btn small ghost" onClick={onCancel}>Cancel</button>
        <button className="btn small" disabled={busy} onClick={() => onConfirm(code, text)}>Reject</button>
      </div>
    </div>
  );
}

export function GroupCard({
  g, b, name, highlight, onHover, onReview, onReadDocument, busy,
}: { g: Group; b: QueueBatch; name: (id: string) => string; highlight: Set<string>; onHover: (ids: string[] | null) => void; onReview: Props["onReview"]; onReadDocument: Props["onReadDocument"]; busy: string | null }) {
  const [rejecting, setRejecting] = useState(false);
  const st = g.status;
  const signed = st === "accepted";
  const dim = st === "proposed" && (g.confidence ?? 1) < LOW_CONFIDENCE;
  const hint = g.subject ? b.review_hints?.[g.subject.id] : undefined;
  const quiet = g.kind === "insight" || g.kind === "document";
  const decideIds = [...(g.subject && g.subject.status === "proposed" ? [g.subject.id] : []), ...g.links.filter((l) => l.status === "proposed").map((l) => l.id)];
  const badge = signed ? "signed" : st === "corrected" ? "corrected" : st === "rejected" ? "rejected"
    : g.kind === "document" ? `${(g.subject as Document).kind} · ${(g.subject as Document).audience}`
    : g.kind === "order" ? `order · ${(g.subject as Order).kind.replace("_", " ")}` : g.kind === "plan" ? "plan" : g.kind;

  return (
    <div
      className={`card ${st === "proposed" ? "pencil" : ""} ${dim ? "dim" : ""} ${g.hoverIds.some((h) => highlight.has(h)) ? "hi" : ""}`}
      onMouseEnter={() => !quiet && onHover(g.hoverIds)}
      onMouseLeave={() => !quiet && onHover(null)}
    >
      <span className={`kind ${signed ? "ok" : st === "rejected" ? "rej" : ""}`}>{badge}</span>
      {g.kind === "insight" ? (
        <>
          <div className="statement">{(g.subject as Insight).statement}</div>
          <div className="action"><b>Consider:</b> {(g.subject as Insight).suggested_action}</div>
          <Chips ids={(g.subject as Insight).evidence} name={name} highlight={highlight} onHover={onHover} />
        </>
      ) : g.kind === "document" ? (
        <>
          <div className="statement">{(g.subject as Document).title}</div>
          <div className="doc-excerpt">
            <b>{(g.subject as Document).sections[0]?.heading}</b>
            {(g.subject as Document).sections[0]?.text.slice(0, 220)}{((g.subject as Document).sections[0]?.text.length ?? 0) > 220 ? "…" : ""}
          </div>
          <div className="row">
            <span className="hint">{(g.subject as Document).sections.length} sections · {(g.subject as Document).provenance.evidence?.length ?? 0} citations · {(g.subject as Document).questions.length} questions</span>
            <span className="spacer" />
            <button className="btn small" onClick={() => onReadDocument(g.subject as Document)}>Read</button>
          </div>
        </>
      ) : (
        <div className="what">{g.title}</div>
      )}
      {g.quote && !quiet && <div className="quote">{g.quote}</div>}
      {g.links.length > 0 && (
        <div className="links">
          {g.links.map((l) => {
            const outgoing = l.from === g.subjectId || l.from.startsWith("note_");
            const other = outgoing ? l.to : l.from;
            const word = outgoing ? (LINK_WORD[l.type] ?? l.type) : ({ relevant_to: "result", evidence_for: "evidence", treats: "treated by", suspected_cause: "suspected cause" }[l.type] ?? l.type) + ":";
            return (
              <span key={l.id} className={`l ${l.type === "suspected_cause" ? "cause" : ""}`} title={l.id}>
                <span className="t">{word} </span><b>{name(other)}</b>
                {g.alsoSigns?.includes(other) && l.status === "proposed" && <span className="t"> · signs it too</span>}
                {l.status !== "proposed" && <span className="t"> · {l.status === "accepted" ? "signed" : l.status.replace(/_/g, " ")}</span>}
              </span>
            );
          })}
        </div>
      )}
      {hint && <div className="hint">{hint}</div>}
      {(g.confidence != null || g.links.length > 0 || b.model) && (
        <details className="system-details">
          <summary>Source details</summary>
          <div className="sd-grid">
            {g.confidence != null && <><span>Estimate</span><span>{g.confidence}</span></>}
            {b.model && <><span>Model</span><span>{b.model.split("/").pop()}</span></>}
            <span>IDs</span><span>{[g.subjectId, ...g.links.map((l) => l.id)].join(", ")}</span>
          </div>
        </details>
      )}
      <ReviewLine r={g.review} />
      {st === "proposed" && !rejecting && (
        <div className="row">
          <span className="spacer" />
          <button className="btn small ghost" disabled={busy === b.stem} onClick={() => setRejecting(true)}>Reject…</button>
          <button className="btn small primary" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept: decideIds })}>
            Sign{g.links.length > 1 ? ` (${decideIds.length})` : ""}
          </button>
        </div>
      )}
      {st === "proposed" && rejecting && (
        <ReasonRow
          busy={busy === b.stem}
          onCancel={() => setRejecting(false)}
          onConfirm={(code, text) => {
            setRejecting(false);
            onReview(b.stem, { reject: decideIds, reason_code: code ?? undefined, reason: text || undefined });
          }}
        />
      )}
    </div>
  );
}
