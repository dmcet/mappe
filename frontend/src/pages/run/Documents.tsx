import { Button, GradientText } from "performative-ui";
import { Link } from "react-router";
import { api, files } from "../../api";
import { ErrorNote, FactRefs, Outcome, Section, useAction } from "../../components/ui";
import type { Draft, RunDetail } from "../../types";
import { EmailPanel } from "./Email";

function finalOf(run: RunDetail): Draft | null {
  const drafts = run.state.drafts ?? [];
  if (!drafts.length) return null;
  return drafts.find((d) => d.iteration === run.state.final_draft) ?? drafts[drafts.length - 1];
}

function Checks({ d }: { d: Draft }) {
  const violations = [...d.cv_report.violations, ...d.letter_report.violations];
  const claims = d.claims ?? [];
  const rec = d.recruiter;
  return (
    <div className="checks">
      <div className="check-row">
        <span className="check-row__name">Fact check</span>
        <Outcome value={violations.length ? "bad" : "good"}>{violations.length ? `${violations.length} problem(s)` : "passed"}</Outcome>
        <div>
          {violations.length ? (
            <ul>{violations.map((v) => <li key={v}>{v}</li>)}</ul>
          ) : (
            "Every statement cites your CV; numbers and skills come from it."
          )}
        </div>
      </div>
      {d.ats && (
        <div className="check-row">
          <span className="check-row__name">Claims check</span>
          <Outcome value={claims.length ? "bad" : violations.length || d.source === "user" ? "neutral" : "good"}>
            {claims.length ? `${claims.length} problem(s)` : violations.length || d.source === "user" ? "not run" : "passed"}
          </Outcome>
          <div>
            {claims.length ? (
              <ul>
                {claims.map((c) => (
                  <li key={c.item + c.explanation}>
                    <strong>{c.kind}</strong>: “{c.text.slice(0, 120)}” — {c.explanation}
                  </li>
                ))}
              </ul>
            ) : d.source === "user" ? (
              "Not re-checked by AI after your edits."
            ) : violations.length ? (
              "Skipped until the fact check passes."
            ) : (
              "No embellishments found."
            )}
          </div>
        </div>
      )}
      {d.ats && (
        <div className="check-row">
          <span className="check-row__name">ATS</span>
          <Outcome value={d.ats.passed ? "good" : "bad"}>{Math.round(d.ats.coverage * 100)}% keywords</Outcome>
          <div>
            {d.ats.keywords_found.length} of {d.ats.keywords_found.length + d.ats.keywords_missing.length} required skills you
            have are visible.
            {d.ats.keywords_missing.length > 0 && ` Missing: ${d.ats.keywords_missing.join(", ")}.`}
            {d.ats.parse_problems.map((p) => (
              <div key={p} className="error-note">{p}</div>
            ))}
          </div>
        </div>
      )}
      {rec && (
        <div className="check-row">
          <span className="check-row__name">Recruiter</span>
          <Outcome value={d.accepted ? "good" : "neutral"}>
            {rec.average}/5{rec.invite ? " · invite" : ""}
          </Outcome>
          <div>
            {rec.summary}
            <div className="scores">
              {(["relevance", "keywords", "evidence", "clarity", "seniority"] as const).map((k) => (
                <span key={k}>
                  {k} <strong>{rec[k]}</strong>
                </span>
              ))}
              {d.letter && rec.cover_letter > 0 && (
                <span>
                  cover letter <strong>{rec.cover_letter}</strong>
                </span>
              )}
            </div>
            {rec.feedback.length > 0 && (
              <ul className="muted">{rec.feedback.map((f) => <li key={f}>{f}</li>)}</ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function Documents({ run, onChange }: { run: RunDetail; onChange: (r: RunDetail) => void }) {
  const d = finalOf(run);
  const action = useAction();
  if (!d) return null;
  const drafts = run.state.drafts ?? [];
  const reviewing = run.status === "waiting_for_final_review";
  const open = d.cv_report.violations.length + d.letter_report.violations.length + (d.claims?.length ?? 0);
  const delivery = run.state.delivery;

  return (
    <>
      {delivery && (
        <Section className="panel--done" eyebrow="Done" title={<GradientText>Ready to send</GradientText>}>
          <div className="downloads">
            {Object.keys(delivery.files).map((name) => (
              <Button key={name} as="a" href={files.final(run.id, name)} download variant="glow" sparkle>
                {name}
              </Button>
            ))}
          </div>
          <p>
            <a href={files.bundle(run.id)} download>Download everything as ZIP</a>{" "}
            <span className="muted">(final documents, all drafts, parsed CV, listing and assessment)</span>
          </p>
          <EmailPanel runId={run.id} />
        </Section>
      )}

      <Section
        id="documents"
        className={reviewing ? "panel--you" : ""}
        eyebrow={reviewing ? "Needs you · final review" : "Documents"}
        title={`Draft ${d.iteration}${d.source === "user" ? " (your edit)" : ""}`}
        actions={
          <div className="downloads">
            {["cv.pdf", "cover-letter.pdf"]
              .filter((n) => n in d.files)
              .map((n) => (
                <Button key={n} as="a" href={files.draft(run.id, d.iteration, n)} download variant="ghost" size="sm">
                  {n === "cv.pdf" ? "CV" : "Cover letter"} PDF
                </Button>
              ))}
          </div>
        }
      >
        {run.state.review_stop_reason && (
          <p className="hint">
            Review finished after {drafts.length} draft(s): {run.state.review_stop_reason}.
            {run.state.final_draft !== drafts[drafts.length - 1].iteration && ` Draft ${run.state.final_draft} is used.`}
          </p>
        )}
        {reviewing && open > 0 && (
          <p className="error-note">
            <strong>This draft still has {open} open problem(s).</strong> Fix them in the editor, or approve anyway if you disagree.
          </p>
        )}
        {reviewing && (
          <div className="actions">
            <Button variant="glow" sparkle loading={action.busy} onClick={() => action.run(() => api.approveRun(run.id).then(onChange))}>
              Approve and finish
            </Button>
            <Button as={Link} to={`/runs/${run.id}/edit`} variant="ghost">
              Edit text
            </Button>
          </div>
        )}
        <ErrorNote error={action.error} />
        <Checks d={d} />

        <details>
          <summary>Content with sources</summary>
          <p>
            <strong>Profile:</strong> {d.cv.profile} <FactRefs ids={d.cv.profile_fact_ids} facts={run.facts} />
          </p>
          {d.cv.titles
            .filter((t) => t.id.startsWith("pos"))
            .map((t) => (
              <div key={t.id}>
                <h4>
                  {t.title} <span className="muted">({run.facts[t.id] ?? t.id})</span>
                </h4>
                <ul>
                  {d.cv.bullets
                    .filter((b) => b.position_id === t.id)
                    .map((b) => (
                      <li key={b.text}>
                        {b.text} <FactRefs ids={b.fact_ids} facts={run.facts} />
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          {d.letter && (
            <>
              <h4>Cover letter: {d.letter.subject}</h4>
              {d.letter.paragraphs.map((p) => (
                <p key={p.text}>
                  {p.text} <FactRefs ids={p.fact_ids} facts={run.facts} />
                </p>
              ))}
            </>
          )}
        </details>

        {drafts.length > 1 && (
          <details>
            <summary>All drafts</summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Draft</th>
                    <th>Fact</th>
                    <th>Claims</th>
                    <th>ATS</th>
                    <th>Recruiter</th>
                    <th>Files</th>
                  </tr>
                </thead>
                <tbody>
                  {drafts.map((e) => (
                    <tr key={e.iteration} className={e.iteration === d.iteration ? "current" : ""}>
                      <td>
                        {e.iteration}
                        {e.source === "user" && " (yours)"}
                        {e.iteration === d.iteration && " ✓"}
                      </td>
                      <td>{e.cv_report.violations.length + e.letter_report.violations.length}</td>
                      <td>{e.claims?.length ?? 0}</td>
                      <td>{e.ats ? `${Math.round(e.ats.coverage * 100)}%` : ""}</td>
                      <td>{e.recruiter ? e.recruiter.average : "—"}</td>
                      <td>
                        {Object.keys(e.files)
                          .filter((n) => n.endsWith(".pdf"))
                          .map((n) => (
                            <a key={n} href={files.draft(run.id, e.iteration, n)} download>
                              {n}{" "}
                            </a>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </Section>
    </>
  );
}
