import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Ctx } from "./App";
import type { Commitment, Commitments, Draft, ManifestGroup, NoteDoc, Practice, Proposal, VisitData } from "./v2types";
import Problem from "./Problem";

const PACE_MS = 2200;
function Watch({ w, go }: { w: Commitment; go: (h: string) => void }) {
  const answered = w.observed || w.status === "unanswered";
  return (
    <div className={`wrow k-${w.kind} s-${w.status}`}>
      <span className="wkind">{w.kind === "set_aside" ? "set aside" : w.kind}</span>
      <span className="wwhat">
        <b>{w.text}</b>
        <span className="wdetail">{w.detail}{w.tested_by ? ` · tested by: ${w.tested_by}` : ""}</span>
        {w.problem_id && <button className="wprob" onClick={() => go(`#/problem/${w.problem_id}`)}>{w.problem}</button>}
      </span>
      <span className={`wby ${answered ? "done" : ""}`}>
        {w.observed ? (w.kind === "plan" ? `resulted ${dmy(w.observed.time)}` : `${w.observed.value} on ${dmy(w.observed.time)} · ${w.observed.status}`)
          : w.by ? `by ${dmy(w.by)}` : "no date"}
      </span>
    </div>
  );
}

/** Step 1 of the reasoning, before the room: why she is here, which problems need attention, and what best practice
 *  says the plan does not yet cover. Nothing here is new data; it is the chart read in the order a clinician reads it. */
function Orient({ v, start, busy }: { v: VisitData; start: () => void; busy: boolean }) {
  const gaps = v.practice.filter((r) => r.status === "gap");
  const byProblem = [...new Set(gaps.map((g) => g.problem))];
  return (
    <section className="orient">
      <span className="eyebrow">Before you go in</span>
      <h2>{v.encounter?.summary ?? "Follow-up visit"}</h2>
      <div className="orient-rows">
        {v.problems.map((p) => (
          <div key={p.id} className="orow"><span className={`dot ${p.standing}`} /><b>{p.name}</b><span className="owhy">{p.why}</span></div>
        ))}
      </div>
      {gaps.length > 0 && (
        <>
          <span className="eyebrow">Best practice the plan does not cover yet · {gaps.length}</span>
          {byProblem.map((name) => (
            <div key={name} className="ogap-group">
              <div className="ogap-problem">{name}</div>
              {gaps.filter((g) => g.problem === name).map((g) => <div key={g.id} className="ogap">{g.text}<span className="src">{g.source}</span></div>)}
            </div>
          ))}
        </>
      )}
      <button className="btn primary" disabled={busy} onClick={start}>{v.note.read ? "Play the visit" : "Start the visit"}</button>
    </section>
  );
}

/** Step 5 at the moment of signing: best practice against the plan as it now stands, so a clinician can see what the
 *  dictated plan covered and add what it did not before the note is closed. Never written into the note itself. */
function PracticeCheck({ rules, busy, add }: { rules: Practice[]; busy: boolean; add: (r: Practice) => void }) {
  const open = rules.filter((r) => r.status === "gap");
  const covered = rules.filter((r) => r.status === "covered");
  if (!rules.length) return null;
  return (
    <div className="pcheck">
      <span className="eyebrow">Best practice, against this plan</span>
      {covered.length > 0 && <div className="pcov">{covered.length} covered by the plan</div>}
      {open.map((r) => (
        <div key={r.id} className="popen">
          <span className="ptext">{r.text}<span className="src">{r.problem} · {r.source}</span></span>
          {r.action ? <button className="btn small" disabled={busy} title={r.action.text} onClick={() => add(r)}>Add</button> : <span className="pill">target</span>}
        </div>
      ))}
    </div>
  );
}

const dmy = (iso: string) => { const d = new Date(iso.slice(0, 10) + "T00:00:00"); return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`; };

/** The visit as one surface. The dictation plays on the left. The recorded reading is revealed as the transcript reaches
 *  each finding's passage, and each finding lands on the problem it touches. Decisions wait as chips; everything else is
 *  accepted when the visit closes. The note grows the whole time; there is no separate review and no assemble step. */
export default function Visit({ pid, listing, busy, run, go, refreshKey }: Ctx) {
  const [v, setV] = useState<VisitData | null>(null);
  const [cursor, setCursor] = useState(-1);          // index of the utterance being spoken; -1 before the visit starts (restored below)
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const KEY = `visit:${pid}`;
  const saved = (() => { try { return JSON.parse(sessionStorage.getItem(KEY) ?? "null"); } catch { return null; } })() as { cursor?: number; decisions?: Record<string, "accept" | "reject">; reasons?: Record<string, string>; authored?: string; selected?: string | null } | null;
  const [decisions, setDecisions] = useState<Record<string, "accept" | "reject">>(saved?.decisions ?? {});
  const [reasons, setReasons] = useState<Record<string, string>>(saved?.reasons ?? {});
  const [authored, setAuthored] = useState(saved?.authored ?? "");
  const [signed, setSigned] = useState<{ attested: number } | null>(null);
  const [preview, setPreview] = useState<{ document: NoteDoc; manifest: ManifestGroup[] } | null>(null);
  // While the note is open the page underneath must not move. It is five thousand pixels of transcript and chart, and
  // any wheel that missed the panel's own scroll — over its header or footer, or momentum past the end of the note —
  // scrolled that instead: the page, its sticky transcript and its fixed bar sliding at different rates behind a panel
  // that stayed put. The scrollbar's width is held as padding so the page does not shift sideways when it goes.
  useEffect(() => {
    if (!preview) return;
    const root = document.documentElement;
    const gutter = window.innerWidth - root.clientWidth;
    const was = { overflow: root.style.overflow, paddingRight: root.style.paddingRight };
    root.style.overflow = "hidden";
    if (gutter > 0) root.style.paddingRight = `${gutter}px`;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPreview(null); };
    window.addEventListener("keydown", onKey);
    return () => { root.style.overflow = was.overflow; root.style.paddingRight = was.paddingRight; window.removeEventListener("keydown", onKey); };
  }, [preview]);
  const [edits, setEdits] = useState<Record<string, string>>({});   // keyed by section key, which survives a recompile
  const [commit, setCommit] = useState<Commitments | null>(null);
  const [pinned, setPinned] = useState(false);            // the clinician chose a problem; stop following the dictation
  const [draft, setDraft] = useState<Draft | null>(null); // the note as it stands, compiled as the dictation goes
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const lastText = useRef<Record<string, string>>({});
  const reqNo = useRef(0);
  const noteCol = useRef<HTMLDivElement>(null);
  const sectionsBody = () => Object.entries(edits).map(([key, text]) => ({ key, text }));
  useEffect(() => { if (saved) { if (typeof saved.cursor === "number") setCursor(saved.cursor); if (saved.selected) setSelected(saved.selected); } }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { sessionStorage.setItem(KEY, JSON.stringify({ cursor, decisions, reasons, authored, selected })); } catch { /* per-viewer convenience only */ } }, [KEY, cursor, decisions, reasons, authored, selected]);
  const [tick, setTick] = useState(0);
  const timer = useRef<number | null>(null);
  const load = useCallback(() => api.visit(pid).then((d) => {
    setV(d);
    // A remembered transcript position outlives a chart reset; without the reading it is stale.
    if (!d.note.read && d.proposals.length === 0) { setCursor(-1); setPlaying(false); setDecisions({}); setReasons({}); }
  }).catch(() => setV(null)), [pid]);
  useEffect(() => { load(); }, [load, refreshKey]);
  // Once it is signed the visit is not over: the chart starts waiting for things, and this is what it is waiting for.
  const isSigned = !!signed || v?.note.status === "signed";
  useEffect(() => { if (isSigned) api.commitments(pid).then(setCommit).catch(() => setCommit(null)); }, [isSigned, pid, refreshKey, tick]);

  const n = v?.utterances.length ?? 0;
  const done = v ? cursor >= n - 1 : false;
  useEffect(() => {
    if (!playing || !v) return;
    if (cursor >= n - 1) { setPlaying(false); return; }
    timer.current = window.setTimeout(() => setCursor((c) => c + 1), PACE_MS / speed);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [playing, cursor, n, speed, v]);

  // which utterance each proposal is spoken in; revealed once the cursor has reached it
  const utteranceOf = useCallback((p: Proposal) => (p.offset == null || !v) ? n - 1 : Math.max(0, v.utterances.findIndex((u) => p.offset! < u.end)), [v, n]);
  const revealed = useMemo(() => (v?.proposals ?? []).filter((p) => cursor >= utteranceOf(p)), [v, cursor, utteranceOf]);
  const perUtterance = useMemo(() => { const m = new Map<number, number>(); for (const p of v?.proposals ?? []) { const i = utteranceOf(p); m.set(i, (m.get(i) ?? 0) + 1); } return m; }, [v, utteranceOf]);
  const touched = useMemo(() => new Set(revealed.flatMap((p) => p.problems)), [revealed]);
  // What the flowsheet is allowed to show yet: a value appears in its row as it is spoken, not when the note was read.
  const revealedIds = useMemo(() => new Set(revealed.map((p) => p.id)), [revealed]);
  // How much of the dictation has landed on each problem. Standing cannot answer this during a visit — it is computed
  // from the chart, and nothing reaches the chart until the signature — so the gate says what it does know: how many
  // findings this problem has collected so far.
  const heardPer = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of revealed) for (const id of p.problems) m.set(id, (m.get(id) ?? 0) + 1);
    return m;
  }, [revealed]);
  // Represent, link, decide: that work happens on whichever problem is being talked about, so the middle follows the
  // dictation — until the clinician picks one, and then it stays put. It follows the way attention does, not every
  // mention: a line that still touches the current problem keeps it, and moving takes two lines in a row agreeing on
  // the new one. Taking every mention switched eleven times in thirty-four lines, with one-line detours ("Hypertension,
  // above goal… with new albuminuria" flicked to albuminuria and back); this switches five times, each where the topic
  // really changes. A pure function of how far the transcript has got, so skipping and reloading agree with playing.
  const followed = useMemo(() => {
    if (!v) return null;
    const onChart = new Set(v.problems.map((q) => q.id));
    const lines = new Map<number, Map<string, number>>();   // utterance -> problem -> findings landing there
    for (const p of v.proposals) {
      if (!p.problems.length) continue;
      const i = utteranceOf(p);
      const m = lines.get(i) ?? new Map<string, number>();
      for (const id of p.problems) m.set(id, (m.get(id) ?? 0) + 1);
      lines.set(i, m);
    }
    const top = (m: Map<string, number>) => [...m.entries()].sort((a, b) => (Number(!onChart.has(a[0])) - Number(!onChart.has(b[0]))) || b[1] - a[1])[0][0];
    let sel: string | null = null, pending: string | null = null;
    for (let c = 0; c <= cursor; c++) {
      const m = lines.get(c);
      if (!m) continue;
      const t = top(m);
      if (sel === null) { sel = t; continue; }
      if (m.has(sel)) { pending = null; continue; }        // the line still touches the current problem
      if (pending === t) { sel = t; pending = null; }        // two lines in a row agree
      else pending = t;
    }
    return sel;
  }, [v, cursor, utteranceOf]);
  useEffect(() => { if (!pinned && followed && followed !== selected) setSelected(followed); }, [followed, pinned, selected]);
  const inferred = revealed.filter((p) => p.origin === "inferred" && p.status === "proposed");
  const unanswered = inferred.filter((p) => !decisions[p.id]);
  const stated = revealed.filter((p) => p.origin === "stated" && p.status === "proposed").length;
  const forSelected = revealed.filter((p) => selected && p.problems.includes(selected));

  // Document: the note is compiled from what has been spoken so far, as it is spoken, so it is written alongside the
  // reasoning rather than after it. Once the dictation is finished it is the whole visit. Compiled on a copy of the
  // chart; nothing is written. Stale answers are dropped, and what changed is marked for a moment so the eye finds it.
  const heardIds = useMemo(() => revealed.map((p) => p.id), [revealed]);
  const upto = v && cursor >= 0 && !done ? v.utterances[cursor].end : null;
  useEffect(() => {
    if (!v || !v.note.read || cursor < 0 || isSigned) return;
    const my = ++reqNo.current;
    const t = window.setTimeout(() => {
      api.previewVisit(pid, { decisions, reasons, authored: "", heard: done ? null : heardIds, upto: done ? null : upto })
        .then((d) => {
          if (my !== reqNo.current) return;
          const changed = new Set<string>();
          for (const sec of d.document.sections) if (lastText.current[sec.key] !== sec.text) changed.add(sec.key);
          lastText.current = Object.fromEntries(d.document.sections.map((sec) => [sec.key, sec.text]));
          setDraft(d);
          if (changed.size) { setFresh(changed); window.setTimeout(() => setFresh(new Set()), 1400); }
        })
        .catch(() => { /* the column keeps the last good draft */ });
    }, 250);
    return () => window.clearTimeout(t);
  }, [pid, v, cursor, done, heardIds, upto, decisions, reasons, isSigned, tick]);  // eslint-disable-line react-hooks/exhaustive-deps
  // keep the section that just changed in view while the dictation plays, without moving the page
  useEffect(() => {
    if (!playing || !fresh.size || editing || !noteCol.current) return;
    const el = noteCol.current.querySelector<HTMLElement>(`[data-key="${CSS.escape([...fresh].pop()!)}"]`);
    if (!el) return;
    const col = noteCol.current;
    const top = el.offsetTop - col.offsetTop - 12;
    if (top < col.scrollTop || top + el.offsetHeight > col.scrollTop + col.clientHeight) {
      col.scrollTo({ top, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }, [fresh, playing, editing]);
  const addPractice = (r: Practice) => r.action && run("intent", () => api.intent(pid, r.problem_id, r.action!.kind, r.action!.text), "Added to the plan; it is in the note").then(() => setTick((t) => t + 1));

  const start = async () => {
    if (!v) return;
    if (!v.note.read) await run("read", () => api.readNote(pid, v.note.file), "Listening: the reading is placed in the transcript as it is spoken");
    await load();
    setCursor(0); setPlaying(true);
  };
  // Decisions are answers, not writes: nothing reaches the chart until the one signature.
  const act = (p: Proposal, decision: "accept" | "reject") => {
    setDecisions((d) => ({ ...d, [p.id]: decision }));
    if (decision === "reject") setReasons((r) => ({ ...r, [p.id]: reason }));
    setRejecting(null); setReason("");
  };
  const sign = () => v && run("sign", async () => {
    const r = await api.signVisit(pid, { decisions, reasons, authored, sections: sectionsBody() });
    setPreview(null);
    setSigned({ attested: r.attested }); try { sessionStorage.removeItem(KEY); } catch { /* ignore */ } await load(); setTick((t) => t + 1);
  }, "Signed. The dictation's findings are on the record; the visit note attests them.");

  if (!v) return <div className="lede">Opening the visit…</div>;
  const note = v.note;
  return (
    <div className="visit">
      <div className="gate-strip">
        {[...v.problems.map((p) => ({ id: p.id, name: p.name, standing: p.standing as string, why: p.why, isNew: false })),
          ...revealed.filter((x) => x.kind === "problem" && !v.problems.some((p) => p.name === x.text)).map((x) => ({ id: x.id, name: x.text, standing: "proposed", why: "raised at this visit; not on the chart until accepted", isNew: true }))].map((p) => (
          <button key={p.id} className={`gchip ${selected === p.id ? "on" : ""} ${touched.has(p.id) ? "touched" : ""} ${p.isNew ? "new" : ""}`} onClick={() => { setSelected(p.id); setPinned(true); }} title={p.why}>
            <span className={`dot ${p.standing}`} />{p.name}{p.isNew && <span className="pill">new</span>}
            {heardPer.get(p.id) ? <span className="tag heardcount" title="findings from this dictation that landed on this problem">{heardPer.get(p.id)}</span> : null}
            {unanswered.filter((x) => x.problems.includes(p.id)).length > 0 && <span className="tag pend" title="the reading added this; say yes or no">{unanswered.filter((x) => x.problems.includes(p.id)).length}</span>}
          </button>
        ))}
      </div>
      <div className="vgrid">
        <aside className="transcript">
          <div className="thead">
            <span className="eyebrow">Transcript · {note.author} · {dmy(note.time)}</span>
            <div className="controls">
              {cursor < 0 ? (isSigned ? <button className="btn small primary" disabled={!!busy} onClick={start}>Play the visit</button> : <span className="muted small">not started</span>)
                : <button className="btn small" disabled={done} onClick={() => setPlaying((p) => !p)}>{done ? "Ended" : playing ? "Pause" : "Resume"}</button>}
              {cursor >= 0 && !done && <button className="btn small ghost" onClick={() => { setPlaying(false); setCursor(n - 1); }}>Skip to end</button>}
              {cursor >= 0 && <button className="btn small ghost" onClick={() => setSpeed((s) => (s === 1 ? 2 : s === 2 ? 4 : 1))}>{speed}×</button>}
            </div>
          </div>
          <div className="utts">
            {v.utterances.map((u) => (
              <p key={u.i} className={`utt ${u.i < cursor ? "said" : u.i === cursor ? "now" : "later"}`}>{u.text}{perUtterance.get(u.i) ? <span className="found" title="findings from this passage">{perUtterance.get(u.i)}</span> : null}</p>
            ))}
          </div>
        </aside>

        <main className="work">
          {isSigned && commit && (
            <section className="handoff">
              <span className="eyebrow">The visit is signed · what the chart is waiting for</span>
              <p className="muted">Signing ended the visit, not the problem. Each line below has a date and something that answers it.</p>
              {commit.watching.map((w, i) => <Watch key={`${w.kind}${i}`} w={w} go={go} />)}
              {commit.followup && !commit.followup.applied && (
                <button className="btn primary" disabled={!!busy} title={commit.followup.label}
                  onClick={() => run("advance", () => api.advance(pid), "Two weeks on: the home log and the BMP have landed").then(() => setTick((t) => t + 1))}>
                  Two weeks later · let the results land
                </button>
              )}
              {commit.followup?.applied && <p className="muted">The follow-up results are on the chart. Open a problem to see what they did to it.</p>}
            </section>
          )}
          {!isSigned && cursor < 0 ? <Orient v={v} start={start} busy={!!busy} /> : selected ? (
            <>
              <section className="heard">
                <span className="eyebrow">Heard at this visit · {v.problems.find((p) => p.id === selected)?.name ?? revealed.find((x) => x.id === selected)?.text}
                  {pinned ? <button className="link small follow" onClick={() => setPinned(false)}>follow the dictation</button> : cursor >= 0 && !done ? <span className="following">following the dictation</span> : null}</span>
                {forSelected.length === 0 && <div className="quiet">{cursor < 0 ? "Nothing yet. Start the visit." : "Nothing said about this problem so far."}</div>}
                {forSelected.map((p) => (
                  <div key={p.id} className={`hline ${p.origin === "inferred" ? "decision" : ""} ${p.status} ${decisions[p.id] ?? ""}`}>
                    <span className="kind">{p.origin === "inferred" ? "added" : p.kind}</span>
                    <span className="what">{p.text}{p.quote && <span className="q">“{p.quote}”</span>}{p.origin === "inferred" && <span className="d">The reading inferred this; the passage does not say it.</span>}</span>
                    {p.status !== "proposed" ? <span className={`tag ${p.status === "accepted" ? "ok" : "warn"}`}>{p.status}</span>
                      : p.origin === "inferred" ? (
                        decisions[p.id] ? <span className={`tag ${decisions[p.id] === "accept" ? "ok" : "warn"}`}>{decisions[p.id] === "accept" ? "yes, take it" : "no"}<button className="link small" onClick={() => setDecisions((d) => { const n = { ...d }; delete n[p.id]; return n; })}> undo</button></span>
                        : <span className="acts">
                          <button className="btn small primary" disabled={!!busy} onClick={() => act(p, "accept")}>Yes</button>
                          <button className="btn small ghost" disabled={!!busy} onClick={() => { setRejecting(rejecting === p.id ? null : p.id); setReason(""); }}>{rejecting === p.id ? "Cancel" : "No"}</button>
                        </span>
                      ) : <span className="pill" title="the passage states it; your signature accepts it">stated</span>}
                    {rejecting === p.id && (
                      <form className="why" onSubmit={(e) => { e.preventDefault(); act(p, "reject"); }}>
                        <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why not? One line; it goes on the record and into the note." aria-label="Reason" />
                        <button className="btn small primary" type="submit" disabled={!!busy}>No, with this reason</button>
                      </form>
                    )}
                  </div>
                ))}
              </section>
              {v.problems.some((p) => p.id === selected) ? <Problem pid={pid} listing={listing} busy={busy} run={run} go={go} refreshKey={refreshKey + tick} problemId={selected} embedded revealed={revealedIds} />
                : <div className="quiet">A problem raised at this visit has no page until it is accepted; then it is watched like any other.</div>}
            </>
          ) : <div className="lede">Pick a problem above, or start the visit and the first one spoken about opens here.</div>}
        </main>

        <aside className="vnote" ref={noteCol}>
          <span className="eyebrow">Visit note</span>
          {signed || note.status === "signed" ? (
            <>
              <div className="big">signed</div>
              <p className="muted">{signed ? `${signed.attested} items attested by one signature.` : "The dictation and the visit note are signed."}</p>
              <button className="btn" onClick={() => go("#/note")}>Open the visit note</button>
              {commit && <p className="muted">{commit.open} things the chart is now waiting for{commit.next_date ? `, the first on ${dmy(commit.next_date)}` : ""}.</p>}
            </>
          ) : cursor < 0 ? (
            <p className="muted">The note writes itself as you dictate: what you say, what it means for each problem, what you plan and what you expect. You read it, change what you want, and sign it once.</p>
          ) : (
            <>
              <div className="dstate">
                {done ? <b>Dictation finished · read it, then sign</b> : <span>Writing as you dictate</span>}
                <span className="dcount">{stated} stated{inferred.length > 0 && <> · {inferred.length} added{unanswered.length ? <span className="warn">, unanswered</span> : ", answered"}</>}</span>
              </div>
              {(draft?.document.sections ?? []).filter((sec) => sec.source !== "authored").map((sec) => sec.source === "transcript" ? (
                sec.collapsed ? null : <div key={sec.key} data-key={sec.key} className="nc-sec is-tr"><h3>{sec.heading}</h3><p className="dtr">as you dictated it · shown in the transcript</p></div>
              ) : (
                <div key={sec.key} data-key={sec.key} className={`nc-sec ${sec.key === "not_addressed" ? "is-open" : ""} ${fresh.has(sec.key) ? "is-fresh" : ""} ${edits[sec.key] != null ? "is-edited" : ""}`}>
                  <h3>{sec.heading}{done && sec.key !== "not_addressed" && editing !== sec.key && <button className="link small" onClick={() => setEditing(sec.key)}>{edits[sec.key] != null ? "edited · change" : "edit"}</button>}</h3>
                  {editing === sec.key
                    ? <textarea autoFocus value={edits[sec.key] ?? sec.text} onChange={(e) => setEdits((x) => ({ ...x, [sec.key]: e.target.value }))} onBlur={() => setEditing(null)} aria-label={sec.heading} />
                    : <p>{edits[sec.key] ?? sec.text}</p>}
                </div>
              ))}
              <div className="nc-sec is-own">
                <h3>In your words</h3>
                <textarea value={authored} rows={2} placeholder="Anything the record cannot say. Optional." onChange={(e) => setAuthored(e.target.value)} aria-label="In your words" />
              </div>
              {done && <PracticeCheck rules={draft?.practice ?? []} busy={!!busy} add={addPractice} />}
              <div className="dfoot">
                {unanswered.length > 0 && <p className="muted warn">{unanswered.length} inferred finding{unanswered.length > 1 ? "s" : ""} without an answer: left out of the note unless you say yes.</p>}
                <button className="btn ghost small" disabled={!draft} onClick={() => draft && setPreview(draft)}>Read full page</button>
                <button className={`btn ${done ? "primary" : ""}`} disabled={!!busy || !done} title={done ? "accepts what the dictation stated and what you said yes to, and signs this note" : "a note is signed once the dictation is finished"} onClick={sign}>
                  {done ? "Sign the visit note" : "Sign when the dictation ends"}
                </button>
              </div>
            </>
          )}
        </aside>
      </div>
      {/* Below 1100px the note pane is static and falls to the foot of a very long page. The counts and the two acts
          stay in reach: the note is the point of this screen, and it should never be four screens away. */}
      {!signed && note.status !== "signed" && cursor >= 0 && (
        <div className="vbar" role="group" aria-label="Visit note">
          <button className="vbar-counts" onClick={() => draft && setPreview(draft)} title="the note as it stands">
            <b>{stated}</b> stated{inferred.length > 0 && <> · <b>{inferred.length}</b> added</>}
            {unanswered.length > 0 && <span className="warn"> · {unanswered.length} unanswered</span>}
          </button>
          <button className="btn" disabled={!draft} onClick={() => draft && setPreview(draft)}>Read the note</button>
          <button className={`btn ${done ? "primary" : ""}`} disabled={!!busy || !done} onClick={sign}>{done ? "Sign the visit note" : "Sign when the dictation ends"}</button>
        </div>
      )}
      {preview && (
        <>
          <div className="scrim" onClick={() => setPreview(null)} />
          <div className="pv" role="dialog" aria-modal="true" aria-labelledby="pv-title">
            <div className="pv-head">
              <div><span className="eyebrow">{done ? "The note as it will be signed" : "The note so far"} · nothing is on the chart yet</span><h2 id="pv-title">{(draft ?? preview).document.title}</h2></div>
              <button className="dclose" aria-label="Close" onClick={() => setPreview(null)}>✕</button>
            </div>
            <div className="pv-body">
              <div className="pv-manifest">{(draft ?? preview).manifest.map((g) => <span key={g.kind} className="pill">{g.count} {g.label}</span>)}</div>
              {(draft ?? preview).document.sections.map((sec) => (
                <section key={sec.key} className={`note-sec src-${sec.source ?? "compiled"}`}>
                  <h2>{sec.heading} {sec.source !== "transcript" && <span className="pill">{sec.source === "authored" ? "your words" : edits[sec.key] != null ? "compiled · edited" : "compiled from the record"}</span>}</h2>
                  {sec.source === "transcript" || sec.source === "authored" ? <p className="ro">{sec.text}</p>
                    : <textarea value={edits[sec.key] ?? sec.text} rows={Math.max(2, Math.ceil((edits[sec.key] ?? sec.text).length / 70))} onChange={(e) => setEdits((x) => ({ ...x, [sec.key]: e.target.value }))} aria-label={sec.heading} />}
                </section>
              ))}
              <p className="muted">Compiled sections can be edited here; edits are kept and travel with the signature.</p>
            </div>
            <div className="pv-foot">
              <button className="btn ghost" onClick={() => setPreview(null)}>Back to the visit</button>
              <span className="spacer" />
              <button className="btn primary" disabled={!!busy || !done} onClick={sign}>{done ? "Sign the visit note" : "Sign when the dictation ends"}</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
