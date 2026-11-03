import type { Requirement } from "../types";

export interface RequirementsForm {
  salary_min: string;
  salary_min_must: boolean;
  max_onsite_days: string;
  max_onsite_days_must: boolean;
  location: string;
  location_must: boolean;
  must_other: string;
  nice_other: string;
}

export const EMPTY_REQUIREMENTS: RequirementsForm = {
  salary_min: "",
  salary_min_must: false,
  max_onsite_days: "",
  max_onsite_days_must: false,
  location: "",
  location_must: false,
  must_other: "",
  nice_other: "",
};

const STRUCTURED = ["salary_min", "max_onsite_days", "location"] as const;

export function toRequirements(form: RequirementsForm): Requirement[] {
  const out: Requirement[] = [];
  for (const kind of STRUCTURED) {
    const value = form[kind].trim();
    if (value) out.push({ kind, value, must_have: form[`${kind}_must`] });
  }
  for (const [field, must] of [["must_other", true], ["nice_other", false]] as const) {
    for (const line of form[field].split("\n")) {
      if (line.trim()) out.push({ kind: "other", value: line.trim(), must_have: must });
    }
  }
  return out;
}

export function fromRequirements(reqs: Requirement[]): RequirementsForm {
  const form = { ...EMPTY_REQUIREMENTS };
  const must: string[] = [];
  const nice: string[] = [];
  for (const r of reqs) {
    if (r.kind === "salary_min" || r.kind === "max_onsite_days" || r.kind === "location") {
      form[r.kind] = r.value;
      form[`${r.kind}_must`] = r.must_have;
    } else {
      (r.must_have ? must : nice).push(r.value);
    }
  }
  return { ...form, must_other: must.join("\n"), nice_other: nice.join("\n") };
}

export function RequirementsEditor({
  value,
  onChange,
}: {
  value: RequirementsForm;
  onChange: (value: RequirementsForm) => void;
}) {
  const set = <K extends keyof RequirementsForm>(key: K, v: RequirementsForm[K]) =>
    onChange({ ...value, [key]: v });

  const row = (
    key: (typeof STRUCTURED)[number],
    label: string,
    placeholder: string,
    numeric = false,
  ) => (
    <div className="req-row">
      <label>
        {label}
        <input
          value={value[key]}
          inputMode={numeric ? "numeric" : undefined}
          placeholder={placeholder}
          onChange={(e) => set(key, e.target.value)}
        />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={value[`${key}_must`]}
          onChange={(e) => set(`${key}_must`, e.target.checked)}
        />
        must-have
      </label>
    </div>
  );

  return (
    <fieldset className="requirements">
      <legend>Your requirements</legend>
      <p className="hint">
        A must-have stops the application early only if the listing clearly contradicts it. If the
        listing doesn't say, it never fails.
      </p>
      {row("salary_min", "Min. salary (EUR / year)", "90000", true)}
      {row("max_onsite_days", "Max. onsite days / week (0 = remote)", "3", true)}
      {row("location", "Cities (comma-separated)", "Nürnberg, Fürth, Erlangen")}
      <label>
        Other must-haves (one per line)
        <textarea rows={2} value={value.must_other} onChange={(e) => set("must_other", e.target.value)} />
      </label>
      <label>
        Nice-to-haves (one per line)
        <textarea
          rows={2}
          value={value.nice_other}
          placeholder={"Hardware budget\nEGYM Wellpass"}
          onChange={(e) => set("nice_other", e.target.value)}
        />
      </label>
    </fieldset>
  );
}
