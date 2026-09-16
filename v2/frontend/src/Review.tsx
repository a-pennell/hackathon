import { useEffect, useState } from "react";
import { api } from "./api";
import type { Ctx } from "./App";
import type { QueueBatch } from "./types";

const KIND_WORD: Record<string, string> = { problems: "problem", observations: "result", medications: "course", links: "link", plans: "plan", insights: "insight", orders: "order" };

/** What the reading proposed, each with the passage it came from. Sign or reject one at a time, or sign what is
 *  left with the note. Nothing reaches the chart before a signature. */
export default function Review({ pid, listing, busy, run, go, refreshKey }: Ctx) {
  const [b, setB] = useState<QueueBatch | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [showRest, setShowRest] = useState(false);
  const note = listing.here_for.note;
  useEffect(() => { if (!note) return; api.queue(pid).then((q) => { setB(q.batches.find((x) => x.note_id === note.id) ?? null); setLabels(q.labels); }).catch(() => setB(null)); }, [pid, note, refreshKey]);
  if (!note) return <div className="lede">No note from this visit.</div>;
  if (!b) return <div className="lede">The note has not been read.</div>;
  const items = (["problems", "medications", "links", "observations", "plans"] as const).flatMap((k) => (b.proposed[k] ?? []).map((it: { id: string; status: string; provenance?: { quote?: string }; name?: string; text?: string; from?: string; to?: string; type?: string; value?: number; unit?: string | null }) => ({ kind: k, it })));
  const local: Record<string, string> = {};
  for (const x of b.proposed.problems ?? []) local[x.id] = x.name;
  for (const x of b.proposed.medications ?? []) local[x.id] = x.name;
  for (const x of b.proposed.observations ?? []) local[x.id] = `${x.name} ${x.value} ${x.unit ?? ""}`.trim();
  if (note) local[note.id] = `${note.author}'s note`;
  const labelOf = (id: string) => local[id] ?? labels[id] ?? id;
  // A decision: a problem raised, a cause asserted, a change to a course on the chart. The rest signs with the note.
  const isDecision = (kind: string, it: { type?: string }) => kind === "problems" || it.type === "suspected_cause";
  const summary = (kind: string, it: { name?: string; text?: string; from?: string; to?: string; type?: string; value?: number; unit?: string | null }) =>
    kind === "links" ? `${labelOf(it.from!)} ${it.type === "suspected_cause" ? "is a suspected cause of" : it.type === "treats" ? "treats" : it.type === "evidence_for" ? "is evidence for" : "bears on"} ${labelOf(it.to!)}` : it.name ? `${it.name}${it.value != null ? ` ${it.value} ${it.unit ?? ""}` : ""}` : it.text ?? "";
  const open = items.filter((x) => x.it.status === "proposed");
  const changes = (b.medication_changes ?? []).filter((c) => c.status === "proposed");
  return (
    <div className="rv">
      <button className="link" onClick={() => go("#/")}>← Problems</button>
      <h1 style={{ marginTop: 6 }}>{note.author}'s note · what it changes</h1>
      <p className="lede">{items.filter((x) => x.it.status === "proposed" && isDecision(x.kind, x.it)).length + changes.length} decisions to make, one at a time: problems raised, causes asserted, courses changed. The other {items.filter((x) => !isDecision(x.kind, x.it)).length} proposals sign with the note. Every line carries the passage it was read from.</p>
      {changes.map((c, i) => (
        <div key={i} className="item"><span className="k">course change</span><span>{labelOf(c.med_id)}: {c.change.replace("_", " ")} effective {c.effective}{c.provenance?.quote && <span className="q">“{c.provenance.quote}”</span>}</span>
          <span className="acts"><button className="btn small primary" disabled={!!busy} onClick={() => run("review", () => api.review(pid, b.stem, { accept_changes: true }), "Course change signed")}>Sign</button></span></div>
      ))}
      {items.filter((x) => isDecision(x.kind, x.it) || showRest).map(({ kind, it }) => (
        <div key={it.id} className="item">
          <span className="k">{it.type === "suspected_cause" ? "cause" : KIND_WORD[kind]}</span>
          <span>{summary(kind, it)}{it.provenance?.quote && <span className="q">“{it.provenance.quote}”</span>}</span>
          {it.status === "proposed" ? (
            <span className="acts"><button className="btn small primary" disabled={!!busy} onClick={() => run("review", () => api.review(pid, b.stem, { accept: [it.id] }), "Signed")}>Sign</button><button className="btn small ghost" disabled={!!busy} onClick={() => { const reason = prompt("Why? One line, in your words.") ?? ""; run("review", () => api.review(pid, b.stem, { reject: [it.id], reason_code: "disagree", reason }), "Rejected, with your reason on the record"); }}>Reject</button></span>
          ) : <span className="done">{it.status}</span>}
        </div>
      ))}
      {!showRest && <div className="addplan"><button className="btn small ghost" onClick={() => setShowRest(true)}>Show the {items.filter((x) => !isDecision(x.kind, x.it)).length} routine items: results, courses, links, plan lines</button></div>}
      <div className="addplan" style={{ marginTop: 16 }}>
        <button className="btn primary" disabled={!!busy || note.status === "signed"} onClick={() => run("sign", () => api.signNote(pid, note.id), "Note signed; everything left was signed with it").then(() => go("#/"))}>{note.status === "signed" ? "Note signed" : `Sign the note${open.length + changes.length ? ` · signs the ${open.length + changes.length} left` : ""}`}</button>
      </div>
    </div>
  );
}
