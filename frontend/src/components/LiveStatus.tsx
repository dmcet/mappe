import { EyebrowPill, StatusDot, WibblingSpinner } from "performative-ui";
import { Link } from "react-router";
import { duration, modelName } from "../format";
import { useLive } from "../live";
import type { Job } from "../types";

function JobLine({ job }: { job: Job }) {
  const href = job.kind === "run" ? `/runs/${job.id}` : `/cvs/${job.id}`;
  const info = [
    duration(job.detail_elapsed_s),
    modelName(job.model),
  ].join(" · ");
  return (
    <Link to={href} className="job-line" title={`${job.title}: running for ${duration(job.elapsed_s)}`}>
      {/* key: a new detail restarts the spinner with that detail as its verb */}
      <WibblingSpinner
        key={job.detail}
        verbs={[job.detail || "Starting"]}
        ellipsis="…"
        info={info}
        glyphColor={job.model ? "var(--pui-grad-mid)" : "var(--pui-grad-to)"}
      />
      <span className="job-title">{job.title}</span>
    </Link>
  );
}

/** The central "what is happening right now" indicator, shown on every page. */
export function LiveStatus() {
  const { status, connected } = useLive();
  if (!connected || !status) {
    return (
      <div className="live-status">
        <EyebrowPill statusColor="var(--pui-fg-mute)">Connecting…</EyebrowPill>
      </div>
    );
  }
  const waiting = status.waiting_for_you;
  return (
    <div className="live-status" aria-live="polite">
      {status.jobs.map((job) => (
        <JobLine key={`${job.kind}-${job.id}`} job={job} />
      ))}
      {status.jobs.length === 0 && (
        <EyebrowPill statusColor="var(--pui-success)" className="idle-pill">
          {waiting.length ? "Nothing running" : "All quiet"}
        </EyebrowPill>
      )}
      {status.queued.length > 0 && (
        <span className="queued">{status.queued.length} queued</span>
      )}
      {waiting.map((run) => (
        <Link key={run.id} to={`/runs/${run.id}`} className="waiting-pill" title={run.prompt}>
          <StatusDot color="var(--pui-warn)" />
          <span>
            <strong>{run.prompt}</strong> · {run.title}
          </span>
        </Link>
      ))}
    </div>
  );
}
