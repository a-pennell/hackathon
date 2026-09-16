import type { Ctx } from "./App";
import type { Standing } from "./v2types";

const GROUPS: { key: Standing; title: string; blurb: string }[] = [
  { key: "off_course", title: "Off course", blurb: "an expectation was missed, or a monitored value is outside its range and still moving the wrong way" },
  { key: "watch", title: "Watch", blurb: "outside range but steady, a change made and not yet answered, an unexplained finding, or an answer still owed" },
  { key: "good", title: "In good standing", blurb: "monitored, in range, steady" },
  { key: "unmonitored", title: "Not monitored", blurb: "no series to watch; the record is whatever was last written" },
];
const dmy = (iso: string) => { const d = new Date(iso.slice(0, 10) + "T00:00:00"); return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`; };

/** The gate: every problem, sorted by standing. The system watches all of them all the time; this is what it found. */
export default function Problems({ listing, go }: Ctx) {
  const here = listing.here_for;
  return (
    <div className="gate">
      <h1>Problems</h1>
      <p className="lede">Standing is computed from the chart by rules, continuously: the monitored series, the expectation set when a course was stopped, the loops still open. Since {dmy(listing.since.date)}, {listing.since.why}.{here.note ? ` A note from ${here.note.author} on ${dmy(here.note.time)} is ${here.note.status === "signed" ? "signed" : here.note.has_queue ? "read and waiting for signature" : "waiting to be read"}.` : ""}</p>
      {GROUPS.map((g) => {
        const rows = listing.problems.filter((p) => p.standing === g.key);
        if (!rows.length) return null;
        return (
          <section key={g.key} className="grp">
            <h3>{g.title} <span className="n">{rows.length}</span> <span className="n" style={{ textTransform: "none", letterSpacing: 0 }}>· {g.blurb}</span></h3>
            {rows.map((p) => (
              <div key={p.id} className="prow" onClick={() => go(`#/problem/${p.id}`)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && go(`#/problem/${p.id}`)}>
                <span className={`dot ${p.standing}`} />
                <div>
                  <div className="name">{p.name}{p.members.length > 0 && <span className="pill" style={{ marginLeft: 8 }} title={p.members.map((m) => m.name).join(" · ")}>+{p.members.length} related</span>}</div>
                  <div className="why">{p.why}</div>
                  {p.next && <div className="next">next: {p.next}</div>}
                </div>
                <div className="right">
                  <span className="tag ep">{p.epistemic}</span><br />
                  {p.pending > 0 && <span className="tag pend">{p.pending} waiting</span>}
                  {p.last_change && <div>last value {dmy(p.last_change)}</div>}
                </div>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
