import { labelOf } from "./labels";
import type { TrailEntry } from "./types";
import { REASON_CODES } from "./types";

type Props = { entries: TrailEntry[]; labels: Record<string, string>; highlight: Set<string>; onHover: (ids: string[] | null) => void };

const codeLabel = (code: string | null) => REASON_CODES.find((c) => c.code === code)?.label ?? code ?? "";
const KIND: Record<string, string> = { problem: "problem", observation: "result", medication: "med", link: "link", insight: "insight", document: "doc", medication_change: "med Δ" };

export default function Trail({ entries, labels, highlight, onHover }: Props) {
  const decided = entries.filter((e) => e.decision !== "pending");
  const pending = entries.length - decided.length;
  return (
    <section className="trail" aria-label="Decision trail">
      <h2>
        Decision trail · {decided.length} decided{pending > 0 ? ` · ${pending} pending` : ""}
      </h2>
      {entries.length === 0 && <div className="quiet">No proposals have touched this problem yet.</div>}
      {entries.map((e, i) => {
        const ids = e.kind === "link" ? e.what.split(" ").filter((w) => /^(prob|obs|med|note|lnk|ins|doc)_|^LOINC:/.test(w)) : [e.id];
        const what = e.kind === "link"
          ? e.what.replace(/^link: /, "").split(" ").map((w) => labelOf(labels, w)).join(" ")
          : e.what.replace(/^(problem|medication|result): /, "");
        return (
          <div key={e.id + i} className={`row ${ids.some((id) => highlight.has(id)) ? "hi" : ""}`} onMouseEnter={() => onHover(ids)} onMouseLeave={() => onHover(null)}>
            <span className="when">{e.at.slice(0, 10)}</span>
            <span className={`dec ${e.decision}`}>{e.decision === "accepted" ? "signed" : e.decision}</span>
            <div>
              <div className="what">
                <span className="k">{KIND[e.kind] ?? e.kind}</span>
                {what}
                {e.by && <span className="who">· {e.by}</span>}
              </div>
              {(e.reason || e.reason_code) && (
                <div className="why">
                  {e.reason_code && codeLabel(e.reason_code)}
                  {e.reason_code && e.reason ? " — " : ""}
                  {e.reason}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
