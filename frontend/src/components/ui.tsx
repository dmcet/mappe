import { Button, Popover, StatusDot } from "performative-ui";
import { useState } from "react";
import type { ReactNode } from "react";
import { STATUS_LABELS, tone } from "../format";

const TONE_COLORS = {
  busy: "var(--pui-grad-to)",
  you: "var(--pui-warn)",
  good: "var(--pui-success)",
  bad: "var(--pui-danger)",
  muted: "var(--pui-fg-mute)",
};

export function StatusBadge({ status }: { status: string }) {
  const t = tone(status);
  return (
    <span className={`badge badge--${t}`}>
      <StatusDot color={TONE_COLORS[t]} static={t !== "busy" && t !== "you"} />
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function Outcome({ value, children }: { value: "good" | "bad" | "neutral"; children: ReactNode }) {
  return <span className={`outcome outcome--${value}`}>{children}</span>;
}

/** Fact IDs as small chips; hover shows the original CV text. */
export function FactRefs({ ids, facts }: { ids: string[]; facts: Record<string, string> }) {
  return (
    <>
      {ids.map((id) => (
        <code key={id} className="fact" title={facts[id] ?? "unknown fact"}>
          {id}
        </code>
      ))}
    </>
  );
}

export function Section({
  title,
  eyebrow,
  actions,
  children,
  className = "",
  id,
}: {
  title?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} id={id}>
      {(title || actions) && (
        <header className="panel__head">
          <div>
            {eyebrow && <div className="panel__eyebrow">{eyebrow}</div>}
            {title && <h2>{title}</h2>}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  return error ? <p className="error-note">{error}</p> : null;
}

/** A button that asks before doing something destructive. */
export function ConfirmButton({
  label,
  title,
  body,
  confirmLabel = "Delete",
  onConfirm,
}: {
  label: ReactNode;
  title: ReactNode;
  body: ReactNode;
  confirmLabel?: string;
  onConfirm: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        {label}
      </Button>
      <Popover
        open={open}
        onOpenChange={setOpen}
        title={title}
        closeLabel={false}
        closeOnEscape
        closeOnBackdrop
      >
        <div className="confirm">
          <div className="confirm__body">{body}</div>
          <ErrorNote error={error} />
          <div className="confirm__actions">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="solid"
              className="danger"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await onConfirm();
                  setOpen(false);
                } catch (err) {
                  setError((err as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </div>
      </Popover>
    </>
  );
}

/** Run an async action with a busy flag and an error message. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError((err as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run, setError };
}
