"""REVIEWING: check and render the current draft, then decide: rework or done.

Per draft, in this order (later checks only run when the earlier ones pass, to save cost):
1. Fact check (Python)                           -> blocking
2. Render CV / cover letter (Typst)
3. Claims check (Claude): embellishments         -> blocking
4. ATS check (Python, on the PDF text)           -> blocking below the keyword threshold
5. Recruiter review (Claude, rubric 1-5)         -> rework below the pass score

The loop ends when a draft passes everything, after ``max_iterations`` drafts, when the
recruiter score stopped improving, or at the cost limit. The best clean draft is final.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from application_crew.checks.ats import check_ats
from application_crew.checks.facts import FactChecker, FactReport
from application_crew.domain import match as match_render
from application_crew.domain.author import AuthorCV, AuthorLetter
from application_crew.domain.models import ParsedCV, ParsedListing
from application_crew.domain.review import ClaimsResult, RecruiterResult, render_claims
from application_crew.llm import client
from application_crew.llm.pricing import cost_usd
from application_crew.render.documents import (
    LABELS,
    cv_data,
    letter_data,
    render_cv,
    render_letter,
)
from application_crew.render.typst import pdf_to_text
from application_crew.runner import activity
from application_crew.runner.engine import StepContext, step
from application_crew.runner.states import RunStatus
from application_crew.steps.author import cv_language, load_analysis
from application_crew.steps.common import run_cv


def render_draft(
    cv: ParsedCV, listing: ParsedListing, draft: dict, out_dir: Path
) -> dict[str, str]:
    doc = AuthorCV.model_validate(draft["cv"])
    lang = draft["lang"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cv.json").write_text(json.dumps(draft["cv"], ensure_ascii=False, indent=2))
    result = render_cv(cv_data(cv, doc, lang, cv_language(cv) != lang), out_dir / "cv.pdf")
    if not result.ok:
        raise RuntimeError(f"CV rendering failed: {result.error}")
    files = {"cv.pdf": "cv.pdf", "cv.json": "cv.json"}
    if draft["letter"]:
        letter = AuthorLetter.model_validate(draft["letter"])
        (out_dir / "cover-letter.json").write_text(
            json.dumps(draft["letter"], ensure_ascii=False, indent=2)
        )
        data = letter_data(cv, listing, letter, lang, date.today())
        result = render_letter(data, out_dir / "cover-letter.pdf")
        if not result.ok:
            raise RuntimeError(f"Cover letter rendering failed: {result.error}")
        files |= {"cover-letter.pdf": "cover-letter.pdf", "cover-letter.json": "cover-letter.json"}
    return files


def _claim_texts(doc: AuthorCV, letter: AuthorLetter | None) -> dict[str, str]:
    texts = {"P0": doc.profile}
    texts |= {f"B{n}": b.text for n, b in enumerate(doc.bullets, 1)}
    texts |= {f"E{n}": b.text for n, b in enumerate(doc.extra, 1)}
    texts |= {f"S{n}": f"skill group '{g.category}'" for n, g in enumerate(doc.skill_groups, 1)}
    if letter:
        texts["L0"] = letter.subject
        texts |= {f"L{n}": p.text for n, p in enumerate(letter.paragraphs, 1)}
    return texts


def _track(ctx: StepContext, step_name: str, usage) -> float:
    cost = cost_usd(ctx.settings.llm_for(step_name).model, usage)
    ctx.run.cost_usd += cost
    ctx.emit("usage", f"{step_name} ≈ ${cost:.4f}", **usage.__dict__)
    return cost


def _no_improvement(scores: list[float], window: int) -> bool:
    """True if the last ``window`` drafts didn't beat the best score before them."""
    if window <= 0 or len(scores) <= window:
        return False
    return max(scores[-window:]) <= max(scores[:-window])


@step(RunStatus.REVIEWING)
async def review(ctx: StepContext) -> RunStatus:
    run, settings = ctx.run, ctx.settings
    cv = run_cv(ctx)
    listing = ParsedListing.model_validate(run.state["listing"])
    analysis = load_analysis(run.state["analysis"])
    draft = run.state["draft"]
    iteration, lang = draft["iteration"], draft["lang"]
    doc = AuthorCV.model_validate(draft["cv"])
    letter = AuthorLetter.model_validate(draft["letter"]) if draft["letter"] else None

    activity.update(f"Fact check (Python) · draft {iteration}", draft=iteration)
    # 1. Fact check
    checker = FactChecker(cv, analysis)
    cv_report = checker.check_cv(doc)
    letter_report = checker.check_letter(letter) if letter else FactReport()
    feedback_cv, feedback_letter = list(cv_report.violations), list(letter_report.violations)

    # 2. Render
    activity.update(f"Rendering PDFs (Typst) · draft {iteration}")
    out_dir = settings.runs_dir / str(run.id) / f"draft-{iteration}"
    files = render_draft(cv, listing, draft, out_dir)
    cv_text = pdf_to_text(out_dir / "cv.pdf")
    letter_text = pdf_to_text(out_dir / "cover-letter.pdf") if letter else ""

    # 3. Claims check
    claims: list[dict] = []
    if not feedback_cv and not feedback_letter:
        result, usage = await client.structured(
            settings,
            step="claims_check",
            output=ClaimsResult,
            stable_context=render_claims(cv, doc, letter, checker.unverified_terms),
            task="Check every item against the facts it cites.",
        )
        _track(ctx, "claims_check", usage)
        texts = _claim_texts(doc, letter)
        for p in result.problems:
            text = texts.get(p.item, "")
            entry = {"item": p.item, "kind": p.kind, "explanation": p.explanation, "text": text}
            claims.append(entry)
            message = f"'{text[:80]}' is {p.kind}: {p.explanation}"
            (feedback_letter if p.item.startswith("L") else feedback_cv).append(message)

    # 4. ATS check (always: it's free and shows template problems early)
    activity.update(f"ATS check on the PDF text · draft {iteration}")
    ats = check_ats(cv_text, cv, analysis, LABELS[lang])
    if not ats.passed:
        feedback_cv += ats.feedback()

    # 5. Recruiter review, only for clean drafts
    clean = not feedback_cv and not feedback_letter and not ats.parse_problems
    recruiter = None
    if clean:
        documents = f"=== CV ===\n{cv_text}"
        if letter_text:
            documents += f"\n\n=== Cover letter ===\n{letter_text}"
        context = (
            f"<listing>\n{match_render.render_listing(listing)}\n</listing>\n\n"
            f"<cv>\n{match_render.render_cv(cv)}\n</cv>\n\n"
            f"<documents>\n{documents}\n</documents>"
        )
        recruiter, usage = await client.structured(
            settings,
            step="recruiter",
            output=RecruiterResult,
            stable_context=context,
            task="Screen this application.",
        )
        _track(ctx, "recruiter", usage)

    score = recruiter.average(has_letter=letter is not None) if recruiter else 0.0
    accepted = (
        clean
        and ats.passed
        and recruiter is not None
        and recruiter.invite
        and score >= settings.review.recruiter_pass_score
    )
    if recruiter and not accepted:
        for item in recruiter.feedback:
            is_letter = item.casefold().startswith(("cover letter:", "anschreiben:"))
            (feedback_letter if is_letter and letter else feedback_cv).append(f"Recruiter: {item}")

    entry = {
        **draft,
        "cv_report": {"violations": cv_report.violations, "warnings": cv_report.warnings},
        "letter_report": {
            "violations": letter_report.violations,
            "warnings": letter_report.warnings,
        },
        "claims": claims,
        "ats": ats.to_dict(),
        "recruiter": (recruiter.model_dump() | {"average": score}) if recruiter else None,
        "clean": clean and ats.passed,
        "score": score,
        "accepted": accepted,
        "feedback_cv": [] if accepted else feedback_cv,
        "feedback_letter": [] if accepted else feedback_letter,
        "files": files,
    }
    # Idempotent on restart: a re-run of this step replaces its own entry.
    drafts = [d for d in run.state.get("drafts", []) if d["iteration"] != iteration] + [entry]

    summary = (
        f"draft {iteration}: {len(cv_report.violations) + len(letter_report.violations)} fact, "
        f"{len(claims)} claim problem(s); ATS {round(ats.coverage * 100)}% keywords"
        + (f"; recruiter {score}/5, invite={recruiter.invite}" if recruiter else "")
    )
    ctx.emit("iteration_result", summary)

    # Decide: done or rework
    reason = None
    # Only drafts the recruiter scored count; earlier drafts were still fixing facts.
    scores = [d["score"] for d in drafts if d.get("recruiter")]
    if accepted:
        reason = "all checks passed"
    elif iteration >= settings.review.max_iterations:
        reason = f"reached {settings.review.max_iterations} drafts"
    elif _no_improvement(scores, settings.review.stop_after_no_improvement):
        reason = "the recruiter score stopped improving"
    elif settings.review.cost_limit_usd and run.cost_usd >= settings.review.cost_limit_usd:
        reason = f"cost limit of ${settings.review.cost_limit_usd:.2f} reached"
    elif not feedback_cv and not feedback_letter:
        reason = "no actionable feedback left"

    if reason is None:
        run.state = run.state | {"drafts": drafts}
        ctx.session.add(run)
        ctx.session.commit()
        return RunStatus.AUTHORING

    clean_drafts = [d for d in drafts if d.get("clean")]
    best = (
        max(clean_drafts, key=lambda d: (d["accepted"], d["score"], d["iteration"]))
        if clean_drafts
        else entry
    )
    run.state = run.state | {
        "drafts": drafts,
        "final_draft": best["iteration"],
        "review_stop_reason": reason,
    }
    ctx.session.add(run)
    ctx.session.commit()
    ctx.emit("step_progress", f"review finished: {reason}; using draft {best['iteration']}")
    return RunStatus.WAITING_FOR_FINAL_REVIEW
