import { useState } from "react";
import type { CareData } from "./types";

type Props = { data: CareData; highlight: Set<string>; onHover: (ids: string[] | null) => void; onOpen: (problemId: string) => void };

type Kind = "all" | "plans" | "orders" | "referrals" | "follow_ups" | "measures";
const KINDS: { key: Kind; label: string }[] = [
  { key: "all", label: "All" }, { key: "plans", label: "Plans" }, { key: "orders", label: "Orders & requests" },
  { key: "referrals", label: "Referrals" }, { key: "follow_ups", label: "Follow-ups" }, { key: "measures", label: "Measures" },
];
const dmy = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })}`;
};

/** Care: what we are doing. Problem cards with their plan, measures and open loops in place; the chips pivot the
 *  same objects to one kind across all problems. Opening a card goes to the problem workspace. */
export default function CareTab({ data, highlight, onHover, onOpen }: Props) {
  const [kind, setKind] = useState<Kind>("all");
  const [showResolved, setShowResolved] = useState(false);
  const active = data.cards.filter((c) => c.status === "active");
  const resolved = data.cards.filter((c) => c.status !== "active");
  const hi = (ids: string[]) => (ids.some((id) => highlight.has(id)) ? "hi" : "");
  const counts: Record<Kind, number> = { all: active.length, plans: data.kinds.plans.length, orders: data.kinds.orders.length, referrals: data.kinds.referrals.length, follow_ups: data.kinds.follow_ups.length, measures: data.kinds.measures.length };

  return (
    <div className="tabpage care-tab">
      <div className="chip-row" role="tablist" aria-label="Kinds of care">
        {KINDS.map((k) => (
          <button key={k.key} className="kchip" aria-pressed={kind === k.key} onClick={() => setKind(k.key)}>
            {k.label}{k.key !== "all" && counts[k.key] > 0 ? <span className="n">{counts[k.key]}</span> : null}
          </button>
        ))}
        <span className="chip-hint">{kind === "all" ? "Grouped by problem. Pick a chip to see one kind across all problems." : "One kind across all problems. All returns to the problem view."}</span>
      </div>

      {data.due.length > 0 && kind === "all" && (
        <div className="due-strip">
          <span className="tag pend">due</span>
          <span className="msg">
            {data.due.map((d, i) => (
              <span key={d.code}>{i > 0 ? " · " : ""}<b>{d.name}</b> last {dmy(d.last)}, due {dmy(d.due)}{d.overdue_days > 0 ? ` (${d.overdue_days} days overdue)` : ""} · {d.problem_name}</span>
            ))}
          </span>
        </div>
      )}

      {kind === "all" && (
        <>
          {active.map((c) => (
            <article key={c.id} className={`ccard ${hi([c.id])}`} onMouseEnter={() => onHover([c.id])} onMouseLeave={() => onHover(null)}>
              <header className="ccard-head">
                <h3 title={c.code ? `${c.code.system} ${c.code.value}` : undefined}>{c.name}</h3>
                <span className="tag ep">{c.epistemic}</span>
                {c.members.length > 0 && <span className="tag soft" title={c.members.map((m) => m.name).join(" · ")}>+{c.members.length} related entr{c.members.length > 1 ? "ies" : "y"}</span>}
                {c.qualifiers.filter((q) => q !== "chronic" && q !== "new").map((q) => <span key={q} className={`tag ${q === "worsening" || q === "unexpected" ? "warn" : "soft"}`}>{q}</span>)}
                <span className="since">since {c.onset_date?.slice(0, 4) ?? "?"}</span>
                <span className="spacer" />
                {c.pending > 0 && <span className="tag pend">{c.pending} waiting</span>}
                <button className="btn small" onClick={() => onOpen(c.id)}>Open workspace</button>
              </header>
              {c.one_liner && <p className="one-liner serif">{c.one_liner}</p>}
              <div className="ccard-body">
                <div className="module">
                  <p className="mod-label">Plan <span className="cnt">{c.plan.length}</span></p>
                  {c.plan.length === 0 && <p className="quiet">Nothing signed yet.</p>}
                  {c.plan.slice(0, 5).map((p) => (
                    <div key={p.id} className={`planrow ${hi([p.id])}`} onMouseEnter={(e) => { e.stopPropagation(); onHover([p.id]); }}>
                      <span className="k">{p.kind.replace("_", " ")}</span><span>{p.text}</span><span className="meta">{p.source}</span>
                    </div>
                  ))}
                  {c.plan.length > 5 && <p className="meta">+{c.plan.length - 5} more in the workspace</p>}
                </div>
                <div className="module">
                  <p className="mod-label">Measures <span className="cnt">since {dmy(data.since.date)}</span></p>
                  {c.measures.length === 0 && <p className="quiet">No monitored series.</p>}
                  {c.measures.map((m, i) => (
                    <div key={i} className={`goal ${hi(m.ids)}`} onMouseEnter={(e) => { e.stopPropagation(); onHover(m.ids); }}>
                      <span className="g">{m.text}</span>
                      <span className="meta">{m.detail}</span>
                    </div>
                  ))}
                  {c.expected && <p className="meta expect">Expected: {c.expected.statement}, by {dmy(c.expected.by)} · {c.expected.status.replace("_", " ")}</p>}
                </div>
                <div className="module wide">
                  <p className="mod-label">Open loops <span className="cnt">{c.loops.length}</span></p>
                  {c.loops.length === 0 && <p className="quiet">Nothing waiting.</p>}
                  {c.loops.map((l) => (
                    <div key={l.id} className="loop">
                      <span className="kind">{l.kind}</span>
                      <span className="what">{l.text}<span className="meta">{l.detail}</span></span>
                      <span className={`tag ${l.status === "awaiting" || l.status === "unsigned" ? "pend" : "ok"}`}>{l.status}</span>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          ))}
          {resolved.length > 0 && (
            <div className="more">
              <button className="fold" onClick={() => setShowResolved((v) => !v)}>{showResolved ? "▾" : "▸"} {resolved.length} resolved</button>
              {showResolved && resolved.map((c) => (
                <article key={c.id} className="ccard resolved">
                  <header className="ccard-head"><h3>{c.name}</h3><span className="tag soft">resolved</span><span className="since">{c.onset_date?.slice(0, 4)}</span></header>
                </article>
              ))}
            </div>
          )}
        </>
      )}

      {kind !== "all" && (
        <section className="kcard">
          <header className="kcard-head">
            <h3>{KINDS.find((k) => k.key === kind)!.label}</h3>
            <p className="meta">One kind, across every problem. Each row is the same object the problem card shows; one home, one URL.</p>
          </header>
          {(kind === "measures" ? data.kinds.measures : data.kinds[kind]).length === 0 && <div className="quiet" style={{ padding: "12px 20px" }}>Nothing of this kind on the chart yet.</div>}
          {kind === "measures"
            ? data.kinds.measures.map((m, i) => (
              <div key={i} className={`krow ${hi(m.ids)}`} onMouseEnter={() => onHover(m.ids)} onMouseLeave={() => onHover(null)}>
                <button className="prob" onClick={() => onOpen(m.problem_id)}>{m.problem_name}</button>
                <span className="what">{m.text} <span className="meta">· {m.detail}</span></span>
              </div>
            ))
            : data.kinds[kind].map((p) => (
              <div key={p.id} className={`krow ${hi([p.id])}`} onMouseEnter={() => onHover([p.id])} onMouseLeave={() => onHover(null)}>
                <button className="prob" onClick={() => onOpen(p.problem_id)}>{p.problem_name}</button>
                <span className="what"><span className="k">{p.kind.replace("_", " ")}</span> {p.text} <span className="meta">· {p.source} · {dmy(p.at)}</span></span>
                <span className="tag ok">signed</span>
              </div>
            ))}
        </section>
      )}
    </div>
  );
}
