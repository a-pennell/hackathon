import { useState } from "react";
import type { Medication } from "./types";

export type IntentDestination = "note" | "treatment_plan" | "both";
export type IntentBody = { kind: string; text: string; destination: IntentDestination; encounter_id?: string; course_id?: string; change?: "stop" | "dose_change"; dose?: string };
type Props = { courses?: Medication[]; busy: string | null; onSubmit: (body: IntentBody) => Promise<void> | void; compact?: boolean };

const KINDS: { key: string; label: string }[] = [
  { key: "therapeutic", label: "Treat" }, { key: "diagnostic", label: "Test" }, { key: "monitoring", label: "Monitor" },
  { key: "referral", label: "Refer" }, { key: "follow_up", label: "Follow up" }, { key: "education", label: "Educate" },
];
const HINT: Record<string, string> = {
  therapeutic: "what to start, stop or change", diagnostic: "the test", monitoring: "what to watch, and when",
  referral: "to whom, for what", follow_up: "when, and what for", education: "what the patient was told",
};

export default function IntentForm({ courses = [], busy, onSubmit, compact }: Props) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("monitoring");
  const [text, setText] = useState("");
  const [course, setCourse] = useState("");
  const [change, setChange] = useState<"stop" | "dose_change">("stop");
  const [dose, setDose] = useState("");
  const [destination, setDestination] = useState<IntentDestination>("note");
  const [error, setError] = useState<string | null>(null);
  const isNoteOnly = destination === "note";
  const active = courses.filter((m) => m.status === "accepted" && !m.segments[m.segments.length - 1]?.end);
  const submit = async () => {
    if (!text.trim()) return;
    const body: IntentBody = { kind, text: text.trim(), destination };
    if (!isNoteOnly && kind === "therapeutic" && course) { body.course_id = course; body.change = change; if (change === "dose_change" && dose.trim()) body.dose = dose.trim(); }
    setError(null);
    try {
      await onSubmit(body);
      setText(""); setCourse(""); setDose(""); setDestination("note"); setOpen(false);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to add this item. Try again."); }
  };
  if (!open) return <button className={`btn small ${compact ? "ghost" : ""}`} disabled={!!busy} onClick={() => setOpen(true)}>+ Add plan item</button>;
  return (
    <form className="intent" onSubmit={(e) => { e.preventDefault(); submit(); }} onClick={(e) => e.stopPropagation()}>
      <fieldset className="intent-destination" disabled={!!busy}>
        <legend>Add to</legend>
        <div>
          {([{ value: "note", label: "Note: Plan" }, { value: "treatment_plan", label: "Treatment plan" }, { value: "both", label: "Both" }] as const).map((option) => (
            <label key={option.value} className={destination === option.value ? "selected" : ""}>
              <input type="radio" name="destination" value={option.value} checked={destination === option.value} onChange={() => { setDestination(option.value); setCourse(""); setDose(""); setError(null); }} />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="kinds" role="radiogroup" aria-label="Kind of plan item">
        {KINDS.map((k) => <button type="button" key={k.key} className={`code ${kind === k.key ? "on" : ""}`} aria-pressed={kind === k.key} onClick={() => setKind(k.key)}>{k.label}</button>)}
      </div>
      <input autoFocus value={text} placeholder={HINT[kind]} onChange={(e) => setText(e.target.value)} aria-label="Plan item" />
      {!isNoteOnly && kind === "therapeutic" && active.length > 0 && (
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
      <div className="intent-impact" role="status">
        {isNoteOnly ? "Unsigned note text only. No treatment-plan or order changes." : destination === "both" ? "Signed treatment plan + unsigned Note: Plan text." : "Signed treatment plan only. Not added to Note: Plan."}
        {!isNoteOnly && kind === "diagnostic" && <strong> Includes a signed lab order.</strong>}
        {!isNoteOnly && kind === "referral" && <strong> Includes a signed referral.</strong>}
        {!isNoteOnly && kind === "therapeutic" && course && <strong> Includes a medication {change === "stop" ? "stop" : "dose change"}.</strong>}
      </div>
      {error && <p className="intent-error" role="alert">{error}</p>}
      <div className="row">
        <span className="spacer" />
        <button type="button" className="btn small ghost" onClick={() => setOpen(false)}>Cancel</button>
        <button type="submit" className="btn small primary" disabled={!!busy || !text.trim() || (!isNoteOnly && kind === "therapeutic" && !!course && change === "dose_change" && !dose.trim())}>{isNoteOnly ? "Add to note" : destination === "both" ? "Sign and add to both" : "Sign treatment plan"}</button>
      </div>
    </form>
  );
}
