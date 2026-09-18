import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CardExpectation, Encounter, Medication, Observation, Series, Timeline as TL } from "./types";

/** An expectation drawn as a corridor on its series: from the value at the stop toward the target, until the due date. */
export type Corridor = Pick<CardExpectation, "code" | "direction" | "since" | "by" | "status" | "ref_value" | "target_value">;

type Props = { data: TL; highlight: Set<string>; onHover?: (id: string | null) => void; onOpenNote?: (noteId: string) => void; corridor?: Corridor | null;
  /** Ids of proposed items the transcript has reached. Omit to show every proposal at once, which is what the
   *  problem page outside a visit wants; during a visit it is what makes a spoken value land as it is said. */
  revealed?: Set<string> | null };

const GUTTER = 176; // the flowsheet margin: lane names, units, latest values
const RIGHT = 24;
const LANE_H = 92;
const LANE_GAP = 10;
const MED_H = 22;
const AXIS_H = 44;
const ENC_H = 26;
const MED_COLORS = ["var(--med-1)", "var(--med-2)", "var(--med-3)", "var(--med-4)", "var(--med-5)", "var(--med-6)"];

const day = (s: string) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
const fmt = (s: string) => s.slice(0, 10);
const fmtShort = (ms: number) => {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
};
const nice = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)).replace(/\.0+$/, "");

type Tip = { x: number; y: number; w: number; body: React.ReactNode } | null;

// The tip is absolutely positioned with only `left` set, so it shrink-to-fits into whatever room is left to its
// right: near the right-hand edge it squeezes into a tall narrow column instead of reading as a line or two. So it
// gets a definite width, and flips to the left of the cursor when it would not fit on the right.
const TIP_W = 320;

export default function Timeline({ data, highlight, onHover, onOpenNote, corridor, revealed }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [tip, setTip] = useState<Tip>(null);
  const [cursor, setCursor] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setWidth(Math.max(560, entries[0].contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const t0 = day(data.window.start);
  // The axis runs to the expectation's due date when that lies past the window, so the corridor is not clipped.
  const t1 = Math.max(day(data.window.end), corridor ? day(corridor.by) : 0) + 86400000;
  const todayX = corridor && day(corridor.by) > day(data.window.end) ? GUTTER + ((day(data.window.end) - t0) / (t1 - t0)) * (width - GUTTER - RIGHT) : null;
  const x = (iso: string) => GUTTER + ((day(iso) - t0) / (t1 - t0)) * (width - GUTTER - RIGHT);

  // Proposed (pencil) observations attach to the series of the same code. During a visit only the ones the dictation
  // has reached are drawn, so the flowsheet fills in as the numbers are spoken rather than all at once.
  const heard = useCallback((id: string) => !revealed || revealed.has(id), [revealed]);
  const pencilByCode = useMemo(() => {
    const m: Record<string, Observation[]> = {};
    for (const o of data.proposed.observations) if (heard(o.id)) (m[o.code.value] ??= []).push(o);
    return m;
  }, [data, heard]);

  const meds: (Medication & { pencil?: boolean })[] = useMemo(
    () => [...data.proposed.medications.filter((m) => heard(m.id)).map((m) => ({ ...m, pencil: true, relation: m.relation ?? ("suspected_cause" as const) })), ...data.medications],
    [data, heard],
  );

  const medTop = data.series.length * (LANE_H + LANE_GAP) + 28;
  const height = medTop + 22 + meds.length * MED_H + ENC_H + AXIS_H;

  // month ticks
  const ticks: number[] = [];
  {
    const d = new Date(t0);
    d.setUTCDate(1);
    d.setUTCMonth(d.getUTCMonth() + 1);
    const span = t1 - t0;
    const step = span > 3 * 365 * 86400000 ? 6 : span > 400 * 86400000 ? 3 : 1;
    while (d.getTime() < t1) {
      if (d.getUTCMonth() % step === 0) ticks.push(d.getTime());
      d.setUTCMonth(d.getUTCMonth() + 1);
    }
  }
  const xms = (ms: number) => GUTTER + ((ms - t0) / (t1 - t0)) * (width - GUTTER - RIGHT);

  const show = (e: React.MouseEvent, body: React.ReactNode) => {
    const r = wrap.current!.getBoundingClientRect();
    const w = Math.min(TIP_W, r.width - 16);
    const cx = e.clientX - r.left;
    const right = cx + 14;
    setTip({ x: right + w <= r.width - 8 ? right : Math.max(8, cx - 14 - w), y: e.clientY - r.top + 12, w, body });
  };
  const hide = () => {
    setTip(null);
    onHover?.(null);
  };

  return (
    <div
      ref={wrap}
      style={{ position: "relative" }}
      onMouseMove={(e) => {
        const r = wrap.current!.getBoundingClientRect();
        const px = e.clientX - r.left;
        setCursor(px > GUTTER && px < width - RIGHT ? px : null);
      }}
      onMouseLeave={() => setCursor(null)}
    >
      <svg className="tl" width={width} height={height}>
        {/* lab lanes */}
        {data.series.map((s, i) => (
          <Lane key={s.code} s={s} i={i} x={x} width={width} pencil={pencilByCode[s.code] ?? []} highlight={highlight} show={show} hide={hide} onHover={onHover} corridor={corridor && corridor.code === s.code ? corridor : null} />
        ))}

        {/* medication lanes */}
        <text className="section" x={GUTTER - 168} y={medTop + 8}>
          MEDICATIONS
        </text>
        <line className="rule" x1={GUTTER} x2={width - RIGHT} y1={medTop + 14} y2={medTop + 14} />
        {meds.map((m, i) => {
          const y = medTop + 22 + i * MED_H;
          const color = MED_COLORS[i % MED_COLORS.length];
          const hi = highlight.has(m.id);
          return (
            <g key={m.id} onMouseEnter={() => onHover?.(m.id)} onMouseLeave={hide}>
              <line className="grid" x1={GUTTER} x2={width - RIGHT} y1={y + MED_H} y2={y + MED_H} />
              <text className={`med-name ${m.pencil ? "pencil" : ""}`} x={GUTTER - 168} y={y + 14.5}>
                {m.name.length > 26 ? m.name.slice(0, 25) + "…" : m.name}
              </text>
              {m.relation === "suspected_cause" && (
                <text className="relation cause" x={GUTTER - 8} y={y + 14.5} textAnchor="end">
                  cause?
                </text>
              )}
              {m.relation === "treats" && (
                <text className="relation" x={GUTTER - 8} y={y + 14.5} textAnchor="end">
                  treats
                </text>
              )}
              {m.segments.map((seg, j) => {
                const s = seg.start ?? data.window.start;
                const e = seg.end ?? data.window.end;
                if (day(e) < t0 || day(s) > t1) return null;
                const x0 = Math.max(GUTTER, x(s));
                const x1 = Math.min(width - RIGHT, x(e) + (seg.end ? 0 : 0));
                const w = Math.max(3, x1 - x0);
                const label = `${seg.dose ?? ""}${seg.frequency ? " · " + seg.frequency : ""}`;
                return (
                  <g
                    key={j}
                    onMouseMove={(ev) =>
                      show(
                        ev,
                        <>
                          <div className="t">{m.pencil ? "PROPOSED · " : ""}{fmt(s)} → {seg.end ? fmt(e) : "ongoing"}</div>
                          <div>
                            <b>{m.name}</b> {seg.dose} {seg.route} {seg.frequency}
                          </div>
                          {m.provenance.quote && <div className="q">{m.provenance.quote}</div>}
                        </>,
                      )
                    }
                  >
                    <rect className={`seg ${hi ? "hi" : ""} ${m.pencil ? "pencil" : ""}`} x={x0} y={y + 4} width={w} height={MED_H - 8} fill={m.pencil ? undefined : color} />
                    {j > 0 && m.segments[j - 1].end === seg.start && <line className="change" x1={x0} x2={x0} y1={y + 2} y2={y + MED_H - 2} />}
                    {w > 70 && !m.pencil && (
                      <text className="med-dose" x={x0 + 5} y={y + 14}>
                        {label.length > w / 6 ? label.slice(0, Math.floor(w / 6)) : label}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}

        {/* encounters + axis */}
        {(() => {
          const y = medTop + 22 + meds.length * MED_H + 6;
          const ay = y + ENC_H;
          return (
            <g>
              <text className="section" x={GUTTER - 168} y={y + 12}>
                ENCOUNTERS
              </text>
              {data.encounters.map((e) => (
                <EncMark key={e.id} e={e} x={x(e.time)} y={y} show={show} hide={hide} onOpen={onOpenNote} />
              ))}
              {(data.orders ?? []).map((o) => {
                const t = (o.ordered_at ?? o.created_at).slice(0, 10);
                const cx = x(t), cy = y + ENC_H / 2 + 2;
                return (
                  <g key={o.id} onMouseEnter={() => onHover?.(o.id)} onMouseLeave={hide}
                    onMouseMove={(ev) => show(ev, <><div className="t">ORDER · {o.id} · {t}</div><div><b>{o.name}</b> {o.detail}</div></>)}>
                    <polygon className={`order ${o.kind === "medication_change" ? "med" : ""} ${highlight.has(o.id) ? "hi" : ""}`}
                      points={`${cx},${cy - 6} ${cx + 6},${cy} ${cx},${cy + 6} ${cx - 6},${cy}`} />
                  </g>
                );
              })}
              <line className="rule" x1={GUTTER} x2={width - RIGHT} y1={ay} y2={ay} />
              {ticks.map((ms) => (
                <g key={ms}>
                  <line className="tick" x1={xms(ms)} x2={xms(ms)} y1={ay} y2={ay + 5} />
                  <text className="axis-label" x={xms(ms)} y={ay + 18} textAnchor="middle">
                    {fmtShort(ms)}
                  </text>
                </g>
              ))}
              <text className="axis-label" x={GUTTER} y={ay + 34}>
                {data.window.start}
              </text>
              <text className="axis-label" x={width - RIGHT} y={ay + 34} textAnchor="end">
                {data.window.end}
              </text>
            </g>
          );
        })()}

        {/* month grid lines behind everything would need ordering; keep light: */}
        {ticks.map((ms) => (
          <line key={"g" + ms} className="grid" x1={xms(ms)} x2={xms(ms)} y1={0} y2={medTop + 22 + meds.length * MED_H} pointerEvents="none" />
        ))}

        {todayX !== null && (
          <g pointerEvents="none">
            <line className="today" x1={todayX} x2={todayX} y1={0} y2={height - AXIS_H} />
            <text className="axis-label" x={todayX + 4} y={12}>today</text>
          </g>
        )}
        {cursor !== null && (
          <g pointerEvents="none">
            <line className="cursor" x1={cursor} x2={cursor} y1={0} y2={height - AXIS_H} />
            <text className="axis-label" x={cursor} y={height - AXIS_H + 30} textAnchor="middle" fill="var(--select)">
              {new Date(t0 + ((cursor - GUTTER) / (width - GUTTER - RIGHT)) * (t1 - t0)).toISOString().slice(0, 10)}
            </text>
          </g>
        )}
      </svg>
      {tip && (
        <div className="tip" style={{ left: tip.x, top: tip.y, width: tip.w }}>
          {tip.body}
        </div>
      )}
    </div>
  );
}

function Lane({
  s, i, x, width, pencil, highlight, show, hide, onHover, corridor,
}: {
  s: Series; i: number; x: (iso: string) => number; width: number; pencil: Observation[]; highlight: Set<string>;
  show: (e: React.MouseEvent, body: React.ReactNode) => void; hide: () => void; onHover?: (id: string | null) => void; corridor?: Corridor | null;
}) {
  const top = i * (LANE_H + LANE_GAP) + 8;
  const plotTop = top + 10;
  const plotH = LANE_H - 22;
  const vals = [...s.points.map((p) => p.value), ...pencil.map((p) => p.value)];
  if (corridor?.ref_value != null) vals.push(corridor.ref_value);
  if (corridor?.target_value != null) vals.push(corridor.target_value);
  const rr = s.reference_range;
  if (rr?.low != null) vals.push(rr.low);
  if (rr?.high != null) vals.push(rr.high);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.12;
  lo -= pad; hi += pad;
  const y = (v: number) => plotTop + plotH - ((v - lo) / (hi - lo)) * plotH;
  const out = (v: number) => (rr?.high != null && v > rr.high) || (rr?.low != null && v < rr.low);
  const path = s.points.map((p, k) => `${k ? "L" : "M"}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const t = s.trend;
  const delta = t.delta_pct != null ? `${t.delta_pct > 0 ? "+" : ""}${t.delta_pct.toFixed(0)}%` : "";
  const arrow = t.direction === "rising" ? "↗" : t.direction === "falling" ? "↘" : t.direction === "stable" ? "→" : "";
  const latestOut = t.latest ? out(t.latest.value) : false;
  // the newest proposal on this series that the transcript has reached
  const spoken = pencil.length ? pencil.reduce((a, b) => (a.effective_time > b.effective_time ? a : b)) : null;
  const bandTop = rr?.high != null ? y(Math.min(rr.high, hi)) : plotTop;
  const bandBot = rr?.low != null ? y(Math.max(rr.low, lo)) : plotTop + plotH;

  return (
    <g>
      <text className="lane-name" x={GUTTER - 168} y={top + 22}>
        {s.name}
      </text>
      <text className="lane-unit" x={GUTTER - 168} y={top + 36}>
        {s.unit} · {s.points.length} results
      </text>
      {/* A value just spoken is the one the clinician is thinking about, so it takes the headline — in the amber of
          something unsigned, with what the chart still holds kept underneath it rather than replaced. */}
      {t.latest && !spoken && (
        <>
          <text className="lane-latest" x={GUTTER - 168} y={top + 60} fill={latestOut ? "var(--flag)" : undefined}>
            {nice(t.latest.value)}
          </text>
          <text className={`lane-delta ${latestOut ? "flag" : ""}`} x={GUTTER - 168} y={top + 74}>
            {arrow} {delta} vs {t.baseline ? nice(t.baseline.value) : ""} · {t.latest.time.slice(0, 7)}
          </text>
        </>
      )}
      {spoken && (
        <g key={spoken.id} className="lane-heard">
          <text className="lane-latest pending" x={GUTTER - 168} y={top + 60}>{nice(spoken.value)}</text>
          <text className="lane-delta pending" x={GUTTER - 168} y={top + 74}>heard at this visit</text>
          {t.latest && (
            <text className="lane-was" x={GUTTER - 168} y={top + 86}>
              was {nice(t.latest.value)} · {t.latest.time.slice(0, 7)}
            </text>
          )}
        </g>
      )}
      {rr && (rr.low != null || rr.high != null) && <rect className="refband" x={GUTTER} y={bandTop} width={width - GUTTER - RIGHT} height={Math.max(0, bandBot - bandTop)} />}
      <line className="rule" x1={GUTTER} x2={width - RIGHT} y1={plotTop + plotH} y2={plotTop + plotH} />
      {rr?.high != null && rr.high < hi && (
        <text className="axis-label" x={width - RIGHT} y={y(rr.high) - 3} textAnchor="end">
          {nice(rr.high)}
        </text>
      )}
      <path className="line" d={path} />
      {corridor && corridor.ref_value != null && corridor.target_value != null && (() => {
        const x0 = x(corridor.since), x1 = x(corridor.by);
        const yRef = y(corridor.ref_value), yTarget = y(corridor.target_value);
        const label = `expected: ${corridor.direction} by ${fmt(corridor.by)} · ${corridor.status.replace("_", " ")}`;
        return (
          <g
            onMouseMove={(e) => show(e, <><div className="t">EXPECTATION · proposed by rules</div><div>{s.name} {corridor.direction} from {nice(corridor.ref_value!)} toward {nice(corridor.target_value!)} by {fmt(corridor.by)}: <b>{corridor.status.replace("_", " ")}</b></div></>)}
            onMouseLeave={hide}
          >
            <polygon className={`corridor ${corridor.status}`} points={`${x0.toFixed(1)},${yRef.toFixed(1)} ${x1.toFixed(1)},${yRef.toFixed(1)} ${x1.toFixed(1)},${yTarget.toFixed(1)}`} />
            <line className={`corridor-edge ${corridor.status}`} x1={x0} x2={x0} y1={plotTop} y2={plotTop + plotH} />
            <text className={`corridor-label ${corridor.status}`} x={x0 + 4} y={corridor.direction === "falling" ? Math.min(yTarget + 12, plotTop + plotH - 2) : Math.max(yTarget - 4, plotTop + 9)}>{label}</text>
          </g>
        );
      })()}
      {s.points.map((p) => (
        <circle
          key={p.id}
          className={`pt ${out(p.value) ? "out" : ""} ${highlight.has(p.id) ? "hi" : ""} ${corridor && day(p.time) > day(corridor.since) && (corridor.direction === "falling" ? p.value >= (corridor.ref_value ?? Infinity) : p.value <= (corridor.ref_value ?? -Infinity)) && day(p.time) > day(corridor.by) ? "mismatch" : ""}`}
          cx={x(p.time)}
          cy={y(p.value)}
          r={highlight.has(p.id) ? 5 : 3}
          onMouseEnter={() => onHover?.(p.id)}
          onMouseMove={(e) =>
            show(
              e,
              <>
                <div className="t">{p.id} · {fmt(p.time)}</div>
                <div>
                  <b>{s.name}</b> {nice(p.value)} {s.unit} {out(p.value) ? "· out of range" : ""}
                </div>
              </>,
            )
          }
          onMouseLeave={hide}
        />
      ))}
      {pencil.map((p) => (
        <circle
          key={p.id}
          className={`pt pencil ${highlight.has(p.id) ? "hi" : ""}`}
          cx={x(p.effective_time)}
          cy={y(p.value)}
          r={4.5}
          onMouseEnter={() => onHover?.(p.id)}
          onMouseMove={(e) =>
            show(
              e,
              <>
                <div className="t">PROPOSED · {p.id} · {fmt(p.effective_time)}</div>
                <div>
                  <b>{s.name}</b> {nice(p.value)} {s.unit}
                </div>
                {p.provenance.quote && <div className="q">{p.provenance.quote}</div>}
              </>,
            )
          }
          onMouseLeave={hide}
        />
      ))}
    </g>
  );
}

function EncMark({ e, x, y, show, hide, onOpen }: { e: Encounter; x: number; y: number; show: (ev: React.MouseEvent, b: React.ReactNode) => void; hide: () => void; onOpen?: (noteId: string) => void }) {
  return (
    <g
      style={{ cursor: e.note_id ? "pointer" : "default" }}
      onClick={() => e.note_id && onOpen?.(e.note_id)}
      onMouseMove={(ev) =>
        show(
          ev,
          <>
            <div className="t">{e.id} · {fmt(e.time)}{e.author ? ` · ${e.author}` : ""}</div>
            <div>
              <b>{e.type}</b> — {e.summary}
            </div>
            {e.excerpt && <div className="q">{e.excerpt.replace(/\s+/g, " ").slice(0, 140)}…</div>}
            {e.note_id && <div className="t">click to open the note</div>}
          </>,
        )
      }
      onMouseLeave={hide}
    >
      <rect x={x - 6} y={y} width={12} height={ENC_H} fill="transparent" />
      <line className={`enc ${e.has_findings ? "findings" : ""}`} x1={x} x2={x} y1={y + 8} y2={y + ENC_H - 4} />
      {e.has_findings && <circle className="enc-note" cx={x} cy={y + 6} r={3} />}
    </g>
  );
}
