import { Button, GlassCard, GradientText } from "performative-ui";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { ErrorNote, Section, StatusBadge, useAction } from "../components/ui";
import { usd, when } from "../format";
import { useLive, useResource } from "../live";

export function Cvs() {
  const { version } = useLive();
  const cvs = useResource(() => api.cvs(), [version("any")]);
  const [label, setLabel] = useState("");
  const [markdown, setMarkdown] = useState("");
  const action = useAction();
  const navigate = useNavigate();

  return (
    <div className="page">
      <div className="hero">
        <h1>
          <GradientText>CVs</GradientText>
        </h1>
        <p className="hero__sub">Your master CVs. Every application is built from one of them, and only from what it says.</p>
      </div>
      <div className="dashboard">
        <div className="run-grid">
          {(cvs.data ?? []).map((cv) => (
            <GlassCard key={cv.id} className="run-card" glowOnHover>
              <Link to={`/cvs/${cv.id}`} className="run-card__link">
                <div className="run-card__top">
                  <StatusBadge status={cv.status} />
                  {cv.warnings > 0 && <span className="verdict-chip verdict-chip--consider">{cv.warnings} warning(s)</span>}
                </div>
                <h3 className="run-card__title">{cv.label}</h3>
                <p className="muted">{cv.runs} application(s)</p>
              </Link>
              <footer className="run-card__foot">
                <span>{when(cv.updated_at)}</span>
                <span className="mono">{usd(cv.cost_usd)}</span>
              </footer>
            </GlassCard>
          ))}
          {cvs.data && cvs.data.length === 0 && <p className="empty">No CVs yet. Paste your first one.</p>}
        </div>
        <Section title="Add a CV" eyebrow="Markdown">
          <form
            className="stack"
            onSubmit={async (e) => {
              e.preventDefault();
              const cv = await action.run(() => api.createCv(label, markdown));
              if (cv) navigate(`/cvs/${cv.id}`);
            }}
          >
            <label>
              Label
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Master CV (DE)" required />
            </label>
            <label>
              CV (Markdown)
              <textarea rows={14} value={markdown} onChange={(e) => setMarkdown(e.target.value)} required />
            </label>
            <ErrorNote error={action.error} />
            <Button type="submit" variant="glow" sparkle loading={action.busy}>
              Parse CV
            </Button>
          </form>
        </Section>
      </div>
    </div>
  );
}
