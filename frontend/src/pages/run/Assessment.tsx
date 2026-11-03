import { Button, StatCounter } from "performative-ui";
import { useState } from "react";
import { api } from "../../api";
import { ErrorNote, FactRefs, Outcome, Section, useAction } from "../../components/ui";
import type { RunDetail } from "../../types";

const VERDICTS = { apply: "Apply", consider: "Consider applying", dont_apply: "Don't apply" };

export function Assessment({ run, onChange }: { run: RunDetail; onChange: (r: RunDetail) => void }) {
  const match = run.state.match!;
  const [letter, setLetter] = useState(Boolean(run.state.cover_letter_suggested));
  const action = useAction();
  const deciding = run.status === "waiting_for_apply_decision";

  return (
    <>
      <Section
        className={`verdict verdict--${match.verdict}${deciding ? " panel--you" : ""}`}
        eyebrow={deciding ? "Needs you · your decision" : "Assessment"}
        title={
          <span className="verdict__title">
            {VERDICTS[match.verdict]}
            <span className="verdict__score">
              <StatCounter target={match.score} durationMs={1200} />
              <small>/100</small>
            </span>
          </span>
        }
      >
        <p className="verdict__rationale">{match.rationale}</p>
        {deciding && (
          <div className="actions">
            <label className="check">
              <input type="checkbox" checked={letter} onChange={(e) => setLetter(e.target.checked)} />
              also write a cover letter
            </label>
            <Button variant="glow" sparkle loading={action.busy} onClick={() => action.run(() => api.applyRun(run.id, letter).then(onChange))}>
              Apply
            </Button>
            <Button variant="ghost" loading={action.busy} onClick={() => action.run(() => api.declineRun(run.id).then(onChange))}>
              Don't apply
            </Button>
          </div>
        )}
        {run.state.decision && (
          <p className="muted">You decided to apply{run.state.decision.cover_letter ? " with a cover letter" : ""}.</p>
        )}
        <ErrorNote error={action.error} />
      </Section>

      <div className="grid-2">
        <Section title="Strengths">
          <ul>
            {match.strengths.map((s) => (
              <li key={s.point}>
                {s.point} <FactRefs ids={s.fact_ids} facts={run.facts} />
              </li>
            ))}
          </ul>
          {match.transferable.length > 0 && (
            <>
              <h4 className="muted">Transferable</h4>
              <ul>
                {match.transferable.map((t) => (
                  <li key={t.missing}>
                    <strong>{t.missing}</strong>: {t.related_experience} <FactRefs ids={t.fact_ids} facts={run.facts} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </Section>
        <Section title="Gaps">
          <ul>
            {match.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
          <h4 className="muted">Focus for the CV</h4>
          <ol>
            {match.highlights.map((h) => (
              <li key={h.point}>
                {h.point} <FactRefs ids={h.fact_ids} facts={run.facts} />
              </li>
            ))}
          </ol>
        </Section>
      </div>
      {(run.state.match_warnings ?? []).length > 0 && (
        <Section title="Removed from the assessment" className="panel--warn">
          <p className="hint">These points referred to CV facts that don't exist.</p>
          <ul>
            {run.state.match_warnings!.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

export function Coverage({ run }: { run: RunDetail }) {
  const a = run.state.analysis!;
  return (
    <Section
      title="Skill coverage"
      eyebrow={`${a.required_matched} matched · ${a.required_related} related · of ${a.required_total} required`}
    >
      <p className="hint">
        Computed from your CV: {a.total_years} years of experience
        {a.student_years ? ` (including ${a.student_years} as working student)` : ""}
        {a.years_required ? ` · listing asks for ${a.years_required}+ years` : ""}.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Skill</th>
              <th>Coverage</th>
              <th>From your CV</th>
              <th>Years</th>
            </tr>
          </thead>
          <tbody>
            {a.coverage.map((c) => (
              <tr key={`${c.skill}-${c.required}`}>
                <td>
                  {c.skill}
                  {!c.required && <span className="muted"> (nice)</span>}
                </td>
                <td>
                  <Outcome value={c.coverage === "match" ? "good" : c.coverage === "missing" ? "bad" : "neutral"}>
                    {c.coverage}
                  </Outcome>
                </td>
                <td>
                  {c.cv_skill ?? (c.note ? <span className="muted">{c.note}</span> : "—")}
                  {c.level && <span className="muted"> ({c.level})</span>} <FactRefs ids={c.positions} facts={run.facts} />
                </td>
                <td className="mono">
                  {c.years || (c.coverage !== "missing" ? "—" : "")}
                  {c.student_years ? <span className="muted"> (incl. {c.student_years} student)</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
