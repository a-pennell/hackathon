import type { ChartData } from "./types";

const fmt = (s?: string | null) => (s ? s.slice(0, 10) : "");
const nice = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)).replace(/\.?0+$/, "");

/** Chart: what we know. Medications, results by series, problems, history. Lenses on the same objects the
 *  problem cards use; nothing here is a second copy. */
export function ChartTab({ data, onOpenProblem }: { data: ChartData; onOpenProblem: (id: string) => void }) {
  const active = data.problems.filter((p) => p.status === "active");
  const resolved = data.problems.filter((p) => p.status !== "active");
  return (
    <div className="tabpage chart-tab">
      <section className="group">
        <h3>Medications <span className="cnt">{data.medications.filter((m) => !m.segments[m.segments.length - 1].end).length} active · {data.medications.length} courses</span></h3>
        <div className="rows">
          {data.medications.map((m) => {
            const last = m.segments[m.segments.length - 1];
            const stopped = !!last.end;
            return (
              <div key={m.id} className={`row3 ${stopped ? "dim" : ""}`}>
                <span className="name">{m.name}</span>
                <span className="num">{last.dose ?? ""} {last.route ?? ""} {last.frequency ?? ""}</span>
                <span className="meta">{stopped ? `stopped ${fmt(last.end)}` : `since ${fmt(last.start) || "?"}`}{m.provenance.source === "nlp_extraction" ? " · from a note" : ""}</span>
              </div>
            );
          })}
        </div>
      </section>
      <section className="group">
        <h3>Lab results and vitals <span className="cnt">latest value per series</span></h3>
        <div className="rows">
          {data.series.map((s) => (
            <div key={s.code} className="row3">
              <span className="name">{s.name}</span>
              <span className={`num ${s.out ? "flag" : ""}`}>{nice(s.latest.value)} {s.unit ?? ""}</span>
              <span className="meta">{fmt(s.latest.time)} · {s.n} results{s.problem_names.length ? ` · ${s.problem_names.join(", ")}` : ""}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="group">
        <h3>Allergies and sensitivities</h3>
        <div className="quiet">No allergies on file.</div>
      </section>
      <section className="group">
        <h3>Problems <span className="cnt">{active.length} active · {resolved.length} resolved</span></h3>
        <div className="rows">
          {active.map((p) => (
            <div key={p.id} className="row3 clickable" onClick={() => onOpenProblem(p.id)}>
              <span className="name">{p.name}</span>
              <span className="num">{p.code?.value ?? ""}</span>
              <span className="meta">since {p.onset_date?.slice(0, 4) ?? "?"}</span>
            </div>
          ))}
          {resolved.map((p) => (
            <div key={p.id} className="row3 dim">
              <span className="name">{p.name}</span>
              <span className="num">{p.code?.value ?? ""}</span>
              <span className="meta">resolved {p.resolved_date?.slice(0, 4) ?? ""}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

