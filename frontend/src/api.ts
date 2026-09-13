import type { Brief, Coding, NoteFile, PatientSummary, QueueBatch, Timeline, TrailEntry } from "./types";

export type ReviewBody = { accept?: string[]; reject?: string[]; accept_all?: boolean; accept_changes?: boolean; reason?: string; reason_code?: string; by?: string };

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  patient: (pid: string) => req<PatientSummary>(`/api/patients/${pid}`),
  timeline: (pid: string, prob: string, window: string) =>
    req<Timeline>(`/api/patients/${pid}/problems/${prob}/timeline?window=${window}`),
  queue: (pid: string) => req<QueueBatch[]>(`/api/patients/${pid}/queue`),
  notes: () => req<NoteFile[]>(`/api/notes`),
  note: (pid: string, note_id: string) => req<NoteFile>(`/api/patients/${pid}/notes/${note_id}`),
  review: (pid: string, stem: string, body: ReviewBody) =>
    req<{ done: string[] }>(`/api/patients/${pid}/queue/${stem}/review`, { method: "POST", body: JSON.stringify(body) }),
  extract: (pid: string, note_file: string, mode: "live" | "replay") =>
    req<QueueBatch>(`/api/patients/${pid}/extract`, { method: "POST", body: JSON.stringify({ note_file, mode }) }),
  compose: (pid: string, problem_id: string, kind: string, audience: string, mode: "live" | "replay", window: string) =>
    req<QueueBatch>(`/api/patients/${pid}/compose`, { method: "POST", body: JSON.stringify({ problem_id, kind, audience, mode, window }) }),
  brief: (pid: string, prob: string, window = "90d") => req<Brief>(`/api/patients/${pid}/problems/${prob}/brief?window=${window}`),
  briefLive: (pid: string, prob: string, mode: "live" | "replay", window = "90d") =>
    req<Brief>(`/api/patients/${pid}/problems/${prob}/brief`, { method: "POST", body: JSON.stringify({ mode, window }) }),
  trail: (pid: string, prob: string) => req<TrailEntry[]>(`/api/patients/${pid}/problems/${prob}/trail`),
  orders: (pid: string, problem_id: string, mode: "live" | "replay", window: string) =>
    req<QueueBatch>(`/api/patients/${pid}/orders`, { method: "POST", body: JSON.stringify({ problem_id, mode, window }) }),
  coding: (pid: string) => req<Coding>(`/api/patients/${pid}/coding`),
  reset: (pid: string) => req<{ restored: string; queues_cleared: string[] }>(`/api/patients/${pid}/reset`, { method: "POST" }),
  reason: (pid: string, problem_id: string, mode: "live" | "rules" | "replay", window: string) =>
    req<QueueBatch>(`/api/patients/${pid}/reason`, { method: "POST", body: JSON.stringify({ problem_id, mode, window }) }),
};
