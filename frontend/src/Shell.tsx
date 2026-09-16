import { useState } from "react";
import type { NextAction } from "./next";
import type { Overview, Patient, PatientSummary } from "./types";

export type Tab = "overview" | "timeline" | "care" | "chart" | "notes";
export type View = Tab | "note" | "problem";

type Props = {
  patients: { id: string; name: string; problems_active: number }[];
  pid: string;
  summary: PatientSummary;
  overview: Overview | null;
  view: View;
  tab: Tab;
  onTab: (t: Tab) => void;
  next: NextAction;
  onNext: () => void;
  busy: string | null;
  mode: "live" | "replay";
  onMode: (m: "live" | "replay") => void;
  onReset: () => void;
  onAbout: () => void;
  pendingCount: number;
  onPending: () => void;
  crumb?: { back: string; onBack: () => void; title: string } | null;
};

function age(dob: string) {
  const d = new Date(dob), n = new Date();
  return n.getFullYear() - d.getFullYear() - (n < new Date(n.getFullYear(), d.getMonth(), d.getDate()) ? 1 : 0);
}
const dmy = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })}`;
};
const hm = (iso: string) => iso.slice(11, 16);
const dmyFull = (iso: string) => { const d = new Date(iso.slice(0, 10) + "T00:00:00"); return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`; };
const BUSY: Record<string, string> = { extract: "Reading the note…", sign: "Signing the note…", reason: "Looking at what changed…", compose: "Drafting the referral…", orders: "Drafting orders…", reset: "Resetting…" };

export default function Shell({ patients, pid, summary, overview, view, tab, onTab, next, onNext, busy, mode, onMode, onReset, onAbout, pendingCount, onPending, crumb }: Props) {
  const [demo, setDemo] = useState(false);
  const pt: Patient = summary.patient;
  const enc = overview?.here_for.encounter ?? null;
  const note = overview?.here_for.note ?? null;
  const visit = enc ? `${enc.type.replace("encounter for ", "")} · ${dmy(enc.time)}` : "no visit today";
  const flags = pendingCount;

  return (
    <div className="shell" onClick={() => demo && setDemo(false)}>
      <div className="session-tabs" role="tablist" aria-label="Open patients">
        {patients.map((p) => {
          const on = p.id === pid;
          const openEnc = on && enc;
          return (
            <a key={p.id} className={`session-tab ${on ? "on" : ""}`} role="tab" aria-selected={on} href={`?patient=${p.id}`}>
              {p.name}
              {openEnc && <><span className="dot" /> <span className="enc">Active encounter</span> <span className="t">({hm(enc!.time)})</span></>}
            </a>
          );
        })}
      </div>

      <div className="practice-bar">
        <span className="practice-name">Riverside Family Medicine</span>
        <span className="practice-addr">210 Elm Street, Somerville</span>
        <span className="spacer" />
        <div className="search" role="search" aria-disabled="true" title="Patient search is not part of this demo">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><line x1="16.5" y1="16.5" x2="21" y2="21" /></svg>
          Find patient by name, DOB, MRN
        </div>
        <div className="rel" onClick={(e) => e.stopPropagation()}>
          <button className="btn small ghost" onClick={() => setDemo((v) => !v)} aria-haspopup="menu" aria-expanded={demo}>Demo ▾</button>
          {demo && (
            <div className="menu demo-menu" role="menu">
              <div className="menu-row">
                <span>Claude</span>
                <span className="seg">
                  <button className={mode === "live" ? "on" : ""} onClick={() => onMode("live")}>live</button>
                  <button className={mode === "replay" ? "on" : ""} onClick={() => onMode("replay")}>saved</button>
                </span>
              </div>
              <button className="menu-item" onClick={() => { setDemo(false); onAbout(); }}>About this record…</button>
              <button className="menu-item danger" disabled={!!busy} onClick={() => { setDemo(false); onReset(); }}>Reset demo</button>
            </div>
          )}
        </div>
      </div>

      <div className="pt-header">
        <span className="pt-name">{pt.name}</span>
        <span className="hchip">{pt.sex === "F" ? "she/her" : pt.sex === "M" ? "he/him" : "they/them"}</span>
        <span className="hchip">{age(pt.dob)} · <span className="soft">DOB {dmyFull(pt.dob)}</span></span>
        <span className="hchip">{pt.id.replace("pt_", "MRN 00")}</span>
        <span className="hchip allergy">No allergies on file</span>
        {flags > 0 ? <button className="hchip flags" onClick={onPending} title="Proposals waiting for a signature">⚑ {flags} waiting</button> : <span className="hchip soft">⚑ nothing waiting</span>}
        <span className="spacer" />
        <button className={`hchip visit ${note && !note.has_queue ? "note-waiting" : ""}`} onClick={() => onTab("notes")} title={(note ? (note.status === "signed" ? "the note is signed" : note.has_queue ? "the note has been read, not yet signed" : "the note has not been read") : "no note today") + " · opens the notes on file"}>
          {visit}{note ? (note.status === "signed" ? " · note signed" : note.has_queue ? " · note in progress" : " · note waiting") : ""}
        </button>
        <span className="next">
          {busy ? (
            <span className="busy-inline">{BUSY[busy] ?? "Saving…"}</span>
          ) : (
            <button className={`btn cta ${next.kind === "done" ? "quiet" : "primary"}`} onClick={onNext} title={next.hint}>
              {next.label}
            </button>
          )}
        </span>
      </div>

      <div className="pt-tabs" role="tablist" aria-label="Patient sections">
        {(["overview", "timeline", "care", "chart", "notes"] as Tab[]).map((t) => (
          <button key={t} className="pt-tab" role="tab" aria-selected={view === t || (view === "problem" && t === "care") || (view === "note" && t === "notes")} onClick={() => onTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
        {crumb && (
          <span className="crumbs">
            <button className="crumb" onClick={crumb.onBack}>← {crumb.back}</button>
            <span className="sep">›</span>
            <span className="here">{crumb.title}</span>
          </span>
        )}
      </div>
    </div>
  );
}
