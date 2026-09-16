import { useState } from "react";
import { api } from "./api";
import Amendments from "./Amendments";
import { labelOf } from "./labels";
import type { DocSection, Document, Problem, QueueBatch, DraftEdit, DraftUpdates, DraftResolution } from "./types";

type Section = DocSection & { collapsed?: boolean };

type Props = {
  batch: QueueBatch;
  labels: Record<string, string>;
  problems: Problem[];
  busy: string | null;
  onSign: (sections: DraftEdit[]) => void;
  onCorrect: (id: string) => void;
  texts: Record<string, string>;
  onTexts: (texts: Record<string, string>) => void;
  onDraftChanged: (batch: QueueBatch) => Promise<void>;
  onOpenProblem: (id: string) => void;
  onOpenNote: (id: string) => void;
  onHover: (ids: string[] | null) => void;
};

const dmy = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`;
};

/** The visit note as a composition: the transcript verbatim, then sections compiled from what the clinician did at this
 *  visit, every sentence citing the record. The clinician edits the prose and signs. Nothing here reaches the chart until
 *  the signature; the citations survive the edit. */
export default function DraftNote({ batch, texts, onTexts, onDraftChanged, labels, problems, busy, onSign, onCorrect, onOpenProblem, onOpenNote, onHover }: Props) {
  const doc = (batch.proposed.documents ?? [])[0] as Document | undefined;
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [updates, setUpdates] = useState<DraftUpdates | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, DraftResolution>>({});
  if (!doc) return <div className="empty">No draft was compiled for this visit.</div>;
  const signed = doc.status === "accepted";
  const name = (id: string) => labelOf(labels, id);
  const sections = doc.sections as Section[];
  const keyOf = (s: DocSection) => s.key ?? `${s.source ?? "compiled"}:${s.problem_id ?? "visit"}:${s.problem_id ? s.heading.split(" · ")[0] : s.heading}`;
  const valueOf = (i: number) => texts[keyOf(sections[i])] ?? sections[i].text;
  const dirty = sections.some((s, i) => valueOf(i) !== s.text);
  const edit = (s: DocSection, text: string) => { onTexts({ ...texts, [keyOf(s)]: text }); setNotice(""); };
  const submitted = (): DraftEdit[] => sections.map((s, i) => ({ key: keyOf(s), heading: s.heading, text: valueOf(i) }));
  const disabled = !!busy || working;
  const pending = batch.updates_count ?? 0;
  const unresolved = updates?.changes.some((c) => c.conflict && !resolutions[c.key]);
  const operate = async (fn: () => Promise<void>) => {
    setWorking(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setWorking(false); }
  };
  const checkUpdates = () => operate(async () => {
    const result = await api.draftUpdates(batch.patient_id, doc.encounter_id!, submitted());
    setUpdates(result.changes.length ? result : null); setResolutions({});
    if (!result.changes.length) setNotice("The draft is up to date with the chart.");
  });
  const save = () => operate(async () => {
    const result = await api.saveDraft(batch.patient_id, doc.encounter_id!, submitted(), batch.draft_revision!);
    onTexts({}); await onDraftChanged(result); setNotice("Draft saved.");
  });
  const incorporate = () => operate(async () => {
    if (!updates) return;
    const result = await api.incorporateDraft(batch.patient_id, doc.encounter_id!, submitted(), updates.revision, resolutions);
    onTexts({}); setUpdates(null); setResolutions({}); await onDraftChanged(result); setNotice("Chart updates reviewed. Draft saved.");
  });
  const events = new Set(doc.provenance.evidence ?? []).size;

  return (
    <div className="cardpage">
      <article className="draft">
        <header className="draft-head">
          <div>
            <span className="eyebrow">{signed ? "Visit note · signed" : "Visit note · draft"}</span>
            <h1>{doc.title}</h1>
            <p className="stamp">
              {signed ? `signed by ${doc.review?.by ?? ""} · ${doc.review?.at ? dmy(doc.review.at) : ""}` : `compiled ${dmy(doc.created_at)} by ${doc.provenance.model} from ${events} record events at this visit`}
              {doc.problems_addressed && doc.problems_addressed.length > 0 && (
                <> · addresses {doc.problems_addressed.map((pid, i) => <span key={pid}>{i > 0 ? ", " : ""}<button className="link" onClick={() => onOpenProblem(pid)}>{problems.find((p) => p.id === pid)?.name ?? name(pid)}</button></span>)}</>
              )}
            </p>
          </div>
          <div className="actions">
            {signed && <button className="btn" onClick={() => onCorrect(doc.id)}>Amend note</button>}
            {!signed && <button className="btn ghost" disabled={disabled || !!updates} onClick={checkUpdates}>Check for updates</button>}
            {!signed && <button className="btn" disabled={disabled || !dirty || !!updates} onClick={save}>Save draft</button>}
            {!signed && <button className="btn primary" disabled={disabled || pending > 0 || !!updates} onClick={() => onSign(submitted())}>Sign the visit note{dirty ? " · with your edits" : ""}</button>}
          </div>
        </header>
        <Amendments items={doc.amendments} />
        {error && <div className="err" role="alert">{error}</div>}
        {notice && <p className="draft-notice" role="status">{notice}</p>}
        {!signed && pending > 0 && !updates && <div className="draft-update-banner" role="status">
          <span><b>Updates available</b> · {pending} section{pending === 1 ? "" : "s"} changed in the chart</span>
          <button className="btn" disabled={disabled} onClick={checkUpdates}>Review updates</button>
        </div>}
        {updates && <section className="draft-updates" aria-label="Review chart updates">
          <h2>Review chart updates</h2>
          {updates.changes.map((c) => <section key={c.key} className="draft-section-update">
            <h3>{c.heading} <span className="tag soft">{c.kind}</span></h3>
            {c.conflict && <><p className="draft-conflict">Your wording and the chart both changed.</p><h4>Your current text</h4><p className="draft-update-text">{c.current?.text || "Removed from the note"}</p></>}
            <h4>Updated chart text</h4><p className="draft-update-text">{c.incoming?.text ?? "This section is no longer supported by the current chart."}</p>
            {c.conflict && <>
              <label className="draft-resolution">Include in the draft<select aria-label={`Resolve ${c.heading}`} value={resolutions[c.key]?.choice ?? ""} disabled={disabled} onChange={(e) => setResolutions((old) => ({ ...old, [c.key]: { choice: e.target.value as DraftResolution["choice"], text: c.current?.text ?? "" } }))}>
                <option value="" disabled>Choose a resolution</option>
                <option value="keep">Keep my text</option><option value="update">{c.incoming ? "Use updated chart text" : "Remove this section"}</option><option value="edit">Edit combined text</option>
              </select></label>
              {resolutions[c.key]?.choice === "edit" && <textarea className="dtext" aria-label={`Combined text for ${c.heading}`} rows={5} disabled={disabled} value={resolutions[c.key].text ?? ""} onChange={(e) => setResolutions((old) => ({ ...old, [c.key]: { choice: "edit", text: e.target.value } }))} />}
            </>}
          </section>)}
          <div className="draft-update-actions"><button className="btn" disabled={disabled} onClick={() => setUpdates(null)}>Back to draft</button><button className="btn primary" disabled={disabled || unresolved} onClick={incorporate}>Apply reviewed updates</button></div>
        </section>}
        {!signed && dirty && <p className="note-edit-notice" role="status">These edits change the note only. Chart entries, medications, and orders remain unchanged.</p>}

        {sections.map((s, i) => s.collapsed ? (
          <details key={keyOf(s)} className={`dsec folded ${s.source ?? "compiled"}`}>
            <summary><span className="eyebrow">{s.heading}</span> <span className="tag soft">folded · the sections below restate it from the record</span></summary>
            <p className="dtext serif">{s.text}</p>
            <div className="cites">{s.cites.map((id) => <button key={id} className="cite" title={id} onClick={() => onOpenNote(id)}>{name(id)}</button>)}</div>
          </details>
        ) : (
          <section key={keyOf(s)} className={`dsec ${s.source ?? "compiled"} ${s.edited ? "edited" : ""}`} onMouseEnter={() => onHover(s.cites)} onMouseLeave={() => onHover(null)}>
            <div className="dsec-head">
              <h2>{s.heading}</h2>
              <span className={`tag ${s.source === "transcript" ? "soft" : "pencil"}`}>{s.source === "transcript" ? "transcript · verbatim" : s.edited ? "compiled · edited by you" : "compiled from the record"}</span>
              {s.problem_id && <button className="link small" onClick={() => onOpenProblem(s.problem_id!)}>open the card</button>}
              {!signed && valueOf(i) && <button className="link small" disabled={disabled || !!updates} onClick={() => edit(s, "")}>Remove from note</button>}
              {!signed && !valueOf(i) && s.text && <button className="link small" disabled={disabled || !!updates} onClick={() => edit(s, s.text)}>Restore text</button>}
            </div>
            {signed ? (
              <p className="dtext serif">{s.text}</p>
            ) : (
              <textarea className="dtext serif" value={valueOf(i)} rows={Math.max(2, Math.ceil(valueOf(i).length / 95) + (valueOf(i).match(/\n/g)?.length ?? 0))}
                disabled={disabled || !!updates} onChange={(e) => edit(s, e.target.value)} aria-label={s.heading} />
            )}
            <div className="cites">
              {s.cites.map((id) => (
                <button key={id} className="cite" title={id} onClick={() => (id.startsWith("prob_") ? onOpenProblem(id) : id.startsWith("note_") ? onOpenNote(id) : undefined)}>{name(id)}</button>
              ))}
            </div>
          </section>
        ))}

        <details className="explain about">
          <summary>About this screen</summary>
          <ul>
            <li>The chart writes the note. Every action taken at this visit is already a dated, signed event with the visit stamped on it; the draft is those events rendered into sections, each sentence carrying the ids it came from.</li>
            <li>The transcript is the first section, verbatim, and is never rewritten. The compiled sections are yours to edit; the citations stay with the section either way.</li>
            <li>Signing puts the note on the record as a document of the visit, listed under Notes and on the Timeline. Nothing here reaches the chart before that.</li>
          </ul>
        </details>
      </article>
    </div>
  );
}
