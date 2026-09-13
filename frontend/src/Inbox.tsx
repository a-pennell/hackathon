import { useState } from "react";
import type { ReviewBody } from "./api";
import type { Document, Insight, Link, Medication, Observation, Order, Problem, QueueBatch, Review } from "./types";
import { REASON_CODES } from "./types";

type Props = {
  queues: QueueBatch[];
  problemId: string | null;
  focusIds: Set<string>;       // the selected problem + its monitored series ("LOINC:<code>")
  chartMedIds: Set<string>;    // medications already on the chart (for folding routine confirmations)
  chartInsights: Insight[];
  chartDocuments: Document[];
  labels: Record<string, string>;
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onReview: (stem: string, body: ReviewBody) => Promise<void>;
  onReadDocument: (doc: Document) => void;
  busy: string | null;
};

type Kind = "problem" | "result" | "medication" | "link" | "insight" | "document" | "order";
type AnyItem = Problem | Observation | Medication | Link | Insight | Document | Order;
type Item = { kind: Kind; it: AnyItem };

const LOW_CONFIDENCE = 0.6;
const fmtTime = (s?: string) => (s ? s.slice(0, 16).replace("T", " ") : "");
const codeLabel = (code: string | null) => REASON_CODES.find((c) => c.code === code)?.label ?? code ?? "";

export default function Inbox({ queues, problemId, focusIds, chartMedIds, chartInsights, chartDocuments, labels, highlight, onHover, onReview, onReadDocument, busy }: Props) {
  const name = (id: string) => labels[id] ?? id;
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
        <h2>Review queue</h2>
        {pending > 0 && <span className="count">{pending} unsigned</span>}
      </div>
      {queues.length === 0 && <div className="quiet">Nothing proposed yet. When a note arrives, its findings land here as pencil until you sign them.</div>}
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

function Batch({
  b, focusIds, chartMedIds, name, highlight, onHover, onReview, onReadDocument, busy,
}: { b: QueueBatch; focusIds: Set<string>; chartMedIds: Set<string>; name: (id: string) => string; highlight: Set<string>; onHover: Props["onHover"]; onReview: Props["onReview"]; onReadDocument: Props["onReadDocument"]; busy: string | null }) {
  const [showRoutine, setShowRoutine] = useState(false);
  const links = (b.proposed.links ?? []) as Link[];
  const items: Item[] = [
    ...(b.proposed.orders ?? []).map((x) => ({ kind: "order" as Kind, it: x as AnyItem })),
    ...(b.proposed.documents ?? []).map((x) => ({ kind: "document" as Kind, it: x as AnyItem })),
    ...(b.proposed.insights ?? []).map((x) => ({ kind: "insight" as Kind, it: x as AnyItem })),
    ...(b.proposed.problems ?? []).map((x) => ({ kind: "problem" as Kind, it: x as AnyItem })),
    ...(b.proposed.medications ?? []).map((x) => ({ kind: "medication" as Kind, it: x as AnyItem })),
    ...(b.proposed.observations ?? []).map((x) => ({ kind: "result" as Kind, it: x as AnyItem })),
    ...links.map((x) => ({ kind: "link" as Kind, it: x as AnyItem })),
  ];

  const touches = (x: Item): boolean => {
    const id = x.it.id;
    if (x.kind === "insight" || x.kind === "document" || x.kind === "order") return focusIds.has((x.it as Insight | Document | Order).problem_id);
    if (x.kind === "link") {
      const l = x.it as Link;
      return focusIds.has(l.to) || focusIds.has(l.from);
    }
    if (x.kind === "problem") return focusIds.has(id);
    return links.some((l) => (l.from === id || l.to === id) && (focusIds.has(l.to) || focusIds.has(l.from)));
  };
  const isRoutine = (x: Item) => x.kind === "link" && (x.it as Link).type === "treats" && chartMedIds.has((x.it as Link).from);

  const routine = items.filter(isRoutine);
  const main = items.filter((x) => !isRoutine(x));
  const focused = main.filter(touches);
  const rest = main.filter((x) => !touches(x));
  const open = items.filter((x) => x.it.status === "proposed").length + (b.medication_changes ?? []).filter((c) => c.status === "proposed").length;

  const card = (x: Item) => (
    <Card key={x.it.id} kind={x.kind} it={x.it} b={b} name={name} highlight={highlight} onHover={onHover} onReview={onReview} onReadDocument={onReadDocument} busy={busy} />
  );
  const title = b.note_id ? `Note ${b.note_id.replace("note_", "")}` : b.kind ? `${b.kind[0].toUpperCase() + b.kind.slice(1)} · ${name(b.problem_id!)}` : b.ordered_at ? `Orders · ${name(b.problem_id!)}` : `Reasoning · ${name(b.problem_id!)}`;

  return (
    <section>
      <div className="batch-title">
        <b>{title}</b> · {b.model.split("/").pop()} · {fmtTime(b.extracted_at ?? b.reasoned_at ?? b.composed_at ?? b.ordered_at)}
        {open > 1 && (
          <>
            {" "}
            ·{" "}
            <button className="btn small ghost" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept_all: true, accept_changes: true })}>
              sign all {open}
            </button>
          </>
        )}
      </div>
      {focused.length > 0 && rest.length > 0 && <div className="focus-head">About this problem</div>}
      {focused.map(card)}
      {(b.medication_changes ?? []).map((c, i) => (
        <div key={i} className={`card ${c.status === "proposed" ? "pencil" : ""}`}>
          <span className={`kind ${c.status === "accepted" ? "ok" : ""}`}>{c.status === "accepted" ? "signed" : "med change"}</span>
          <span className="conf">{c.provenance.confidence}</span>
          <div className="what">
            <b>{name(c.med_id)}</b>: {c.change.replace("_", " ")} effective {c.effective}
            {c.dose && c.change === "dose_change" && <> → {c.dose}</>}
          </div>
          <div className="quote">{c.provenance.quote}</div>
          {c.hint && <div className="hint">{c.hint}</div>}
          <ReviewLine r={c.review} />
          {c.status === "proposed" && (
            <div className="row">
              <span className="spacer" />
              <button className="btn small primary" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept_changes: true })}>
                Sign
              </button>
            </div>
          )}
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
        <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={name(id)} onMouseEnter={() => onHover([id])}>
          {id}
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

function Card({
  kind, it, b, name, highlight, onHover, onReview, onReadDocument, busy,
}: {
  kind: Kind; it: AnyItem; b: QueueBatch; name: (id: string) => string; highlight: Set<string>;
  onHover: (ids: string[] | null) => void; onReview: Props["onReview"]; onReadDocument: Props["onReadDocument"]; busy: string | null;
}) {
  const [rejecting, setRejecting] = useState(false);
  const st = it.status;
  const hint = b.review_hints?.[it.id];
  const prov = it.provenance;
  let what: React.ReactNode = null;
  let hoverIds: string[] = [it.id];
  if (kind === "problem") {
    const p = it as Problem;
    what = <>New problem <b>{p.name}</b></>;
  } else if (kind === "result") {
    const o = it as Observation;
    what = <><b>{o.name}</b> <span className="num">{o.value}</span> {o.unit} · {o.effective_time.slice(0, 10)}</>;
  } else if (kind === "medication") {
    const m = it as Medication;
    const s = m.segments[0];
    what = <><b>{m.name}</b> {s.dose} {s.route} {s.frequency} · {s.start ?? "?"} → {s.end ?? "ongoing"}</>;
  } else if (kind === "link") {
    const l = it as Link;
    hoverIds = [l.from, l.to];
    what = (
      <span className="link">
        {name(l.from)}
        <span className="arrow">—{l.type.replace("_", " ")}→</span>
        {name(l.to)}
      </span>
    );
  } else if (kind === "insight") {
    hoverIds = (it as Insight).evidence;
  } else if (kind === "document") {
    hoverIds = (it as Document).provenance.evidence ?? [];
  } else if (kind === "order") {
    const o = it as Order;
    hoverIds = o.provenance.evidence ?? [];
    const target = o.kind === "medication_change" ? ` · ${o.change === "stop" ? "stop" : "change dose of"} ${name(o.med_id!)}${o.dose ? " → " + o.dose : ""}`
      : o.kind === "referral" ? ` · to ${o.audience}` : o.code ? ` · ${o.code.system} ${o.code.value}` : "";
    what = (
      <>
        <b>{o.name}</b>{target}
        <div className="hint" style={{ marginTop: 2 }}>{o.detail}{o.provenance.from_insight ? ` · from ${o.provenance.from_insight}` : ""}</div>
      </>
    );
  }
  const signed = st === "accepted";
  const dim = st === "proposed" && (prov.confidence ?? 1) < LOW_CONFIDENCE;
  const badge = signed ? "signed" : st === "rejected" ? "rejected" : kind === "document" ? `${(it as Document).kind} · ${(it as Document).audience}` : kind === "order" ? `order · ${(it as Order).kind.replace("_", " ")}` : kind;
  const quiet = kind === "insight" || kind === "document";
  return (
    <div
      className={`card ${st === "proposed" ? "pencil" : ""} ${dim ? "dim" : ""} ${hoverIds.some((h) => highlight.has(h)) ? "hi" : ""}`}
      onMouseEnter={() => !quiet && onHover(hoverIds)}
      onMouseLeave={() => !quiet && onHover(null)}
    >
      <span className={`kind ${signed ? "ok" : st === "rejected" ? "rej" : ""}`}>{badge}</span>
      {prov.confidence != null && <span className="conf">{prov.confidence}</span>}
      {kind === "insight" ? (
        <>
          <div className="statement">{(it as Insight).statement}</div>
          <div className="action"><b>Consider:</b> {(it as Insight).suggested_action}</div>
          <Chips ids={(it as Insight).evidence} name={name} highlight={highlight} onHover={onHover} />
        </>
      ) : kind === "document" ? (
        <>
          <div className="statement">{(it as Document).title}</div>
          <div className="doc-excerpt">
            <b>{(it as Document).sections[0]?.heading}</b>
            {(it as Document).sections[0]?.text.slice(0, 220)}{((it as Document).sections[0]?.text.length ?? 0) > 220 ? "…" : ""}
          </div>
          <div className="row">
            <span className="hint">{(it as Document).sections.length} sections · {(it as Document).provenance.evidence?.length ?? 0} citations · {(it as Document).questions.length} questions</span>
            <span className="spacer" />
            <button className="btn small" onClick={() => onReadDocument(it as Document)}>Read</button>
          </div>
        </>
      ) : (
        <div className="what">{what}</div>
      )}
      {prov.quote && !quiet && <div className="quote">{prov.quote}</div>}
      {hint && <div className="hint">{hint}</div>}
      <ReviewLine r={(it as { review?: Review }).review} />
      {st === "proposed" && !rejecting && (
        <div className="row">
          <span className="spacer" />
          <button className="btn small ghost" disabled={busy === b.stem} onClick={() => setRejecting(true)}>Reject…</button>
          <button className="btn small primary" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept: [it.id] })}>Sign</button>
        </div>
      )}
      {st === "proposed" && rejecting && (
        <ReasonRow
          busy={busy === b.stem}
          onCancel={() => setRejecting(false)}
          onConfirm={(code, text) => {
            setRejecting(false);
            onReview(b.stem, { reject: [it.id], reason_code: code ?? undefined, reason: text || undefined });
          }}
        />
      )}
    </div>
  );
}
