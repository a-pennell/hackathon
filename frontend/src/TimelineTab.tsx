import { useState } from "react";
import type { TimelineData, TimelineLane } from "./types";

type Props = { data: TimelineData; highlight: Set<string>; onHover: (ids: string[] | null) => void };

const LANES: { key: TimelineLane; label: string }[] = [
  { key: "sessions", label: "Sessions" }, { key: "results", label: "Results" }, { key: "documents", label: "Documents" },
  { key: "changes", label: "Changes" }, { key: "reasoning", label: "Reasoning" },
];
const TAG_CLASS: Record<string, string> = { signed: "ok", proposed: "pend", rejected: "warn", unsigned: "pend", imported: "soft" };
const LANE_CLASS: Record<TimelineLane, string> = { sessions: "ep", results: "soft", documents: "soft", changes: "chg", reasoning: "pencil" };
const dmy = (day: string) => {
  const d = new Date(day + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`;
};

/** The Timeline: everything that happened, on one list, newest first, in five lanes a chip can hide. A visit log
 *  is the first lane alone; the record is all five. Results fold to one row per day with the monitored series
 *  called out; courses sit on their clinical dates; reasoning carries the signature or the rejection. */
export default function TimelineTab({ data, highlight, onHover }: Props) {
  const [on, setOn] = useState<Set<TimelineLane>>(new Set(LANES.map((l) => l.key)));
  const toggle = (k: TimelineLane) => setOn((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const items = data.items.filter((x) => on.has(x.lane));
  let lastDay = "";
  return (
    <div className="tabpage timeline-tab">
      <section className="group">
        <h3>
          Timeline <span className="cnt">{items.length} of {data.items.length} events</span>
          <span className="tl-chips" role="group" aria-label="Lanes">
            {LANES.map((l) => (
              <button key={l.key} className={`tl-chip ${on.has(l.key) ? "on" : ""}`} aria-pressed={on.has(l.key)} onClick={() => toggle(l.key)}>
                {l.label} <span className="n">{data.lanes[l.key]}</span>
              </button>
            ))}
          </span>
        </h3>
        <div className="rows">
          {items.map((x, i) => {
            const head = x.day !== lastDay;
            lastDay = x.day;
            const tag = x.tag && !/out of range/.test(x.tag) ? x.tag : null;
            return (
              <div key={i} className={`tl-row ${head ? "day" : ""} ${x.ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(x.ids)} onMouseLeave={() => onHover(null)}>
                <span className="when">{head ? dmy(x.day) : ""}</span>
                <span className={`tag ${LANE_CLASS[x.lane]}`}>{x.kind}</span>
                <span className="grow">
                  {x.text}
                  {x.detail && <span className={`detail ${x.lane === "results" ? "mono" : ""}`}>{x.detail}</span>}
                </span>
                <span className="meta">
                  {x.tag && /out of range/.test(x.tag) && <span className="tag warn">{x.tag}</span>}
                  {tag && <span className={`tag ${TAG_CLASS[tag] ?? "soft"}`}>{tag}</span>}
                  {x.by ? ` ${x.by}` : ""}
                </span>
              </div>
            );
          })}
          {items.length === 0 && <div className="quiet">Nothing in the lanes you have on.</div>}
        </div>
      </section>
    </div>
  );
}
