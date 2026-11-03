"""Build template data for the CV and cover letter, and render them to PDF.

Facts that must not change (employers, clients, dates, locations, education,
certifications, languages, contact data) come from the parsed CV; only the wording
comes from the author.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from application_crew.checks.completeness import parse_month
from application_crew.domain.author import AuthorCV, AuthorLetter
from application_crew.domain.models import ParsedCV, ParsedListing, Position
from application_crew.render.typst import RenderResult, render

LABELS = {
    "de": {
        "profile": "Profil",
        "experience": "Berufserfahrung",
        "skills": "Kenntnisse",
        "education": "Ausbildung",
        "certifications": "Zertifizierungen",
        "languages": "Sprachen",
        "extra": "Projekte und Engagement",
        "present": "heute",
        "client": "Kundeneinsatz bei",
        "native": "Muttersprache",
        "salutation": "Sehr geehrte Damen und Herren,",
        "closing": "Mit freundlichen Grüßen",
    },
    "en": {
        "profile": "Profile",
        "experience": "Experience",
        "skills": "Skills",
        "education": "Education",
        "certifications": "Certifications",
        "languages": "Languages",
        "extra": "Projects and Activities",
        "present": "Present",
        "client": "client:",
        "native": "Native",
        "salutation": "Dear Hiring Team,",
        "closing": "Kind regards",
    },
}

MONTHS = {
    "de": [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ],
    "en": [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
}

# Spoken language names for the other document language.
LANGUAGE_NAMES = {
    "en": {
        "deutsch": "German",
        "englisch": "English",
        "russisch": "Russian",
        "französisch": "French",
        "spanisch": "Spanish",
        "italienisch": "Italian",
        "polnisch": "Polish",
        "türkisch": "Turkish",
        "ukrainisch": "Ukrainian",
    },
    "de": {
        "german": "Deutsch",
        "english": "Englisch",
        "russian": "Russisch",
        "french": "Französisch",
        "spanish": "Spanisch",
        "italian": "Italienisch",
        "polish": "Polnisch",
        "turkish": "Türkisch",
        "ukrainian": "Ukrainisch",
    },
}


def _month(value: str | None) -> str:
    d = parse_month(value)
    if d is None:
        return value or ""
    return f"{d.month:02d}/{d.year}" if value and "-" in value else str(d.year)


def _dates(start: str | None, end: str | None, lang: str, ongoing: bool) -> str:
    end_text = LABELS[lang]["present"] if ongoing else _month(end)
    start_text = _month(start)
    return f"{start_text} – {end_text}" if start_text else end_text


def _company(p: Position, lang: str) -> str:
    if not p.client:
        return p.company
    return f"{p.company} · {LABELS[lang]['client']} {p.client}"


def _language_line(cv: ParsedCV, lang: str) -> str:
    parts = []
    for item in cv.languages:
        name = LANGUAGE_NAMES[lang].get(item.name.casefold(), item.name)
        level = LABELS[lang]["native"] if item.level.casefold() == "native" else item.level
        parts.append(f"{name} ({level})" if level else name)
    return " · ".join(parts)


def _links(cv: ParsedCV) -> dict[str, str]:
    out = {"github": "", "linkedin": "", "site": ""}
    for link in cv.contact.links:
        bare = link.split("://", 1)[-1].rstrip("/")
        if "github.com" in bare and not out["github"]:
            out["github"] = bare
        elif "linkedin.com" in bare and not out["linkedin"]:
            out["linkedin"] = bare
        elif not out["site"]:
            out["site"] = bare
    return out


def cv_data(cv: ParsedCV, doc: AuthorCV, lang: str, translate_titles: bool) -> dict[str, Any]:
    labels = LABELS[lang]
    titles = {t.position_id: t.title for t in doc.titles}
    positions = []
    for p in cv.positions:
        title = titles.get(p.id) if translate_titles else None
        positions.append(
            {
                "title": title or p.role,
                "company": _company(p, lang),
                "location": p.location or "",
                "dates": _dates(p.start, p.end, lang, ongoing=p.end is None),
                "bullets": [b.text for b in doc.bullets if b.position_id == p.id],
            }
        )
    extra_texts = {f.id: f.text for f in cv.projects + cv.publications + cv.volunteering}
    return {
        "lang": lang,
        "name": cv.contact.name,
        "headline": cv.headline or "",
        "contact": {
            "location": cv.contact.city or "",
            "email": cv.contact.email or "",
            "phone": cv.contact.phone or "",
            **_links(cv),
        },
        "labels": labels,
        "profile": doc.profile,
        "positions": positions,
        "skills": [
            {"category": g.category, "items": ", ".join(g.skills)}
            for g in doc.skill_groups
            if g.skills
        ],
        "education": [
            {
                "institution": e.institution,
                "degree": e.qualification,
                "location": e.location or "",
                "dates": _dates(e.start, e.end, lang, ongoing=False),
            }
            for e in cv.education
        ],
        "certifications": [
            {
                "name": f"{c.name} ({c.abbreviation})" if c.abbreviation else c.name,
                "issuer": c.issuer or "",
                "date": str(c.year or ""),
            }
            for c in cv.certifications
        ],
        "extra": [b.text for b in doc.extra if any(i in extra_texts for i in b.fact_ids)],
        "languages": _language_line(cv, lang),
    }


def letter_data(
    cv: ParsedCV, listing: ParsedListing, letter: AuthorLetter, lang: str, today: date
) -> dict[str, Any]:
    labels = LABELS[lang]
    c = cv.contact
    if lang == "de":
        when = f"{today.day}. {MONTHS['de'][today.month - 1]} {today.year}"
    else:
        when = f"{today.day} {MONTHS['en'][today.month - 1]} {today.year}"
    recipient = [x for x in (listing.company, listing.location) if x] or ["—"]
    return {
        "lang": lang,
        "date": when,
        "subject": letter.subject,
        "sender": {
            "name": c.name,
            "address": c.address or c.city or "",
            "contact": [x for x in (c.phone, c.email) if x],
        },
        "recipient": recipient,
        "salutation": labels["salutation"],
        "paragraphs": [p.text for p in letter.paragraphs],
        "closing": labels["closing"],
    }


def render_cv(data: dict[str, Any], out: Path) -> RenderResult:
    return render("cv", data, out)


def render_letter(data: dict[str, Any], out: Path) -> RenderResult:
    return render("cover-letter", data, out)
