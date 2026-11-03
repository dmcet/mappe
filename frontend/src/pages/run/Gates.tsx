import { Button } from "performative-ui";
import { useState } from "react";
import { api } from "../../api";
import { ErrorNote, Section, useAction } from "../../components/ui";
import type { RunDetail } from "../../types";

/** The panels where the run waits for the user: paste text, must-have stop. */
export function Gates({ run, onChange }: { run: RunDetail; onChange: (r: RunDetail) => void }) {
  const [text, setText] = useState("");
  const action = useAction();

  if (run.status === "waiting_for_listing_text") {
    const reason = [...run.events].reverse().find((e) => e.kind === "step_progress")?.message;
    return (
      <Section title="Paste the listing" eyebrow="Needs you" className="panel--you">
        <p>
          The listing couldn't be used automatically{reason ? `: ${reason}` : ""}. Copy the text from the page and paste
          it here.
        </p>
        <div className="stack">
          <textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} />
          <ErrorNote error={action.error} />
          <Button
            variant="glow"
            sparkle
            disabled={!text.trim()}
            loading={action.busy}
            onClick={() => action.run(() => api.submitListingText(run.id, text).then(onChange))}
          >
            Continue
          </Button>
        </div>
      </Section>
    );
  }

  if (run.status === "stopped_by_requirements") {
    return (
      <Section title="A must-have isn't met" eyebrow="Needs you" className="panel--you">
        <p>The listing contradicts at least one of your must-haves (see the requirements below). Stop here, or continue anyway.</p>
        <ErrorNote error={action.error} />
        <div className="actions">
          <Button variant="solid" loading={action.busy} onClick={() => action.run(() => api.declineRun(run.id).then(onChange))}>
            Don't apply
          </Button>
          <Button variant="ghost" loading={action.busy} onClick={() => action.run(() => api.continueRun(run.id).then(onChange))}>
            Continue anyway
          </Button>
        </div>
      </Section>
    );
  }
  return null;
}
