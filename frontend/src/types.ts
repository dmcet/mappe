// Shapes of the JSON API (mappe/web/*.py).

export type CVStatus = "parsing" | "waiting_for_confirmation" | "confirmed" | "failed";

export type RunStatus =
  | "created"
  | "fetching_listing"
  | "waiting_for_listing_text"
  | "parsing_listing"
  | "checking_requirements"
  | "stopped_by_requirements"
  | "matching"
  | "waiting_for_apply_decision"
  | "declined"
  | "authoring"
  | "reviewing"
  | "waiting_for_final_review"
  | "delivering"
  | "done"
  | "failed";

export interface SourceProgress {
  label: string;
  state: "running" | "done" | "failed";
  count: number;
  error: string | null;
}

export interface Job {
  kind: "run" | "cv" | "search";
  id: number;
  title: string;
  phase: string;
  detail: string;
  model: string | null;
  draft: number | null;
  progress?: Record<string, SourceProgress> | null;
  elapsed_s: number;
  detail_elapsed_s: number;
}

export interface WaitingRun {
  id: number;
  title: string;
  status: RunStatus;
  prompt: string;
}

export interface Status {
  jobs: Job[];
  queued: { kind: string; id: number }[];
  waiting_for_you: WaitingRun[];
  demo: boolean;
  costs: { total_usd: number; today_usd: number; limit_per_run_usd: number };
  changed?: { runs: number[]; cvs: number[] };
}

export interface CostSummary {
  total_usd: number;
  today_usd: number;
  month_usd: number;
  by_model: { model: string; name: string; cost_usd: number; calls: number }[];
  by_step: { step: string; cost_usd: number; calls: number }[];
  last_30_days: { date: string; cost_usd: number }[];
  last_call: { step: string; model: string; cost_usd: number; at: string } | null;
}

export interface CVSummary {
  id: number;
  label: string;
  status: CVStatus;
  error: string | null;
  cost_usd: number;
  warnings: number;
  runs: number;
  roles_status: RolesStatus;
  created_at: string;
  updated_at: string;
}

export interface Fact {
  id: string;
  text: string;
}

export interface Skill {
  name: string;
  level: "advanced" | "intermediate" | "basic" | null;
  level_text: string | null;
}

export interface Position {
  id: string;
  company: string;
  client: string | null;
  role: string;
  location: string | null;
  start: string;
  end: string | null;
  responsibilities: Fact[];
  achievements: Fact[];
  technologies: string[];
}

export interface ParsedCV {
  contact: {
    name: string;
    city: string | null;
    address: string | null;
    email: string | null;
    phone: string | null;
    links: string[];
  };
  headline: string | null;
  languages: { name: string; level: string }[];
  skills: Skill[];
  soft_skills: string[];
  certifications: { id: string; name: string; abbreviation: string | null; issuer: string | null; year: number | null }[];
  education: { id: string; qualification: string; institution: string; location: string | null; start: string | null; end: string | null }[];
  positions: Position[];
  projects: Fact[];
  publications: Fact[];
  volunteering: Fact[];
}

export interface CVDetail extends Omit<CVSummary, "warnings"> {
  markdown: string;
  warnings: string[];
  parsed: ParsedCV | null;
  summary: {
    name: string;
    positions: number;
    years_of_experience: number;
    current_role: string | null;
    skills: number;
    languages: string[];
    certifications: number;
    education: number;
  } | null;
  quick_fields: Record<string, string>;
  quick_values: Record<string, string>;
  roles: (SuggestedRole & { fact_ids: string[] })[];
  roles_error: string | null;
}

export type RolesStatus = "suggesting" | "done" | "failed" | null;

/** An alternative role Claude suggested for the CV (opt-in search title). */
export interface SuggestedRole {
  title: string;
  title_alt: string;
  reason: string;
}

export interface Requirement {
  kind: "salary_min" | "max_onsite_days" | "remote" | "location" | "benefit" | "other";
  value: string;
  must_have: boolean;
}

/** The search form of one CV, kept between visits. */
export interface SearchPrefs {
  titles: string[];
  titles_off: string[];
  requirements: Requirement[];
  requirements_off: Requirement[];
  sources: string[] | null;
}

export interface RequirementResult {
  requirement: Requirement;
  outcome: "passed" | "failed" | "unknown";
  note: string;
  evidence: string | null;
}

export interface Listing {
  title: string | null;
  company: string | null;
  domain: string | null;
  language: string;
  responsibilities: string[];
  required_skills: string[];
  nice_to_have_skills: string[];
  qualifications: string[];
  location: string | null;
  remote: "remote" | "hybrid" | "onsite" | null;
  onsite_days_per_week: number | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: "year" | "month" | "hour" | null;
  benefits: string[];
  cover_letter_requested: boolean;
  // Missing in runs parsed before contacts were read.
  contact_name?: string | null;
  contact_gender?: "female" | "male" | null;
  contact_academic_title?: string | null;
  contact_email?: string | null;
  /** Confirmed postal address ("street", "postal code city"); the letter layout needs it. */
  company_address?: string[] | null;
}

/** The application email of a finished run (GET /api/runs/{id}/email). */
export type ApplicationEmail =
  | { available: false; reason: string }
  | {
      available: true;
      to: string;
      subject: string;
      body: string;
      cv_name: string;
      cv_url: string;
      eml_url: string;
      shortcut_url: string;
    };

export interface Evidence {
  point: string;
  fact_ids: string[];
}

export interface Match {
  verdict: "apply" | "consider" | "dont_apply";
  score: number;
  rationale: string;
  strengths: Evidence[];
  gaps: string[];
  transferable: { missing: string; related_experience: string; fact_ids: string[] }[];
  highlights: Evidence[];
}

export interface Coverage {
  skill: string;
  required: boolean;
  coverage: "match" | "related" | "missing";
  cv_skill: string | null;
  level: string | null;
  years: number;
  student_years: number;
  positions: string[];
  note: string;
}

export interface Analysis {
  coverage: Coverage[];
  total_years: number;
  student_years?: number;
  years_required: number | null;
  required_matched: number;
  required_related: number;
  required_total: number;
  nice_matched: number;
  nice_total: number;
}

export interface AuthorBullet {
  position_id: string;
  text: string;
  fact_ids: string[];
}

export interface AuthorCV {
  profile: string;
  profile_fact_ids: string[];
  titles: { id: string; title: string }[];
  bullets: AuthorBullet[];
  skill_groups: { category: string; skills: string[] }[];
  extra: AuthorBullet[];
}

export interface AuthorLetter {
  subject: string;
  paragraphs: { text: string; fact_ids: string[] }[];
}

export interface Recruiter {
  relevance: number;
  keywords: number;
  evidence: number;
  clarity: number;
  seniority: number;
  cover_letter: number;
  invite: boolean;
  summary: string;
  feedback: string[];
  average: number;
}

export interface Draft {
  iteration: number;
  lang: string;
  cv: AuthorCV;
  letter: AuthorLetter | null;
  cv_report: { violations: string[]; warnings: string[] };
  letter_report: { violations: string[]; warnings: string[] };
  claims?: { item: string; kind: string; explanation: string; text: string }[];
  ats?: {
    parse_problems: string[];
    keywords_found: string[];
    keywords_missing: string[];
    stuffing: string[];
    coverage: number;
    passed: boolean;
  };
  recruiter?: Recruiter | null;
  clean?: boolean;
  score?: number;
  accepted?: boolean;
  source?: "user";
  based_on?: number;
  files: Record<string, string>;
}

export interface Stage {
  key: string;
  label: string;
  state: "done" | "active" | "waiting" | "failed" | "declined" | "pending";
  hint: string;
}

export interface RunSummary {
  id: number;
  cv_id: number;
  title: string;
  company: string | null;
  listing_url: string | null;
  status: RunStatus;
  error: string | null;
  verdict: Match["verdict"] | null;
  score: number | null;
  cost_usd: number;
  created_at: string;
  updated_at: string;
  pipeline: Stage[];
}

export interface RunDetail extends RunSummary {
  requirements: Requirement[];
  has_listing_text: boolean;
  previous_status: RunStatus | null;
  state: {
    listing: Listing | null;
    requirement_results: RequirementResult[] | null;
    analysis: Analysis | null;
    match: Match | null;
    match_warnings: string[] | null;
    cover_letter_suggested: boolean | null;
    decision: { cover_letter: boolean } | null;
    drafts: Draft[] | null;
    final_draft: number | null;
    review_stop_reason: string | null;
    delivery: { draft: number; files: Record<string, string> } | null;
    cv: ParsedCV | null;
    fetch: { job_posting: unknown; language: string; final_url?: string } | null;
  };
  facts: Record<string, string>;
  events: { id: number; kind: string; message: string; at: string }[];
  usage: {
    step: string;
    model: string;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
    at: string;
  }[];
}

export interface EditData {
  draft: Draft;
  cv: ParsedCV;
  title: string;
}

// ---------- job search ----------

export type HiddenReason = "dismissed" | "requirements" | "elsewhere" | "low_score";

export interface SearchSource {
  key: string;
  label: string;
  home: string;
  remote_only: boolean;
  default: boolean;
  missing_env: string[];
}

export interface SourceStatus {
  label: string;
  count: number;
  error: string | null;
  seconds: number;
}

export interface JobHit {
  id: number;
  status: "new" | "dismissed" | "applied";
  run_id: number | null;
  source: string;
  source_label: string;
  source_home: string | null;
  full_text: boolean;
  first_seen_at: string;
  url: string;
  view_url: string;
  title: string;
  company: string | null;
  location: string | null;
  remote: "remote" | "hybrid" | "onsite" | null;
  onsite_days_per_week: number | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: "year" | "month" | "hour" | null;
  tags: string[];
  posted_at: string | null;
  also_on: string[];
  excerpt: string;
}

export interface SearchResultItem {
  score: number;
  reasons: {
    score: number;
    matched_skills: string[];
    title_fit: number;
    semantic_fit: number | null;
    basis: "description" | "title only";
    hidden: HiddenReason | null;
    notes: string[];
  };
  hidden: HiddenReason | null;
  is_new: boolean;
  hit: JobHit;
}

export interface SearchSummary {
  id: number;
  cv_id: number;
  saved_id: number | null;
  titles: string[];
  places: string[];
  remote_only: boolean;
  created_at: string;
  total: number;
  shown: number;
  new: number;
}

export interface Ranking {
  semantic: boolean;
  model?: string;
  embedded?: number;
  reused?: number;
  note: string | null;
}

export interface SearchDetail extends SearchSummary {
  requirements: Requirement[];
  sources: Record<string, SourceStatus>;
  ranking: Ranking;
  results: SearchResultItem[];
}

export interface SavedSearch {
  id: number;
  cv_id: number;
  name: string;
  titles: string[];
  requirements: Requirement[];
  sources: string[];
  created_at: string;
  last_run: SearchSummary | null;
}
