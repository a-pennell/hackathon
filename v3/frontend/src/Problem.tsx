import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Ctx } from "./App";
import type { Timeline as TL, QueueBatch } from "./types";
import type { ProblemView } from "./v2types";
import Timeline from "./Timeline";

const KINDS = ["therapeutic", "diagnostic", "monitoring", "referral", "follow_up", "education"];
const nice = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? String(+v.toFixed(1)) : String(+v.toFixed(2)));
const dmy = (iso: string) => { const d = new Date(iso.slice(0, 10) + "T00:00:00"); return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`; };

const HoverCtx = createContext<(ids: string[] | null) => void>(() => {});

function Q({ n, ask, sub, children }: { n: number; ask: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="q" id={`q${n}`}><div className="ask"><span className="n">{n}</span><h2>{ask}</h2>{sub && <div className="sub">{sub}</div>}</div><div className="ans">{children}</div></section>
  );
}

function Line({ x, v: mark }: { x: { text: string; detail?: string; ids: string[]; source?: string; valence?: string }; v?: string }) {
  const hover = useContext(HoverCtx);
  return (
    <div className="line" onMouseEnter={() => hover(x.ids)} onMouseLeave={() => hover(null)}>
      <span className={`v ${mark ?? x.valence ?? ""}`}>{mark === "for" || x.valence === "for" ? "+" : mark === "against" || x.valence === "against" ? "−" : x.valence === "unx" ? "○" : "·"}</span>
      <span>{x.text}{x.detail && <span className="d">{x.detail}</span>}</span>
      <span className="src">{x.source ?? ""}</span>
    </div>
  );
}

/** One problem as seven answers. Everything on this page is computed from the record; the buttons are the only
 *  places a signature happens: acknowledging a detected change, signing an insight, adding to the plan. */
export default function Problem({ pid, problemId, busy, run, go, refreshKey, embedded }: Ctx & { problemId: string; embedded?: boolean }) {
  const [v, setV] = useState<ProblemView | null>(null);
  const [tl, setTl] = useState<TL | null>(null);
  const [queues, setQueues] = useState<QueueBatch[]>([]);
  const [hi, setHi] = useState<Set<string>>(new Set());
  const [kind, setKind] = useState("monitoring");
  const [text, setText] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const first = (t: string) => { const m = t.match(/^(.*?[a-z0-9%)\]])\.\s+(?=[A-Z])/s); return m ? m[1] + "." : t; };
  useEffect(() => {
    let live = true;
    api.problem(pid, problemId).then((x) => live && setV(x)).catch(() => live && setV(null));
    api.trajectory(pid, problemId).then((x) => live && setTl(x)).catch(() => live && setTl(null));
    api.queue(pid).then((q) => live && setQueues(q.batches)).catch(() => live && setQueues([]));
    return () => { live = false; };
  }, [pid, problemId, refreshKey]);
  const hover = useCallback((ids: string[] | null) => setHi((prev) => { const next = ids ?? []; return prev.size === next.length && next.every((i) => prev.has(i)) ? prev : new Set(next); }), []);
  const hoverOne = useCallback((id: string | null) => hover(id ? [id] : null), [hover]);
  // Stable across hovers, so the chart is not handed a new corridor object (and redrawn) every time the highlight changes.
  const corridor = useMemo(() => {
    const cc = v?.answers.change_course;
    const pj = cc?.projection, po = cc?.projection_of;
    if (pj && po) return { code: po.code, direction: "falling", since: po.from.time, by: pj.full_effect_by, status: pj.observed?.status === "missed" ? "missed" : "not_yet", ref_value: po.from.value, target_value: (pj.at_full_effect.low + pj.at_full_effect.high) / 2 };
    return cc?.expected ?? null;
  }, [v]);
  if (!v) return <div className="lede">Reading the record for this problem…</div>;
  const a = v.answers;
  // The corridor on the trajectory: the current plan's projection when there is one, otherwise the card's expectation.
  const reasonStem = `reason_${problemId}`;
  const reasonBatch = queues.find((b) => b.stem === reasonStem);
  const signInsight = (id: string) => reasonBatch && run("agree", () => api.review(pid, reasonStem, { accept: [id] }), "Agreed: its first sentence goes into the visit note");
  const rejectInsight = (id: string) => reasonBatch && run("dismiss", () => api.review(pid, reasonStem, { reject: [id], reason_code: "disagree" }), "Dismissed");
  return (
    <HoverCtx.Provider value={hover}>
    <div>
      {!embedded && <button className="link" onClick={() => go("#/")}>← Problems</button>}
      <h1 style={{ marginTop: 6 }}>{v.problem.name} <span className={`dot ${v.problem.standing}`} style={{ display: "inline-block", marginLeft: 8 }} /> <span className="tag">{v.problem.standing_word}</span> <span className="tag ep" title={v.problem.epistemic.why}>{v.problem.epistemic.value}</span></h1>
      <p className="lede">{v.problem.why}. {v.problem.steward ? `Steward ${typeof v.problem.steward === "string" ? v.problem.steward : v.problem.steward.name}. ` : ""}{v.problem.onset ? `On the chart since ${dmy(v.problem.onset)}. ` : ""}{v.decisions} decisions on the record.</p>

      <Q n={1} ask="What is happening?" sub="the monitored series, the courses on board, what the patient reported">
        {a.happening.map((x, i) => <Line key={i} x={x} />)}
        {tl && <div className="chart"><Timeline data={tl} highlight={hi} onHover={hoverOne} corridor={corridor as never} /></div>}
        <div style={{ fontSize: 11.5, color: "var(--graphite)" }}>Courses are drawn as bands under the series they are linked to, so a medication's effect on a value is read off the same axis.</div>
      </Q>

      <Q n={2} ask="What do we think it means?" sub="the working summary, the causes on the record, what the reasoning found">
        <p className="serif" onMouseEnter={() => hover(a.means.cites)} onMouseLeave={() => hover(null)}>{a.means.text}</p>
        {a.means.causes.map((c, i) => <Line key={i} x={{ ...c, source: c.signed ? "signed" : "rejected" }} v={c.signed ? "for" : "against"} />)}
        {a.means.insights.map((i) => (
          <div key={i.id} className="line" onMouseEnter={() => hover(i.ids)} onMouseLeave={() => hover(null)}>
            <span className="v">{i.status === "signed" ? "✓" : "?"}</span>
            <span>{open.has(i.id) ? i.text : first(i.text)}{first(i.text) !== i.text && <button className="link more" onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(i.id)) n.delete(i.id); else n.add(i.id); return n; })}>{open.has(i.id) ? " less" : " more"}</button>}{i.action && <span className="d">Suggests: {i.action}</span>}</span>
            {i.status === "proposed" ? <span className="acts"><button className="btn small primary" disabled={!!busy} onClick={() => signInsight(i.id)}>Agree</button> <button className="btn small ghost" disabled={!!busy} onClick={() => rejectInsight(i.id)}>Dismiss</button></span> : <span className="src">{i.source === "rules" ? "noted by you" : "agreed"}</span>}
          </div>
        ))}
        {!a.means.insights.some((i) => i.status === "proposed") && <div className="addplan"><button className="btn small" disabled={!!busy || !!reasonBatch} title={reasonBatch ? "the reasoning has run for this problem; its insights are above" : undefined} onClick={() => run("reason", () => api.reason(pid, problemId), "The reasoning ran; agree or dismiss what it found")}>Ask what changed</button><span className="pill">the model reads the trends and the course events; nothing is written until you agree</span></div>}
      </Q>

      <Q n={3} ask="What changed?" sub={`since ${dmy(a.changed.since)} · detected by rules, noted by you`}>
        {a.changed.lines.map((x, i) => <Line key={i} x={x} />)}
        {a.changed.detected.map((d) => (
          <div key={d.id} className={`det ${d.acknowledged ? "ack" : ""}`} onMouseEnter={() => hover(d.ids)} onMouseLeave={() => hover(null)}>
            <span className="grow">{d.text}</span>
            {d.acknowledged ? <span className="pill">noted · in the visit note</span> : <button className="btn small primary" disabled={!!busy} onClick={() => run("ack", () => api.acknowledge(pid, problemId, d.text, d.ids), "Noted: it is on the record and goes into the visit note")}>Noted</button>}
          </div>
        ))}
        {a.changed.lines.length + a.changed.detected.length === 0 && <div className="quiet">Nothing has moved. Quiet is a valid answer.</div>}
      </Q>

      <Q n={4} ask="What are we doing?" sub="the plan on the record, the courses, the loops open; add your own line">
        {a.doing.linked.map((l, i) => <Line key={i} x={{ text: `${l.rel}: ${l.text}`, detail: l.detail, ids: l.ids }} />)}
        {a.doing.plan.map((p) => <Line key={p.id} x={{ text: p.text, detail: `${p.plan_kind.replace("_", " ")} · ${p.detail}`, ids: p.ids, source: p.status }} />)}
        {a.doing.loops.map((l) => <Line key={l.id} x={{ text: l.text, detail: l.detail, ids: [l.id], source: l.status }} />)}
        <form className="addplan" onSubmit={(e) => { e.preventDefault(); if (text.trim()) run("intent", () => api.intent(pid, problemId, kind, text.trim()), "Added to the plan").then(() => setText("")); }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">{KINDS.map((k) => <option key={k} value={k}>{k.replace("_", " ")}</option>)}</select>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Your own line for the plan" aria-label="Plan item" />
          <button className="btn small primary" disabled={!!busy || !text.trim()} type="submit">Add</button>
        </form>
      </Q>

      <Q n={5} ask="What are we uncertain about?" sub="what does not fit, what is only proposed, what is still unanswered">
        {a.uncertain.map((x, i) => <Line key={i} x={x} />)}
        {a.uncertain.length === 0 && <div className="quiet">Nothing on the chart argues against the current reading.</div>}
      </Q>

      <Q n={6} ask="What should happen next?" sub="loops to close, what best practice recommends, and what each option is projected to do">
        {a.next.map((x, i) => <Line key={i} x={x} />)}
        {a.guidelines.length > 0 && <h3 className="sub3">Best practice <span className="n">rules checked against the chart, each with its source</span></h3>}
        {a.guidelines.map((g) => (
          <div key={g.id} className="line" onMouseEnter={() => hover(g.ids)} onMouseLeave={() => hover(null)}>
            <span className={`v ${g.status === "gap" ? "unx" : "for"}`}>{g.status === "gap" ? "○" : "✓"}</span>
            <span>{g.text}<span className="d">{g.source} · {g.status === "gap" ? "not on the plan" : "covered by the plan"}</span></span>
            {g.action ? <button className="btn small" disabled={!!busy} onClick={() => run("intent", () => api.intent(pid, problemId, g.action!.kind, g.action!.text), "Added to the plan")}>Add</button> : <span className="src" />}
          </div>
        ))}
        {a.options.length > 0 && a.change_course.projection_of && (
          <>
            <h3 className="sub3">Options, projected <span className="n">{a.change_course.projection_of.name} from {a.change_course.projection_of.from.value}{a.change_course.projection_of.goal ? ` · goal under ${a.change_course.projection_of.goal}` : ""}</span></h3>
            <div className="opts">
              {a.options.map((o) => (
                <div key={o.id} className={`opt ${o.on_plan ? "on" : ""}`}>
                  <span className="lab">{o.label}</span>
                  <span className="eff num">{o.effect.low} to {o.effect.high}</span>
                  <span className="by">full effect by {dmy(o.full_effect_by)}{o.reaches_goal_by ? ` · to goal about ${dmy(o.reaches_goal_by)}` : " · alone, not to goal"}</span>
                  {o.on_plan ? <span className="pill ok">on the plan</span> : <button className="btn small" disabled={!!busy} onClick={() => run("intent", () => api.intent(pid, problemId, o.kind, o.text), "Added to the plan")}>Add</button>}
                  <span className="srcline">{o.source}</span>
                </div>
              ))}
            </div>
            <div className="simnote">{a.change_course.projection_of.note}</div>
          </>
        )}
        {a.next.length + a.guidelines.length + a.options.length === 0 && <div className="quiet">Nothing is owed on this problem.</div>}
      </Q>

      <Q n={7} ask="What would make us change course?" sub="the expectation, and the thresholds the rules watch">
        {a.change_course.expected ? (
          <p className="serif">{a.change_course.expected.statement}, by {dmy(a.change_course.expected.by)} · <b>{a.change_course.expected.status.replace("_", " ")}</b>.</p>
        ) : !a.change_course.projection && <p className="serif">No expectation is set. One is written when something on the plan is projected to move the value.</p>}
        {a.change_course.projection && a.change_course.projection_of && (
          <p className="serif">On the current plan ({a.change_course.projection.labels.join("; ").toLowerCase()}), {a.change_course.projection_of.name.toLowerCase()} is projected at <b className="num">{a.change_course.projection.at_full_effect.low} to {a.change_course.projection.at_full_effect.high}</b> by {dmy(a.change_course.projection.full_effect_by)}{a.change_course.projection.reaches_goal_by ? `, under goal by about ${dmy(a.change_course.projection.reaches_goal_by)}` : ", not to goal"}. A value above that band after that date is a miss, and the plan is what changes.{a.change_course.projection.observed ? ` Observed ${a.change_course.projection.observed.value} on ${dmy(a.change_course.projection.observed.time)}: ${a.change_course.projection.observed.status}.` : ""}</p>
        )}
        {a.change_course.expected_moves.map((m) => (
          <div key={m.id} className={`emove ${m.observed ? m.observed.status : ""}`} onMouseEnter={() => hover(m.ids)} onMouseLeave={() => hover(null)}>
            <div className="emove-head"><b>{m.value.name}</b> is expected to rise · <span className="trigger">{m.trigger.text}</span></div>
            <p className="serif">From <b className="num">{m.baseline.value} {m.value.unit}</b> on {dmy(m.baseline.time)}, expect {m.expect}, because {m.because}. Not expected: <b>{m.not_expected}</b> — {m.then}</p>
            {m.note && <p className="emove-note">{m.note}</p>}
            {m.counter && <p className="emove-note">{m.counter}</p>}
            <div className="emove-foot">
              {m.tested_by ? <span className="pill ok">tested by: {m.tested_by.text}</span> : <span className="pill gap">nothing on the plan tests this</span>}
              {m.observed
                ? <span className={`pill ${m.observed.status === "beyond" ? "gap" : "ok"}`}>observed {m.observed.value} {m.value.unit} on {dmy(m.observed.time)} · {m.observed.status === "beyond" ? "beyond what was expected" : "within"}</span>
                : <span className="pill">answered by {dmy(m.by)}</span>}
              <span className="src">{m.source}</span>
            </div>
          </div>
        ))}
        {a.change_course.reconsider_if.map((r, i) => <Line key={`r${i}`} x={{ text: `Reassess if ${r}`, ids: [] }} v="unx" />)}
        {a.change_course.tripwires.map((t, i) => <Line key={i} x={{ text: `${t.name} ${nice(t.latest.value)} · ${t.state}`, detail: t.set_by ? `tripwire: ${t.threshold} · set by ${t.set_by}, not the standing rule` : `tripwire: ${t.threshold}`, ids: t.ids }} />)}
      </Q>
    </div>
    </HoverCtx.Provider>
  );
}
