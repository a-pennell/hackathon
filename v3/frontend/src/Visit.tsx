import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Ctx } from "./App";
import type { Commitment, Commitments, ManifestGroup, NoteDoc, Proposal, VisitData } from "./v2types";
import Problem from "./Problem";

const PACE_MS = 2200;
function Watch({ w, go }: { w: Commitment; go: (h: string) => void }) {
  const answered = w.observed || w.status === "unanswered";
  return (
    <div className={`wrow ${w.kind} ${w.status}`}>
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
  const [edits, setEdits] = useState<Record<string, string>>({});   // keyed by section key, which survives a recompile
  const [commit, setCommit] = useState<Commitments | null>(null);
  const sectionsBody = () => Object.entries(edits).map(([key, text]) => ({ key, text }));
  const openPreview = () => run("preview", async () => { setPreview(await api.previewVisit(pid, { decisions, reasons, authored, sections: sectionsBody() })); });
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
  useEffect(() => { if (!selected && revealed.length) { const first = revealed.find((p) => p.problems.length); if (first) setSelected(first.problems[0]); } }, [revealed, selected]);
  const inferred = revealed.filter((p) => p.origin === "inferred" && p.status === "proposed");
  const unanswered = inferred.filter((p) => !decisions[p.id]);
  const stated = revealed.filter((p) => p.origin === "stated" && p.status === "proposed").length;
  const forSelected = revealed.filter((p) => selected && p.problems.includes(selected));

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
          <button key={p.id} className={`gchip ${selected === p.id ? "on" : ""} ${touched.has(p.id) ? "touched" : ""} ${p.isNew ? "new" : ""}`} onClick={() => setSelected(p.id)} title={p.why}>
            <span className={`dot ${p.standing}`} />{p.name}{p.isNew && <span className="pill">new</span>}
            {unanswered.filter((x) => x.problems.includes(p.id)).length > 0 && <span className="tag pend" title="the reading added this; say yes or no">{unanswered.filter((x) => x.problems.includes(p.id)).length}</span>}
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
          {isSigned && commit && (
            <section className="watch">
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
          {selected ? (
            <>
              <section className="heard">
                <span className="eyebrow">Heard at this visit · {v.problems.find((p) => p.id === selected)?.name ?? revealed.find((x) => x.id === selected)?.text}</span>
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

        <aside className="vnote">
          <span className="eyebrow">Visit note</span>
          {signed || note.status === "signed" ? (
            <>
              <div className="big">signed</div>
              <p className="muted">{signed ? `${signed.attested} items attested by one signature.` : "The dictation and the visit note are signed."}</p>
              <button className="btn" onClick={() => go("#/note")}>Open the visit note</button>
              {commit && <p className="muted">{commit.open} things the chart is now waiting for{commit.next_date ? `, the first on ${dmy(commit.next_date)}` : ""}.</p>}
            </>
          ) : (
            <>
              <button className="big asbtn" onClick={openPreview} title="read the note these become">{stated}<small> stated</small></button>
              <p className="muted">What the dictation states is accepted by your signature. Nothing to click.</p>
              <div className="big">{inferred.length}<small> added by the reading</small></div>
              <p className="muted">{inferred.length === 0 ? "Nothing the passage does not say." : unanswered.length ? `${unanswered.length} without an answer: left out of the note unless you say yes.` : "All answered."}</p>
              <textarea className="own" value={authored} rows={3} placeholder="Your own words, if any. The rest is compiled from what was said and decided." onChange={(e) => setAuthored(e.target.value)} aria-label="Your own words" />
              <button className="btn" disabled={!!busy || cursor < 0} title="the visit note exactly as the signature would produce it, to read and edit before signing" onClick={openPreview}>Review the note</button>
              <button className="btn primary" disabled={!!busy || cursor < 0} title="accepts everything the dictation stated, takes what you said yes to, and signs the visit note" onClick={sign}>Sign the visit note</button>
              {!done && cursor >= 0 && <div className="muted">Signing before the end takes what has been heard so far; the rest is still in the dictation.</div>}
              <div className="muted">{v.unattested > 0 ? `${v.unattested} to attest from earlier.` : ""}</div>
            </>
          )}
        </aside>
      </div>
      {/* Below 1100px the note pane is static and falls to the foot of a very long page. The counts and the two acts
          stay in reach: the note is the point of this screen, and it should never be four screens away. */}
      {!signed && note.status !== "signed" && cursor >= 0 && (
        <div className="vbar" role="group" aria-label="Visit note">
          <button className="vbar-counts" onClick={openPreview} title="what the signature would accept, listed">
            <b>{stated}</b> stated{inferred.length > 0 && <> · <b>{inferred.length}</b> added</>}
            {unanswered.length > 0 && <span className="warn"> · {unanswered.length} unanswered</span>}
          </button>
          <button className="btn" disabled={!!busy} onClick={openPreview}>Review the note</button>
          <button className="btn primary" disabled={!!busy} onClick={sign}>Sign the visit note</button>
        </div>
      )}
      {preview && (
        <>
          <div className="scrim" onClick={() => setPreview(null)} />
          <div className="pv" role="dialog" aria-modal="true" aria-labelledby="pv-title">
            <div className="pv-head">
              <div><span className="eyebrow">Review before signing · nothing is on the chart yet</span><h2 id="pv-title">{preview.document.title}</h2></div>
              <button className="dclose" aria-label="Close" onClick={() => setPreview(null)}>✕</button>
            </div>
            <div className="pv-body">
              <div className="pv-manifest">{preview.manifest.map((g) => <span key={g.kind} className="pill">{g.count} {g.label}</span>)}</div>
              {preview.document.sections.map((sec) => (
                <section key={sec.key} className={`note-sec ${sec.source ?? "compiled"}`}>
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
              <button className="btn primary" disabled={!!busy} onClick={sign}>Sign the visit note</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
