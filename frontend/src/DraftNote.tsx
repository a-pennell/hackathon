import { useState } from "react";
import { labelOf } from "./labels";
import type { DocSection, Document, Problem, QueueBatch } from "./types";

type Props = {
  batch: QueueBatch;
  labels: Record<string, string>;
  problems: Problem[];
  busy: string | null;
  onSign: (sections: { heading: string; text: string }[]) => void;
  onRecompile: () => void;
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
export default function DraftNote({ batch, labels, problems, busy, onSign, onRecompile, onOpenProblem, onOpenNote, onHover }: Props) {
  const doc = (batch.proposed.documents ?? [])[0] as Document | undefined;
  const [text, setText] = useState<Record<number, string>>({});
  if (!doc) return <div className="empty">No draft was compiled for this visit.</div>;
  const signed = doc.status === "accepted";
  const name = (id: string) => labelOf(labels, id);
  const sections = doc.sections as DocSection[];
  const valueOf = (i: number) => text[i] ?? sections[i].text;
  const dirty = sections.some((s, i) => (text[i] ?? s.text) !== s.text);
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
            {!signed && <button className="btn ghost" disabled={!!busy} onClick={onRecompile} title="Throw this draft away and compile it again from the record">Recompile</button>}
            {!signed && <button className="btn primary" disabled={!!busy} onClick={() => onSign(sections.map((s, i) => ({ heading: s.heading, text: valueOf(i) })))}>Sign the visit note{dirty ? " · with your edits" : ""}</button>}
          </div>
        </header>

        {sections.map((s, i) => (
          <section key={i} className={`dsec ${s.source ?? "compiled"} ${s.edited ? "edited" : ""}`} onMouseEnter={() => onHover(s.cites)} onMouseLeave={() => onHover(null)}>
            <div className="dsec-head">
              <h2>{s.heading}</h2>
              <span className={`tag ${s.source === "transcript" ? "soft" : "pencil"}`}>{s.source === "transcript" ? "transcript · verbatim" : s.edited ? "compiled · edited by you" : "compiled from the record"}</span>
              {s.problem_id && <button className="link small" onClick={() => onOpenProblem(s.problem_id!)}>open the card</button>}
            </div>
            {signed ? (
              <p className="dtext serif">{s.text}</p>
            ) : (
              <textarea className="dtext serif" value={valueOf(i)} rows={Math.max(2, Math.ceil(valueOf(i).length / 95) + (valueOf(i).match(/\n/g)?.length ?? 0))}
                onChange={(e) => setText((t) => ({ ...t, [i]: e.target.value }))} aria-label={s.heading} />
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
