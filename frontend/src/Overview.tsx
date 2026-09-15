import { useState } from "react";
import type { Overview as OverviewT, Problem } from "./types";

type Props = {
  data: OverviewT;
  problems: Problem[];
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onOpen: (problemId: string) => void;
  onReadNote: (noteId: string) => void;
  busy: string | null;
};

const dmy = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })}`;
};
const days = (a: string, b: string) => Math.round((new Date(b.slice(0, 10)).getTime() - new Date(a.slice(0, 10)).getTime()) / 86400000);
function age(dob: string) {
  const d = new Date(dob), n = new Date();
  return n.getFullYear() - d.getFullYear() - (n < new Date(n.getFullYear(), d.getMonth(), d.getDate()) ? 1 : 0);
}
const TAG_CLASS: Record<string, string> = { mismatch: "warn", unexplained: "warn", worsening: "warn", proposed: "pend" };

export default function Overview({ data, problems, highlight, onHover, onOpen, onReadNote, busy }: Props) {
  const [showMore, setShowMore] = useState(false);
  const pt = data.patient;
  const enc = data.here_for.encounter;
  const note = data.here_for.note;
  const restProblems = problems.filter((p) => p.status === "active" && !data.concerns.some((c) => c.id === p.id));
  const hi = (ids: string[]) => (ids.some((id) => highlight.has(id)) ? "hi" : "");

  return (
    <div className="cardpage">
      <section className="explain top">
        <h2>The overview</h2>
        <p>
          Orientation in under ten seconds: who this is, why they are here, what changed since you last looked, which concerns need something from you, and which loops are still open.
          "What changed" is ranked by clinical meaning rather than listed by time: a missed expectation first, then staging changes, medication changes on linked courses, parameters
          leaving their range, unexplained findings, and only then proposals and decisions. Every line is computed from the chart; nothing here is stored.
        </p>
        <p className="qs"><b>Q1</b> what is happening · <b>Q3</b> what changed · <b>Q4</b> what we are doing</p>
      </section>

      <article className="ov">
        <div className="ovbar">
          <h1>{pt.name}</h1>
          <span className="dim">{age(pt.dob)} · {pt.sex} · DOB {pt.dob}</span>
          {enc && (
            <span className="here">
              Here for: <b>{enc.type}</b>, {dmy(enc.time)}
              {note && (
                <>
                  <span className="tag pend" title={note.file}>{note.has_queue ? "note read" : "note waiting"}</span>
                  {!note.has_queue && <button className="btn small" disabled={!!busy} onClick={() => onReadNote(note.id)}>Read it</button>}
                </>
              )}
            </span>
          )}
        </div>
        <div className="ovgrid">
          <section>
            <h3>
              Since you last looked <span className="cnt">{dmy(data.since.date)} · {days(data.since.date, data.as_of)} days</span>
            </h3>
            {data.changes.length === 0 && <div className="quiet">Nothing ranked has changed since {dmy(data.since.date)}. Quiet is a valid answer.</div>}
            {data.changes.map((l, i) => (
              <div key={i} className={`ovrow ${hi(l.ids)}`} onMouseEnter={() => onHover(l.ids)} onMouseLeave={() => onHover(null)}>
                <span className="rank">{i + 1}</span>
                <div className="grow">
                  {l.text}
                  <div className="why"><span className="p">{l.problem_name}</span> · {l.why}</div>
                </div>
                {l.tag && <span className={`tag ${TAG_CLASS[l.tag] ?? "soft"}`}>{l.tag === "unexplained" ? "○ unexplained" : l.tag}</span>}
                <button className="btn small ghost" onClick={() => onOpen(l.problem_id)}>Open</button>
              </div>
            ))}
            {data.other_changes > 0 && <div className="more">{data.other_changes} other change{data.other_changes > 1 ? "s" : ""}, none ranked above proposals and decisions.</div>}
            <div className="more" style={{ marginTop: 6 }}>Since: {data.since.why}.</div>
          </section>
          <section>
            <h3>Active concerns <span className="cnt">by what they need</span></h3>
            {data.concerns.map((c) => (
              <div key={c.id} className={`ovrow concern ${highlight.has(c.id) ? "hi" : ""}`} onClick={() => onOpen(c.id)} onMouseEnter={() => onHover([c.id])} onMouseLeave={() => onHover(null)}>
                <div className="grow">
                  <span className="name">{c.name}</span> <span className="tag ep">{c.epistemic}</span>
                  {c.members.length > 0 && <span className="tag soft" style={{ marginLeft: 4 }} title={c.members.map((m) => m.name).join(" · ")}>+{c.members.length} related entr{c.members.length > 1 ? "ies" : "y"}</span>}
                  {c.qualifiers.filter((q) => q !== "chronic" && q !== "new").map((q) => (
                    <span key={q} className={`tag ${q === "worsening" || q === "unexpected" ? "warn" : "soft"}`} style={{ marginLeft: 4 }}>{q}</span>
                  ))}
                  <div className="why">
                    {c.lead ? `${c.lead.text} · ${c.lead.detail}` : c.monitored ? "monitored, steady" : "no monitored series"}
                    {c.decisions > 0 ? ` · ${c.decisions} decisions` : ""}
                  </div>
                </div>
                {c.action ? (
                  <button className={`btn small ${c.action.kind === "review" ? "primary" : ""}`} onClick={(e) => { e.stopPropagation(); onOpen(c.id); }}>{c.action.label}</button>
                ) : null}
              </div>
            ))}
            {(data.more_concerns > 0 || restProblems.length > 0) && (
              <div className="more">
                <button onClick={() => setShowMore((v) => !v)}>{showMore ? "▾" : "▸"} {restProblems.length} more active problems, nothing owed</button>
                {showMore && restProblems.map((p) => (
                  <div key={p.id} className="ovrow concern" onClick={() => onOpen(p.id)}>
                    <div className="grow"><span className="name">{p.name}</span><div className="why">since {p.onset_date?.slice(0, 4) ?? "?"}</div></div>
                  </div>
                ))}
              </div>
            )}

            <h3>Pending <span className="cnt">{data.pending.length}</span></h3>
            {data.pending.length === 0 && <div className="quiet">No orders or referrals waiting on an answer.</div>}
            {data.pending.map((x) => (
              <div key={x.id} className={`ovrow ${highlight.has(x.id) ? "hi" : ""}`} onMouseEnter={() => onHover([x.id])} onMouseLeave={() => onHover(null)}>
                <div className="grow">
                  {x.text}
                  <div className="why"><span className="p">{x.problem_name}</span> · {x.detail}</div>
                </div>
                <span className={`tag ${x.status === "awaiting" || x.status === "unsigned" ? "pend" : "ok"}`}>{x.status}</span>
              </div>
            ))}
          </section>
        </div>
      </article>

      <section className="explain bottom">
        <h2>What you are looking at</h2>
        <ul>
          <li><b>Since you last looked</b> is the last routine visit before the newest encounter, at least two weeks earlier, so a run of visits in one week reads as one. The ranking rule is fixed and stated: a missed expectation or a triggered contingency always leads; a change in what a problem is called comes next; then medication changes on courses linked to an active problem; then a monitored parameter leaving its range or moving by more than a quarter; then a finding the current story cannot explain; and only then proposals waiting and decisions made.</li>
          <li><b>Active concerns</b> are ordered by what they need, not by when they were added. A row's button is its pending item made actionable; a row with no button says nothing is owed. The chip after the name is the only certainty encoding on the screen.</li>
          <li><b>Pending</b> shows the loop rule: an order and its result show each other. A lab order stays here until a result with its code lands on the chart, and a referral until a reply does.</li>
          <li>Opening a row goes to that problem's card. The overview is a lens on the same objects; nothing is duplicated.</li>
        </ul>
      </section>
    </div>
  );
}
