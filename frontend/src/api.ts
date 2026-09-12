import type { NoteFile, PatientSummary, QueueBatch, Timeline } from "./types";

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
  review: (pid: string, stem: string, body: { accept?: string[]; reject?: string[]; accept_all?: boolean; accept_changes?: boolean }) =>
    req<{ done: string[] }>(`/api/patients/${pid}/queue/${stem}/review`, { method: "POST", body: JSON.stringify(body) }),
  extract: (pid: string, note_file: string, mode: "live" | "replay") =>
    req<QueueBatch>(`/api/patients/${pid}/extract`, { method: "POST", body: JSON.stringify({ note_file, mode }) }),
  reset: (pid: string) => req<{ restored: string; queues_cleared: string[] }>(`/api/patients/${pid}/reset`, { method: "POST" }),
  reason: (pid: string, problem_id: string, mode: "live" | "rules" | "replay", window: string) =>
    req<QueueBatch>(`/api/patients/${pid}/reason`, { method: "POST", body: JSON.stringify({ problem_id, mode, window }) }),
};
