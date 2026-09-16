import { useMemo, useState } from "react";
import type { ReviewBody } from "./api";
import { buildGroups, GroupCard, type Group } from "./Inbox";
import ReviewDrawer, { isConsequential, type Reviewable } from "./ReviewDrawer";
import Coding from "./Coding";
import type { CareData, ChartData, Coding as CodingT, NoteFile, Problem, QueueBatch, RecordEvent } from "./types";

type Props = {
  note: NoteFile;
  batch: QueueBatch | null;
  problems: Problem[];
  labels: Record<string, string>;
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onReview: (stem: string, body: ReviewBody) => Promise<void>;
  onRead: (mode: "live" | "replay") => void;
  onSign: () => void;
  onOpenProblem: (id: string) => void;
  record: RecordEvent[];
  busy: string | null;
  mode: "live" | "replay";
  chart: ChartData | null;
  care: CareData | null;
  coding: CodingT | null;
  lastNote: NoteFile | null;
};

type Span = { start: number; end: number; ids: string[]; status: string };

const fmtTime = (s?: string) => (s ? s.slice(0, 16).replace("T", " ") : "");
const KIND_WORD: Record<string, string> = {
  "note.received": "note", "note.signed": "signed", "observation.recorded": "result", "problem.raised": "problem", "problem.status_changed": "status",
  "medication.course_opened": "course", "medication.dose_changed": "dose", "medication.segment_closed": "stopped", "edge.asserted": "link",
  "plan.set": "plan", "insight.raised": "insight", "order.placed": "order", "document.signed": "document", "proposal.rejected": "rejected",
};

/** Every proposal's verbatim quote, located in the note text, so the text itself shows what the reading found. */
function spansOf(text: string, batch: QueueBatch | null): Span[] {
  if (!batch) return [];
  const items: { quote?: string; ids: string[]; status: string }[] = [];
  const p = batch.proposed;
  for (const x of [...(p.problems ?? []), ...(p.observations ?? []), ...(p.medications ?? []), ...(p.plans ?? [])]) items.push({ quote: x.provenance.quote, ids: [x.id], status: x.status });
  for (const l of p.links ?? []) items.push({ quote: l.provenance.quote, ids: [l.id, l.from, l.to], status: l.status });
  for (const c of batch.medication_changes ?? []) items.push({ quote: c.provenance.quote, ids: [c.med_id], status: c.status });
  const lower = text.toLowerCase();
  const found: Span[] = [];
  for (const it of items) {
    if (!it.quote) continue;
    const i = lower.indexOf(it.quote.toLowerCase());
    if (i < 0) continue;
    const span = { start: i, end: i + it.quote.length, ids: it.ids, status: it.status };
    const same = found.find((f) => f.start === span.start && f.end === span.end);
    if (same) {
      same.ids = [...new Set([...same.ids, ...span.ids])];
      if (same.status === "accepted" && span.status === "proposed") same.status = "proposed";
    } else found.push(span);
  }
  found.sort((a, b) => a.start - b.start || b.end - a.end);
  const out: Span[] = [];
  let cursor = 0;
  for (const s of found) {
    if (s.start < cursor) continue; // nested or overlapping: the earlier, longer span wins
    out.push(s);
    cursor = s.end;
  }
  return out;
}

export default function NoteView({ note, batch, problems, labels, highlight, onHover, onReview, onRead, onSign, onOpenProblem, record, busy, mode, chart, care, coding, lastNote }: Props) {
  const name = (id: string) => labels[id] ?? id;
  const [showSigned, setShowSigned] = useState(false);
  const [reviewing, setReviewing] = useState<Reviewable | null>(null);
  const [panels, setPanels] = useState<Set<string>>(new Set(["plan", "last"]));
  const [charge, setCharge] = useState(false);
  const togglePanel = (p: string) => setPanels((s) => { const n = new Set(s); n.has(p) ? n.delete(p) : n.add(p); return n; });
  const spans = useMemo(() => spansOf(note.text, batch), [note.text, batch]);
  const groups = useMemo(() => (batch ? buildGroups(batch, name, new Set()) : []), [batch, labels]); // eslint-disable-line react-hooks/exhaustive-deps
  const open = groups.filter((g) => g.status === "proposed" && !(g.subject && g.subject.status === "rejected"));
  const decided = groups.filter((g) => g.status !== "proposed" || (g.subject && g.subject.status === "rejected"));
  const changes = (batch?.medication_changes ?? []);
  const openChanges = changes.filter((c) => c.status === "proposed");
  const signed = note.status === "signed";
  const waiting = open.length + openChanges.length;
  const consequential = open.filter(isConsequential);
  const batchable = open.filter((g) => !isConsequential(g));
  const gated = consequential.length + openChanges.length;

  // Group proposals by the problem they touch, in problem-list order; the rest under "the note".
  const byProblem = useMemo(() => {
    const m = new Map<string, Group[]>();
    for (const g of batchable) {
      const pid = g.hoverIds.find((id) => problems.some((p) => p.id === id)) ?? (g.subject && "problem_id" in g.subject ? (g.subject as { problem_id: string }).problem_id : null) ?? "_";
      m.set(pid, [...(m.get(pid) ?? []), g]);
    }
    const order = [...problems.map((p) => p.id), "_"];
    return [...m.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
  }, [batchable, problems]);

  // The clinical diff: every proposal as one line in diff notation, before the cards.
  const changeset = useMemo(() => {
    if (!batch) return [];
    const rows: { sym: string; cls: string; text: string; ids: string[]; status: string }[] = [];
    for (const g of groups) {
      const status = g.subject && g.subject.status === "rejected" ? "rejected" : g.status;
      if (g.kind === "problem") rows.push({ sym: "+", cls: "add", text: `New problem: ${name(g.subjectId)}`, ids: g.hoverIds, status });
      else if (g.kind === "medication" && g.subject) rows.push({ sym: "+", cls: "add", text: `Course: ${name(g.subjectId)}`, ids: g.hoverIds, status });
      else if (g.kind === "result") rows.push({ sym: "+", cls: "add", text: `Result: ${name(g.subjectId)}`, ids: g.hoverIds, status });
      else if (g.kind === "plan") rows.push({ sym: "+", cls: "add", text: `Plan: ${name(g.subjectId).replace(/^plan: /, "")}`, ids: g.hoverIds, status });
      for (const l of g.links) {
        if (l.type === "suspected_cause") rows.push({ sym: "→", cls: "chg", text: `Link: ${name(l.from)} → suspected cause of ${name(l.to)}`, ids: [l.id, l.from, l.to], status: l.status });
      }
      if (g.kind === "finding") rows.push({ sym: "+", cls: "add", text: `Finding for ${g.links.map((l) => name(l.to)).join(", ")}`, ids: g.hoverIds, status });
    }
    for (const c of batch.medication_changes ?? []) rows.push({ sym: c.change === "stop" ? "−" : "~", cls: c.change === "stop" ? "rm" : "chg", text: `${c.change === "stop" ? "Stop" : "Change"}: ${name(c.med_id)}${c.dose && c.change === "dose_change" ? ` → ${c.dose}` : ""}`, ids: [c.med_id], status: c.status });
    return rows;
  }, [batch, groups, labels]); // eslint-disable-line react-hooks/exhaustive-deps
  const touched = useMemo(() => new Set(groups.flatMap((g) => g.hoverIds.filter((id) => problems.some((p) => p.id === id)))), [groups, problems]);

  const pieces: React.ReactNode[] = [];
  let cursor = 0;
  spans.forEach((s, i) => {
    if (s.start > cursor) pieces.push(note.text.slice(cursor, s.start));
    pieces.push(
      <mark key={i} className={`q ${s.status} ${s.ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(s.ids)} onMouseLeave={() => onHover(null)}>
        {note.text.slice(s.start, s.end)}
      </mark>,
    );
    cursor = s.end;
  });
  pieces.push(note.text.slice(cursor));

  return (
    <div className="cardpage">


      <article className="noteview">
        <header className="ntitle">
          <h1>Note · {fmtTime(note.time)} · {note.author}</h1>
          {signed ? (
            <span className="tag ok">signed by {note.review?.by} · {fmtTime(note.review?.at)}</span>
          ) : batch ? (
            <span className="tag pend">read · {waiting} waiting</span>
          ) : (
            <span className="tag soft">not read yet</span>
          )}
          <span className="spacer" />
          {!batch && note.file && (
            <button className="btn primary" disabled={!!busy || (mode === "replay" && !note.has_replay)} title={mode === "replay" && !note.has_replay ? "no saved reading; switch Claude to live" : ""} onClick={() => onRead(mode)}>
              {mode === "live" ? "Read with Claude" : "Read (saved)"}
            </button>
          )}
          {coding && coding.signed_today > 0 && <button className="btn" onClick={() => setCharge(true)} title="Visit coding computed from what was signed today">Charge capture</button>}
          {batch && !signed && (
            <button className="btn primary" disabled={!!busy || gated > 0} onClick={onSign} title={gated > 0 ? `${gated} consequential item${gated > 1 ? "s" : ""} first, one at a time` : "Signs every batchable proposal you have not rejected, then the note itself"}>
              {gated > 0 ? `Sign note · ${gated} to review first` : `Sign note${batchable.length > 0 ? ` · ${batchable.length}` : ""}`}
            </button>
          )}
        </header>

        <div className="ngrid">
          <section className="ntext">
            <h3>{note.file ? note.file.split("/").pop() : "chart note"} <span className="cnt">{spans.length ? `${spans.length} passages the reading used` : ""}</span></h3>
            <pre className="note-body">{pieces}</pre>
          </section>
          <div className="panelrail">
          <section className="nprops">
            {changeset.length > 0 && (
              <div className="changeset" aria-label="The clinical diff">
                <div className="cs-head"><span className="eyebrow">The clinical diff</span><span className="cnt">{changeset.filter((r) => r.status === "proposed").length} proposed · {changeset.filter((r) => r.status === "accepted").length} signed · {changeset.filter((r) => r.status === "rejected").length} rejected</span></div>
                {changeset.map((r, i) => (
                  <div key={i} className={`cs-row ${r.cls} ${r.status} ${r.ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(r.ids)} onMouseLeave={() => onHover(null)}><span className="sym">{r.sym}</span><span className="txt">{r.text}</span><span className="st">{r.status === "proposed" ? "" : r.status}</span></div>
                ))}
              </div>
            )}
            <h3>What this note proposes <span className="cnt">{batch ? `${waiting} waiting · ${decided.length + changes.length - openChanges.length} decided` : "read the note to find out"}</span></h3>
            {!batch && <div className="quiet">Nothing has been read from this note. Reading it proposes changes; nothing reaches the chart until you sign.</div>}
            {(consequential.length > 0 || openChanges.length > 0) && (
              <div className="pgroup consequential">
                <div className="pgroup-head">Consequential · reviewed one at a time <span className="cnt">{consequential.length + openChanges.length}</span></div>
                {consequential.map((g) => (
                  <div key={g.key} className="crow" onMouseEnter={() => onHover(g.hoverIds)} onMouseLeave={() => onHover(null)}>
                    <span className="kind">{g.kind === "problem" ? "problem" : g.kind === "medication" ? "course" : "cause"}</span>
                    <span className="what">{g.title}</span>
                    <button className="btn small primary" disabled={!!busy} onClick={() => setReviewing({ g, b: batch! })}>Review</button>
                  </div>
                ))}
                {openChanges.map((c, i) => (
                  <div key={i} className="crow" onMouseEnter={() => onHover([c.med_id])} onMouseLeave={() => onHover(null)}>
                    <span className="kind">{c.change === "stop" ? "stop" : "dose"}</span>
                    <span className="what"><b>{name(c.med_id)}</b>: {c.change.replace("_", " ")} effective {c.effective}</span>
                    <button className="btn small primary" disabled={!!busy} onClick={() => setReviewing({ c, b: batch! })}>Review</button>
                  </div>
                ))}
              </div>
            )}
            {batch && waiting === 0 && !signed && <div className="quiet">Everything is decided. Sign the note to attest it.</div>}
            {byProblem.map(([pid, gs]) => (
              <div key={pid} className="pgroup">
                <div className="pgroup-head">
                  {pid === "_" ? "About the note" : <button className="link" onClick={() => onOpenProblem(pid)}>{name(pid)}</button>}
                  <span className="cnt">{gs.length}</span>
                </div>
                {gs.map((g) => <GroupCard key={g.key} g={g} b={batch!} name={name} highlight={highlight} onHover={onHover} onReview={onReview} onReadDocument={() => undefined} busy={busy} />)}
              </div>
            ))}
            {decided.length > 0 && (
              <div className="strip">
                <button onClick={() => setShowSigned((v) => !v)}>{showSigned ? "▾" : "▸"} <span className="n">{decided.length}</span> decided</button>
                {showSigned && decided.map((g) => <GroupCard key={g.key} g={g} b={batch!} name={name} highlight={highlight} onHover={onHover} onReview={onReview} onReadDocument={() => undefined} busy={busy} />)}
              </div>
            )}
            {batch && batch.rejected.length > 0 && (
              <div className="quiet">{batch.rejected.length} item{batch.rejected.length > 1 ? "s" : ""} the reading produced could not be verified against the note and {batch.rejected.length > 1 ? "were" : "was"} dropped.</div>
            )}
          </section>

          <div className="rail-closed">
            <span className="lbl">Panels</span>
            {[["plan", "Plan"], ["last", "Last note"], ["meds", "Meds"], ["results", "Results"]].map(([k, l]) => (
              <button key={k} className={`pchip ${panels.has(k) ? "on" : ""}`} aria-pressed={panels.has(k)} onClick={() => togglePanel(k)}>{panels.has(k) ? "− " : "+ "}{l}</button>
            ))}
          </div>
          {panels.has("plan") && (
            <section className="panel">
              <div className="panel-head"><h4>Plan · {[...touched].map((id) => name(id)).join(", ") || "problems this note touches"}</h4><span className="lens">lens · Care › Plans</span><span className="spacer" /><button className="x" aria-label="Close panel" onClick={() => togglePanel("plan")}>×</button></div>
              <div className="panel-body">
                {care ? care.cards.filter((c) => touched.size === 0 || touched.has(c.id) || c.members.some((m) => touched.has(m.id))).map((c) => (
                  <div key={c.id} className="panel-prob">
                    <button className="link" onClick={() => onOpenProblem(c.id)}>{c.name}</button>
                    {c.plan.length === 0 && <div className="meta">nothing signed yet</div>}
                    {c.plan.slice(0, 4).map((p) => <div key={p.id} className="planrow"><span className="k">{p.kind.replace("_", " ")}</span><span>{p.text}</span></div>)}
                    {c.expected && <div className="meta">expected: {c.expected.statement}</div>}
                  </div>
                )) : <div className="meta">Loading the plan…</div>}
              </div>
            </section>
          )}
          {panels.has("last") && (
            <section className="panel">
              <div className="panel-head"><h4>Last note{lastNote ? ` · ${lastNote.time.slice(0, 10)}` : ""}</h4>{lastNote?.status === "signed" && <span className="tag ok">signed</span>}<span className="spacer" /><button className="x" aria-label="Close panel" onClick={() => togglePanel("last")}>×</button></div>
              <div className="panel-body">
                {lastNote ? <><div className="note-preview">{lastNote.text.replace(/\s+/g, " ").slice(0, 320)}…</div><div className="meta">{lastNote.author}</div></> : <div className="meta">No earlier note on file for this patient.</div>}
              </div>
            </section>
          )}
          {panels.has("meds") && (
            <section className="panel">
              <div className="panel-head"><h4>Medications</h4><span className="lens">lens · Chart › Medical info</span><span className="spacer" /><button className="x" aria-label="Close panel" onClick={() => togglePanel("meds")}>×</button></div>
              <div className="panel-body">
                {chart ? chart.medications.filter((m) => !m.segments[m.segments.length - 1].end).map((m) => { const last = m.segments[m.segments.length - 1]; return <div key={m.id} className={`planrow ${highlight.has(m.id) ? "hi" : ""}`} onMouseEnter={() => onHover([m.id])} onMouseLeave={() => onHover(null)}><span>{m.name}</span><span className="meta">{last.dose ?? ""} {last.frequency ?? ""}</span></div>; }) : <div className="meta">Loading…</div>}
              </div>
            </section>
          )}
          {panels.has("results") && (
            <section className="panel">
              <div className="panel-head"><h4>Results</h4><span className="lens">lens · Chart › Lab results</span><span className="spacer" /><button className="x" aria-label="Close panel" onClick={() => togglePanel("results")}>×</button></div>
              <div className="panel-body">
                {chart ? chart.series.map((r) => <div key={r.code} className="planrow"><span>{r.name}</span><span className={`num ${r.out ? "flag" : ""}`}>{r.latest.value} {r.unit ?? ""}</span><span className="meta">{r.latest.time.slice(0, 10)}</span></div>) : <div className="meta">Loading…</div>}
              </div>
            </section>
          )}
          </div>
        </div>

        <section className="nrecord">
          <h3>The record <span className="cnt">{record.length} event{record.length === 1 ? "" : "s"} from this note</span></h3>
          {record.length === 0 && <div className="quiet">Nothing has been written from this note yet.</div>}
          {record.map((e, i) => (
            <div key={i} className={`rev ${e.kind.replace(".", "-")} ${e.ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(e.ids)} onMouseLeave={() => onHover(null)}>
              <span className="when">{fmtTime(e.at)}</span>
              <span className={`tag ${e.kind === "note.signed" || e.kind === "plan.set" ? "ok" : e.kind === "proposal.rejected" ? "warn" : "soft"}`}>{KIND_WORD[e.kind] ?? e.kind}</span>
              <div className="grow">
                {e.text}
                {e.quote && <div className="quote">{e.quote}</div>}
                <div className="why">{e.source}{e.by ? ` · ${e.by}` : ""}</div>
              </div>
            </div>
          ))}
        </section>
      </article>
      {charge && coding && (
        <div className="modal-bg" onClick={() => setCharge(false)}>
          <div className="modal wide" onClick={(e) => e.stopPropagation()}>
            <Coding coding={coding} highlight={highlight} onHover={onHover} />
            <div className="row"><span className="spacer" /><button className="btn ghost" onClick={() => setCharge(false)}>Close</button></div>
          </div>
        </div>
      )}
      {reviewing && <ReviewDrawer item={reviewing} labels={labels} problems={problems} onReview={onReview} onClose={() => setReviewing(null)} busy={busy} />}

      <details className="explain bottom">
        <summary>About this screen</summary>
        <ul>
          <li><b>The text is the evidence.</b> Every proposal carries a verbatim quote, and the quote is marked where it sits in the note. Hover a mark to see what it proposes; hover a proposal to see where it came from. A proposal whose quote is not in the note is dropped before you see it.</li>
          <li><b>One signature.</b> Reject anything you disagree with, with a reason, then sign the note. Signing commits every remaining proposal and stamps the note itself; the note becomes a signed thing on the chart, not a draft in an editor.</li>
          <li><b>The record</b> is the ledger read back: the note arriving, each result, course, link and plan item the signature wrote, each rejection with its reason, and the signature. Nothing here is a stored log; it is folded from the provenance and review stamps every item already carries.</li>
          <li><b>Plan items are entities.</b> Each thing the assessment-and-plan says will be done is one item with a kind, tied to the problem it addresses. They show here, on the problem card under Plan, and in the record.</li>
        </ul>
      </details>
    </div>
  );
}
