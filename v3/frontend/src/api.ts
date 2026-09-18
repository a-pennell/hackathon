import type { QueueBatch, Timeline } from "./types";
import type { Listing, ManifestGroup, NoteDoc, NoteView, ProblemView, VisitData } from "./v2types";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep msg */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}
const post = (body?: unknown) => ({ method: "POST", body: JSON.stringify(body ?? {}) });

// The date the chart is read as of: null is today; the demo's follow-up sets it two weeks on.
let AS_OF: string | null = null;
export const setAsOf = (d: string | null) => { AS_OF = d; };
const q = (first = true) => (AS_OF ? `${first ? "?" : "&"}as_of=${AS_OF}` : "");

export const api = {
  patients: () => req<{ id: string; name: string }[]>("/api/patients"),
  problems: (pid: string) => req<Listing>(`/v2/api/patients/${pid}/problems${q()}`),
  visit: (pid: string) => req<VisitData>(`/v3/api/patients/${pid}/visit${q()}`),
  signVisit: (pid: string, body: { decisions: Record<string, string>; reasons: Record<string, string>; authored: string; sections?: { heading: string; text: string }[] }) => req<{ document_id: string; attested: number }>(`/v3/api/patients/${pid}/visit/sign${q()}`, post(body)),
  previewVisit: (pid: string, body: { decisions: Record<string, string>; reasons: Record<string, string>; authored: string; sections?: { heading: string; text: string }[] }) => req<{ document: NoteDoc; manifest: ManifestGroup[] }>(`/v3/api/patients/${pid}/visit/preview${q()}`, post(body)),
  problem: (pid: string, prob: string) => req<ProblemView>(`/v2/api/patients/${pid}/problems/${prob}${q()}`),
  trajectory: (pid: string, prob: string) => req<Timeline>(`/api/patients/${pid}/problems/${prob}/timeline?window=9m${q(false)}`),
  advance: (pid: string) => req<{ as_of: string; label: string }>(`/v2/api/patients/${pid}/advance`, post()),
  acknowledge: (pid: string, prob: string, text: string, ids: string[]) => req<{ insight_id: string }>(`/v2/api/patients/${pid}/problems/${prob}/acknowledge`, post({ text, ids })),
  intent: (pid: string, prob: string, kind: string, text: string) => req<{ plan_id: string }>(`/api/patients/${pid}/problems/${prob}/intents`, post({ kind, text })),
  note: (pid: string) => req<NoteView>(`/v2/api/patients/${pid}/note${q()}`),
  signVisitNote: (pid: string, sections: { heading: string; text: string }[], authored: string) => req<{ document_id: string }>(`/v2/api/patients/${pid}/note/sign`, post({ sections, authored })),
  queue: (pid: string) => req<{ batches: QueueBatch[]; labels: Record<string, string> }>(`/api/patients/${pid}/queue`),
  readNote: (pid: string, note_file: string) => req<unknown>(`/api/patients/${pid}/extract`, post({ note_file, mode: "replay" })),
  review: (pid: string, stem: string, body: { accept?: string[]; reject?: string[]; reason?: string; reason_code?: string; accept_changes?: boolean }) => req<{ decided: string[] }>(`/api/patients/${pid}/queue/${stem}/review`, post(body)),
  signNote: (pid: string, note_id: string) => req<{ by: string }>(`/api/patients/${pid}/notes/${note_id}/sign`, post({})),
  reason: (pid: string, prob: string) => req<unknown>(`/api/patients/${pid}/reason`, post({ problem_id: prob, mode: "replay", window: "1y" })),
  reset: (pid: string) => req<unknown>(`/api/patients/${pid}/reset`, post()),
};
