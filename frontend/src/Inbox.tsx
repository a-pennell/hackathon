import type { Insight, Link, Medication, Observation, Problem, QueueBatch } from "./types";

type Props = {
  queues: QueueBatch[];
  problemId: string | null;
  chartInsights: Insight[];
  labels: Record<string, string>;
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onReview: (stem: string, body: { accept?: string[]; reject?: string[]; accept_all?: boolean; accept_changes?: boolean }) => Promise<void>;
  busy: string | null;
};

const fmtTime = (s?: string) => (s ? s.slice(0, 16).replace("T", " ") : "");

export default function Inbox({ queues, problemId, chartInsights, labels, highlight, onHover, onReview, busy }: Props) {
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
      {queues.map((b) => {
        const items = [
          ...(b.proposed.problems ?? []).map((x) => ({ kind: "problem", it: x as Problem })),
          ...(b.proposed.observations ?? []).map((x) => ({ kind: "result", it: x as Observation })),
          ...(b.proposed.medications ?? []).map((x) => ({ kind: "medication", it: x as Medication })),
          ...(b.proposed.links ?? []).map((x) => ({ kind: "link", it: x as Link })),
          ...(b.proposed.insights ?? []).map((x) => ({ kind: "insight", it: x as Insight })),
        ];
        const open = items.filter((x) => x.it.status === "proposed").length + (b.medication_changes ?? []).filter((c) => c.status === "proposed").length;
        return (
          <section key={b.stem}>
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
            {items.map(({ kind, it }) => (
              <Card key={it.id} kind={kind} it={it} b={b} name={name} highlight={highlight} onHover={onHover} onReview={onReview} busy={busy} />
            ))}
            {(b.medication_changes ?? []).map((c, i) => (
              <div key={i} className={`card ${c.status === "proposed" ? "pencil" : ""}`}>
                <span className={`kind ${c.status === "accepted" ? "ok" : ""}`}>{c.status === "accepted" ? "signed" : "med change"}</span>
                <span className="conf">{c.provenance.confidence}</span>
                <div className="what">
                  <b>{name(c.med_id)}</b>: {c.change.replace("_", " ")} effective {c.effective}
                </div>
                <div className="quote">{c.provenance.quote}</div>
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
            {b.rejected.length > 0 && (
              <div className="quiet">
                {b.rejected.length} item{b.rejected.length > 1 ? "s" : ""} could not be verified and {b.rejected.length > 1 ? "were" : "was"} dropped:{" "}
                {b.rejected.map((r) => r.reason).join("; ").slice(0, 240)}
              </div>
            )}
          </section>
        );
      })}

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
  kind: string; it: Problem | Observation | Medication | Link | Insight; b: QueueBatch; name: (id: string) => string; highlight: Set<string>;
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
    const i = it as Insight;
    hoverIds = i.evidence;
    what = null;
  }
  const signed = st === "accepted";
  return (
    <div
      className={`card ${st === "proposed" ? "pencil" : ""} ${hoverIds.some((h) => highlight.has(h)) ? "hi" : ""}`}
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
