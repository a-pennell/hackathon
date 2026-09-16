import { useState } from "react";
import type { Medication } from "./types";

export type IntentBody = { kind: string; text: string; course_id?: string; change?: "stop" | "dose_change"; dose?: string };
type Props = { courses?: Medication[]; busy: string | null; onSubmit: (body: IntentBody) => Promise<void> | void; compact?: boolean };

const KINDS: { key: string; label: string }[] = [
  { key: "therapeutic", label: "Treat" }, { key: "diagnostic", label: "Test" }, { key: "monitoring", label: "Monitor" },
  { key: "referral", label: "Refer" }, { key: "follow_up", label: "Follow up" }, { key: "education", label: "Educate" },
];
const HINT: Record<string, string> = {
  therapeutic: "what to start, stop or change", diagnostic: "the test; it is ordered as you sign", monitoring: "what to watch, and when",
  referral: "to whom, for what; the referral is placed as you sign", follow_up: "when, and what for", education: "what the patient was told",
};

/** A clinician's own decision on a problem: a typed line, signed as it is made and stamped with the visit. A diagnostic
 *  or referral line also places the order; a treat line can close or re-dose a course on the chart. It reaches the
 *  Care card, the workspace, the Timeline and the compiled visit note the moment it is added. */
export default function IntentForm({ courses = [], busy, onSubmit, compact }: Props) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("monitoring");
  const [text, setText] = useState("");
  const [course, setCourse] = useState("");
  const [change, setChange] = useState<"stop" | "dose_change">("stop");
  const [dose, setDose] = useState("");
  const active = courses.filter((m) => m.status === "accepted" && !m.segments[m.segments.length - 1]?.end);
  const submit = async () => {
    if (!text.trim()) return;
    const body: IntentBody = { kind, text: text.trim() };
    if (kind === "therapeutic" && course) { body.course_id = course; body.change = change; if (change === "dose_change" && dose.trim()) body.dose = dose.trim(); }
    await onSubmit(body);
    setText(""); setCourse(""); setDose(""); setOpen(false);
  };
  if (!open) return <button className={`btn small ${compact ? "ghost" : ""}`} disabled={!!busy} onClick={() => setOpen(true)} title="Your own decision on this problem: signed as you add it, in the visit note when it is drafted">+ Add to plan</button>;
  return (
    <form className="intent" onSubmit={(e) => { e.preventDefault(); submit(); }} onClick={(e) => e.stopPropagation()}>
      <div className="kinds" role="radiogroup" aria-label="Kind of plan item">
        {KINDS.map((k) => <button type="button" key={k.key} className={`code ${kind === k.key ? "on" : ""}`} aria-pressed={kind === k.key} onClick={() => setKind(k.key)}>{k.label}</button>)}
      </div>
      <input autoFocus value={text} placeholder={HINT[kind]} onChange={(e) => setText(e.target.value)} aria-label="Plan item" />
      {kind === "therapeutic" && active.length > 0 && (
        <div className="course-row">
          <select value={course} onChange={(e) => setCourse(e.target.value)} aria-label="Course on the chart">
            <option value="">no course change</option>
            {active.map((m) => <option key={m.id} value={m.id}>{m.name} {m.segments[m.segments.length - 1]?.dose ?? ""}</option>)}
          </select>
          {course && (
            <>
              <button type="button" className={`code ${change === "stop" ? "on" : ""}`} onClick={() => setChange("stop")}>stop</button>
              <button type="button" className={`code ${change === "dose_change" ? "on" : ""}`} onClick={() => setChange("dose_change")}>new dose</button>
              {change === "dose_change" && <input value={dose} placeholder="e.g. 50 mg" onChange={(e) => setDose(e.target.value)} aria-label="New dose" style={{ width: 90 }} />}
            </>
          )}
        </div>
      )}
      <div className="row">
        <span className="hint">signed by you as you add it · stamped with this visit</span>
        <span className="spacer" />
        <button type="button" className="btn small ghost" onClick={() => setOpen(false)}>Cancel</button>
        <button type="submit" className="btn small primary" disabled={!!busy || !text.trim()}>Sign and add</button>
      </div>
    </form>
  );
}
