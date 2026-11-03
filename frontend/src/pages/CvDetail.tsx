import { Button, GradientText, WibblingSpinner } from "performative-ui";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { api } from "../api";
import { ConfirmButton, ErrorNote, Section, StatusBadge, useAction } from "../components/ui";
import { usd } from "../format";
import { useLive, useResource } from "../live";
import type { CVDetail, Skill } from "../types";

const LEVELS: [Skill["level"], string][] = [
  ["advanced", "Advanced"],
  ["intermediate", "Intermediate"],
  ["basic", "Basic"],
  [null, "No level stated"],
];

function Extracted({ cv }: { cv: CVDetail }) {
  const p = cv.parsed!;
  return (
    <>
      <Section title="Experience" eyebrow={`${p.positions.length} positions`}>
        {p.positions.map((pos) => (
          <article key={pos.id} className="position">
            <h3>
              {pos.role} · {pos.company}
              {pos.client && <span className="muted"> · client: {pos.client}</span>}
            </h3>
            <p className="muted">
              {pos.start || "?"} – {pos.end ?? "present"}
              {pos.location && ` · ${pos.location}`} <code className="fact">{pos.id}</code>
            </p>
            <ul>
              {pos.responsibilities.map((f) => (
                <li key={f.id}>{f.text}</li>
              ))}
              {pos.achievements.map((f) => (
                <li key={f.id} className="achievement">
                  {f.text}
                </li>
              ))}
            </ul>
            {pos.technologies.length > 0 && (
              <p className="tags">
                {pos.technologies.map((t) => (
                  <span key={t}>{t}</span>
                ))}
              </p>
            )}
          </article>
        ))}
      </Section>
      <div className="grid-2">
        <Section title="Skills">
          {LEVELS.map(([level, label]) => {
            const group = p.skills.filter((s) => s.level === level);
            return group.length ? (
              <div key={label}>
                <h4 className="muted">{label}</h4>
                <p className="tags">
                  {group.map((s) => (
                    <span key={s.name} title={s.level_text ?? undefined}>
                      {s.name}
                    </span>
                  ))}
                </p>
              </div>
            ) : null;
          })}
          <h4 className="muted">Languages</h4>
          <p>{p.languages.map((l) => `${l.name} (${l.level || "level missing"})`).join(" · ")}</p>
        </Section>
        <Section title="Education & certifications">
          <ul>
            {p.education.map((e) => (
              <li key={e.id}>
                {e.qualification}, {e.institution} · {e.start ?? "?"} – {e.end ?? "?"}
              </li>
            ))}
            {p.certifications.map((c) => (
              <li key={c.id}>
                {c.name}
                {c.issuer && `, ${c.issuer}`}
                {c.year && `, ${c.year}`}
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </>
  );
}

export function CvDetailPage() {
  const id = Number(useParams().id);
  const { version } = useLive();
  const cv = useResource(() => api.cv(id), [id, version("cv", id)]);
  const [quick, setQuick] = useState<Record<string, string>>({});
  const [markdown, setMarkdown] = useState("");
  const action = useAction();
  const navigate = useNavigate();

  useEffect(() => {
    if (cv.data) {
      setQuick(cv.data.quick_values);
      setMarkdown(cv.data.markdown);
    }
  }, [cv.data]);

  if (!cv.data) return <div className="page"><ErrorNote error={cv.error} /></div>;
  const data = cv.data;

  return (
    <div className="page">
      <div className="hero hero--row">
        <div>
          <h1>
            <GradientText>{data.label}</GradientText>
          </h1>
          <p className="hero__sub">
            <StatusBadge status={data.status} /> <span className="mono">{usd(data.cost_usd)}</span>
          </p>
        </div>
        <ConfirmButton
          label="Delete CV"
          title="Delete this CV?"
          body={
            data.runs ? (
              <p>
                It has <strong>{data.runs} application(s)</strong>. They will be deleted too, with all drafts and files.
                The cost history is kept.
              </p>
            ) : (
              <p>The CV will be deleted. The cost history is kept.</p>
            )
          }
          onConfirm={async () => {
            await api.deleteCv(id, data.runs > 0);
            navigate("/cvs");
          }}
        />
      </div>

      {data.status === "parsing" && (
        <Section>
          <WibblingSpinner verbs={["Reading your CV"]} info="Claude extracts every position, bullet and skill" />
        </Section>
      )}
      <ErrorNote error={data.error} />

      {data.summary && (
        <Section title="Summary" eyebrow="Extracted">
          <ul className="facts">
            <li>
              <strong>{data.summary.name}</strong>
              {data.summary.current_role && ` · ${data.summary.current_role}`}
            </li>
            {data.parsed?.headline && <li className="muted">{data.parsed.headline}</li>}
            <li>
              {data.summary.years_of_experience} years of experience across {data.summary.positions} positions
            </li>
            <li>
              {data.summary.skills} skills · {data.summary.certifications} certifications · {data.summary.education} education
              entries
            </li>
            <li>Languages: {data.summary.languages.join(", ") || "none"}</li>
          </ul>
        </Section>
      )}

      {data.warnings.length > 0 && (
        <Section title={`Missing or unclear (${data.warnings.length})`} className="panel--warn">
          <ul>
            {data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          <p className="hint">Fill in the fields below, fix the Markdown and parse again, or confirm anyway if something doesn't apply.</p>
        </Section>
      )}

      {data.status === "waiting_for_confirmation" && (
        <div className="grid-2">
          <Section title="Quick fixes">
            <div className="stack">
              {Object.entries(data.quick_fields).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input value={quick[key] ?? ""} onChange={(e) => setQuick({ ...quick, [key]: e.target.value })} />
                </label>
              ))}
              <Button variant="ghost" loading={action.busy} onClick={() => action.run(() => api.updateCvFields(id, quick).then(cv.setData))}>
                Save fields
              </Button>
            </div>
          </Section>
          <Section title="Confirm" eyebrow="Gate">
            <p>Check the extracted data below. Everything later is based on it, and nothing outside it is used.</p>
            <Button variant="glow" sparkle loading={action.busy} onClick={() => action.run(() => api.confirmCv(id).then(cv.setData))}>
              Confirm CV{data.warnings.length ? " anyway" : ""}
            </Button>
          </Section>
        </div>
      )}
      <ErrorNote error={action.error} />

      {data.parsed && <Extracted cv={data} />}

      {data.status !== "parsing" && (
        <Section title={data.status === "failed" ? "Retry" : "Edit and parse again"}>
          <div className="stack">
            <textarea rows={14} value={markdown} onChange={(e) => setMarkdown(e.target.value)} />
            {data.status === "confirmed" && <p className="hint">Parsing again resets the confirmation.</p>}
            <Button variant="ghost" loading={action.busy} onClick={() => action.run(() => api.reparseCv(id, markdown).then(cv.setData))}>
              Save and parse again
            </Button>
          </div>
        </Section>
      )}
    </div>
  );
}
