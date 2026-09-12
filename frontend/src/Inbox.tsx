import { useState } from "react";
import type { Insight, Link, Medication, Observation, Problem, QueueBatch } from "./types";

type Props = {
  queues: QueueBatch[];
  problemId: string | null;
  focusIds: Set<string>;       // the selected problem + its monitored series ("LOINC:<code>")
  chartMedIds: Set<string>;    // medications already on the chart (for folding routine confirmations)
  chartInsights: Insight[];
  labels: Record<string, string>;
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onReview: (stem: string, body: { accept?: string[]; reject?: string[]; accept_all?: boolean; accept_changes?: boolean }) => Promise<void>;
  busy: string | null;
};

type Kind = "problem" | "result" | "medication" | "link" | "insight";
type Item = { kind: Kind; it: Problem | Observation | Medication | Link | Insight };

const LOW_CONFIDENCE = 0.6;
const fmtTime = (s?: string) => (s ? s.slice(0, 16).replace("T", " ") : "");

export default function Inbox({ queues, problemId, focusIds, chartMedIds, chartInsights, labels, highlight, onHover, onReview, busy }: Props) {
  const name = (id: string) => labels[id] ?? id;
  const pending = queues.reduce(
    (n, b) => n + Object.values(b.proposed).flat().filter((it) => it && (it as { status: string }).status === "proposed").length +
      (b.medication_changes ?? []).filter((c) => c.status === "proposed").length,
    0,
  );
  const relevantInsights = chartInsights.filter((i) => !problemId || i.problem_id === problemId);

  return (
    <aside className="inbox">
      <div className="section-head">
        <h2>Review queue</h2>
        {pending > 0 && <span className="count">{pending} unsigned</span>}
      </div>
      {queues.length === 0 && <div className="quiet">Nothing proposed yet. When a note arrives, its findings land here as pencil until you sign them.</div>}
      {queues.map((b) => (
        <Batch key={b.stem} b={b} focusIds={focusIds} chartMedIds={chartMedIds} name={name} highlight={highlight} onHover={onHover} onReview={onReview} busy={busy} />
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
        </div>
      ))}
    </aside>
  );
}

function Batch({
  b, focusIds, chartMedIds, name, highlight, onHover, onReview, busy,
}: { b: QueueBatch; focusIds: Set<string>; chartMedIds: Set<string>; name: (id: string) => string; highlight: Set<string>; onHover: Props["onHover"]; onReview: Props["onReview"]; busy: string | null }) {
  const [showRoutine, setShowRoutine] = useState(false);
  const links = (b.proposed.links ?? []) as Link[];
  const items: Item[] = [
    ...(b.proposed.problems ?? []).map((x) => ({ kind: "problem" as Kind, it: x as Problem })),
    ...(b.proposed.medications ?? []).map((x) => ({ kind: "medication" as Kind, it: x as Medication })),
    ...(b.proposed.observations ?? []).map((x) => ({ kind: "result" as Kind, it: x as Observation })),
    ...links.map((x) => ({ kind: "link" as Kind, it: x as Link })),
    ...(b.proposed.insights ?? []).map((x) => ({ kind: "insight" as Kind, it: x as Insight })),
  ];

  // Which items are "about" the selected problem: direct references, or an item whose proposed link lands on it.
  const touches = (x: Item): boolean => {
    const id = x.it.id;
    if (x.kind === "insight") return (x.it as Insight).problem_id ? focusIds.has((x.it as Insight).problem_id) : false;
    if (x.kind === "link") {
      const l = x.it as Link;
      return focusIds.has(l.to) || focusIds.has(l.from);
    }
    if (x.kind === "problem") return focusIds.has(id);
    return links.some((l) => (l.from === id || l.to === id) && (focusIds.has(l.to) || focusIds.has(l.from)));
  };
  // Routine: a "treats" link from a medication already on the chart - the note merely restated it.
  const isRoutine = (x: Item) => x.kind === "link" && (x.it as Link).type === "treats" && chartMedIds.has((x.it as Link).from);

  const routine = items.filter(isRoutine);
  const main = items.filter((x) => !isRoutine(x));
  const focused = main.filter(touches);
  const rest = main.filter((x) => !touches(x));
  const open = items.filter((x) => x.it.status === "proposed").length + (b.medication_changes ?? []).filter((c) => c.status === "proposed").length;

  const card = (x: Item) => (
    <Card key={x.it.id} kind={x.kind} it={x.it} b={b} name={name} highlight={highlight} onHover={onHover} onReview={onReview} busy={busy} />
  );

  return (
    <section>
      <div className="batch-title">
        <b>{b.note_id ? `Note ${b.note_id.replace("note_", "")}` : `Reasoning · ${name(b.problem_id!)}`}</b> · {b.model.split("/").pop()} ·{" "}
        {fmtTime(b.extracted_at ?? b.reasoned_at)}
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

function Card({
  kind, it, b, name, highlight, onHover, onReview, busy,
}: {
  kind: Kind; it: Problem | Observation | Medication | Link | Insight; b: QueueBatch; name: (id: string) => string; highlight: Set<string>;
  onHover: (ids: string[] | null) => void; onReview: Props["onReview"]; busy: string | null;
}) {
  const st = it.status;
  const hint = b.review_hints?.[it.id];
  const prov = it.provenance;
  let what: React.ReactNode = null;
  let hoverIds: string[] = [it.id];
  if (kind === "problem") {
    const p = it as Problem;
    what = (
      <>
        New problem <b>{p.name}</b>
      </>
    );
  } else if (kind === "result") {
    const o = it as Observation;
    what = (
      <>
        <b>{o.name}</b> <span className="num">{o.value}</span> {o.unit} · {o.effective_time.slice(0, 10)}
      </>
    );
  } else if (kind === "medication") {
    const m = it as Medication;
    const s = m.segments[0];
    what = (
      <>
        <b>{m.name}</b> {s.dose} {s.route} {s.frequency} · {s.start ?? "?"} → {s.end ?? "ongoing"}
      </>
    );
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
  }
  const signed = st === "accepted";
  const dim = st === "proposed" && (prov.confidence ?? 1) < LOW_CONFIDENCE;
  return (
    <div
      className={`card ${st === "proposed" ? "pencil" : ""} ${dim ? "dim" : ""} ${hoverIds.some((h) => highlight.has(h)) ? "hi" : ""}`}
      onMouseEnter={() => kind !== "insight" && onHover(hoverIds)}
      onMouseLeave={() => kind !== "insight" && onHover(null)}
    >
      <span className={`kind ${signed ? "ok" : st === "rejected" ? "rej" : ""}`}>{signed ? "signed" : st === "rejected" ? "rejected" : kind}</span>
      {prov.confidence != null && <span className="conf">{prov.confidence}</span>}
      {kind === "insight" ? (
        <>
          <div className="statement">{(it as Insight).statement}</div>
          <div className="action">
            <b>Consider:</b> {(it as Insight).suggested_action}
          </div>
          <Chips ids={(it as Insight).evidence} name={name} highlight={highlight} onHover={onHover} />
        </>
      ) : (
        <div className="what">{what}</div>
      )}
      {prov.quote && kind !== "insight" && <div className="quote">{prov.quote}</div>}
      {hint && <div className="hint">{hint}</div>}
      {st === "proposed" && (
        <div className="row">
          <span className="spacer" />
          <button className="btn small ghost" disabled={busy === b.stem} onClick={() => onReview(b.stem, { reject: [it.id] })}>
            Reject
          </button>
          <button className="btn small primary" disabled={busy === b.stem} onClick={() => onReview(b.stem, { accept: [it.id] })}>
            Sign
          </button>
        </div>
      )}
    </div>
  );
}
