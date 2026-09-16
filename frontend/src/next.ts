import { buildGroups } from "./Inbox";
import type { NoteFile, Overview, PatientSummary, QueueBatch } from "./types";

/** The one thing the clinician should do next, computed from chart state. Shown in the patient header.
 *  The order is the visit's order: read the note, decide what it proposed, sign it, ask what changed on
 *  the concern that needs it, sign the insights, draft and sign the orders. When nothing is owed, say so. */
export type NextAction = {
  label: string;
  hint: string;
  kind: "read" | "review" | "sign" | "reason" | "sign-insights" | "orders" | "sign-orders" | "draft" | "finish-draft" | "done";
  noteId?: string;
  encounterId?: string;
  notesScope?: "patient" | "mine";  // what the Notes tab shows when the button opens it
  problemId?: string;
};

/** Decisions waiting on a note, counted the way the Note view shows them: one per card, not one per link. */
export const waitingIn = (b: QueueBatch | undefined) =>
  b ? buildGroups(b, (id) => id, new Set()).filter((g) => g.status === "proposed" && !(g.subject && g.subject.status === "rejected")).length + (b.medication_changes ?? []).filter((c) => c.status === "proposed").length : 0;

export function nextAction(overview: Overview | null, notes: NoteFile[], queues: QueueBatch[], summary: PatientSummary | null): NextAction {
  const here = overview?.here_for.note;
  if (here) {
    const note = notes.find((n) => n.id === here.id);
    const batch = queues.find((b) => b.note_id === here.id);
    if (!batch) return { label: "Read the note", hint: `${note?.author ? note.author + "’s" : "The"} note from this visit has not been read`, kind: "read", noteId: here.id };
    const waiting = waitingIn(batch);
    if (waiting > 0) return { label: `Review the note · ${waiting}`, hint: "decide what it proposed, then sign it", kind: "review", noteId: here.id };
    if (note?.status !== "signed") return { label: "Sign the note", hint: "everything it proposed is decided", kind: "sign", noteId: here.id };
  }
  const concerns = overview?.concerns.filter((c) => c.monitored) ?? [];
  for (const c of concerns) {
    const short = c.name.replace("Essential ", "").replace("Diabetes mellitus type 2", "diabetes").replace("Chronic kidney disease", "CKD").replace("Chronic congestive heart failure", "heart failure").toLowerCase().replace("ckd", "CKD");
    const reason = queues.find((b) => b.stem === `reason_${c.id}`);
    const pendingInsights = reason ? (reason.proposed.insights ?? []).filter((i) => i.status === "proposed").length : 0;
    if (pendingInsights > 0) return { label: `Sign ${pendingInsights} insight${pendingInsights > 1 ? "s" : ""} on ${short}`, hint: "the reasoning is waiting for your signature", kind: "sign-insights", problemId: c.id };
    const signedInsights = (summary?.insights ?? []).filter((i) => i.problem_id === c.id && i.status === "accepted").length;
    if (!reason && signedInsights === 0 && (c.qualifiers.includes("worsening") || c.qualifiers.includes("unexpected") || c.pending > 0)) {
      return { label: `Ask what changed on ${short}`, hint: "the concern is moving and nothing has reasoned over it", kind: "reason", problemId: c.id };
    }
    const orders = queues.find((b) => b.stem === `orders_${c.id}`);
    const pendingOrders = orders ? (orders.proposed.orders ?? []).filter((o) => o.status === "proposed").length : 0;
    if (pendingOrders > 0) return { label: `Sign ${pendingOrders} order${pendingOrders > 1 ? "s" : ""} on ${short}`, kind: "sign-orders", hint: "orders drafted from the signed insights", problemId: c.id };
    const signedOrders = (summary?.orders ?? []).filter((o) => o.problem_id === c.id).length;
    if (signedInsights > 0 && !orders && signedOrders === 0) return { label: `Draft orders for ${short}`, hint: "turn the signed actions into orders", kind: "orders", problemId: c.id };
  }
  // The visit note: once the transcript is signed and every concern is settled, the visit's decisions compile into
  // a draft the clinician edits and signs. Only for a visit that had a transcript (the composer for a blank visit
  // is PRD-06).
  const enc = overview?.here_for.encounter;
  if (enc && here && notes.find((n) => n.id === here.id)?.status === "signed") {
    const signedVisitNote = (summary?.documents ?? []).some((d) => d.kind === "encounter_note" && d.encounter_id === enc.id);
    if (!signedVisitNote) {
      const draft = queues.find((b) => b.stem === `visitnote_${enc.id}`);
      if (draft) return { label: "Finish the visit note", hint: "the draft is compiled from what you did at this visit; edit it, then sign", kind: "finish-draft", encounterId: enc.id };
      return { label: "Draft the visit note", hint: "compiled from what you did at this visit; every sentence cites the record", kind: "draft", encounterId: enc.id };
    }
  }
  // Nothing owed here. The idle state is the clinician's documentation debt, not the patient's: unsigned notes on
  // other patients come first, and only then "nothing owed".
  const elsewhere = notes.filter((n) => n.patient_id !== summary?.patient.id && n.status !== "signed").length;
  if (elsewhere > 0) return { label: `Unsigned notes · ${elsewhere}`, hint: "nothing is owed on this patient; these notes on other patients are still unsigned", kind: "done", notesScope: "mine" };
  return { label: "Nothing owed", hint: "the visit is documented; results will reopen loops when they land. Opens the notes on file", kind: "done", notesScope: "patient" };
}
