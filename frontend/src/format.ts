export function usd(value: number, digits?: number): string {
  const d = digits ?? (value !== 0 && Math.abs(value) < 0.1 ? 3 : 2);
  return `$${value.toFixed(d)}`;
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function when(iso: string): string {
  const date = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return date.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function sentence(value: string): string {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const STATUS_LABELS: Record<string, string> = {
  created: "Queued",
  fetching_listing: "Fetching listing",
  waiting_for_listing_text: "Needs the listing text",
  parsing_listing: "Reading listing",
  checking_requirements: "Checking requirements",
  stopped_by_requirements: "Must-have not met",
  matching: "Assessing fit",
  waiting_for_apply_decision: "Your decision",
  declined: "Declined",
  authoring: "Writing",
  reviewing: "Reviewing",
  waiting_for_final_review: "Your final review",
  delivering: "Delivering",
  done: "Ready to send",
  failed: "Failed",
  parsing: "Parsing",
  waiting_for_confirmation: "Needs confirmation",
  confirmed: "Confirmed",
};

export type Tone = "busy" | "you" | "good" | "bad" | "muted";

export function tone(status: string): Tone {
  if (status === "failed") return "bad";
  if (status === "stopped_by_requirements") return "you";
  if (status === "done" || status === "confirmed") return "good";
  if (status === "declined") return "muted";
  if (status.startsWith("waiting")) return "you";
  return "busy";
}

export const STEP_NAMES: Record<string, string> = {
  parse_cv: "CV parsing",
  parse_listing: "Listing parsing",
  match: "Fit assessment",
  author_cv: "CV writing",
  author_letter: "Cover letter",
  claims_check: "Claims check",
  recruiter: "Recruiter review",
  legacy: "Before cost tracking",
};

export const MODEL_NAMES: Record<string, string> = {
  "claude-opus-5-5": "Opus 5.5",
  "claude-sonnet-5-5": "Sonnet 5.5",
  "claude-haiku-5-5": "Haiku 5.5",
  demo: "demo",
};

export function modelName(model: string | null): string {
  return model ? (MODEL_NAMES[model] ?? model) : "Python";
}
