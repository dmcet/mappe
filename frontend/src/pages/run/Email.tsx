import { Button } from "performative-ui";
import { useEffect, useState } from "react";
import { api } from "../../api";
import type { ApplicationEmail } from "../../types";

const SETUP_DOCS = "https://github.com/dmcet/mappe/blob/main/docs/email.md";

export function isMac(platform = navigator.userAgent): boolean {
  return /Macintosh|Mac OS X/.test(platform) && !/iPhone|iPad/.test(platform);
}

/** Hand the application email to the user's mail client. Mappe itself never sends. */
export function EmailPanel({ runId, mac = isMac() }: { runId: number; mac?: boolean }) {
  const [email, setEmail] = useState<ApplicationEmail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.email(runId).then(setEmail, (err: Error) => setError(err.message));
  }, [runId]);

  if (error) return <p className="error-note">{error}</p>;
  if (!email) return null;
  if (!email.available) return <p className="muted">Email: {email.reason}</p>;

  const shortcut = (
    <Button key="mac" as="a" href={email.shortcut_url} variant={mac ? "glow" : "ghost"}>
      Open in Apple Mail
    </Button>
  );
  const eml = (
    <Button key="eml" as="a" href={email.eml_url} download variant={mac ? "ghost" : "glow"}>
      Download email (.eml)
    </Button>
  );

  return (
    <div className="email">
      <h4>Send by email</h4>
      <dl className="kv">
        <dt>To</dt>
        <dd>{email.to}</dd>
        <dt>Subject</dt>
        <dd>{email.subject}</dd>
        <dt>Attachment</dt>
        <dd>{email.cv_name}</dd>
      </dl>
      <details>
        <summary>Email text</summary>
        <pre className="email__body">{email.body}</pre>
      </details>
      <div className="downloads">{mac ? [shortcut, eml] : [eml, shortcut]}</div>
      <p className="muted">
        Mappe doesn't send anything: your mail app opens the email ready to check and send.{" "}
        {mac ? (
          <>
            The Apple Mail button needs the “Mappe Mail” shortcut once (<a href={SETUP_DOCS}>setup</a>).
          </>
        ) : (
          <>Open the .eml file in Outlook or Thunderbird (“Edit as New Message”).</>
        )}
      </p>
    </div>
  );
}
