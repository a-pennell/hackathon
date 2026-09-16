import type { NoteFile, QueueBatch, VisitNoteRow } from "./types";
import { waitingIn } from "./next";

type Props = {
  notes: NoteFile[];                 // every note on file, all patients
  pid: string;
  patients: { id: string; name: string }[];
  scope: "patient" | "mine";
  onScope: (s: "patient" | "mine") => void;
  queues: QueueBatch[];
  visitNotes: VisitNoteRow[];        // compiled visit notes, in progress or signed
  onOpenVisitNote: (encounterId: string) => void;
  onOpen: (id: string) => void;
  onRead: (n: NoteFile) => void;
  busy: string | null;
};

type State = "in_progress" | "waiting" | "signed";
const stateOf = (n: NoteFile): State => (n.status === "signed" ? "signed" : n.has_queue ? "in_progress" : "waiting");
const SECTIONS: [State, string, string][] = [
  ["in_progress", "In progress", "Read, with decisions or a signature still owed."],
  ["waiting", "Waiting to be read", "Arrived with a visit; nothing has been read from them yet."],
  ["signed", "Signed", "Attested; what each wrote to the record is under the note."],
];
const dmy = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`;
};

/** Notes by state: in progress (read, not signed), waiting to be read, signed. The row's button is the next thing
 *  owed on that note: read it, review what is waiting, sign it, or open it. Scoped to this patient, or to every
 *  patient with a note on file (the clinician's day): a row on another patient opens that patient. */
export default function NotesTab({ notes, pid, patients, scope, onScope, queues, visitNotes, onOpenVisitNote, onOpen, onRead, busy }: Props) {
  const rows = notes.filter((n) => scope === "mine" || n.patient_id === pid).sort((a, b) => b.time.localeCompare(a.time));
  const nameOf = (id: string) => patients.find((p) => p.id === id)?.name ?? id;
  const unsignedElsewhere = notes.filter((n) => n.patient_id !== pid && n.status !== "signed").length;
  return (
    <div className="cardpage">
      <article className="ov notes">
        <div className="ovbar">
          <h1>Notes</h1>
          <span className="scope">
            <button className={`btn small ${scope === "patient" ? "primary" : "ghost"}`} onClick={() => onScope("patient")}>{nameOf(pid)}</button>
            <button className={`btn small ${scope === "mine" ? "primary" : "ghost"}`} onClick={() => onScope("mine")}>All my patients{unsignedElsewhere > 0 ? ` · ${unsignedElsewhere} unsigned elsewhere` : ""}</button>
          </span>
        </div>
        <div className="ovgrid one">
          {SECTIONS.map(([st, title, blurb]) => {
            const list = rows.filter((n) => stateOf(n) === st);
            return (
              <section key={st}>
                <h3>{title} <span className="cnt">{list.length}</span></h3>
                {visitNotes.filter((v) => v.status === (st === "in_progress" ? "in_progress" : st === "signed" ? "signed" : "none") && (scope === "mine" || v.patient_id === pid)).map((v) => (
                  <div key={v.id} className="ovrow note-row visit">
                    <div className="grow">
                      <span className="name">{scope === "mine" ? `${nameOf(v.patient_id)} · ` : ""}Visit note · {v.author} · {dmy(v.time)}</span>{" "}
                      <span className={`tag ${v.status === "signed" ? "ok" : "pend"}`}>{v.status === "signed" ? `signed by ${v.by ?? v.author}` : "compiled · unsigned"}</span>
                      <div className="why">{v.excerpt.slice(0, 160)}…</div>
                    </div>
                    <button className={`btn small ${v.status === "signed" ? "ghost" : "primary"}`} disabled={!!busy} onClick={() => onOpenVisitNote(v.encounter_id)}>{v.status === "signed" ? "Open" : "Finish"}</button>
                  </div>
                ))}
                {list.length === 0 && !visitNotes.some((v) => v.status === st && (scope === "mine" || v.patient_id === pid)) && <div className="quiet">{st === "in_progress" ? "No note is in progress." : st === "waiting" ? "Every note on file has been read." : "Nothing signed yet."}</div>}
                {list.map((n) => {
                  const waiting = st === "in_progress" ? waitingIn(queues.find((q) => q.note_id === n.id)) : 0;
                  const label = st === "waiting" ? "Read" : st === "in_progress" ? (waiting > 0 ? `Review · ${waiting}` : "Sign") : "Open";
                  const tag = st === "signed" ? `signed by ${n.review?.by ?? n.author}${n.review?.at ? ` · ${dmy(n.review.at)}` : ""}` : st === "in_progress" ? (waiting > 0 ? `${waiting} to decide` : "ready to sign") : "not yet read";
                  return (
                    <div key={n.id} className="ovrow note-row">
                      <div className="grow">
                        <span className="name">{scope === "mine" ? `${nameOf(n.patient_id)} · ` : ""}{n.author} · {dmy(n.time)} {n.time.slice(11, 16)}</span>{" "}
                        <span className={`tag ${st === "signed" ? "ok" : st === "in_progress" ? "warn" : "soft"}`}>{tag}</span>
                        <div className="why">{n.excerpt.replace(/\s+/g, " ").slice(0, 160)}…</div>
                      </div>
                      {n.patient_id === pid
                        ? <button className={`btn small ${st === "signed" ? "ghost" : "primary"}`} disabled={!!busy} onClick={() => (st === "waiting" ? onRead(n) : onOpen(n.id))}>{label}</button>
                        : <a className={`btn small ${st === "signed" ? "ghost" : "primary"}`} href={`?patient=${n.patient_id}`} title={`opens ${nameOf(n.patient_id)}`}>{label} ↗</a>}
                    </div>
                  );
                })}
                <div className="more">{blurb}</div>
              </section>
            );
          })}
        </div>
      </article>
    </div>
  );
}
