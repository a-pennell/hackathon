import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Ctx } from "./App";
import type { Proposal, VisitData } from "./v2types";
import Problem from "./Problem";

const PACE_MS = 2200;
const dmy = (iso: string) => { const d = new Date(iso.slice(0, 10) + "T00:00:00"); return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`; };

/** The visit as one surface. The dictation plays on the left. The recorded reading is revealed as the transcript reaches
 *  each finding's passage, and each finding lands on the problem it touches. Decisions wait as chips; everything else is
 *  accepted when the visit closes. The note grows the whole time; there is no separate review and no assemble step. */
export default function Visit({ pid, listing, busy, run, go, refreshKey }: Ctx) {
  const [v, setV] = useState<VisitData | null>(null);
  const [cursor, setCursor] = useState(-1);          // index of the utterance being spoken; -1 before the visit starts
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [tick, setTick] = useState(0);
  const timer = useRef<number | null>(null);
  const load = useCallback(() => api.visit(pid).then(setV).catch(() => setV(null)), [pid]);
  useEffect(() => { load(); }, [load, refreshKey]);

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
  useEffect(() => { if (!selected && revealed.length) { const first = revealed.find((p) => p.problems.length); if (first) setSelected(first.problems[0]); } }, [revealed, selected]);
  const pendingDecisions = revealed.filter((p) => p.decision && p.status === "proposed");
  const accepted = (v?.proposals ?? []).filter((p) => p.status === "accepted").length;
  const forSelected = revealed.filter((p) => selected && p.problems.includes(selected));

  const start = async () => {
    if (!v) return;
    if (!v.note.read) await run("read", () => api.readNote(pid, v.note.file), "Listening: the reading is placed in the transcript as it is spoken");
    await load();
    setCursor(0); setPlaying(true);
  };
  const act = (p: Proposal, decision: "accept" | "reject") => run("review", async () => {
    if (p.change) await api.review(pid, p.stem, { accept_changes: true });
    else if (decision === "accept") await api.review(pid, p.stem, { accept: [p.id] });
    else await api.review(pid, p.stem, { reject: [p.id, ...p.link_ids.filter((l) => l !== p.id)], reason_code: "disagree", reason });
    await load(); setTick((t) => t + 1);
  }, decision === "accept" ? "Accepted" : "Rejected; your reason is on the record").then(() => { setRejecting(null); setReason(""); });
  const close = () => v && run("sign", () => api.signNote(pid, v.note.id), "Visit closed: what was left is accepted; sign the visit note when you are ready").then(() => { load(); setTick((t) => t + 1); });

  if (!v) return <div className="lede">Opening the visit…</div>;
  const note = v.note;
  return (
    <div className="visit">
      <div className="gate-strip">
        {[...v.problems.map((p) => ({ id: p.id, name: p.name, standing: p.standing as string, why: p.why, isNew: false })),
          ...revealed.filter((x) => x.kind === "problem" && !v.problems.some((p) => p.name === x.text)).map((x) => ({ id: x.id, name: x.text, standing: "proposed", why: "raised at this visit; not on the chart until accepted", isNew: true }))].map((p) => (
          <button key={p.id} className={`gchip ${selected === p.id ? "on" : ""} ${touched.has(p.id) ? "touched" : ""} ${p.isNew ? "new" : ""}`} onClick={() => setSelected(p.id)} title={p.why}>
            <span className={`dot ${p.standing}`} />{p.name}{p.isNew && <span className="pill">new</span>}
            {revealed.filter((x) => x.problems.includes(p.id) && x.decision && x.status === "proposed").length > 0 && <span className="tag pend">{revealed.filter((x) => x.problems.includes(p.id) && x.decision && x.status === "proposed").length}</span>}
          </button>
        ))}
      </div>
      <div className="vgrid">
        <aside className="transcript">
          <div className="thead">
            <span className="eyebrow">Transcript · {note.author} · {dmy(note.time)}</span>
            <div className="controls">
              {cursor < 0 ? <button className="btn small primary" disabled={!!busy} onClick={start}>{note.read ? "Play the visit" : "Start the visit"}</button>
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
          {selected ? (
            <>
              <section className="heard">
                <span className="eyebrow">Heard at this visit · {v.problems.find((p) => p.id === selected)?.name ?? revealed.find((x) => x.id === selected)?.text}</span>
                {forSelected.length === 0 && <div className="quiet">{cursor < 0 ? "Nothing yet. Start the visit." : "Nothing said about this problem so far."}</div>}
                {forSelected.map((p) => (
                  <div key={p.id} className={`hline ${p.decision ? "decision" : ""} ${p.status}`}>
                    <span className="kind">{p.kind}</span>
                    <span className="what">{p.text}{p.quote && <span className="q">“{p.quote}”</span>}</span>
                    {p.status !== "proposed" ? <span className={`tag ${p.status === "accepted" ? "ok" : "warn"}`}>{p.status}</span>
                      : p.decision ? (
                        <span className="acts">
                          <button className="btn small primary" disabled={!!busy} onClick={() => act(p, "accept")}>Accept</button>
                          <button className="btn small ghost" disabled={!!busy} onClick={() => { setRejecting(rejecting === p.id ? null : p.id); setReason(""); }}>{rejecting === p.id ? "Cancel" : "Reject"}</button>
                        </span>
                      ) : <span className="pill">accepted at close</span>}
                    {rejecting === p.id && (
                      <form className="why" onSubmit={(e) => { e.preventDefault(); act(p, "reject"); }}>
                        <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why? One line; it goes on the record and into the note." aria-label="Reason" />
                        <button className="btn small primary" type="submit" disabled={!!busy}>Reject with this reason</button>
                      </form>
                    )}
                  </div>
                ))}
              </section>
              {v.problems.some((p) => p.id === selected) ? <Problem pid={pid} listing={listing} busy={busy} run={run} go={go} refreshKey={refreshKey + tick} problemId={selected} embedded />
                : <div className="quiet">A problem raised at this visit has no page until it is accepted; then it is watched like any other.</div>}
            </>
          ) : <div className="lede">Pick a problem above, or start the visit and the first one spoken about opens here.</div>}
        </main>

        <aside className="vnote">
          <span className="eyebrow">Visit note</span>
          <div className="big">{accepted}<small> accepted</small></div>
          <div className="small">{revealed.length - accepted - revealed.filter((p) => p.status === "rejected").length} heard, not yet accepted · {pendingDecisions.length} decision{pendingDecisions.length === 1 ? "" : "s"} waiting · {v.unattested} to attest</div>
          <p className="muted">The note is the visit's record rendered. Every accepted line is already a sentence in it; nothing is typed twice.</p>
          {note.status !== "signed" ? (
            <button className="btn primary" disabled={!!busy || cursor < 0 || pendingDecisions.length > 0} title={pendingDecisions.length ? "decide the chips first" : "accepts everything heard, then the note is yours to sign"} onClick={close}>Close the visit{revealed.length - accepted > 0 ? ` · accepts ${revealed.length - accepted - revealed.filter((p) => p.status === "rejected").length}` : ""}</button>
          ) : (
            <button className="btn primary" onClick={() => go("#/note")}>Sign the visit note</button>
          )}
          {!done && cursor >= 0 && <div className="muted">Closing before the end accepts what has been heard so far; the rest is still in the dictation.</div>}
        </aside>
      </div>
    </div>
  );
}
