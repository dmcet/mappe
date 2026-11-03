import { Button, GlassCard, GradientText } from "performative-ui";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { MiniPipeline } from "../components/Pipeline";
import {
  EMPTY_REQUIREMENTS,
  RequirementsEditor,
  fromRequirements,
  toRequirements,
} from "../components/RequirementsEditor";
import { ConfirmButton, ErrorNote, Section, StatusBadge, useAction } from "../components/ui";
import { usd, when } from "../format";
import { useLive, useResource } from "../live";
import type { RunSummary } from "../types";

const VERDICTS = { apply: "Apply", consider: "Consider", dont_apply: "Don't apply" };

function RunCard({ run, onDeleted }: { run: RunSummary; onDeleted: () => void }) {
  const working = run.pipeline.some((s) => s.state === "active");
  return (
    <GlassCard className={`run-card${working ? " run-card--working" : ""}`} glowOnHover>
      <Link to={`/runs/${run.id}`} className="run-card__link">
        <div className="run-card__top">
          <StatusBadge status={run.status} />
          {run.verdict && (
            <span className={`verdict-chip verdict-chip--${run.verdict}`}>
              {VERDICTS[run.verdict]} · {run.score}
            </span>
          )}
        </div>
        <h3 className="run-card__title">{run.title}</h3>
        <MiniPipeline stages={run.pipeline} />
        {run.error && <p className="run-card__error">{run.error}</p>}
      </Link>
      <footer className="run-card__foot">
        <span>{when(run.updated_at)}</span>
        <span className="mono">{usd(run.cost_usd)}</span>
        {!working && (
          <ConfirmButton
            label="Delete"
            title="Delete this application?"
            body={
              <p>
                <strong>{run.title}</strong> with all drafts and files will be deleted. Its costs
                stay in the cost history.
              </p>
            }
            onConfirm={async () => {
              await api.deleteRun(run.id);
              onDeleted();
            }}
          />
        )}
      </footer>
    </GlassCard>
  );
}

function NewApplication({ onCreated }: { onCreated: () => void }) {
  const { version } = useLive();
  const cvs = useResource(() => api.cvs(), [version("any")]);
  const confirmed = (cvs.data ?? []).filter((c) => c.status === "confirmed");
  const [cvId, setCvId] = useState<number | null>(null);
  const [urls, setUrls] = useState("");
  const [text, setText] = useState("");
  const [reqs, setReqs] = useState(EMPTY_REQUIREMENTS);
  const action = useAction();
  const navigate = useNavigate();

  useEffect(() => {
    api.lastRequirements().then((r) => setReqs(fromRequirements(r)));
  }, []);
  useEffect(() => {
    if (cvId === null && confirmed.length) setCvId(confirmed[0].id);
  }, [confirmed, cvId]);

  if (cvs.data && !confirmed.length) {
    return (
      <Section title="New application" eyebrow="Start here">
        <p>
          First add your CV and confirm what was extracted. <Link to="/cvs">Go to CVs →</Link>
        </p>
      </Section>
    );
  }

  return (
    <Section title="New application" eyebrow="Start">
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          if (cvId === null) return;
          const created = await action.run(() =>
            api.createRuns({
              cv_id: cvId,
              urls: urls.split("\n").map((u) => u.trim()).filter(Boolean),
              listing_text: text,
              requirements: toRequirements(reqs),
            }),
          );
          if (created) {
            setUrls("");
            setText("");
            onCreated();
            if (created.length === 1) navigate(`/runs/${created[0].id}`);
          }
        }}
      >
        <label>
          CV
          <select value={cvId ?? ""} onChange={(e) => setCvId(Number(e.target.value))}>
            {confirmed.map((cv) => (
              <option key={cv.id} value={cv.id}>
                {cv.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Job listing URLs (one per line)
          <textarea rows={3} value={urls} onChange={(e) => setUrls(e.target.value)} placeholder="https://…" />
        </label>
        <label>
          …or paste a listing
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <RequirementsEditor value={reqs} onChange={setReqs} />
        <ErrorNote error={action.error} />
        <Button type="submit" variant="glow" sparkle loading={action.busy} disabled={!urls.trim() && !text.trim()}>
          Start
        </Button>
      </form>
    </Section>
  );
}

export function Dashboard() {
  const { version, status } = useLive();
  const runs = useResource(() => api.runs(), [version("any")]);
  const waiting = status?.waiting_for_you ?? [];

  return (
    <div className="page">
      <div className="hero">
        <h1>
          <GradientText>Applications</GradientText>
        </h1>
        <p className="hero__sub">
          Tailored, fact-checked CVs and cover letters for the German IT market.
        </p>
      </div>

      {waiting.length > 0 && (
        <div className="needs-you">
          {waiting.map((w) => (
            <Link key={w.id} to={`/runs/${w.id}`} className="needs-you__item">
              <span className="needs-you__prompt">{w.prompt}</span>
              <span className="needs-you__title">{w.title}</span>
              <span className="pui-arrow">→</span>
            </Link>
          ))}
        </div>
      )}

      <div className="dashboard">
        <div>
          <ErrorNote error={runs.error} />
          {runs.data && runs.data.length === 0 && (
            <p className="empty">No applications yet. Start one on the right.</p>
          )}
          <div className="run-grid">
            {(runs.data ?? []).map((run) => (
              <RunCard key={run.id} run={run} onDeleted={runs.reload} />
            ))}
          </div>
        </div>
        <NewApplication onCreated={runs.reload} />
      </div>
    </div>
  );
}
