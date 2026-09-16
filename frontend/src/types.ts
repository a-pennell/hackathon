export type Provenance = {
  source: "fhir_import" | "nlp_extraction" | "reasoning" | "clinician";
  note_id?: string;
  quote?: string;
  model?: string;
  confidence?: number;
  trend_codes?: string[];
};

export type Patient = { id: string; name: string; dob: string; sex: string };

export type Review = { by: string; at: string; decision: "accepted" | "rejected"; reason_code: string | null; reason: string | null };
export type Amendment = { id: string; by: string; at: string; reason: string; text: string };
export type CorrectionAction = "entered_in_error" | "stop" | "resolve" | "cancel" | "end_plan" | "amend";
export type CorrectionItem = { id: string; kind: string; label: string; actions: CorrectionAction[]; item: Record<string, unknown> };
export type Correction = Amendment & { action: CorrectionAction; item_id: string; kind: string; label: string; effective: string; before: Record<string, unknown>; after: Record<string, unknown> | null; related: { id: string; kind: string; label: string }[] };
export type CorrectionPreview = { revision: string; kind: string; action: CorrectionAction; item: Record<string, unknown>; withdrawn: { id: string; kind: string; label: string }[]; related: { id: string; kind: string; label: string }[]; warnings: string[]; blockers: string[] };
export const REASON_CODES: { code: string; label: string }[] = [
  { code: "already_known", label: "Already known" },
  { code: "not_relevant", label: "Not relevant here" },
  { code: "disagree", label: "Disagree" },
  { code: "needs_confirmation", label: "Needs confirmation" },
  { code: "other", label: "Other" },
];

export type DocSection = { key?: string; heading: string; text: string; cites: string[]; source?: "transcript" | "compiled"; edited?: boolean; problem_id?: string };
export type DraftEdit = { key: string; heading: string; text: string };
export type DraftUpdates = { revision: string; changes: { key: string; heading: string; current: DocSection | null; incoming: DocSection | null; conflict: boolean; kind: "added" | "removed" | "changed" }[] };
export type DraftResolution = { choice: "keep" | "update" | "edit"; text?: string };
export type Document = {
  amendments?: Amendment[];
  id: string;
  patient_id: string;
  problem_id: string | null;   // null for a visit note, which addresses several problems
  encounter_id?: string;       // visit notes (ehr/draft.py)
  problems_addressed?: string[];
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
  code?: { system: string; value: string } | null;
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
  kind?: "assessment" | "representation";
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
  draft_revision?: string;
  updates_count?: number;
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
    plans?: Plan[];
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
  amendments?: Amendment[];
  file: string | null; // null for a chart note that has no file under data/notes
  id: string;
  patient_id: string;
  time: string;
  author: string;
  excerpt: string;
  text: string;
  has_replay: boolean;
  has_queue: boolean;
  status?: "received" | "signed";
  review?: Review;
};

/* A plan item (ehr/extract.py plans): what the note says will be done, tied to a problem. */
export type Plan = {
  id: string;
  patient_id: string;
  problem_id: string;
  kind: "diagnostic" | "therapeutic" | "monitoring" | "referral" | "education" | "follow_up";
  text: string;
  status: string;
  provenance: Provenance;
  created_at: string;
  review?: Review;
  queue?: string;
};

/* One line of the record (ehr/record.py): derived from provenance and review stamps. */
export type RecordEvent = { kind: string; at: string; subject: string; text: string; by: string | null; source: string | null; note_id: string | null; quote: string | null; ids: string[] };

export type PatientSummary = {
  corrections?: Correction[];
  patient: Patient;
  problems: Problem[];
  counts: Record<string, number>;
  insights: Insight[];
  documents: Document[];
  orders: Order[];
  plans: Plan[];
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
  decision: "accepted" | "rejected" | "pending" | "corrected";
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

/* The problem card (ehr/card.py): computed from the chart, never stored. */
export type CardEvidence = { id: string; ids: string[]; kind: string; text: string; detail: string; source: string; valence: "for" | "against" | "unexplained" };
export type CardPlan = { id: string; plan_kind: string; text: string; detail: string; status: string; ids: string[]; destination?: "treatment_plan" | "both" | null };
export type CardExpectation = {
  statement: string; code: string; name: string; direction: string; since: string; by: string;
  ref_value: number | null; target_value: number | null;
  status: "met" | "not_yet" | "missed"; tier: string; source: string; ids: string[];
  reconsider_if: { trigger: string; then: string }[];
};
export type Card = {
  patient_id: string; problem_id: string; window: { start: string; end: string }; as_of: string;
  problem: { id: string; name: string; status: string; onset_date: string | null; code: { system: string; value: string } | null; provenance: Provenance };
  kind: "problem" | "concern";
  epistemic: { value: string; computed: boolean; why: string };
  qualifiers: { label: string; computed: boolean; why: string }[];
  representation: { text: string; tier: string; source: string; cites: string[]; as_of: string };
  assessment: null;
  supporting: CardEvidence[];
  doesnt_fit: CardEvidence[];
  plan: CardPlan[];
  expected: CardExpectation | null;
  changed: BriefLine[];
  pending: number;
  decisions: number;
  lead_code: string | null;
  members: { id: string; name: string; onset_date: string | null }[];
  linked: { rel: string; id: string; text: string; detail: string; ids: string[] }[];
  surveillance: { rows: { code: string; name: string; latest: { value: number; time: string }; threshold: string; state: string; tripped: boolean; ids: string[] }[]; next_review: string; expected: CardExpectation | null };
  steward: { name: string; role: string };
};

/* The patient overview (ehr/overview.py): orientation, computed from the chart. */
export type OverviewChange = { rank: number; kind: string; text: string; why: string; ids: string[]; problem_id: string; problem_name: string; tag: string | null };
export type OverviewConcern = {
  id: string; name: string; status: string; onset_date: string | null; members: { id: string; name: string }[]; epistemic: string; qualifiers: string[]; monitored: boolean;
  pending: number; top_rank: number; lead: { text: string; detail: string } | null; action: { label: string; kind: string } | null; decisions: number;
};
export type OverviewLoop = { id: string; kind: string; text: string; detail: string; status: string; problem_id: string; problem_name: string };
export type Overview = {
  patient: Patient; as_of: string; since: { date: string; baseline?: string; why: string; encounter_id?: string };
  here_for: { encounter: { id: string; time: string; type: string; summary: string } | null; note: { id: string; file: string; author: string; time: string; has_queue: boolean; has_replay: boolean; status?: "received" | "signed" } | null };
  changes: OverviewChange[]; other_changes: number; concerns: OverviewConcern[]; more_concerns: number; pending: OverviewLoop[];
};

/* Chart tab (backend chart_tab): medications, latest value per series, problems, encounters. */
export type ChartData = {
  medications: Medication[];
  series: { code: string; name: string; unit: string | null; n: number; out: boolean; latest: { value: number; time: string }; problem_names: string[] }[];
  problems: Problem[];
  encounters: { id: string; time: string; type: string; summary: string }[];
};
export type PatientRow = { id: string; name: string; dob: string; sex: string; problems_active: number };

/* Care tab (ehr/care.py): one card per concern with its plan, measures and open loops; the same objects by kind. */
export type CarePlanRow = { id: string; kind: string; text: string; status: string; source: string; at: string; problem_id: string; problem_name: string; destination?: "treatment_plan" | "both" | null };
export type CareMeasure = { text: string; detail: string; ids: string[]; latest_time: string | null; problem_id: string; problem_name: string };
export type CareCard = {
  id: string; name: string; code: { system: string; value: string } | null; status: string; onset_date: string | null;
  members: { id: string; name: string }[]; epistemic: string; qualifiers: string[]; one_liner: string | null; assessment: null;
  plan: Omit<CarePlanRow, "problem_id" | "problem_name">[];
  measures: { text: string; detail: string; ids: string[]; latest_time: string | null }[];
  loops: OverviewLoop[]; pending: number; expected: { statement: string; by: string; status: string } | null; decisions: number;
};
export type CareData = {
  patient_id: string; as_of: string; since: { date: string; baseline: string; why: string };
  cards: CareCard[];
  kinds: { plans: CarePlanRow[]; orders: CarePlanRow[]; referrals: CarePlanRow[]; follow_ups: CarePlanRow[]; measures: CareMeasure[] };
  due: { code: string; name: string; last: string; due: string; overdue_days: number; problem_id: string; problem_name: string }[];
  loops: OverviewLoop[];
};

/* Timeline tab (ehr/timeline.py): everything that happened, in five lanes. */
export type TimelineLane = "sessions" | "results" | "documents" | "changes" | "reasoning";
export type TimelineItem = { lane: TimelineLane; at: string; day: string; kind: string; text: string; detail: string; by: string | null; ids: string[]; tag: string | null };
export type TimelineData = { patient_id: string; as_of: string; lanes: Record<TimelineLane, number>; items: TimelineItem[] };

/* A visit note row for the Notes tab: compiled from the encounter's decisions, in progress or signed. */
export type VisitNoteRow = { id: string; encounter_id: string; patient_id: string; time: string; author: string; excerpt: string; status: "in_progress" | "signed"; by: string | null };
