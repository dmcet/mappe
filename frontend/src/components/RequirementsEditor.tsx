import { useState } from "react";
import { GERMAN_CITIES } from "../cities";
import type { Requirement } from "../types";

export interface Place {
  name: string;
  km: number;
}

export interface Wish {
  value: string;
  must: boolean;
  on: boolean; // off = kept as a chip, not checked
}

export interface RequirementsForm {
  salary_min: number | null; // null = no minimum
  salary_min_must: boolean;
  max_onsite_days: number | null; // null = any
  remote_ok: boolean;
  work_must: boolean; // onsite days and remote
  places: Place[];
  location_must: boolean;
  wishes: Wish[];
}

export const SALARY = { min: 30000, max: 200000, step: 5000 };
export const RADII = [5, 10, 20, 30, 50, 100];
export const DEFAULT_RADIUS = 30;

export const EMPTY_REQUIREMENTS: RequirementsForm = {
  salary_min: null,
  salary_min_must: false,
  max_onsite_days: null,
  remote_ok: true,
  work_must: false,
  places: [],
  location_must: false,
  wishes: [],
};

/** "Nürnberg (30 km), Fürth" → places; a city without a radius gets the default. */
export function parsePlaces(value: string): Place[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const m = part.match(/^(.*?)\s*\(\s*(\d+)\s*km\s*\)$/i);
      return m ? { name: m[1].trim(), km: Number(m[2]) } : { name: part, km: DEFAULT_RADIUS };
    })
    .filter((p) => p.name);
}

export const placesText = (places: Place[]) => places.map((p) => `${p.name} (${p.km} km)`).join(", ");

/** "90000", "90.000 €", "90k" → 90000. */
function toNumber(value: string): number | null {
  const digits = value.replace(/[^\d]/g, "");
  if (!digits) return null;
  return Number(digits) * (/k\s*$/i.test(value.trim()) ? 1000 : 1);
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

/** The requirements the form stands for (wishes that are switched off are left out). */
export function toRequirements(form: RequirementsForm): Requirement[] {
  const out: Requirement[] = [];
  if (form.salary_min !== null) {
    out.push({ kind: "salary_min", value: String(form.salary_min), must_have: form.salary_min_must });
  }
  if (form.max_onsite_days !== null) {
    out.push({ kind: "max_onsite_days", value: String(form.max_onsite_days), must_have: form.work_must });
  }
  if (!form.remote_ok && form.max_onsite_days !== 0) {
    out.push({ kind: "remote", value: "no", must_have: form.work_must });
  }
  if (form.places.length) {
    out.push({ kind: "location", value: placesText(form.places), must_have: form.location_must });
  }
  for (const w of form.wishes) {
    if (w.on) out.push({ kind: "other", value: w.value, must_have: w.must });
  }
  return out;
}

/** Wishes that are switched off, to keep them as chips between visits. */
export const parkedWishes = (form: RequirementsForm): Requirement[] =>
  form.wishes.filter((w) => !w.on).map((w) => ({ kind: "other", value: w.value, must_have: w.must }));

export function fromRequirements(reqs: Requirement[], parked: Requirement[] = []): RequirementsForm {
  const form: RequirementsForm = { ...EMPTY_REQUIREMENTS, places: [], wishes: [] };
  for (const r of reqs) {
    if (r.kind === "salary_min") {
      const n = toNumber(r.value);
      form.salary_min = n === null ? null : clamp(n, SALARY.min, SALARY.max);
      form.salary_min_must = r.must_have;
    } else if (r.kind === "max_onsite_days") {
      const n = toNumber(r.value);
      form.max_onsite_days = n === null || n >= 5 ? null : n;
      form.work_must = r.must_have;
    } else if (r.kind === "remote") {
      form.remote_ok = r.value.trim().toLowerCase() !== "no";
      form.work_must ||= r.must_have;
    } else if (r.kind === "location") {
      form.places = parsePlaces(r.value);
      form.location_must = r.must_have;
    } else {
      form.wishes.push({ value: r.value, must: r.must_have, on: true });
    }
  }
  for (const r of parked) form.wishes.push({ value: r.value, must: r.must_have, on: false });
  return form;
}

const salaryLabel = (n: number | null) =>
  n === null ? "no minimum" : `${Math.round(n / 1000)}k EUR / year`;

export function onsiteLabel(days: number | null): string {
  if (days === null) return "any";
  if (days === 0) return "remote only";
  return `up to ${days} / week`;
}

function MustToggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="check must-toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      must-have
    </label>
  );
}

function Places({ places, onChange }: { places: Place[]; onChange: (p: Place[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const names = draft.split(",").map((t) => t.trim()).filter(Boolean);
    const have = new Set(places.map((p) => p.name.toLowerCase()));
    const added = names.filter((n) => !have.has(n.toLowerCase())).map((name) => ({ name, km: DEFAULT_RADIUS }));
    if (added.length) onChange([...places, ...added]);
    setDraft("");
  };
  return (
    <div className="places">
      <div className="chip-input">
        <input
          aria-label="Add a city"
          list="german-cities"
          autoComplete="off"
          value={draft}
          placeholder="Add a city, e.g. Nürnberg"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="chip-btn" onClick={add} disabled={!draft.trim()}>
          Add city
        </button>
        <datalist id="german-cities">
          {GERMAN_CITIES.filter((c) => !places.some((p) => p.name.toLowerCase() === c.toLowerCase())).map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </div>
      {places.length > 0 && (
        <ul className="chips">
          {places.map((p, i) => (
            <li key={p.name} className="chip chip--on place-chip">
              {p.name}
              <select
                aria-label={`Radius around ${p.name}`}
                value={p.km}
                onChange={(e) =>
                  onChange(places.map((q, j) => (j === i ? { ...q, km: Number(e.target.value) } : q)))
                }
              >
                {[...new Set([...RADII, p.km])].sort((a, b) => a - b).map((km) => (
                  <option key={km} value={km}>
                    +{km} km
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="chip__remove"
                aria-label={`Remove ${p.name}`}
                onClick={() => onChange(places.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Wishes({ wishes, onChange }: { wishes: Wish[]; onChange: (w: Wish[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = (must: boolean) => {
    const value = draft.trim();
    if (!value) return;
    const rest = wishes.filter((w) => w.value.toLowerCase() !== value.toLowerCase());
    onChange([...rest, { value, must, on: true }]);
    setDraft("");
  };
  const set = (i: number, patch: Partial<Wish>) => onChange(wishes.map((w, j) => (j === i ? { ...w, ...patch } : w)));
  return (
    <div className="wishes">
      <div className="chip-input chip-input--stack">
        <input
          aria-label="Add a must-have or nice-to-have"
          value={draft}
          placeholder="e.g. 30 days vacation"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(false);
            }
          }}
        />
        <div className="chip-input__buttons">
          <button type="button" className="chip-btn chip-btn--must" onClick={() => add(true)} disabled={!draft.trim()}>
            Add as must-have
          </button>
          <button type="button" className="chip-btn" onClick={() => add(false)} disabled={!draft.trim()}>
            Add as nice-to-have
          </button>
        </div>
      </div>
      {wishes.length > 0 && (
        <ul className="chips">
          {wishes.map((w, i) => (
            <li key={w.value} className={`chip${w.on ? " chip--on" : ""}${w.must ? " chip--must" : ""}`}>
              <button
                type="button"
                className="chip__toggle"
                aria-pressed={w.on}
                title={w.on ? "Click to switch off" : "Click to switch on"}
                onClick={() => set(i, { on: !w.on })}
              >
                {w.value}
              </button>
              <button
                type="button"
                className="chip__kind"
                title={w.must ? "Make it a nice-to-have" : "Make it a must-have"}
                onClick={() => set(i, { must: !w.must })}
              >
                {w.must ? "must" : "nice"}
              </button>
              <button
                type="button"
                className="chip__remove"
                aria-label={`Remove ${w.value}`}
                onClick={() => onChange(wishes.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
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
  const remoteOnly = value.max_onsite_days === 0;

  return (
    <fieldset className="requirements">
      <legend>Your requirements</legend>
      <p className="hint">
        A must-have stops the application early only if the listing clearly contradicts it. If the
        listing doesn't say, it never fails.
      </p>

      <div className="req-block">
        <div className="req-block__head">
          <label htmlFor="req-salary">Min. salary</label>
          <span className="req-block__value">{salaryLabel(value.salary_min)}</span>
          <MustToggle checked={value.salary_min_must} onChange={(v) => set("salary_min_must", v)} />
        </div>
        <input
          id="req-salary"
          type="range"
          min={SALARY.min}
          max={SALARY.max}
          step={SALARY.step}
          value={value.salary_min ?? SALARY.min}
          aria-valuetext={salaryLabel(value.salary_min)}
          onChange={(e) => {
            const n = Number(e.target.value);
            set("salary_min", n <= SALARY.min ? null : n);
          }}
        />
        <div className="range-scale" aria-hidden="true">
          <span>any</span>
          <span>200k</span>
        </div>
      </div>

      <div className="req-block">
        <div className="req-block__head">
          <label htmlFor="req-onsite">Onsite days</label>
          <span className="req-block__value">{onsiteLabel(value.max_onsite_days)}</span>
          <MustToggle checked={value.work_must} onChange={(v) => set("work_must", v)} />
        </div>
        <input
          id="req-onsite"
          type="range"
          min={0}
          max={5}
          step={1}
          value={value.max_onsite_days ?? 5}
          aria-valuetext={onsiteLabel(value.max_onsite_days)}
          onChange={(e) => {
            const n = Number(e.target.value);
            set("max_onsite_days", n >= 5 ? null : n);
          }}
        />
        <div className="range-scale" aria-hidden="true">
          <span>remote only</span>
          <span>any</span>
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={remoteOnly || value.remote_ok}
            disabled={remoteOnly}
            onChange={(e) => set("remote_ok", e.target.checked)}
          />
          Fully remote jobs are fine
        </label>
      </div>

      <div className="req-block">
        <div className="req-block__head">
          <span>Cities</span>
          <span className="req-block__value">{value.places.length ? "" : "anywhere in Germany"}</span>
          <MustToggle checked={value.location_must} onChange={(v) => set("location_must", v)} />
        </div>
        <Places places={value.places} onChange={(p) => set("places", p)} />
      </div>

      <div className="req-block">
        <div className="req-block__head">
          <span>Must-haves and nice-to-haves</span>
        </div>
        <Wishes wishes={value.wishes} onChange={(w) => set("wishes", w)} />
        {value.wishes.length > 0 && (
          <p className="hint">Click a chip to switch it off, or its tag to change must / nice.</p>
        )}
      </div>
    </fieldset>
  );
}
