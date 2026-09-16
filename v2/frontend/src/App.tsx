import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Listing } from "./v2types";
import Problems from "./Problems";
import Problem from "./Problem";
import Review from "./Review";
import Note from "./Note";

const PID = new URLSearchParams(location.search).get("patient") ?? "pt_002";
const age = (dob: string) => { const d = new Date(dob), n = new Date(); return n.getFullYear() - d.getFullYear() - (n < new Date(n.getFullYear(), d.getMonth(), d.getDate()) ? 1 : 0); };
const useHash = () => { const [h, setH] = useState(location.hash || "#/"); useEffect(() => { const f = () => setH(location.hash || "#/"); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []); return h; };

/** v2: three views. The gate (which problems are in good standing), one problem as seven answers, and the visit note
 *  assembled from what was decided. One button in the header names the next thing owed. */
export default function App() {
  const hash = useHash();
  const [listing, setListing] = useState<Listing | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(async () => { try { setListing(await api.problems(PID)); setTick((t) => t + 1); } catch (e) { setError(String((e as Error).message)); } }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(null), 3500); return () => clearTimeout(t); } }, [toast]);
  const run = async (what: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(what); setError(null);
    try { await fn(); await refresh(); if (done) setToast(done); } catch (e) { setError(String((e as Error).message)); } finally { setBusy(null); }
  };
  const go = (h: string) => { location.hash = h; scrollTo(0, 0); };
  const next = listing?.next_action;
  const doNext = () => {
    if (!next || !listing) return;
    const note = listing.here_for.note;
    switch (next.kind) {
      case "read": return note && run("read", () => api.readNote(PID, note.file), "The note was read; nothing has touched the chart yet").then(() => go("#/review"));
      case "review": return go("#/review");
      case "sign": return note && run("sign", () => api.signNote(PID, note.id), "Note signed; what it proposed is on the record");
      case "draft": case "sign-draft": return go("#/note");
      default: return;
    }
  };
  if (!listing) return <div className="v2"><div className="page">{error ?? "Opening the chart…"}</div></div>;
  const pt = listing.patient;
  const view = hash.startsWith("#/problem/") ? "problem" : hash.startsWith("#/review") ? "review" : hash.startsWith("#/note") ? "note" : "problems";
  const ctx = { pid: PID, listing, busy, run, go, refreshKey: tick };
  return (
    <div className="v2">
      <header className="top">
        <span className="who">{pt.name}<small>{age(pt.dob)} · {pt.sex === "F" ? "she/her" : "he/him"} · {listing.counts.off_course} off course · {listing.counts.watch} to watch · {listing.counts.good} in good standing</small></span>
        <nav>
          <a href="#/" className={view === "problems" ? "on" : ""}>Problems</a>
          <a href="#/note" className={view === "note" ? "on" : ""}>Visit note</a>
        </nav>
        <span className="spacer" />
        {busy ? <span className="busy-inline">Working…</span> : next && <button className={`btn cta ${next.kind === "done" ? "quiet" : "primary"}`} title={next.hint} onClick={doNext} disabled={next.kind === "done"}>{next.label}</button>}
        <button className="btn small ghost" disabled={!!busy} onClick={() => run("reset", () => api.reset(PID), "Chart reset").then(() => go("#/"))} title="Restore the chart to its server-start state">Reset demo</button>
      </header>
      <main className="page">
        {error && <div className="err2">{error}</div>}
        {view === "problems" && <Problems {...ctx} />}
        {view === "problem" && <Problem {...ctx} problemId={hash.slice("#/problem/".length)} />}
        {view === "review" && <Review {...ctx} />}
        {view === "note" && <Note {...ctx} />}
      </main>
      {toast && <div className="toast2" role="status">{toast}</div>}
    </div>
  );
}

export type Ctx = { pid: string; listing: Listing; busy: string | null; run: (what: string, fn: () => Promise<unknown>, done?: string) => Promise<void>; go: (h: string) => void; refreshKey: number };
