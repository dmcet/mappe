import { Sparkle, StatusDot } from "performative-ui";
import type { Job, Stage } from "../types";

const ICONS: Record<Stage["state"], string> = {
  done: "✓",
  active: "",
  waiting: "",
  failed: "✕",
  declined: "–",
  pending: "",
};

/** The pipeline stepper: every stage of an application with its live state. */
export function Pipeline({ stages, job }: { stages: Stage[]; job?: Job }) {
  return (
    <ol className="pipeline" aria-label="Pipeline">
      {stages.map((stage) => (
        <li key={stage.key} className={`stage stage--${stage.state}`} aria-current={stage.state === "active" ? "step" : undefined}>
          <span className="stage__node">
            {stage.state === "active" ? (
              <Sparkle glyph="✦" />
            ) : stage.state === "waiting" ? (
              <StatusDot color="var(--pui-warn)" />
            ) : (
              ICONS[stage.state]
            )}
          </span>
          <span className="stage__label">{stage.label}</span>
          <span className="stage__hint">
            {stage.state === "active" && job?.detail ? job.detail : stage.hint}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Compact version for run cards. */
export function MiniPipeline({ stages }: { stages: Stage[] }) {
  return (
    <span className="mini-pipeline" aria-hidden="true">
      {stages.map((s) => (
        <span key={s.key} className={`mini-pipeline__dot stage--${s.state}`} title={`${s.label}: ${s.state}`} />
      ))}
    </span>
  );
}
