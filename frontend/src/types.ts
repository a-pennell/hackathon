export type Provenance = {
  source: "fhir_import" | "nlp_extraction" | "reasoning";
  note_id?: string;
  quote?: string;
  model?: string;
  confidence?: number;
  trend_codes?: string[];
};

export type Patient = { id: string; name: string; dob: string; sex: string };

export type Problem = {
  id: string;
  name: string;
  status: "active" | "resolved" | "proposed";
  onset_date: string | null;
  resolved_date: string | null;
  provenance: Provenance;
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
  };
  confirmed_medications?: { med_id: string; quote: string; confidence: number }[];
  medication_changes?: { med_id: string; change: string; effective: string; status: string; provenance: Provenance }[];
  review_hints?: Record<string, string>;
  rejected: { kind?: string; reason: string }[];
};

export type NoteFile = {
  file: string;
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
};
