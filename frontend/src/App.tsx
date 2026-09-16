import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import Card from "./Card";
import Overview from "./Overview";
import NoteView from "./NoteView";
import Shell, { type Tab, type View } from "./Shell";
import About from "./About";
import { ChartTab, TimelineTab } from "./ChartTab";
import CareTab from "./CareTab";
import { nextAction } from "./next";
import type { Card as CardT, CareData, ChartData, Coding as CodingT, Document, NoteFile, Overview as OverviewT, PatientRow, PatientSummary, QueueBatch, RecordEvent, Timeline as TL, TrailEntry } from "./types";

const PID = new URLSearchParams(window.location.search).get("patient") ?? "pt_002";
const WINDOWS = ["3m", "6m", "1y", "2y", "5y", "all"];

export default function App() {
  const [patients, setPatients] = useState<PatientRow[]>([]);
  const [summary, setSummary] = useState<PatientSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [window_, setWindow] = useState("1y");
  const [tl, setTl] = useState<TL | null>(null);
  const [card, setCard] = useState<CardT | null>(null);
  const [overview, setOverview] = useState<OverviewT | null>(null);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [care, setCare] = useState<CareData | null>(null);
  const [view, setView] = useState<View>("overview");
  const [tab, setTab] = useState<Tab>("overview");
  const [noteId, setNoteId] = useState<string | null>(null);
  const [record, setRecord] = useState<RecordEvent[]>([]);
  const [patientRecord, setPatientRecord] = useState<RecordEvent[]>([]);
  const [problemRecord, setProblemRecord] = useState<RecordEvent[]>([]);
  const [trail, setTrail] = useState<TrailEntry[]>([]);
  const [coding, setCoding] = useState<CodingT | null>(null);
  const [queues, setQueues] = useState<QueueBatch[]>([]);
  const [queueLabels, setQueueLabels] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<NoteFile[]>([]);
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [about, setAbout] = useState(false);
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
    const [s, q, n, o, ps] = await Promise.all([api.patient(PID), api.queue(PID), api.notes(), api.overview(PID).catch(() => null), api.patients().catch(() => [])]);
    setSummary(s);
    setOverview(o);
    setQueues(q.batches);
    setQueueLabels(q.labels);
    setNotes(n.filter((x) => x.patient_id === PID));
    setPatients(ps);
    setProblem((p) => p ?? o?.concerns[0]?.id ?? s.problems.find((x) => (x.monitored_codes?.length ?? 0) > 0)?.id ?? null);
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message ?? e)));
  }, [refresh]);

  useEffect(() => {
    if (!problem) return;
    let live = true;
    api.timeline(PID, problem, window_).then((d) => live && setTl(d)).catch((e) => setError(String(e.message ?? e)));
    api.card(PID, problem, window_).then((c) => live && setCard(c)).catch(() => live && setCard(null));
    api.trail(PID, problem).then((t) => live && setTrail(t)).catch(() => live && setTrail([]));
    api.coding(PID).then((c) => live && setCoding(c)).catch(() => live && setCoding(null));
    api.record(PID, undefined, problem).then((r) => live && setProblemRecord(r)).catch(() => live && setProblemRecord([]));
    return () => {
      live = false;
    };
  }, [problem, window_, queues, summary]);

  useEffect(() => {
    let live = true;
    if (view === "chart") api.chart(PID).then((c) => live && setChart(c)).catch(() => live && setChart(null));
    if (view === "care") api.care(PID).then((c) => live && setCare(c)).catch(() => live && setCare(null));
    if (view === "timeline") {
      api.chart(PID).then((c) => live && setChart(c)).catch(() => live && setChart(null));
      api.record(PID).then((r) => live && setPatientRecord(r)).catch(() => live && setPatientRecord([]));
    }
    return () => {
      live = false;
    };
  }, [view, queues, summary]);

  useEffect(() => {
    if (!noteId) return;
    let live = true;
    api.record(PID, noteId).then((r) => live && setRecord(r)).catch(() => live && setRecord([]));
    return () => {
      live = false;
    };
  }, [noteId, queues, summary]);

  // id -> human label, for chips and link rows
  const labels = useMemo(() => {
    const m: Record<string, string> = { ...queueLabels };
    if (summary) for (const p of summary.problems) m[p.id] = p.name;
    if (summary) for (const pl of summary.plans ?? []) m[pl.id] = `plan: ${pl.text}`;
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
      for (const pl of b.proposed.plans ?? []) m[pl.id] = `plan: ${pl.text}`;
      if (b.note_id) m[b.note_id] = `note ${b.note_id.replace("note_", "")}`;
    }
    return m;
  }, [summary, tl, queues, queueLabels]);

  const pendingCount = useMemo(
    () => queues.reduce((n, b) => n + Object.values(b.proposed).flat().filter((it) => it && (it as { status: string }).status === "proposed").length + (b.medication_changes ?? []).filter((c) => c.status === "proposed").length, 0),
    [queues],
  );

  const fail = (e: unknown) => setError(String((e as Error).message ?? e));

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
        fail(e);
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
      fail(e);
    } finally {
      setBusy(null);
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

  const goTab = (t: Tab) => {
    setTab(t);
    setView(t);
    window.scrollTo(0, 0);
  };
  const openNote = (id: string) => {
    setNoteId(id);
    setView("note");
    window.scrollTo(0, 0);
  };
  const openProblem = (id: string) => {
    setProblem(id);
    setTab("care");
    setView("problem");
    window.scrollTo(0, 0);
  };

  const run = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(what);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };
  const signNote = () => noteId && run("sign", async () => { const r = await api.signNote(PID, noteId); setToast({ stem: noteId, ids: [], text: `Note signed by ${r.by}` }); });
  const runExtract = (n: NoteFile, m: "live" | "replay") => { setReading(null); if (n.file) return run("extract", () => api.extract(PID, n.file!, m)); };
  const runReason = (pid: string) => run("reason", () => api.reason(PID, pid, mode, window_));
  const runOrders = (pid: string) => run("orders", () => api.orders(PID, pid, mode, window_));
  const runCompose = (pid: string) => run("compose", () => api.compose(PID, pid, "referral", "nephrology", mode, window_));
  const runReset = () => {
    if (!window.confirm("Reset the demo? Unsigns everything and clears the review queue (saved model responses are kept).")) return;
    return run("reset", async () => { await api.reset(PID); setSummary(null); setNoteId(null); goTab("overview"); });
  };

  const next = useMemo(() => nextAction(overview, notes, queues, summary), [overview, notes, queues, summary]);
  const doNext = async () => {
    switch (next.kind) {
      case "read": {
        const n = notes.find((x) => x.id === next.noteId);
        if (!n) return;
        openNote(n.id);
        if (n.file && (mode === "live" || n.has_replay)) await runExtract(n, mode);
        return;
      }
      case "review": return openNote(next.noteId!);
      case "sign": openNote(next.noteId!); return signNote();
      case "reason": openProblem(next.problemId!); return runReason(next.problemId!);
      case "orders": openProblem(next.problemId!); return runOrders(next.problemId!);
      case "sign-insights":
      case "sign-orders": return openProblem(next.problemId!);
      default: return;
    }
  };

  const hover = useCallback((ids: string[] | null) => setHighlight(new Set(ids ?? [])), []);
  const openChartNote = async (id: string) => {
    try {
      setReading(await api.note(PID, id));
    } catch (e) {
      fail(e);
    }
  };

  if (!summary) return <div className="sheet empty">{error ?? "Opening chart…"}</div>;
  const pt = summary.patient;
  const selected = summary.problems.find((p) => p.id === problem);
  const openNoteFile = noteId ? notes.find((x) => x.id === noteId) : null;
  const crumb = view === "problem" && selected ? { back: "Care", onBack: () => goTab("care"), title: selected.name }
    : view === "note" && openNoteFile ? { back: tab[0].toUpperCase() + tab.slice(1), onBack: () => goTab(tab), title: `Note · ${openNoteFile.time.slice(0, 10)}` } : null;

  return (
    <div className="app">
      <Shell
        patients={patients.length ? patients : [{ id: pt.id, name: pt.name, problems_active: summary.problems.length }]}
        pid={PID}
        summary={summary}
        overview={overview}
        view={view}
        tab={tab}
        onTab={goTab}
        next={next}
        onNext={doNext}
        busy={busy}
        mode={mode}
        onMode={setModePersist}
        onReset={runReset}
        onAbout={() => setAbout(true)}
        pendingCount={pendingCount}
        onPending={() => (overview?.here_for.note && queues.some((b) => b.note_id === overview.here_for.note!.id) ? openNote(overview.here_for.note.id) : goTab("care"))}
        crumb={crumb}
      />

      <main className="canvas">
        {error && <div className="err">{error}</div>}
        {view === "overview" && (overview ? (
          <Overview data={overview} problems={summary.problems} highlight={highlight} onHover={hover} onOpen={openProblem} />
        ) : <div className="empty">Computing the overview…</div>)}
        {view === "timeline" && (chart ? <TimelineTab record={patientRecord} encounters={chart.encounters} /> : <div className="empty">Loading the timeline…</div>)}
        {view === "chart" && (chart ? <ChartTab data={chart} onOpenProblem={openProblem} /> : <div className="empty">Loading the chart…</div>)}
        {view === "care" && (care ? <CareTab data={care} highlight={highlight} onHover={hover} onOpen={openProblem} /> : <div className="empty">Loading care…</div>)}
        {view === "problem" && (
          <>
            <div className="sheet">
              {selected && card && card.problem_id === selected.id ? (
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
                  actions={{ reason: () => runReason(selected.id), orders: () => runOrders(selected.id), compose: () => runCompose(selected.id), readNote: () => overview?.here_for.note && openNote(overview.here_for.note.id) }}
                  trail={trail}
                  coding={coding}
                  record={problemRecord}
                />
              ) : <div className="empty">Computing the card…</div>}
            </div>
          </>
        )}
        {view === "note" && (openNoteFile ? (
          <NoteView
            key={openNoteFile.id}
            note={openNoteFile}
            batch={queues.find((b) => b.note_id === openNoteFile.id) ?? null}
            problems={summary.problems}
            labels={labels}
            highlight={highlight}
            onHover={hover}
            onReview={review}
            onRead={(m) => runExtract(openNoteFile, m)}
            onSign={signNote}
            onOpenProblem={openProblem}
            record={record}
            busy={busy}
            mode={mode}
          />
        ) : <div className="empty">That note is not on file.</div>)}
      </main>

      {about && <About onClose={() => setAbout(false)} />}
      {toast && (
        <div className="toast" role="status">
          <span>{toast.text}</span>
          {toast.ids.length > 0 && <button onClick={undo}>Undo</button>}
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
                      <span key={id} className={`chip ${highlight.has(id) ? "hi" : ""}`} title={id} onMouseEnter={() => hover([id])}>
                        {labels[id] ?? id}
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
            <h3>Note {reading.id.replace("note_", "")} · {reading.author}</h3>
            <div className="meta">{reading.time.slice(0, 16).replace("T", " ")} · {reading.file ?? "chart note (imported)"}</div>
            <pre>{reading.text.trim()}</pre>
            <div className="row">
              <span className="spacer" />
              <button className="btn ghost" onClick={() => setReading(null)}>Close</button>
              {reading.file && <button className="btn" onClick={() => { setReading(null); openNote(reading.id); }}>Open the note</button>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
