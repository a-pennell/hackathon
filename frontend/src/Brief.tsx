import type { Brief as BriefT } from "./types";

type Props = {
  brief: BriefT | null;
  highlight: Set<string>;
  onHover: (ids: string[] | null) => void;
  onAskClaude: () => void;
  busy: boolean;
  mode: "live" | "replay";
};

const dmy = (iso: string) => {
  const d = new Date(iso + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })}`;
};

export default function Brief({ brief, highlight, onHover, onAskClaude, busy, mode }: Props) {
  if (!brief) return null;
  const model = brief.source !== "computed";
  return (
    <section className="brief" aria-label="Pre-visit brief">
      <div className="brief-head">
        <h2>Before you start</h2>
        <span className="win">
          {dmy(brief.window.start)} → {dmy(brief.window.end)}
        </span>
        <span className="spacer" />
        <span className="src">{model ? `written by ${brief.source.split("/").pop()}` : "computed from the chart"}</span>
        {!model && (
          <button className="btn small ghost" disabled={busy} onClick={onAskClaude} title={mode === "live" ? "Three or four sentences from Claude over the same evidence" : "The saved Claude brief"}>
            {mode === "live" ? "Ask Claude" : "Claude’s version"}
          </button>
        )}
      </div>
      <p>
        {brief.lines.length === 0 && <span className="empty-brief">Nothing has changed on this problem in the window.</span>}
        {brief.lines.map((l, i) => (
          <span
            key={i}
            className={`line ${l.kind} ${l.ids.some((id) => highlight.has(id)) ? "hi" : ""}`}
            onMouseEnter={() => onHover(l.ids)}
            onMouseLeave={() => onHover(null)}
            title={l.ids.join(", ")}
          >
            {l.text}{" "}
          </span>
        ))}
      </p>
    </section>
  );
}
