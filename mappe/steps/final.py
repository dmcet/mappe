"""Final review (user edits) and delivery.

Final review: the user edits the final draft in the UI. Each save becomes a new draft that
is rendered and checked deterministically (fact check + ATS, no Claude calls). Problems are
shown as warnings: the user has the last word.

Delivery: the approved draft's PDFs get clean file names in the run's ``final`` folder.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from mappe.checks.ats import check_ats
from mappe.checks.facts import FactChecker
from mappe.config import Settings
from mappe.domain.author import (
    AuthorBullet,
    AuthorCV,
    AuthorLetter,
    LetterParagraph,
    SkillGroup,
    Title,
)
from mappe.domain.models import ParsedCV, ParsedListing
from mappe.render.documents import LABELS
from mappe.render.typst import pdf_to_text
from mappe.runner import activity
from mappe.runner.engine import StepContext, step
from mappe.runner.states import RunStatus
from mappe.steps.author import load_analysis
from mappe.steps.common import run_cv
from mappe.steps.review import render_draft

MATCH_THRESHOLD = 60  # similarity (0-100) to keep an edited line's fact IDs


def final_draft(state: dict) -> dict:
    drafts = state["drafts"]
    wanted = state.get("final_draft", drafts[-1]["iteration"])
    return next(d for d in drafts if d["iteration"] == wanted)


class LetterEdit(BaseModel):
    subject: str
    paragraphs: list[str]


class DocumentEdit(BaseModel):
    """The user's edits of the final draft (sent by the editor)."""

    profile: str
    titles: dict[str, str] = Field(default_factory=dict)  # pos/edu/cert ID -> title
    bullets: dict[str, list[str]] = Field(default_factory=dict)  # position ID -> lines
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    letter: LetterEdit | None = None


def _match_ids(text: str, previous: list[tuple[str, list[str]]], fallback: list[str]) -> list[str]:
    """Fact IDs of the most similar previous item, or ``fallback`` for new text."""
    best, best_score = None, 0.0
    for old_text, ids in previous:
        score = fuzz.token_set_ratio(text, old_text)
        if score > best_score:
            best, best_score = ids, score
    return best if best is not None and best_score >= MATCH_THRESHOLD else fallback


def _clean(text: str) -> str:
    return " ".join(text.strip(" \t-•").split())


def apply_edits(
    cv: ParsedCV, doc: AuthorCV, letter: AuthorLetter | None, edit: DocumentEdit
) -> tuple[AuthorCV, AuthorLetter | None]:
    """Build new documents from the edits, keeping fact IDs where text was kept."""
    bullets: list[AuthorBullet] = []
    for p in cv.positions:
        previous = [(b.text, b.fact_ids) for b in doc.bullets if b.position_id == p.id]
        all_ids = [p.id] + [f.id for f in p.responsibilities + p.achievements]
        for line in edit.bullets.get(p.id, []):
            text = _clean(line)
            if text:
                ids = _match_ids(text, previous, all_ids)
                bullets.append(AuthorBullet(position_id=p.id, text=text, fact_ids=ids))

    titles = [
        Title(id=t.id, title=(edit.titles.get(t.id) or "").strip() or t.title) for t in doc.titles
    ]
    groups = [
        SkillGroup(category=g.category.strip(), skills=[s.strip() for s in g.skills if s.strip()])
        for g in edit.skill_groups
        if g.category.strip() and any(s.strip() for s in g.skills)
    ]
    new_doc = doc.model_copy(
        update={
            "profile": edit.profile.strip(),
            "titles": titles,
            "bullets": bullets,
            "skill_groups": groups,
        }
    )

    new_letter = None
    if letter is not None and edit.letter is not None:
        previous = [(p.text, p.fact_ids) for p in letter.paragraphs]
        new_letter = AuthorLetter(
            subject=edit.letter.subject.strip() or letter.subject,
            paragraphs=[
                LetterParagraph(text=_clean(p), fact_ids=_match_ids(_clean(p), previous, []))
                for p in edit.letter.paragraphs
                if _clean(p)
            ],
        )
    elif letter is not None:
        new_letter = letter
    return new_doc, new_letter


def save_user_draft(settings: Settings, run, edit: DocumentEdit) -> dict:
    """Store the user's edits as a new draft, rendered and checked without Claude."""
    state = run.state
    cv = ParsedCV.model_validate(state["cv"])
    listing = ParsedListing.model_validate(state["listing"])
    analysis = load_analysis(state["analysis"])
    base = final_draft(state)
    doc = AuthorCV.model_validate(base["cv"])
    letter = AuthorLetter.model_validate(base["letter"]) if base["letter"] else None
    new_doc, new_letter = apply_edits(cv, doc, letter, edit)

    iteration = max(d["iteration"] for d in state["drafts"]) + 1
    draft = {
        "iteration": iteration,
        "lang": base["lang"],
        "cv": new_doc.model_dump(mode="json"),
        "letter": new_letter.model_dump(mode="json") if new_letter else None,
    }
    out_dir = settings.runs_dir / str(run.id) / f"draft-{iteration}"
    files = render_draft(cv, listing, draft, out_dir)  # raises on a rendering error

    checker = FactChecker(cv, analysis)
    cv_report = checker.check_cv(new_doc)
    letter_report = checker.check_letter(new_letter) if new_letter else None
    ats = check_ats(pdf_to_text(out_dir / "cv.pdf"), cv, analysis, LABELS[base["lang"]])
    entry = {
        **draft,
        "source": "user",
        "based_on": base["iteration"],
        "cv_report": {"violations": cv_report.violations, "warnings": cv_report.warnings},
        "letter_report": {
            "violations": letter_report.violations if letter_report else [],
            "warnings": letter_report.warnings if letter_report else [],
        },
        "claims": [],
        "ats": ats.to_dict(),
        "recruiter": None,
        "clean": cv_report.ok and (letter_report is None or letter_report.ok) and ats.passed,
        "score": 0.0,
        "accepted": False,
        "files": files,
    }
    run.state = state | {"drafts": [*state["drafts"], entry], "final_draft": iteration}
    return entry


# --- delivery ---------------------------------------------------------------------------

DOC_NAMES = {
    "de": {"cv": "Lebenslauf", "letter": "Anschreiben"},
    "en": {"cv": "CV", "letter": "Cover_Letter"},
}


def file_part(text: str) -> str:
    """'Müller-Lüdenscheidt GmbH & Co.' -> 'Mueller-Luedenscheidt_GmbH_Co'."""
    text = text.translate(
        str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})
    )
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9-]+", "_", text).strip("_-") or "x"


def delivery_names(cv: ParsedCV, listing: ParsedListing, lang: str) -> dict[str, str]:
    parts = cv.contact.name.split()
    person = (
        f"{file_part(parts[-1])}_{file_part(' '.join(parts[:-1]))}"
        if len(parts) > 1
        else file_part(cv.contact.name)
    )
    company = file_part(listing.company or listing.title or "Application")
    names = DOC_NAMES[lang]
    return {
        "cv.pdf": f"{person}_{names['cv']}_{company}.pdf",
        "cover-letter.pdf": f"{person}_{names['letter']}_{company}.pdf",
    }


@step(RunStatus.DELIVERING)
async def deliver(ctx: StepContext) -> RunStatus:
    run = ctx.run
    cv = run_cv(ctx)
    listing = ParsedListing.model_validate(run.state["listing"])
    draft = final_draft(run.state)
    run_dir = ctx.settings.runs_dir / str(run.id)
    source = run_dir / f"draft-{draft['iteration']}"
    target = run_dir / "final"
    target.mkdir(parents=True, exist_ok=True)

    activity.update("Naming and packaging the final documents")
    names = delivery_names(cv, listing, draft["lang"])
    delivered = {}
    for original, name in names.items():
        if original in draft["files"]:
            (target / name).write_bytes((source / original).read_bytes())
            delivered[name] = original
    run.state = run.state | {"delivery": {"draft": draft["iteration"], "files": delivered}}
    ctx.session.add(run)
    ctx.session.commit()
    ctx.emit("step_progress", "delivered " + ", ".join(delivered))
    return RunStatus.DONE


def bundle(settings: Settings, run) -> bytes:
    """ZIP with the final documents, all drafts and the intermediate results."""
    run_dir: Path = settings.runs_dir / str(run.id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file() and path.suffix in {".pdf", ".json"}:
                z.write(path, path.relative_to(run_dir).as_posix())
        for key, name in [
            ("cv", "intermediates/parsed-cv.json"),
            ("listing", "intermediates/listing.json"),
            ("requirement_results", "intermediates/requirements.json"),
            ("analysis", "intermediates/skill-analysis.json"),
            ("match", "intermediates/assessment.json"),
        ]:
            if key in run.state:
                z.writestr(name, json.dumps(run.state[key], ensure_ascii=False, indent=2))
        if run.listing_text:
            z.writestr("intermediates/listing.txt", run.listing_text)
    return buffer.getvalue()
