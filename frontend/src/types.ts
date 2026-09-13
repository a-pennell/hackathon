export type Provenance = {
  source: "fhir_import" | "nlp_extraction" | "reasoning";
  note_id?: string;
  quote?: string;
  model?: string;
  confidence?: number;
  trend_codes?: string[];
};

export type Patient = { id: string; name: string; dob: string; sex: string };

export type Review = { by: string; at: string; decision: "accepted" | "rejected"; reason_code: string | null; reason: string | null };
export const REASON_CODES: { code: string; label: string }[] = [
  { code: "already_known", label: "Already known" },
  { code: "not_relevant", label: "Not relevant here" },
  { code: "disagree", label: "Disagree" },
  { code: "needs_confirmation", label: "Needs confirmation" },
  { code: "other", label: "Other" },
];

export type DocSection = { heading: string; text: string; cites: string[] };
export type Document = {
  id: string;
  patient_id: string;
  problem_id: string;
  kind: string;
  audience: string;
  title: string;
  sections: DocSection[];
  questions: string[];
  status: string;
  provenance: Provenance & { evidence?: string[] };
  created_at: string;
  review?: Review;
  queue?: string;
};

export type Problem = {
  id: string;
  name: string;
  status: "active" | "resolved" | "proposed";
  onset_date: string | null;
  resolved_date: string | null;
  provenance: Provenance;
  review?: Review;
  monitored_codes?: string[];
  note_links?: number;
};

export type Segment = { start: string | null; end: string | null; dose: string | null; route: string | null; frequency: string | null };

export type Medication = {
  id: string;
  name: string;
  segments: Segment[];
  status: string;
  provenance: Provenance;
  review?: Review;
  relation?: "treats" | "suspected_cause" | "on_board";
  queue?: string;
};

export type Point = { id: string; time: string; value: number; source: string };

export type Trend = {
  code: string;
  name: string;
  n_points: number;
  latest: { value: number; time: string } | null;
  baseline: { value: number; time: string } | null;
  delta_abs: number | null;
  delta_pct: number | null;
  slope_per_week: number | null;
  direction: string;
  ref_range_crossing: { crossed: string; at: string } | null;
  events_in_window: { kind: string; med_id: string; name: string; time: string }[];
};

export type Series = {
  code: string;
  name: string;
  unit: string | null;
  reference_range: { low: number | null; high: number | null } | null;
  points: Point[];
  trend: Trend;
};

export type Encounter = {
  id: string;
  time: string;
  type: string;
  summary: string;
  note_id: string | null;
  author: string | null;
  has_findings: boolean;
  excerpt: string | null;
};

export type Link = {
  id: string;
  from: string;
  to: string;
  type: string;
  status: string;
  provenance: Provenance;
  created_at: string;
  review?: Review;
  queue?: string;
};

export type Observation = {
  id: string;
  code: { system: string; value: string };
  name: string;
  value: number;
  unit: string | null;
  effective_time: string;
  status: string;
  provenance: Provenance;
  review?: Review;
  queue?: string;
};

export type Insight = {
  id: string;
  problem_id: string;
  statement: string;
  evidence: string[];
  suggested_action: string;
  status: string;
  provenance: Provenance;
  created_at: string;
  review?: Review;
  queue?: string;
};

export type Timeline = {
  patient: Patient;
  problem: Problem;
  window: { start: string; end: string };
  series: Series[];
  medications: Medication[];
  encounters: Encounter[];
  links: Link[];
  insights: Insight[];
  orders: Order[];
  proposed: {
    observations: Observation[];
    medications: Medication[];
    links: Link[];
    insights: Insight[];
    problems: Problem[];
  };
};

export type QueueBatch = {
  stem: string;
  patient_id: string;
  note_id?: string;
  problem_id?: string;
  model: string;
  extracted_at?: string;
  reasoned_at?: string;
  proposed: {
    problems?: Problem[];
    observations?: Observation[];
    medications?: Medication[];
    links?: Link[];
    insights?: Insight[];
    documents?: Document[];
    orders?: Order[];
  };
  ordered_at?: string;
  kind?: string;
  audience?: string;
  composed_at?: string;
  confirmed_medications?: { med_id: string; quote: string; confidence: number }[];
  medication_changes?: { med_id: string; change: string; effective: string; status: string; provenance: Provenance; dose?: string | null; hint?: string; review?: Review }[];
  review_hints?: Record<string, string>;
  rejected: { kind?: string; reason: string }[];
};

export type NoteFile = {
  file: string | null; // null for a chart note that has no file under data/notes
  id: string;
  patient_id: string;
  time: string;
  author: string;
  excerpt: string;
  text: string;
  has_replay: boolean;
  has_queue: boolean;
};

export type PatientSummary = {
  patient: Patient;
  problems: Problem[];
  counts: Record<string, number>;
  insights: Insight[];
  documents: Document[];
  orders: Order[];
};

export type BriefLine = { kind: string; text: string; ids: string[]; code?: string };
export type Brief = {
  patient_id: string;
  problem_id: string;
  window: { start: string; end: string };
  source: string; // "computed" or "brief-v1/<model>"
  lines: BriefLine[];
  pending: number;
  dropped_citations?: string[];
};

export type TrailEntry = {
  id: string;
  kind: string;
  what: string;
  queue: string | null;
  source: string | null;
  confidence: number | null;
  quote: string | null;
  decision: "accepted" | "rejected" | "pending";
  reason_code: string | null;
  reason: string | null;
  by: string | null;
  at: string;
};

export type Order = {
  id: string;
  patient_id: string;
  problem_id: string;
  kind: "lab" | "medication_change" | "referral" | "imaging";
  name: string;
  detail: string;
  code: { system: string; value: string } | null;
  med_id: string | null;
  change: "stop" | "dose_change" | null;
  dose: string | null;
  audience: string | null;
  status: string;
  provenance: Provenance & { from_insight?: string; evidence?: string[] };
  created_at: string;
  ordered_at?: string;
  review?: Review;
  queue?: string;
};

export type Coding = {
  patient_id: string;
  encounter_id: string | null;
  date: string;
  status: "computed";
  problems_addressed: { problem_id: string; name: string; evidence: string[]; complexity?: string }[];
  mdm: {
    problems: { level: string; why: string[] };
    data: { level: string; why: string[] };
    risk: { level: string; why: string[] };
    level: string;
    cpt: string;
    rule: string;
  };
  diagnosis_codes: { problem_id: string | null; name: string; code: string | null; description: string; mapping: string; evidence?: string[] }[];
  signed_today: number;
};
