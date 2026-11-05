"""The application contact of a listing: email address, name and form of address.

Claude reads the contact name and email from the listing as part of the listing parse (no
extra call). Python keeps only what the listing text shows: an email address must appear in
the text or in the JSON-LD, and a name must appear in the text. The form of address comes
from Python alone: "Frau"/"Herr" (Ms/Mr) right before the name, never the first name. When
Claude found no address, a regex scan of the text fills the gap.
"""

from __future__ import annotations

import re
from typing import Any, Literal

ContactGender = Literal["female", "male"]

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# "bewerbung(at)firma.de", "jobs [at] firma [dot] de"
_AT = re.compile(r"\s*[\(\[\{]\s*(?:at|ät)\s*[\)\]\}]\s*", re.IGNORECASE)
_DOT = re.compile(r"\s*[\(\[\{]\s*(?:dot|punkt)\s*[\)\]\}]\s*", re.IGNORECASE)

# Addresses nobody reads, or that are not for applications.
_IGNORED = re.compile(
    r"^(no-?reply|do-?not-?reply|datenschutz|privacy|dsb|gdpr|webmaster|presse|press|"
    r"marketing|newsletter|support|abuse|postmaster)\b",
    re.IGNORECASE,
)
_APPLICATION_WORDS = re.compile(
    r"bewerb|job|karriere|career|recruit|talent|hr\b|personal|people|hiring", re.IGNORECASE
)

_FEMALE = r"Frau|Fr\.|Ms\.?|Mrs\.?"
_MALE = r"Herrn?|Hr\.|Mr\.?"
_ACADEMIC = r"(?:(?:Prof\.|Dr\.(?:-Ing\.)?|Dipl\.-\w+\.)\s*)*"


def _deobfuscate(text: str) -> str:
    return _DOT.sub(".", _AT.sub("@", text))


def emails_in(text: str) -> list[str]:
    """Email addresses in the text, in order, without duplicates (case-insensitive)."""
    seen: dict[str, str] = {}
    for match in _EMAIL.finditer(_deobfuscate(text)):
        address = match.group(0).strip(".")
        seen.setdefault(address.lower(), address)
    return list(seen.values())


def _posting_emails(job_posting: dict[str, Any] | None) -> list[str]:
    contact = (job_posting or {}).get("applicationContact")
    contacts = contact if isinstance(contact, list) else [contact]
    return [
        c["email"].removeprefix("mailto:").strip()
        for c in contacts
        if isinstance(c, dict) and isinstance(c.get("email"), str) and "@" in c["email"]
    ]


def _usable(address: str) -> bool:
    return not _IGNORED.match(address.split("@")[0])


def choose_email(
    claimed: str | None, text: str, job_posting: dict[str, Any] | None, name: str | None
) -> str | None:
    """The address to send the application to, or None.

    Claude's choice wins if the listing contains it. Otherwise: the JSON-LD contact, then an
    address that matches the contact name or looks like an application address, then the only
    usable address in the text. Several unrelated addresses and no hint: None.
    """
    found = [a for a in _posting_emails(job_posting) + emails_in(text) if _usable(a)]
    by_lower = {a.lower(): a for a in found}
    if claimed and claimed.strip().lower() in by_lower:
        return by_lower[claimed.strip().lower()]
    if not found:
        return None
    posting = [a for a in _posting_emails(job_posting) if _usable(a)]
    if posting:
        return posting[0]
    if name:
        last = name.split()[-1].lower()
        for address in found:
            if last and last in address.split("@")[0].lower():
                return address
    for address in found:
        if _APPLICATION_WORDS.search(address.split("@")[0]):
            return address
    return found[0] if len(by_lower) == 1 else None


def _normalize(text: str) -> str:
    return " ".join(text.split())


def verify_name(name: str | None, text: str) -> str | None:
    """Keep a contact name only if the listing text contains it."""
    if not name or not name.strip():
        return None
    name = _normalize(re.sub(rf"^(?:(?:{_FEMALE}|{_MALE})\s+)?{_ACADEMIC}", "", name.strip()))
    return name if name and name.lower() in _normalize(text).lower() else None


def verify_gender(name: str | None, text: str) -> ContactGender | None:
    """Female/male only when "Frau"/"Herr" (or Ms/Mr) stands right before the name."""
    if not name:
        return None
    last = re.escape(name.split()[-1])
    full = re.escape(name).replace(r"\ ", r"\s+")
    flat = _normalize(text)
    found: set[ContactGender] = set()
    for gender, words in (("female", _FEMALE), ("male", _MALE)):
        pattern = rf"(?<!\w)(?:{words})\s+{_ACADEMIC}(?:{full}|{last})(?!\w)"
        if re.search(pattern, flat):
            found.add(gender)  # type: ignore[arg-type]
    return found.pop() if len(found) == 1 else None


def academic_title(name: str | None, text: str) -> str | None:
    """The academic title ("Dr.", "Prof. Dr.") the listing puts before the name."""
    if not name:
        return None
    last = re.escape(name.split()[-1])
    flat = _normalize(text)
    match = re.search(rf"((?:Prof\.\s*)?Dr\.)(?:-Ing\.)?\s+(?:[\w-]+\s+){{0,2}}{last}(?!\w)", flat)
    return " ".join(match.group(1).split()) if match else None


def resolve_contact(
    claimed_name: str | None,
    claimed_email: str | None,
    text: str,
    job_posting: dict[str, Any] | None,
) -> dict[str, Any]:
    """ParsedListing contact fields, verified against the listing."""
    name = verify_name(claimed_name, text)
    return {
        "contact_name": name,
        "contact_gender": verify_gender(name, text),
        "contact_academic_title": academic_title(name, text),
        "contact_email": choose_email(claimed_email, text, job_posting, name),
    }
