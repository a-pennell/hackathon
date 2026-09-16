import type { Brief, Card, CareData, ChartData, Coding, Overview, PatientRow, RecordEvent, NoteFile, PatientSummary, QueueBatch, Timeline, TrailEntry, TimelineData } from "./types";

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
  patients: () => req<PatientRow[]>(`/api/patients`),
  patient: (pid: string) => req<PatientSummary>(`/api/patients/${pid}`),
  chart: (pid: string) => req<ChartData>(`/api/patients/${pid}/chart`),
  care: (pid: string) => req<CareData>(`/api/patients/${pid}/care`),
  timeline: (pid: string, prob: string, window: string) =>
    req<Timeline>(`/api/patients/${pid}/problems/${prob}/timeline?window=${window}`),
  queue: (pid: string) => req<{ batches: QueueBatch[]; labels: Record<string, string> }>(`/api/patients/${pid}/queue`),
  notes: () => req<NoteFile[]>(`/api/notes`),
  note: (pid: string, note_id: string) => req<NoteFile>(`/api/patients/${pid}/notes/${note_id}`),
  review: (pid: string, stem: string, body: ReviewBody) =>
    req<{ done: string[]; decided: string[] }>(`/api/patients/${pid}/queue/${stem}/review`, { method: "POST", body: JSON.stringify(body) }),
  extract: (pid: string, note_file: string, mode: "live" | "replay") =>
    req<QueueBatch>(`/api/patients/${pid}/extract`, { method: "POST", body: JSON.stringify({ note_file, mode }) }),
  compose: (pid: string, problem_id: string, kind: string, audience: string, mode: "live" | "replay", window: string) =>
    req<QueueBatch>(`/api/patients/${pid}/compose`, { method: "POST", body: JSON.stringify({ problem_id, kind, audience, mode, window }) }),
  brief: (pid: string, prob: string, window = "90d") => req<Brief>(`/api/patients/${pid}/problems/${prob}/brief?window=${window}`),
  briefLive: (pid: string, prob: string, mode: "live" | "replay", window = "90d") =>
    req<Brief>(`/api/patients/${pid}/problems/${prob}/brief`, { method: "POST", body: JSON.stringify({ mode, window }) }),
  overview: (pid: string) => req<Overview>(`/api/patients/${pid}/overview`),
  card: (pid: string, prob: string, window = "1y") => req<Card>(`/api/patients/${pid}/problems/${prob}/card?window=${window}`),
  trail: (pid: string, prob: string) => req<TrailEntry[]>(`/api/patients/${pid}/problems/${prob}/trail`),
  orders: (pid: string, problem_id: string, mode: "live" | "replay", window: string) =>
    req<QueueBatch>(`/api/patients/${pid}/orders`, { method: "POST", body: JSON.stringify({ problem_id, mode, window }) }),
  coding: (pid: string) => req<Coding>(`/api/patients/${pid}/coding`),
  undo: (pid: string, stem: string, ids: string[]) =>
    req<{ done: string[] }>(`/api/patients/${pid}/queue/${stem}/undo`, { method: "POST", body: JSON.stringify({ ids }) }),
  signNote: (pid: string, note_id: string) => req<{ note_id: string; signed_at: string; by: string; done: string[] }>(`/api/patients/${pid}/notes/${note_id}/sign`, { method: "POST", body: JSON.stringify({}) }),
  timelineTab: (pid: string) => req<TimelineData>(`/api/patients/${pid}/timeline`),
  record: (pid: string, note_id?: string, problem_id?: string) => req<RecordEvent[]>(`/api/patients/${pid}/record${note_id ? `?note_id=${note_id}` : problem_id ? `?problem_id=${problem_id}` : ""}`),
  reset: (pid: string) => req<{ restored: string; queues_cleared: string[] }>(`/api/patients/${pid}/reset`, { method: "POST" }),
  reason: (pid: string, problem_id: string, mode: "live" | "rules" | "replay", window: string) =>
    req<QueueBatch>(`/api/patients/${pid}/reason`, { method: "POST", body: JSON.stringify({ problem_id, mode, window }) }),
};
