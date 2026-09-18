import { useCallback, useEffect, useRef, useState } from "react";
import { api, setAsOf } from "./api";
import type { Listing } from "./v2types";
import Problems from "./Problems";
import Problem from "./Problem";
import Review from "./Review";
import Note from "./Note";
import Visit from "./Visit";

const PID = new URLSearchParams(location.search).get("patient") ?? "pt_002";
const age = (dob: string) => { const d = new Date(dob), n = new Date(); return n.getFullYear() - d.getFullYear() - (n < new Date(n.getFullYear(), d.getMonth(), d.getDate()) ? 1 : 0); };
const useHash = () => { const [h, setH] = useState(location.hash || "#/visit"); useEffect(() => { const f = () => setH(location.hash || "#/visit"); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []); return h; };

/** v2: three views. The gate (which problems are in good standing), one problem as seven answers, and the visit note
 *  assembled from what was decided. One button in the header names the next thing owed. */
export default function App() {
  const hash = useHash();
  const asOfRef = useRef<string | null>(null);
  const [listing, setListing] = useState<Listing | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [asOf, setAsOfState] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      let l = await api.problems(PID);
      // A follow-up already on the chart means the clock was advanced: read the chart as of that date.
      const want = l.followup?.applied ? l.followup.as_of : null;
      if (want !== asOfRef.current) { asOfRef.current = want; setAsOf(want); setAsOfState(want); l = await api.problems(PID); }
      setListing(l); setTick((t) => t + 1);
    } catch (e) { setError(String((e as Error).message)); }
  }, []);
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
      case "read": case "review": case "sign": case "draft": case "sign-draft": return go("#/visit");
      case "sign": return note && run("sign", () => api.signNote(PID, note.id), "Review closed; what was left is accepted");
      case "draft": case "sign-draft": return go("#/note");
      default: return;
    }
  };
  if (!listing) return <div className="v2"><div className="page">{error ?? "Opening the chart…"}</div></div>;
  const pt = listing.patient;
  const view = hash.startsWith("#/problem/") ? "problem" : hash.startsWith("#/review") ? "review" : hash.startsWith("#/note") ? "note" : hash.startsWith("#/visit") ? "visit" : "problems";
  const ctx = { pid: PID, listing, busy, run, go, refreshKey: tick };
  return (
    <div className="v2">
      <header className="top">
        <span className="who">{pt.name}<small>{age(pt.dob)} · {pt.sex === "F" ? "she/her" : "he/him"}</small></span>
        <span className="chips">
          {listing.counts.off_course > 0 && <span className="tag warn">{listing.counts.off_course} off course</span>}
          {listing.counts.watch > 0 && <span className="tag pend">{listing.counts.watch} to watch</span>}
          {listing.counts.good > 0 && <span className="tag ok">{listing.counts.good} in good standing</span>}
          {listing.unattested > 0 && <span className="tag soft" title="accepted at this visit, waiting for the visit note's signature">{listing.unattested} to attest</span>}
          {asOf && <span className="tag ep" title={listing.followup?.label}>as of {asOf}</span>}
        </span>
        <nav>
          <a href="#/visit" className={view === "visit" ? "on" : ""}>Visit</a>
          <a href="#/" className={view === "problems" ? "on" : ""}>Problems</a>
          <a href="#/note" className={view === "note" ? "on" : ""}>Visit note</a>
        </nav>
        <span className="spacer" />
        {busy ? <span className="busy-inline">Working…</span> : next && <button className={`btn cta ${next.kind === "done" ? "quiet" : "primary"}`} title={next.kind === "read" ? "the dictation plays and the reading lands on the problems it touches" : next.kind === "done" ? next.hint : "the visit is waiting for its one signature; it is on the visit screen, with what it attests beside it"} onClick={doNext} disabled={next.kind === "done"}>{next.kind === "read" ? "Start the visit" : next.kind === "done" ? next.label : "Finish the visit · sign"}</button>}
        {listing.followup && !listing.followup.applied && next?.kind === "done" && <button className="btn small" disabled={!!busy} title={listing.followup.label} onClick={() => run("advance", () => api.advance(PID), "Two weeks on: the home log and the BMP have landed").then(() => go("#/"))}>Two weeks later</button>}
        <button className="btn small ghost" disabled={!!busy} onClick={() => run("reset", () => api.reset(PID), "Chart reset").then(() => { try { sessionStorage.removeItem(`visit:${PID}`); } catch { /* ignore */ } go("#/visit"); })} title="Restore the chart to its server-start state">Reset demo</button>
      </header>
      <main className="page">
        {error && <div className="err2">{error}</div>}
        {view === "visit" && <Visit {...ctx} />}
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
