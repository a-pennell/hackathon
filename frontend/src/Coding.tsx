import type { Coding as CodingT } from "./types";

type Props = { coding: CodingT | null; highlight: Set<string>; onHover: (ids: string[] | null) => void };

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export default function Coding({ coding, highlight, onHover }: Props) {
  if (!coding) return null;
  const m = coding.mdm;
  const ids = (xs: { evidence: string[] }[]) => xs.flatMap((x) => x.evidence);
  return (
    <section className="coding" aria-label="Visit coding">
      <h2>
        Visit coding · computed from today's signatures
        <span className="cpt">
          {m.cpt} <span className="lvl">{cap(m.level)}</span>
        </span>
        <span style={{ fontWeight: 400, letterSpacing: 0, textTransform: "none", color: "var(--graphite)" }}>
          {coding.signed_today} items signed on {coding.date}
        </span>
      </h2>
      <div className="grid">
        {(["problems", "data", "risk"] as const).map((k) => (
          <div key={k} className="el" onMouseEnter={() => k === "problems" && onHover(ids(coding.problems_addressed))} onMouseLeave={() => onHover(null)}>
            <div className="name">{k === "problems" ? "Problems addressed" : k === "data" ? "Data reviewed / ordered" : "Risk of management"}</div>
            <div className={`level ${m[k].level}`}>{cap(m[k].level)}</div>
            <ul>
              {m[k].why.length === 0 && <li>nothing signed today counts here</li>}
              {m[k].why.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="dx">
        {coding.diagnosis_codes.map((d, i) => (
          <div key={i} style={{ display: "contents" }}>
            <span className={`code ${d.code ? "" : "none"} ${d.problem_id && highlight.has(d.problem_id) ? "hi" : ""}`} onMouseEnter={() => onHover(d.problem_id ? [d.problem_id] : d.evidence ?? [])} onMouseLeave={() => onHover(null)}>
              {d.code ?? "—"}
            </span>
            <span className="desc">
              {d.description} <small>· {d.name}{d.mapping === "demo table" ? "" : ` · ${d.mapping}`}</small>
            </span>
          </div>
        ))}
      </div>
      <div className="note">{m.rule}. Diagnosis codes are a demo mapping from the chart's SNOMED codes; nothing here is written to the chart, and nothing is generated to justify a code.</div>
    </section>
  );
}
