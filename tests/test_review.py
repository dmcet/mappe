from datetime import date

from sqlmodel import Session

from mappe.checks.ats import check_ats
from mappe.checks.skills import analyze_skills
from mappe.config import DEFAULT_CONFIG_PATH, load_settings
from mappe.db import Run
from mappe.domain.author import AuthorBullet
from mappe.domain.extraction import to_parsed_cv
from mappe.domain.listing import merge_listing
from mappe.domain.review import ClaimProblem, ClaimsResult, render_claims
from mappe.llm.demo import (
    demo_author_cv,
    demo_author_letter,
    demo_listing,
    demo_recruiter,
)
from mappe.render.documents import LABELS, cv_data, render_cv
from mappe.render.typst import pdf_to_text
from mappe.runner.states import RunStatus
from mappe.steps.review import _no_improvement
from tests.conftest import make_extracted
from tests.test_author import drive_to_documents, make_run

TODAY = date(2026, 11, 3)


def rendered_text(tmp_path, doc):
    cv = to_parsed_cv(make_extracted())
    render_cv(cv_data(cv, doc, "de", True), tmp_path / "cv.pdf")
    return pdf_to_text(tmp_path / "cv.pdf"), cv


def analysis_for(cv):
    return analyze_skills(cv, merge_listing(demo_listing(), None, "de"), TODAY)


def test_ats_finds_contact_headings_and_keywords(tmp_path):
    text, cv = rendered_text(tmp_path, demo_author_cv())
    report = check_ats(text, cv, analysis_for(cv), LABELS["de"])
    assert report.parse_problems == []
    assert sorted(report.keywords_found) == ["FastAPI", "Kubernetes", "PostgreSQL", "Python"]
    assert report.passed


def test_ats_reports_supported_keywords_missing_from_the_document(tmp_path):
    doc = demo_author_cv().model_copy(
        update={
            "profile": "Backend-Entwickler.",
            "skill_groups": [],
            "bullets": [
                AuthorBullet(position_id="pos1", text="Payments API", fact_ids=["pos1.resp1"])
            ],
        }
    )
    text, cv = rendered_text(tmp_path, doc)
    report = check_ats(text, cv, analysis_for(cv), LABELS["de"])
    # Python stays visible in the headline, Kubernetes in the certification name.
    assert set(report.keywords_missing) == {"FastAPI", "PostgreSQL"}
    assert report.coverage == 0.5 and not report.passed
    assert "is supported by the CV but doesn't appear" in report.feedback()[0]


def test_claims_context_shows_cited_facts_levels_and_usage():
    cv = to_parsed_cv(make_extracted())
    text = render_claims(cv, demo_author_cv(), demo_author_letter())
    assert "B2 (pos1): Senkung der p99-Latenz um 40 %" in text
    assert "[pos1.ach1] Cut p99 latency by 40%" in text
    assert "Kubernetes [in the CV skills section, level basic; technologies of: —]" in text
    assert (
        "Python [in the CV skills section, level advanced; "
        "technologies of: pos1 (Senior Backend Engineer)]" in text
    )
    assert "skills section (also facts" in text and "Python (advanced)" in text
    assert text.count("L1 (cover letter paragraph)") == 1


def test_claims_context_lists_unverified_terms_and_slash_skills():
    from mappe.domain.author import SkillGroup
    from mappe.domain.extraction import ExtractedSkill

    cv = to_parsed_cv(
        make_extracted(
            skills=[ExtractedSkill(name="Protocol Buffers/gRPC", level="Fortgeschritten")]
        )
    )
    doc = demo_author_cv().model_copy(
        update={"skill_groups": [SkillGroup(category="APIs", skills=["gRPC"])]}
    )
    text = render_claims(cv, doc, None, ["AI agents"])
    assert "gRPC [in the CV skills section, level advanced" in text
    assert "doesn't show by name" in text and "AI agents" in text


def test_no_improvement_window():
    assert not _no_improvement([3.0, 3.5], 2)
    assert _no_improvement([3.8, 3.5, 3.6], 2)
    assert not _no_improvement([3.0, 3.5, 3.9], 2)


async def test_claims_problem_and_low_recruiter_score_trigger_rework(
    tmp_path, monkeypatch, fake_llm
):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    settings = load_settings(DEFAULT_CONFIG_PATH)
    fake_llm.results["author_cv"] = [demo_author_cv(), demo_author_cv(), demo_author_cv()]
    fake_llm.results["author_letter"] = [demo_author_letter(), demo_author_letter()]
    embellished = ClaimsResult(
        problems=[ClaimProblem(item="L2", kind="embellished", explanation="'verantworte' vs 'own'")]
    )
    low = demo_recruiter().model_copy(
        update={"evidence": 2, "invite": False, "feedback": ["CV: Lead with the latency result."]}
    )
    fake_llm.results["claims_check"] = [
        embellished,
        ClaimsResult(problems=[]),
        ClaimsResult(problems=[]),
    ]
    fake_llm.results["recruiter"] = [low, demo_recruiter()]
    db, run_id = make_run(tmp_path, cover_letter=True)

    await drive_to_documents(db, run_id, settings, cover_letter=True)

    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.WAITING_FOR_FINAL_REVIEW
        d1, d2, d3 = run.state["drafts"]
        assert d1["claims"][0]["item"] == "L2" and d1["recruiter"] is None  # recruiter skipped
        assert d1["feedback_letter"] and not d1["feedback_cv"]
        assert d2["recruiter"]["average"] < 4 and d2["feedback_cv"] == [
            "Recruiter: CV: Lead with the latency result."
        ]
        assert d3["accepted"] and run.state["final_draft"] == 3
        assert run.state["review_stop_reason"] == "all checks passed"

    calls = [c["step"] for c in fake_llm.calls]
    # draft 1: CV + letter; draft 2: only the letter is reworked; draft 3: only the CV.
    assert calls.count("author_cv") == 2 and calls.count("author_letter") == 2
    assert calls.count("recruiter") == 2


async def test_best_clean_draft_is_final_when_scores_stop_improving(
    tmp_path, monkeypatch, fake_llm
):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    settings = load_settings(DEFAULT_CONFIG_PATH)
    fake_llm.results["author_cv"] = [demo_author_cv()] * 5

    def score(value, invite=False):
        fields = dict.fromkeys(["relevance", "keywords", "evidence", "clarity", "seniority"], value)
        return demo_recruiter().model_copy(
            update={**fields, "cover_letter": 0, "invite": invite, "feedback": ["CV: tweak"]}
        )

    fake_llm.results["recruiter"] = [score(4), score(3), score(3)]  # never invited
    fake_llm.results["claims_check"] = [ClaimsResult(problems=[])] * 5
    db, run_id = make_run(tmp_path, cover_letter=False)

    await drive_to_documents(db, run_id, settings, cover_letter=False)

    with Session(db) as session:
        run = session.get(Run, run_id)
        assert len(run.state["drafts"]) == 3  # drafts 2 and 3 didn't beat draft 1
        assert run.state["review_stop_reason"] == "the recruiter score stopped improving"
        assert run.state["final_draft"] == 1
