import { useState } from "react";
import type { Problem } from "./types";

type Props = { problems: Problem[]; selected: string | null; onSelect: (id: string) => void; proposedNames?: string[] };

const TAG: Record<string, string> = {
  "Chronic kidney disease stage 3": "CKD",
  "Chronic congestive heart failure": "CHF",
  "Diabetes mellitus type 2": "T2DM",
  "Essential hypertension": "HTN",
};

function Row({ p, n, on, onSelect }: { p: Problem; n: number; on: boolean; onSelect: (id: string) => void }) {
  const codes = p.monitored_codes?.length ?? 0;
  return (
    <button className={`prob ${p.status} ${on ? "on" : ""}`} onClick={() => onSelect(p.id)} title={p.id}>
      <span className="n">{String(n).padStart(2, " ")}</span>
      <span className="name">{p.name}</span>
      <span className="meta">
        {p.onset_date?.slice(0, 4)}
        {codes > 0 && <span className="dot" title={`${codes} monitored series`} />}
        {(p.note_links ?? 0) > 0 && <span className="pend" title={`${p.note_links} findings signed from notes`}> · {p.note_links}✎</span>}
        {TAG[p.name] && <span> · {TAG[p.name]}</span>}
      </span>
    </button>
  );
}

export default function ProblemList({ problems, selected, onSelect, proposedNames = [] }: Props) {
  const [showResolved, setShowResolved] = useState(false);
  const active = problems.filter((p) => p.status === "active");
  const resolved = problems.filter((p) => p.status !== "active");
  // Problems with monitored series first: those are the ones the timeline can say something about.
  const byOnsetDesc = (a: Problem, b: Problem) => (b.onset_date ?? "").localeCompare(a.onset_date ?? "");
  const ordered = [
    ...active.filter((p) => (p.monitored_codes?.length ?? 0) > 0).sort(byOnsetDesc),
    ...active.filter((p) => (p.monitored_codes?.length ?? 0) === 0).sort(byOnsetDesc),
  ];
  return (
    <nav className="list">
      <h2>Problem list</h2>
      {ordered.map((p, i) => (
        <Row key={p.id} p={p} n={i + 1} on={p.id === selected} onSelect={onSelect} />
      ))}
      {proposedNames.length > 0 && (
        <>
          <h2 style={{ marginTop: 12 }}>Proposed by notes</h2>
          {proposedNames.map((name) => (
            <div key={name} className="prob proposed">
              <span className="n">·</span>
              <span className="name">{name}</span>
              <span className="meta pend">in queue</span>
            </div>
          ))}
        </>
      )}
      <button className="fold" onClick={() => setShowResolved((s) => !s)}>
        {showResolved ? "▾" : "▸"} {resolved.length} resolved
      </button>
      {showResolved && resolved.map((p, i) => <Row key={p.id} p={p} n={ordered.length + i + 1} on={p.id === selected} onSelect={onSelect} />)}
    </nav>
  );
}
