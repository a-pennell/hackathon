import type { CardExpectation } from "./types";

export type Standing = "off_course" | "watch" | "good" | "unmonitored";
export type ProblemRow = {
  id: string; name: string; members: { id: string; name: string }[]; standing: Standing; standing_word: string; why: string;
  epistemic: string; lead: { text: string; detail: string; ids: string[] } | null; pending: number;
  expected: { statement: string; by: string; status: string } | null; next: string | null; last_change: string | null; onset: string | null;
};
export type NextAction = { kind: "read" | "review" | "sign" | "draft" | "sign-draft" | "done"; label: string; hint: string; note_id?: string; encounter_id?: string };
export type Listing = {
  patient: { id: string; name: string; dob: string; sex: string }; as_of: string; since: { date: string; why: string };
  here_for: { encounter: { id: string; time: string; type: string; summary: string } | null; note: { id: string; file: string; author: string; time: string; has_queue: boolean; has_replay: boolean; status?: string } | null };
  problems: ProblemRow[]; counts: Record<Standing, number>; next_action: NextAction; unattested: number;
};
export type Line = { text: string; detail?: string; ids: string[]; source?: string; kind?: string; valence?: string };
export type Detected = { id: string; text: string; ids: string[]; code: string | null; acknowledged: boolean };
export type ProblemView = {
  problem: { id: string; name: string; standing: Standing; standing_word: string; why: string; epistemic: { value: string; why: string }; qualifiers: { label: string; why: string }[]; steward: { name: string; role?: string } | string | null; onset: string | null; members: { id: string; name: string }[] };
  window: { start: string; end: string }; as_of: string;
  answers: {
    happening: Line[];
    means: { text: string; cites: string[]; epistemic: { value: string; why: string }; causes: { text: string; ids: string[]; signed: boolean }[]; insights: { id: string; text: string; action: string | null; ids: string[]; status: string; source?: string; confidence?: number }[] };
    changed: { since: string; lines: Line[]; detected: Detected[] };
    doing: { plan: { id: string; plan_kind: string; text: string; detail: string; status: string; ids: string[] }[]; linked: { rel: string; id: string; text: string; detail: string; ids: string[] }[]; loops: { id: string; kind: string; text: string; detail: string; status: string; problem_id: string }[] };
    uncertain: Line[];
    next: Line[];
    change_course: { expected: CardExpectation | null; tripwires: { name: string; code: string; threshold: string; state: string; latest: { value: number; time: string }; ids: string[] }[]; reconsider_if: string[] };
  };
  decisions: number; pending: number;
};
export type NoteSection = { heading: string; text: string; cites: string[]; source?: string; edited?: boolean; collapsed?: boolean; problem_id?: string };
export type NoteDoc = { id: string; title: string; sections: NoteSection[]; status: string; problems_addressed?: string[]; review?: { by: string; at: string }; created_at: string };
export type ManifestGroup = { kind: string; label: string; count: number; items: { id: string; text: string; attested: boolean | null }[] };
export type NoteView = { encounter: { id: string; time: string; type: string; summary: string }; signed: NoteDoc | null; draft: NoteDoc | null; compiled: NoteDoc; manifest: ManifestGroup[] };
