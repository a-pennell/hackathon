import type { Amendment } from "./types";

export default function Amendments({ items = [] }: { items?: Amendment[] }) {
  if (!items.length) return null;
  return <section className="amendments" aria-label="Signed amendments">
    <h3>Signed amendments</h3>
    {items.map((a) => <div key={a.id} className="amendment">
      <p className="stamp">{a.by} · {a.at.slice(0, 16).replace("T", " ")}</p>
      <p className="amendment-text">{a.text}</p>
      <p className="meta">Reason: {a.reason}</p>
    </div>)}
  </section>;
}
