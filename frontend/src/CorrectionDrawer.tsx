import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Correction, CorrectionAction, CorrectionItem, CorrectionPreview } from "./types";

const actionLabels: Record<CorrectionAction, string> = {
  entered_in_error: "Mark entered in error", stop: "Stop medication", resolve: "Resolve problem",
  cancel: "Cancel order", end_plan: "End plan", amend: "Amend note",
};
const effectLabels: Record<CorrectionAction, string> = {
  entered_in_error: "This entry will leave the current chart. Its original content and signature will remain in correction history.",
  stop: "The current medication segment will end on the effective date. Earlier treatment remains in the record.",
  resolve: "This problem will move to resolved. Its history, plans, and orders remain on file.",
  cancel: "This order will leave the active order list. Its signed history remains on file. This prototype does not send a cancellation to a pharmacy or laboratory.",
  end_plan: "This plan will leave the current plan list. Any associated order remains active until separately canceled.",
  amend: "A signed amendment will appear with the original note.",
};
const localDay = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

export default function CorrectionDrawer({ pid, initialId, onClose, onSaved }: { pid: string; initialId?: string; onClose: () => void; onSaved: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [items, setItems] = useState<CorrectionItem[]>([]);
  const [history, setHistory] = useState<Correction[]>([]);
  const [selected, setSelected] = useState(initialId ?? "");
  const [action, setAction] = useState<CorrectionAction>("entered_in_error");
  const [reason, setReason] = useState("");
  const [text, setText] = useState("");
  const [effective, setEffective] = useState(localDay);
  const [search, setSearch] = useState("");
  const [impact, setImpact] = useState<CorrectionPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [historyView, setHistoryView] = useState(false);
  const item = items.find((i) => i.id === selected);

  useEffect(() => {
    const el = dialog.current!;
    const previous = document.activeElement as HTMLElement | null;
    el.showModal();
    return () => { el.close(); previous?.focus(); };
  }, []);
  useEffect(() => {
    let live = true;
    api.corrections(pid).then((data) => {
      if (!live) return;
      setItems(data.items); setHistory(data.history);
      const found = data.items.find((i) => i.id === initialId);
      if (found) setAction(found.actions[0]);
    }).catch((e) => live && setError(e.message)).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [pid, initialId]);
  const invalidate = () => { setImpact(null); setError(""); setSaved(""); };
  const choose = (id: string) => {
    setSelected(id); setAction(items.find((i) => i.id === id)?.actions[0] ?? "entered_in_error");
    setReason(""); setText(""); invalidate();
  };
  const preview = async () => {
    setBusy(true); setError("");
    try { setImpact(await api.previewCorrection(pid, selected, action)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const sign = async () => {
    if (!impact) return;
    setBusy(true); setError("");
    try {
      await api.correct(pid, { item_id: selected, action, reason, text, effective, expected_revision: impact.revision });
      setImpact(null); setSelected(""); setReason(""); setText("");
      setSaved(action === "amend" ? "Amendment signed." : "Correction signed.");
      const data = await api.corrections(pid); setItems(data.items); setHistory(data.history);
      await onSaved();
    } catch (e) { setError((e as Error).message); setImpact(null); }
    finally { setBusy(false); }
  };
  const original = item?.item;
  const review = original?.review as { by?: string; at?: string } | undefined;
  const noteSections = original?.sections as { heading: string; text: string }[] | undefined;
  return <dialog ref={dialog} className="correction-drawer" aria-labelledby="correction-title" onCancel={(e) => { e.preventDefault(); if (!busy) onClose(); }}>
    <header className="correction-head"><h2 id="correction-title">Correct chart</h2><button className="btn" onClick={onClose} disabled={busy}>Close</button></header>
    <div className="correction-tabs" role="tablist" aria-label="Correction views" onKeyDown={(e) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const next = e.key === "Home" ? false : e.key === "End" ? true : !historyView;
      setHistoryView(next);
      (e.currentTarget.children[next ? 1 : 0] as HTMLButtonElement).focus();
    }}>
      <button id="correction-new-tab" role="tab" aria-controls="correction-panel" tabIndex={historyView ? -1 : 0} aria-selected={!historyView} onClick={() => setHistoryView(false)}>New correction</button>
      <button id="correction-history-tab" role="tab" aria-controls="correction-panel" tabIndex={historyView ? 0 : -1} aria-selected={historyView} onClick={() => setHistoryView(true)}>History ({history.length})</button>
    </div>
    <div className="correction-body" id="correction-panel" role="tabpanel" aria-labelledby={historyView ? "correction-history-tab" : "correction-new-tab"}>
      {error && <div className="err" role="alert">{error}</div>}
      {saved && <p className="correction-success" role="status">{saved}</p>}
      {loading ? <p role="status">Loading chart entries...</p> : historyView ? <>
        {!history.length && <p className="quiet">No signed corrections.</p>}
        {[...history].reverse().map((c) => <section key={c.id} className="correction-history">
          <h3>{actionLabels[c.action]}: {c.label}</h3>
          <p className="stamp">{c.by} · {c.at.slice(0, 16).replace("T", " ")} · effective {c.effective}</p>
          <p>{c.reason}</p>{c.text && <p className="amendment-text">{c.text}</p>}
          {c.related.length > 0 && <p className="meta">Related entries retained: {c.related.map((r) => r.label).join("; ")}</p>}
          <details className="system-details"><summary>Original entry and signed change</summary><pre>{JSON.stringify({ original: c.before, corrected: c.after }, null, 2)}</pre></details>
        </section>)}
      </> : <>
        <label className="correction-field">Find an entry<input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Medication, problem, note, or plan" /></label>
        <label className="correction-field">Chart entry<select value={selected} onChange={(e) => choose(e.target.value)} disabled={busy}>
          <option value="">Select an entry</option>
          {items.filter((i) => i.id === selected || `${i.kind} ${i.label}`.toLowerCase().includes(search.toLowerCase())).map((i) => <option key={i.id} value={i.id}>{i.kind.replace(/_/g, " ")}: {i.label.slice(0, 160)}</option>)}
        </select></label>
        {item && <>
          <section className="correction-original"><h3>{item.label}</h3>
            <p className="stamp">{review?.by ? `Signed by ${review.by} ${review.at?.slice(0, 16).replace("T", " ") ?? ""}` : "Existing chart entry"}</p>
            {noteSections || original?.text ? <details><summary>Original content</summary>{noteSections ? noteSections.map((s, i) => <div key={i}><h4>{s.heading}</h4><p className="amendment-text">{s.text}</p></div>) : <p className="amendment-text">{String(original?.text)}</p>}</details> : null}
          </section>
          <label className="correction-field">Action<select value={action} disabled={busy} onChange={(e) => { setAction(e.target.value as CorrectionAction); invalidate(); }}>
            {item.actions.map((a) => <option key={a} value={a}>{actionLabels[a]}</option>)}
          </select></label>
          <p className="correction-impact">{effectLabels[action]}</p>
          {action === "amend" && <label className="correction-field">Amendment<textarea rows={5} value={text} disabled={busy} onChange={(e) => { setText(e.target.value); invalidate(); }} /></label>}
          <label className="correction-field">Reason<textarea rows={2} value={reason} disabled={busy} onChange={(e) => { setReason(e.target.value); invalidate(); }} /></label>
          {!["entered_in_error", "amend"].includes(action) && <label className="correction-field">Effective date<input type="date" max={localDay()} value={effective} disabled={busy} onChange={(e) => { setEffective(e.target.value); invalidate(); }} /></label>}
          {impact && <section className="correction-preview" aria-label="Correction preview">
            <h3>What changes when you sign</h3>
            <p>{effectLabels[action]}</p>
            {impact.withdrawn.length > 0 && <><h4>Also removed from current reasoning</h4><ul>{impact.withdrawn.map((r) => <li key={r.id}>{r.kind}: {r.label}</li>)}</ul></>}
            {impact.related.length > 0 && <><h4>Retained entries to review separately</h4><ul>{impact.related.map((r) => <li key={r.id}>{r.kind}: {r.label}</li>)}</ul></>}
            {impact.warnings.map((w) => <p key={w}>{w}</p>)}
            {impact.blockers.map((w) => <p key={w} className="err" role="alert">{w}</p>)}
          </section>}
          <footer className="correction-actions">
            {impact ? <button className="btn primary" disabled={busy || impact.blockers.length > 0 || !reason.trim() || (action === "amend" && !text.trim())} onClick={sign}>{busy ? "Signing..." : action === "amend" ? "Sign amendment" : "Sign correction"}</button>
              : <button className="btn primary" disabled={busy || !reason.trim() || (action === "amend" && !text.trim())} onClick={preview}>{busy ? "Checking..." : "Preview correction"}</button>}
          </footer>
        </>}
      </>}
    </div>
  </dialog>;
}
