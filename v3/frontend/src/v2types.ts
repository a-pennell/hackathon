import type { CardExpectation } from "./types";

export type Standing = "off_course" | "watch" | "good" | "unmonitored";
export type ProblemRow = {
  id: string; name: string; members: { id: string; name: string }[]; standing: Standing; standing_word: string; why: string;
  epistemic: string; lead: { text: string; detail: string; ids: string[] } | null; pending: number;
  expected: { statement: string; by: string; status: string } | null; next: string | null; last_change: string | null; onset: string | null; forecast: string | null; gaps: number;
};
export type NextAction = { kind: "read" | "review" | "sign" | "draft" | "sign-draft" | "done"; label: string; hint: string; note_id?: string; encounter_id?: string };
export type Listing = {
  patient: { id: string; name: string; dob: string; sex: string }; as_of: string; since: { date: string; why: string };
  here_for: { encounter: { id: string; time: string; type: string; summary: string } | null; note: { id: string; file: string; author: string; time: string; has_queue: boolean; has_replay: boolean; status?: string } | null };
  problems: ProblemRow[]; counts: Record<Standing, number>; next_action: NextAction; unattested: number; followup: { label: string; as_of: string; applied: boolean } | null;
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
    options: SimOption[];
    guidelines: Guideline[];
    change_course: { projection: Projection | null; projection_of: { code: string; name: string; unit: string | null; from: { value: number; time: string }; goal: number | null; note: string } | null; expected: CardExpectation | null; expected_moves: ExpectedMove[]; tripwires: { name: string; code: string; threshold: string; state: string; latest: { value: number; time: string }; ids: string[]; set_by?: string }[]; reconsider_if: string[] };
  };
  decisions: number; pending: number;
};
export type Band = { t: string; low: number; high: number };
export type SimOption = { id: string; label: string; kind: string; text: string; on_plan: boolean; effect: { low: number; high: number }; weeks: number; full_effect_by: string; points: Band[]; reaches_goal_by: string | null; source: string };
export type Projection = { options: string[]; labels: string[]; points: Band[]; weeks: number; full_effect_by: string; at_full_effect: { low: number; high: number }; reaches_goal_by: string | null; observed?: { value: number; time: string; status: string } };
export type ExpectedMove = {
  id: string; value: { code: string; name: string; unit: string }; trigger: { text: string; ids: string[] };
  baseline: { value: number; time: string; id: string }; because: string; expect: string; limit: number; by: string;
  not_expected: string; then: string; reference_range: { low: number; high: number } | null; inside_range: boolean;
  note: string; tested_by: { text: string; ids: string[] } | null;
  observed: { value: number; time: string; id: string; status: "within" | "beyond" } | null;
  source: string; counter: string | null; ids: string[];
};
export type Guideline = { id: string; text: string; source: string; status: "covered" | "gap"; ids: string[]; action: { kind: string; text: string } | null };
export type NoteSection = { heading: string; text: string; cites: string[]; source?: string; edited?: boolean; collapsed?: boolean; problem_id?: string };
export type NoteDoc = { id: string; title: string; sections: NoteSection[]; status: string; problems_addressed?: string[]; review?: { by: string; at: string }; created_at: string };
export type ManifestGroup = { kind: string; label: string; count: number; items: { id: string; text: string; attested: boolean | null }[] };
export type NoteView = { encounter: { id: string; time: string; type: string; summary: string }; signed: NoteDoc | null; draft: NoteDoc | null; compiled: NoteDoc; manifest: ManifestGroup[] };

/* v3: the visit as one surface */
export type Utterance = { i: number; start: number; end: number; text: string };
export type Proposal = { id: string; kind: string; text: string; problems: string[]; quote: string | null; offset: number | null; decision: boolean; origin: "stated" | "inferred"; status: string; link_ids: string[]; cause_link_ids?: string[]; stem: string; change?: boolean };
export type VisitData = {
  note: { id: string; author: string; time: string; status?: string; read: boolean; file: string };
  encounter: { id: string; time: string; type: string; summary: string } | null;
  utterances: Utterance[]; text: string; proposals: Proposal[]; problems: ProblemRow[]; counts: Record<Standing, number>; next_action: NextAction; unattested: number;
  followup: { label: string; as_of: string; applied: boolean } | null;
};
