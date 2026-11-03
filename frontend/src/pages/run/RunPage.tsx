import { GradientText, WibblingSpinner } from "performative-ui";
import { useNavigate, useParams } from "react-router";
import { api } from "../../api";
import { Pipeline } from "../../components/Pipeline";
import { ConfirmButton, ErrorNote, Section, StatusBadge } from "../../components/ui";
import { duration, modelName, usd } from "../../format";
import { useLive, useResource } from "../../live";
import { Assessment, Coverage } from "./Assessment";
import { ActivityPanel, ListingPanel, RequirementsPanel } from "./Details";
import { Documents } from "./Documents";
import { Gates } from "./Gates";

export function RunPage() {
  const id = Number(useParams().id);
  const { version, status } = useLive();
  const run = useResource(() => api.run(id), [id, version("run", id)]);
  const navigate = useNavigate();
  const job = status?.jobs.find((j) => j.kind === "run" && j.id === id);

  if (!run.data) return <div className="page"><ErrorNote error={run.error} /></div>;
  const data = run.data;
  const working = data.pipeline.some((s) => s.state === "active");

  return (
    <div className="page">
      <div className="hero hero--row">
        <div>
          <h1>
            <GradientText>{data.title}</GradientText>
          </h1>
          <p className="hero__sub">
            <StatusBadge status={data.status} />
            {data.listing_url && (
              <a href={data.listing_url} target="_blank" rel="noreferrer noopener">
                {data.listing_url}
              </a>
            )}
            <span className="mono">{usd(data.cost_usd)}</span>
          </p>
        </div>
        {!working && (
          <ConfirmButton
            label="Delete"
            title="Delete this application?"
            body={<p>All drafts and files of this application will be deleted. Its costs stay in the cost history.</p>}
            onConfirm={async () => {
              await api.deleteRun(id);
              navigate("/");
            }}
          />
        )}
      </div>

      <Section className="pipeline-panel">
        <Pipeline stages={data.pipeline} job={job} />
        {job && (
          <div className="now">
            <WibblingSpinner
              key={job.detail}
              verbs={[job.detail || "Starting"]}
              info={`${duration(job.detail_elapsed_s)} · ${modelName(job.model)}`}
              glyphColor="var(--pui-grad-mid)"
            />
            <span className="muted">running for {duration(job.elapsed_s)}</span>
          </div>
        )}
        {data.status === "failed" && <ErrorNote error={data.error} />}
      </Section>

      <Gates run={data} onChange={run.setData} />
      <Documents run={data} onChange={run.setData} />
      {data.state.match && <Assessment run={data} onChange={run.setData} />}
      {data.state.analysis && <Coverage run={data} />}
      <RequirementsPanel run={data} />
      <ListingPanel run={data} />
      <ActivityPanel run={data} />
    </div>
  );
}
