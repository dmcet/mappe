"""Authoring and review loop.

AUTHORING: Claude writes the CV content (and the cover letter if chosen).
REVIEWING: Python fact check + Typst rendering. Violations go back to AUTHORING with
concrete feedback, up to ``review.max_iterations`` drafts. ATS and recruiter checks are
added to REVIEWING in the next step.
"""

from __future__ import annotations

import json
from datetime import date

from application_crew.checks.facts import FactChecker, FactReport
from application_crew.checks.skills import SkillAnalysis, SkillCoverage
from application_crew.domain import match as match_render
from application_crew.domain.author import AuthorCV, AuthorLetter
from application_crew.domain.match import MatchResult
from application_crew.domain.models import ParsedCV, ParsedListing
from application_crew.fetch.listing import detect_language
from application_crew.llm import client
from application_crew.llm.pricing import cost_usd
from application_crew.render.documents import cv_data, letter_data, render_cv, render_letter
from application_crew.runner.engine import StepContext, step
from application_crew.runner.states import RunStatus
from application_crew.steps.common import run_cv

LANGUAGE_NAMES = {"de": "German", "en": "English"}


def load_analysis(data: dict) -> SkillAnalysis:
    fields = {k: v for k, v in data.items() if k != "coverage"}
    fields.setdefault("student_years", 0.0)  # runs analysed before this field existed
    fields.pop("professional_years", None)
    return SkillAnalysis(coverage=[SkillCoverage(**c) for c in data["coverage"]], **fields)


def cv_language(cv: ParsedCV) -> str:
    texts = [f.text for p in cv.positions for f in p.responsibilities + p.achievements]
    return detect_language(" ".join(texts)) if texts else "en"


def _context(cv: ParsedCV, listing: ParsedListing, match: MatchResult, analysis: SkillAnalysis):
    assessment = [
        "Strengths:",
        *[f"  - {e.point} {e.fact_ids}" for e in match.strengths],
        "Gaps (don't cover these with invented experience):",
        *[f"  - {g}" for g in match.gaps],
        "Highlight in the CV (most important first):",
        *[f"  - {e.point} {e.fact_ids}" for e in match.highlights],
    ]
    missing = [c.skill for c in analysis.coverage if c.coverage == "missing"]
    experience = [
        f"Total experience: {analysis.total_years} years "
        f"(you may write e.g. '{int(analysis.total_years)}+ years').",
        "Years per skill: "
        + ", ".join(f"{c.skill} {c.years}y" for c in analysis.coverage if c.years),
        "Listing skills the CV does NOT have (never mention them): "
        + (", ".join(missing) or "none"),
    ]
    return (
        f"<cv>\n{match_render.render_cv(cv)}\n</cv>\n\n"
        f"<listing>\n{match_render.render_listing(listing)}\n</listing>\n\n"
        f"<assessment>\n" + "\n".join(assessment) + "\n</assessment>\n\n"
        "<experience>\n" + "\n".join(experience) + "\n</experience>"
    )


def _feedback(report: dict, previous: dict, what: str) -> str:
    problems = "\n".join(f"- {v}" for v in report["violations"])
    return (
        f"Rework your previous {what}. Fix every one of these problems and keep everything "
        f"else unchanged:\n{problems}\n\n"
        f"Previous {what} (JSON):\n{json.dumps(previous, ensure_ascii=False)}"
    )


@step(RunStatus.AUTHORING)
async def author(ctx: StepContext) -> RunStatus:
    run = ctx.run
    cv = run_cv(ctx)
    listing = ParsedListing.model_validate(run.state["listing"])
    match = MatchResult.model_validate(run.state["match"])
    analysis = load_analysis(run.state["analysis"])
    lang = listing.language
    drafts = run.state.get("drafts", [])
    iteration = len(drafts) + 1
    last = drafts[-1] if drafts else None
    wants_letter = run.state.get("decision", {}).get("cover_letter", False)

    context = _context(cv, listing, match, analysis)
    language = (
        f"Document language: {LANGUAGE_NAMES[lang]}. "
        f"CV language: {LANGUAGE_NAMES[cv_language(cv)]}."
    )
    total_cost = 0.0

    # CV: first draft, or rework when the last review found problems with it.
    if last is None or last["cv_report"]["violations"]:
        task = f"{language}\nWrite the tailored CV content."
        if last is not None:
            task = f"{language}\n" + _feedback(last["cv_report"], last["cv"], "CV draft")
        doc, usage = await client.structured(
            ctx.settings, step="author_cv", output=AuthorCV, stable_context=context, task=task
        )
        total_cost += cost_usd(ctx.settings.llm_for("author_cv").model, usage)
        ctx.emit("usage", f"author_cv (draft {iteration}) ≈ ${total_cost:.4f}", **usage.__dict__)
    else:
        doc = AuthorCV.model_validate(last["cv"])

    letter = None
    if wants_letter:
        if last is None or last.get("letter") is None or last["letter_report"]["violations"]:
            letter_context = f"{context}\n\n<tailored_cv>\n{doc.model_dump_json()}\n</tailored_cv>"
            task = f"{language}\nWrite the cover letter."
            if last is not None and last.get("letter") is not None:
                task = f"{language}\n" + _feedback(
                    last["letter_report"], last["letter"], "cover letter"
                )
            letter, usage = await client.structured(
                ctx.settings,
                step="author_letter",
                output=AuthorLetter,
                stable_context=letter_context,
                task=task,
            )
            cost = cost_usd(ctx.settings.llm_for("author_letter").model, usage)
            total_cost += cost
            ctx.emit("usage", f"author_letter (draft {iteration}) ≈ ${cost:.4f}", **usage.__dict__)
        else:
            letter = AuthorLetter.model_validate(last["letter"])

    run.cost_usd += total_cost
    run.state = run.state | {
        "draft": {
            "iteration": iteration,
            "lang": lang,
            "cv": doc.model_dump(mode="json"),
            "letter": letter.model_dump(mode="json") if letter else None,
        }
    }
    ctx.session.add(run)
    ctx.session.commit()
    ctx.emit("step_progress", f"draft {iteration} written")
    return RunStatus.REVIEWING


@step(RunStatus.REVIEWING)
async def review(ctx: StepContext) -> RunStatus:
    run = ctx.run
    cv = run_cv(ctx)
    listing = ParsedListing.model_validate(run.state["listing"])
    analysis = load_analysis(run.state["analysis"])
    draft = run.state["draft"]
    iteration, lang = draft["iteration"], draft["lang"]
    doc = AuthorCV.model_validate(draft["cv"])
    letter = AuthorLetter.model_validate(draft["letter"]) if draft["letter"] else None

    checker = FactChecker(cv, analysis)
    cv_report = checker.check_cv(doc)
    letter_report = checker.check_letter(letter) if letter else FactReport()

    out_dir = ctx.settings.runs_dir / str(run.id) / f"draft-{iteration}"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    data = cv_data(cv, doc, lang, translate_titles=cv_language(cv) != lang)
    (out_dir / "cv.json").write_text(json.dumps(draft["cv"], ensure_ascii=False, indent=2))
    result = render_cv(data, out_dir / "cv.pdf")
    if not result.ok:
        raise RuntimeError(f"CV rendering failed: {result.error}")
    files["cv.pdf"] = "cv.pdf"
    files["cv.json"] = "cv.json"
    if letter:
        ldata = letter_data(cv, listing, letter, lang, date.today())
        (out_dir / "cover-letter.json").write_text(
            json.dumps(draft["letter"], ensure_ascii=False, indent=2)
        )
        result = render_letter(ldata, out_dir / "cover-letter.pdf")
        if not result.ok:
            raise RuntimeError(f"Cover letter rendering failed: {result.error}")
        files["cover-letter.pdf"] = "cover-letter.pdf"
        files["cover-letter.json"] = "cover-letter.json"

    entry = {
        **draft,
        "cv_report": {"violations": cv_report.violations, "warnings": cv_report.warnings},
        "letter_report": {
            "violations": letter_report.violations,
            "warnings": letter_report.warnings,
        },
        "files": files,
    }
    # Idempotent on restart: a re-run of this step replaces its own entry.
    previous = [d for d in run.state.get("drafts", []) if d["iteration"] != iteration]
    run.state = run.state | {"drafts": [*previous, entry]}
    ctx.session.add(run)
    ctx.session.commit()

    problems = len(cv_report.violations) + len(letter_report.violations)
    ctx.emit("iteration_result", f"draft {iteration}: {problems} fact-check problem(s)")
    for v in cv_report.violations + letter_report.violations:
        ctx.emit("step_progress", v)
    if problems and iteration < ctx.settings.review.max_iterations:
        return RunStatus.AUTHORING
    return RunStatus.WAITING_FOR_FINAL_REVIEW
