import { Outcome, Section } from "../../components/ui";
import { STEP_NAMES, usd, when } from "../../format";
import type { RunDetail } from "../../types";

export function RequirementsPanel({ run }: { run: RunDetail }) {
  const results = run.state.requirement_results ?? [];
  if (!results.length) return null;
  return (
    <Section title="Your requirements">
      <div className="table-wrap">
        <table>
          <tbody>
            {results.map((r) => (
              <tr key={r.requirement.kind + r.requirement.value}>
                <td>
                  {r.requirement.kind.replaceAll("_", " ")}: {r.requirement.value}
                  {r.requirement.must_have && <strong> (must)</strong>}
                </td>
                <td>
                  <Outcome value={r.outcome === "passed" ? "good" : r.outcome === "failed" ? "bad" : "neutral"}>{r.outcome}</Outcome>
                </td>
                <td>
                  {r.note}
                  {r.evidence && <blockquote>“{r.evidence}”</blockquote>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

export function ListingPanel({ run }: { run: RunDetail }) {
  const l = run.state.listing;
  if (!l) return null;
  const salary =
    l.salary_min || l.salary_max
      ? `${(l.salary_min ?? l.salary_max)!.toLocaleString()}${
          l.salary_max && l.salary_max !== l.salary_min ? `–${l.salary_max.toLocaleString()}` : ""
        } ${l.salary_currency ?? ""}/${l.salary_period ?? "?"}`
      : "not stated";
  return (
    <Section title="The listing" eyebrow={l.company ?? undefined}>
      <dl className="kv">
        <dt>Location</dt>
        <dd>{l.location ?? "—"}</dd>
        <dt>Work mode</dt>
        <dd>
          {l.remote ?? "—"}
          {l.onsite_days_per_week != null && `, ${l.onsite_days_per_week} onsite day(s)/week`}
        </dd>
        <dt>Salary</dt>
        <dd>{salary}</dd>
        <dt>Language</dt>
        <dd>{l.language === "de" ? "German" : "English"}</dd>
        <dt>Cover letter</dt>
        <dd>{l.cover_letter_requested ? "requested" : "not requested"}</dd>
      </dl>
      <div className="grid-2">
        <div>
          <h4 className="muted">Required skills</h4>
          <p className="tags">{l.required_skills.map((s) => <span key={s}>{s}</span>)}</p>
          <h4 className="muted">Nice to have</h4>
          <p className="tags">{l.nice_to_have_skills.map((s) => <span key={s}>{s}</span>)}</p>
          <h4 className="muted">Benefits</h4>
          <ul>{l.benefits.map((b) => <li key={b}>{b}</li>)}</ul>
        </div>
        <div>
          <h4 className="muted">Responsibilities</h4>
          <ul>{l.responsibilities.map((r) => <li key={r}>{r}</li>)}</ul>
          <h4 className="muted">Qualifications</h4>
          <ul>{l.qualifications.map((q) => <li key={q}>{q}</li>)}</ul>
        </div>
      </div>
    </Section>
  );
}

export function ActivityPanel({ run }: { run: RunDetail }) {
  const total = run.usage.reduce((sum, u) => sum + u.cost_usd, 0);
  const events = run.events.filter((e) => !["step_started", "step_finished"].includes(e.kind));
  return (
    <div className="grid-2">
      <Section title="Activity" eyebrow={`${events.length} events`}>
        <ol className="timeline">
          {[...events].reverse().map((e) => (
            <li key={e.id} className={`timeline__item timeline__item--${e.kind}`}>
              <time>{when(e.at)}</time>
              <span>{e.kind === "status" ? `→ ${e.message.replaceAll("_", " ")}` : e.message}</span>
            </li>
          ))}
        </ol>
      </Section>
      <Section title="Model costs of this application" eyebrow={usd(total)}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Step</th>
                <th>Model</th>
                <th>Tokens in / out</th>
                <th>Cache write / read</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {run.usage.map((u, i) => (
                <tr key={i}>
                  <td>{STEP_NAMES[u.step] ?? u.step}</td>
                  <td>{u.model}</td>
                  <td className="mono">
                    {u.input_tokens.toLocaleString()} / {u.output_tokens.toLocaleString()}
                  </td>
                  <td className="mono">
                    {u.cache_write_tokens.toLocaleString()} / {u.cache_read_tokens.toLocaleString()}
                  </td>
                  <td className="mono">{usd(u.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!run.usage.length && <p className="hint">No model calls recorded for this application.</p>}
      </Section>
    </div>
  );
}
