import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import Inbox from "./Inbox";
import ProblemList from "./ProblemList";
import Timeline from "./Timeline";
import Brief from "./Brief";
import Trail from "./Trail";
import type { Brief as BriefT, Document, NoteFile, PatientSummary, QueueBatch, Timeline as TL, TrailEntry } from "./types";

const PID = "pt_001";
const WINDOWS = ["3m", "6m", "1y", "2y", "5y", "all"];

function age(dob: string) {
  const d = new Date(dob), n = new Date();
  return n.getFullYear() - d.getFullYear() - (n < new Date(n.getFullYear(), d.getMonth(), d.getDate()) ? 1 : 0);
}

export default function App() {
  const [summary, setSummary] = useState<PatientSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [window_, setWindow] = useState("1y");
  const [tl, setTl] = useState<TL | null>(null);
  const [brief, setBrief] = useState<BriefT | null>(null);
  const [trail, setTrail] = useState<TrailEntry[]>([]);
  const [queues, setQueues] = useState<QueueBatch[]>([]);
  const [notes, setNotes] = useState<NoteFile[]>([]);
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState<"note" | "reason" | "compose" | null>(null);
  const [reading, setReading] = useState<NoteFile | null>(null);
  const [readingDoc, setReadingDoc] = useState<Document | null>(null);

  const refresh = useCallback(async () => {
    const [s, q, n] = await Promise.all([api.patient(PID), api.queue(PID), api.notes()]);
    setSummary(s);
    setQueues(q);
    setNotes(n.filter((x) => x.patient_id === PID));
    setProblem((p) => p ?? s.problems.find((x) => x.name.startsWith("Chronic kidney disease stage 3"))?.id ?? s.problems.find((x) => (x.monitored_codes?.length ?? 0) > 0)?.id ?? null);
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message ?? e)));
  }, [refresh]);

  useEffect(() => {
    if (!problem) return;
    let live = true;
    api.timeline(PID, problem, window_).then((d) => live && setTl(d)).catch((e) => setError(String(e.message ?? e)));
    api.brief(PID, problem).then((b) => live && setBrief(b)).catch(() => live && setBrief(null));
    api.trail(PID, problem).then((t) => live && setTrail(t)).catch(() => live && setTrail([]));
    return () => {
      live = false;
    };
  }, [problem, window_, queues, summary]);

  const askBrief = async (mode: "live" | "replay") => {
    if (!problem) return;
    setBusy("brief");
    setError(null);
    try {
      setBrief(await api.briefLive(PID, problem, mode));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  // id -> human label, for chips and link rows
  const labels = useMemo(() => {
    const m: Record<string, string> = {};
    if (summary) for (const p of summary.problems) m[p.id] = p.name;
    if (tl) {
      for (const med of [...tl.medications, ...tl.proposed.medications]) m[med.id] = med.name;
      for (const s of tl.series) {
        m[`LOINC:${s.code}`] = `${s.name} series`;
        for (const p of s.points) m[p.id] = `${s.name} ${p.value} ${s.unit ?? ""} · ${p.time.slice(0, 10)}`;
      }
      for (const o of tl.proposed.observations) m[o.id] = `${o.name} ${o.value} ${o.unit ?? ""} · ${o.effective_time.slice(0, 10)}`;
      for (const p of tl.proposed.problems) m[p.id] = p.name;
      for (const e of tl.encounters) if (e.note_id) m[e.note_id] = `note · ${e.time.slice(0, 10)} · ${e.author ?? ""}`;
    }
    for (const b of queues) {
      for (const p of b.proposed.problems ?? []) m[p.id] = p.name;
      for (const med of b.proposed.medications ?? []) m[med.id] = med.name;
      for (const o of b.proposed.observations ?? []) m[o.id] = `${o.name} ${o.value} ${o.unit ?? ""}`;
      if (b.note_id) m[b.note_id] = `note ${b.note_id.replace("note_", "")}`;
    }
    return m;
  }, [summary, tl, queues]);

  const proposedProblemNames = useMemo(
    () => [...new Set(queues.flatMap((b) => (b.proposed.problems ?? []).filter((p) => p.status === "proposed").map((p) => p.name)))],
    [queues],
  );

  const review = useCallback(
    async (stem: string, body: import("./api").ReviewBody) => {
      setBusy(stem);
      setError(null);
      try {
        await api.review(PID, stem, body);
        await refresh();
      } catch (e) {
        setError(String((e as Error).message ?? e));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const runExtract = async (n: NoteFile, mode: "live" | "replay") => {
    setMenu(null);
    setReading(null);
    setBusy("extract");
    setError(null);
    try {
      if (!n.file) return;
      await api.extract(PID, n.file, mode);
      await refresh();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const runCompose = async (mode: "live" | "replay") => {
    if (!problem) return;
    setMenu(null);
    setBusy("compose");
    setError(null);
    try {
      await api.compose(PID, problem, "referral", "nephrology", mode, window_);
      await refresh();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const runReason = async (mode: "live" | "rules" | "replay") => {
    if (!problem) return;
    setMenu(null);
    setBusy("reason");
    setError(null);
    try {
      await api.reason(PID, problem, mode, window_);
      await refresh();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const hover = useCallback((ids: string[] | null) => setHighlight(new Set(ids ?? [])), []);

  const openChartNote = async (noteId: string) => {
    try {
      setReading(await api.note(PID, noteId));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  // ids the inbox treats as "about the selected problem": the problem itself and its monitored series
  const focusIds = useMemo(() => new Set([...(problem ? [problem] : []), ...(tl?.series.map((s) => `LOINC:${s.code}`) ?? [])]), [problem, tl]);

  const runReset = async () => {
    if (!window.confirm("Reset the demo? Unsigns everything and clears the review queue (saved model responses are kept).")) return;
    setBusy("reset");
    setError(null);
    try {
      await api.reset(PID);
      setSummary(null);
      await refresh();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  if (!summary) return <div className="sheet empty">{error ?? "Opening chart…"}</div>;
  const pt = summary.patient;
  const selected = summary.problems.find((p) => p.id === problem);

  return (
    <div className="desk" onClick={() => menu && setMenu(null)}>
      <header className="head">
        <div className="who">
          {pt.name}
          <small>
            {pt.sex} · {age(pt.dob)} · DOB {pt.dob} · {pt.id}
          </small>
        </div>
        <span className="spacer" />
        {busy && <span className="busy">{busy === "extract" ? "Reading the note…" : busy === "reason" ? "Reasoning…" : busy === "compose" ? "Composing the referral…" : busy === "brief" ? "Writing the brief…" : busy === "reset" ? "Resetting…" : "Signing…"}</span>}
        <button className="btn ghost small" disabled={!!busy} onClick={runReset} title="Restore the chart to its state at server start">
          Reset demo
        </button>
        <div className="rel" onClick={(e) => e.stopPropagation()}>
          <button className="btn" disabled={!!busy} onClick={() => setMenu(menu === "note" ? null : "note")}>
            A note arrives ▾
          </button>
          {menu === "note" && (
            <div className="menu">
              {notes.map((n) => (
                <button key={n.id} onClick={() => { setMenu(null); setReading(n); }}>
                  <div className="t">
                    {n.id} · {n.time.slice(0, 10)} · {n.author}
                    {n.has_queue ? " · extracted" : ""}
                  </div>
                  <div className="x">{n.excerpt.replace(/\s+/g, " ").slice(0, 90)}…</div>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="rel" onClick={(e) => e.stopPropagation()}>
          <button className="btn primary" disabled={!!busy || !problem} onClick={() => setMenu(menu === "reason" ? null : "reason")}>
            Reason about this problem ▾
          </button>
          {menu === "reason" && (
            <div className="menu">
              <button onClick={() => runReason("live")}>
                <div className="x">Ask Claude <small>· trend summaries + med events → insight</small></div>
              </button>
              <button onClick={() => runReason("replay")}>
                <div className="x">Replay last Claude run <small>· no API call</small></div>
              </button>
              <button onClick={() => runReason("rules")}>
                <div className="x">Rules only <small>· deterministic, offline</small></div>
              </button>
            </div>
          )}
        </div>
        <div className="rel" onClick={(e) => e.stopPropagation()}>
          <button className="btn" disabled={!!busy || !problem} onClick={() => setMenu(menu === "compose" ? null : "compose")}>
            Generate referral ▾
          </button>
          {menu === "compose" && (
            <div className="menu">
              <button onClick={() => runCompose("live")}>
                <div className="x">Nephrology referral with Claude <small>· chart state + signed insights + your decisions</small></div>
              </button>
              <button onClick={() => runCompose("replay")}>
                <div className="x">Replay last Claude run <small>· no API call</small></div>
              </button>
            </div>
          )}
        </div>
        <div className="seg">
          {WINDOWS.map((w) => (
            <button key={w} className={w === window_ ? "on" : ""} onClick={() => setWindow(w)}>
              {w}
            </button>
          ))}
        </div>
      </header>

      <ProblemList problems={summary.problems} selected={problem} onSelect={setProblem} proposedNames={proposedProblemNames} />

      <main className="sheet">
        {error && <div className="err">{error}</div>}
        {selected && (
          <div className="sheet-head">
            <h1>{selected.name}</h1>
            <span className="since">
              since {selected.onset_date} · {tl?.series.length ?? 0} monitored series · {tl?.medications.length ?? 0} medications on board
            </span>
          </div>
        )}
        {selected && <Brief brief={brief} highlight={highlight} onHover={hover} onAskClaude={askBrief} busy={!!busy} />}
        {tl && tl.series.length > 0 ? (
          <Timeline data={tl} highlight={highlight} onHover={(id) => hover(id ? [id] : null)} onOpenNote={openChartNote} />
        ) : (
          <div className="empty">{selected ? `No monitored lab series is linked to ${selected.name} in this window.` : "Pick a problem."}</div>
        )}
        {selected && <Trail entries={trail} labels={labels} highlight={highlight} onHover={hover} />}
      </main>

      <Inbox queues={queues} problemId={problem} focusIds={focusIds} chartMedIds={new Set((tl?.medications ?? []).map((m) => m.id))} chartInsights={summary.insights} chartDocuments={summary.documents ?? []} labels={labels} highlight={highlight} onHover={hover} onReview={review} onReadDocument={setReadingDoc} busy={busy} />

      {readingDoc && (
        <div className="modal-bg" onClick={() => setReadingDoc(null)}>
          <div className="modal wide" onClick={(e) => e.stopPropagation()}>
            <h3>{readingDoc.title}</h3>
            <div className="meta">
              {readingDoc.kind} to {readingDoc.audience} · {readingDoc.status === "accepted" ? "signed" : "proposed, unsigned"} · {readingDoc.provenance.model} · {readingDoc.created_at.slice(0, 16).replace("T", " ")}
            </div>
            <div className="letter">
              <p>Re: {pt.name}, DOB {pt.dob} · {summary.problems.find((p) => p.id === readingDoc.problem_id)?.name}</p>
              {readingDoc.sections.map((s, i) => (
                <div key={i}>
                  <h4>{s.heading}</h4>
                  <p>{s.text}</p>
                  <div className="chips" onMouseLeave={() => hover(null)}>
                    {s.cites.map((id) => (
                      <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={labels[id] ?? id} onMouseEnter={() => hover([id])}>
                        {id}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              {readingDoc.questions.length > 0 && (
                <>
                  <h4>Questions for the recipient</h4>
                  <ol>
                    {readingDoc.questions.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ol>
                </>
              )}
              <div className="from">Generated from the chart by {readingDoc.provenance.model}. {readingDoc.review ? `${readingDoc.review.decision === "accepted" ? "Signed" : "Rejected"} by ${readingDoc.review.by}.` : "Unsigned."}</div>
            </div>
            <div className="row">
              <span className="spacer" />
              <button className="btn ghost" onClick={() => setReadingDoc(null)}>Close</button>
              {readingDoc.status === "proposed" && readingDoc.queue && (
                <button className="btn primary" onClick={() => { const q = readingDoc.queue!; setReadingDoc(null); review(q, { accept: [readingDoc.id] }); }}>
                  Sign referral
                </button>
              )}
            </div>
          </div>
        </div>
      )}
      {reading && (
        <div className="modal-bg" onClick={() => setReading(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>
              Note {reading.id.replace("note_", "")} · {reading.author}
            </h3>
            <div className="meta">
              {reading.time.slice(0, 16).replace("T", " ")} · {reading.file ?? "chart note (imported)"}
              {reading.has_queue ? " · already extracted (re-running replaces the queue)" : ""}
            </div>
            <pre>{reading.text.trim()}</pre>
            <div className="row">
              <span className="spacer" />
              <button className="btn ghost" onClick={() => setReading(null)}>
                Close
              </button>
              {reading.file && (
                <>
                  <button className="btn" disabled={!reading.has_replay} title={reading.has_replay ? "" : "no saved model response yet"} onClick={() => runExtract(reading, "replay")}>
                    Extract (replay)
                  </button>
                  <button className="btn primary" onClick={() => runExtract(reading, "live")}>
                    Extract with Claude
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
