import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import Inbox from "./Inbox";
import ProblemList from "./ProblemList";
import Timeline from "./Timeline";
import Brief from "./Brief";
import Trail from "./Trail";
import Coding from "./Coding";
import Card from "./Card";
import Overview from "./Overview";
import type { Brief as BriefT, Card as CardT, Coding as CodingT, Document, NoteFile, Overview as OverviewT, PatientSummary, QueueBatch, Timeline as TL, TrailEntry } from "./types";

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
  const [card, setCard] = useState<CardT | null>(null);
  const [overview, setOverview] = useState<OverviewT | null>(null);
  const [view, setView] = useState<"overview" | "card" | "desk">(() => {
    try {
      return (localStorage.getItem("view") as "overview" | "card" | "desk") || "overview";
    } catch {
      return "overview";
    }
  });
  const [trail, setTrail] = useState<TrailEntry[]>([]);
  const [coding, setCoding] = useState<CodingT | null>(null);
  const [queues, setQueues] = useState<QueueBatch[]>([]);
  const [queueLabels, setQueueLabels] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<NoteFile[]>([]);
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState<"note" | null>(null);
  const [mode, setMode] = useState<"live" | "replay">(() => {
    try {
      return (localStorage.getItem("claudeMode") as "live" | "replay") || "replay";
    } catch {
      return "replay";
    }
  });
  const [toast, setToast] = useState<{ stem: string; ids: string[]; text: string } | null>(null);
  const [reading, setReading] = useState<NoteFile | null>(null);
  const [readingDoc, setReadingDoc] = useState<Document | null>(null);

  const refresh = useCallback(async () => {
    const [s, q, n, o] = await Promise.all([api.patient(PID), api.queue(PID), api.notes(), api.overview(PID).catch(() => null)]);
    setSummary(s);
    setOverview(o);
    setQueues(q.batches);
    setQueueLabels(q.labels);
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
    api.card(PID, problem, window_).then((c) => live && setCard(c)).catch(() => live && setCard(null));
    api.trail(PID, problem).then((t) => live && setTrail(t)).catch(() => live && setTrail([]));
    api.coding(PID).then((c) => live && setCoding(c)).catch(() => live && setCoding(null));
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
    const m: Record<string, string> = { ...queueLabels };
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
      for (const o of b.proposed.orders ?? []) m[o.id] = `order: ${o.name}`;
      if (b.note_id) m[b.note_id] = `note ${b.note_id.replace("note_", "")}`;
    }
    return m;
  }, [summary, tl, queues, queueLabels]);

  const proposedProblemNames = useMemo(
    () => [...new Set(queues.flatMap((b) => (b.proposed.problems ?? []).filter((p) => p.status === "proposed").map((p) => p.name)))],
    [queues],
  );

  const review = useCallback(
    async (stem: string, body: import("./api").ReviewBody) => {
      setBusy(stem);
      setError(null);
      try {
        const r = await api.review(PID, stem, body);
        await refresh();
        const n = r.decided.length;
        const verb = body.reject?.length ? "Rejected" : "Signed";
        if (n > 0) setToast({ stem, ids: r.decided, text: `${verb} ${n === 1 ? "1 item" : n + " items"}` });
      } catch (e) {
        setError(String((e as Error).message ?? e));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 10000);
    return () => clearTimeout(t);
  }, [toast]);

  const undo = async () => {
    if (!toast) return;
    const { stem, ids } = toast;
    setToast(null);
    setBusy(stem);
    try {
      await api.undo(PID, stem, ids);
      await refresh();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const setViewPersist = (v: "overview" | "card" | "desk") => {
    setView(v);
    try {
      localStorage.setItem("view", v);
    } catch {
      /* private mode: fine */
    }
  };

  const setModePersist = (m: "live" | "replay") => {
    setMode(m);
    try {
      localStorage.setItem("claudeMode", m);
    } catch {
      /* private mode: fine */
    }
  };

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

  const runOrders = async (mode: "live" | "replay") => {
    if (!problem) return;
    setMenu(null);
    setBusy("orders");
    setError(null);
    try {
      await api.orders(PID, problem, mode, window_);
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
    <div className={`desk ${view !== "desk" ? "cardview" : ""}`} onClick={() => menu && setMenu(null)}>
      <header className="head">
        <div className="who">
          {pt.name}
          <small>
            {pt.sex} · {age(pt.dob)} · DOB {pt.dob} · {pt.id}
          </small>
        </div>
        <span className="seg view" title="Desk: list, sheet and inbox. Card: the problem card, with proposals in their slots">
          <button className={view === "overview" ? "on" : ""} onClick={() => setViewPersist("overview")}>Overview</button>
          <button className={view === "card" ? "on" : ""} onClick={() => setViewPersist("card")}>Card</button>
          <button className={view === "desk" ? "on" : ""} onClick={() => setViewPersist("desk")}>Desk</button>
        </span>
        <span className="spacer" />
        {busy && <span className="busy">{busy === "extract" ? "Reading the note…" : busy === "reason" ? "Looking at what changed…" : busy === "compose" ? "Drafting the referral…" : busy === "orders" ? "Drafting orders…" : busy === "brief" ? "Writing the brief…" : busy === "reset" ? "Resetting…" : "Saving…"}</span>}
        <span className="mode" title="Live asks Claude now; saved uses the recorded response, no network">
          Claude
          <span className="seg">
            <button className={mode === "live" ? "on" : ""} onClick={() => setModePersist("live")}>live</button>
            <button className={mode === "replay" ? "on" : ""} onClick={() => setModePersist("replay")}>saved</button>
          </span>
        </span>
        <div className="rel" onClick={(e) => e.stopPropagation()}>
          <button className="btn" disabled={!!busy} onClick={() => setMenu(menu === "note" ? null : "note")}>
            Read a note ▾
          </button>
          {menu === "note" && (
            <div className="menu">
              {notes.map((n) => (
                <button key={n.id} onClick={() => { setMenu(null); setReading(n); }}>
                  <div className="t">
                    {n.id} · {n.time.slice(0, 10)} · {n.author}
                    {n.has_queue ? " · read" : ""}
                  </div>
                  <div className="x">{n.excerpt.replace(/\s+/g, " ").slice(0, 90)}…</div>
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="btn primary" disabled={!!busy || !problem} onClick={() => runReason(mode)} title="Trend summaries and medication events go to Claude; insights come back for your signature">
          What's changed?
        </button>
        <button className="btn" disabled={!!busy || !problem} onClick={() => runOrders(mode)} title="Turn the actions in signed insights into orders to sign">
          Draft orders
        </button>
        <button className="btn" disabled={!!busy || !problem} onClick={() => runCompose(mode)} title="A nephrology referral rendered from the chart, signed insights and your decisions">
          Draft referral
        </button>
        <button className="btn ghost small" disabled={!!busy} onClick={runReset} title="Restore the chart to its state at server start">
          Reset demo
        </button>
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
        {view === "overview" && overview && (
          <Overview
            data={overview}
            problems={summary.problems}
            highlight={highlight}
            onHover={hover}
            onOpen={(id) => { setProblem(id); setViewPersist("card"); }}
            onReadNote={(id) => { const n = notes.find((x) => x.id === id); if (n) setReading(n); }}
            busy={busy}
          />
        )}
        {view === "overview" && !overview && <div className="empty">Computing the overview…</div>}
        {view === "card" && selected && card && card.problem_id === selected.id && (
          <Card
            key={card.problem_id}
            card={card}
            tl={tl && tl.problem.id === selected.id ? tl : null}
            queues={queues}
            chartInsights={summary.insights}
            chartDocuments={summary.documents ?? []}
            labels={labels}
            highlight={highlight}
            onHover={hover}
            onReview={review}
            onReadDocument={setReadingDoc}
            onOpenNote={openChartNote}
            busy={busy}
            mode={mode}
            window_={window_}
            setWindow={setWindow}
            windows={WINDOWS}
            actions={{ reason: () => runReason(mode), orders: () => runOrders(mode), compose: () => runCompose(mode), readNote: () => setMenu("note") }}
            trail={trail}
            coding={coding}
          />
        )}
        {view === "card" && selected && !card && <div className="empty">Computing the card…</div>}
        {view === "desk" && selected && (
          <div className="sheet-head">
            <h1>{selected.name}</h1>
            <span className="since">
              since {selected.onset_date} · {tl?.series.length ?? 0} monitored series · {tl?.medications.length ?? 0} medications on board
            </span>
          </div>
        )}
        {view === "desk" && selected && <Brief brief={brief} highlight={highlight} onHover={hover} onAskClaude={() => askBrief(mode)} busy={!!busy} mode={mode} />}
        {view === "desk" && (tl && tl.series.length > 0 ? (
          <Timeline data={tl} highlight={highlight} onHover={(id) => hover(id ? [id] : null)} onOpenNote={openChartNote} />
        ) : (
          <div className="empty">{selected ? `No monitored lab series is linked to ${selected.name} in this window.` : "Pick a problem."}</div>
        ))}
        {view === "desk" && selected && <Trail entries={trail} labels={labels} highlight={highlight} onHover={hover} />}
        {view === "desk" && selected && coding && coding.signed_today > 0 && <Coding coding={coding} highlight={highlight} onHover={hover} />}
      </main>

      {view === "desk" && <Inbox queues={queues} problemId={problem} focusIds={focusIds} chartMedIds={new Set((tl?.medications ?? []).map((m) => m.id))} chartInsights={summary.insights} chartDocuments={summary.documents ?? []} labels={labels} highlight={highlight} onHover={hover} onReview={review} onReadDocument={setReadingDoc} busy={busy} />}

      {toast && (
        <div className="toast" role="status">
          <span>{toast.text}</span>
          <button onClick={undo}>Undo</button>
          <span className="bar" />
        </div>
      )}
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
              {reading.has_queue ? " · already read (reading again replaces what is waiting)" : ""}
            </div>
            <pre>{reading.text.trim()}</pre>
            <div className="row">
              <span className="spacer" />
              <button className="btn ghost" onClick={() => setReading(null)}>
                Close
              </button>
              {reading.file && (
                <>
                  <button className="btn primary" disabled={mode === "replay" && !reading.has_replay} title={mode === "replay" && !reading.has_replay ? "no saved reading yet; switch Claude to live" : ""} onClick={() => runExtract(reading, mode)}>
                    {mode === "live" ? "Read with Claude" : "Read (saved)"}
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
