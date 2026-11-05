"""Build the application email from a finished run (deterministic, no Claude calls)."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr
from pathlib import Path

from mappe.domain.author import AuthorLetter
from mappe.domain.contact import choose_email
from mappe.domain.models import ParsedCV, ParsedListing
from mappe.render.documents import LABELS, salutation

SHORTCUT_NAME = "Mappe Mail"  # the Apple Shortcut the Mac button runs (docs/email.md)


class EmailUnavailable(Exception):
    """The run can't be sent by email; the message says why, for the UI."""


@dataclass
class EmailDraft:
    to: str
    subject: str
    body: str
    sender_name: str
    sender_email: str | None
    cv_name: str  # delivered file name, e.g. Doe_Jane_Lebenslauf_Firma.pdf
    cv_path: Path


def recipient(listing: ParsedListing, listing_text: str, job_posting: dict | None) -> str | None:
    """The listing's application address. Runs parsed before contacts existed fall back to a
    scan of the listing text."""
    return listing.contact_email or choose_email(
        None, listing_text, job_posting, listing.contact_name
    )


def body_text(cv: ParsedCV, listing: ParsedListing, letter: AuthorLetter, lang: str) -> str:
    """Greeting, the letter's paragraphs, closing formula and a signature from the CV."""
    c = cv.contact
    signature = [c.name, *(x for x in (c.phone, c.email) if x)]
    parts = [
        salutation(listing, lang),
        *(p.text for p in letter.paragraphs),
        LABELS[lang]["closing"] + "\n" + "\n".join(signature),
    ]
    return "\n\n".join(parts) + "\n"


def email_draft(runs_dir: Path, run) -> EmailDraft:
    """The email for a delivered run. Raises EmailUnavailable with a reason for the UI."""
    state = run.state or {}
    delivery = state.get("delivery")
    if not delivery:
        raise EmailUnavailable("The application isn't finished yet.")
    draft = next((d for d in state.get("drafts", []) if d["iteration"] == delivery["draft"]), None)
    if draft is None or not draft.get("letter"):
        raise EmailUnavailable("There is no cover letter, and the email text is the cover letter.")
    listing = ParsedListing.model_validate(state["listing"])
    job_posting = (state.get("fetch") or {}).get("job_posting")
    to = recipient(listing, run.listing_text or "", job_posting)
    if not to:
        raise EmailUnavailable("The listing gives no email address for applications.")
    cv_name = next((name for name, src in delivery["files"].items() if src == "cv.pdf"), None)
    cv_path = runs_dir / str(run.id) / "final" / (cv_name or "")
    if not cv_name or not cv_path.is_file():
        raise EmailUnavailable("The final CV PDF is missing.")

    cv = ParsedCV.model_validate(state["cv"])
    letter = AuthorLetter.model_validate(draft["letter"])
    lang = draft["lang"]
    return EmailDraft(
        to=to,
        subject=letter.subject,
        body=body_text(cv, listing, letter, lang),
        sender_name=cv.contact.name,
        sender_email=cv.contact.email,
        cv_name=cv_name,
        cv_path=cv_path,
    )


def build_eml(draft: EmailDraft) -> bytes:
    """An unsent email draft. ``X-Unsent: 1`` makes Outlook open it ready to edit and send."""
    msg = EmailMessage(policy=SMTP)
    if draft.sender_email:
        msg["From"] = formataddr((draft.sender_name, draft.sender_email))
    msg["To"] = draft.to
    msg["Subject"] = draft.subject
    msg["X-Unsent"] = "1"
    msg.set_content(draft.body)
    msg.add_attachment(
        draft.cv_path.read_bytes(), maintype="application", subtype="pdf", filename=draft.cv_name
    )
    return msg.as_bytes()
