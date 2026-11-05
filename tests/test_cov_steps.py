"""Step edge cases: CV jobs, listing fetch/parse, match warnings, edits, review stop reasons."""

import dataclasses
from functools import partial

import httpx
import pytest
from sqlmodel import Session, select

import mappe.steps  # noqa: F401 - registers steps
from mappe.config import DEFAULT_CONFIG_PATH, ReviewConfig, load_settings
from mappe.db import CV, Event, Run, init_engine
from mappe.domain.author import AuthorBullet
from mappe.domain.extraction import to_parsed_cv
from mappe.domain.match import Evidence
from mappe.domain.review import ClaimsResult
from mappe.fetch.listing import FetchResult, fetch_listing
from mappe.llm.demo import demo_author_cv, demo_author_letter, demo_match, demo_recruiter
from mappe.render.typst import RenderResult
from mappe.runner.engine import Engine
from mappe.runner.states import CVStatus, RunStatus
from mappe.steps import cv as cv_steps
from mappe.steps import review as review_steps
from mappe.steps.final import DocumentEdit, apply_edits
from mappe.steps.listing import MAX_LISTING_CHARS
from tests.conftest import make_extracted
from tests.test_author import drive_to_documents
from tests.test_author import make_run as make_authoring_run
from tests.test_fetch import PAGE

LISTING = "Wir suchen eine Senior Python Developerin. Wir bieten 30 Urlaubstage und ein Jobrad."


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_DEMO", raising=False)
    return load_settings(DEFAULT_CONFIG_PATH)


@pytest.fixture
def db(tmp_path):
    return init_engine(f"sqlite:///{tmp_path / 'test.db'}")


def add_cv(db, **fields):
    fields = {"label": "t", "markdown": "# Jane Doe", "status": CVStatus.CONFIRMED} | fields
    if fields["status"] == CVStatus.CONFIRMED and "parsed" not in fields:
        fields["parsed"] = to_parsed_cv(make_extracted()).model_dump(mode="json")
    with Session(db) as session:
        cv = CV(**fields)
        session.add(cv)
        session.commit()
        return cv.id


def add_run(db, cv_id, **fields):
    with Session(db) as session:
        run = Run(cv_id=cv_id, **fields)
        session.add(run)
        session.commit()
        return run.id


def messages(db, run_id, kind="step_progress"):
    with Session(db) as session:
        stmt = select(Event).where(Event.run_id == run_id, Event.kind == kind)
        return [e.message for e in session.exec(stmt)]


# --- CV jobs --------------------------------------------------------------------------------


async def test_cv_jobs_ignore_missing_or_unsuitable_cvs(db, settings, fake_llm):
    await cv_steps.process_cv(999, settings)  # deleted meanwhile
    confirmed = add_cv(db, roles_status="done")
    await cv_steps.parse_cv(confirmed, settings)  # not (any longer) parsing
    await cv_steps.suggest_roles(confirmed, settings)  # roles not requested
    unparsed = add_cv(db, status=CVStatus.PARSING, roles_status="suggesting")
    await cv_steps.suggest_roles(unparsed, settings)  # nothing parsed yet

    assert fake_llm.calls == []
    with Session(db) as session:
        cv = session.get(CV, confirmed)
        assert (cv.status, cv.roles_status) == (CVStatus.CONFIRMED, "done")
        assert session.get(CV, unparsed).status == CVStatus.PARSING


async def test_a_run_needs_a_parsed_cv(db, settings, fake_llm):
    run_id = add_run(db, add_cv(db, status=CVStatus.PARSING), listing_text=LISTING)
    await Engine(settings).drive(run_id)
    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.FAILED
        assert run.error == "created: the run's CV has no parsed data"


# --- listing --------------------------------------------------------------------------------


async def test_without_url_or_text_the_run_waits_for_pasted_text(db, settings, fake_llm):
    run_id = add_run(db, add_cv(db))
    await Engine(settings).drive(run_id)
    with Session(db) as session:
        assert session.get(Run, run_id).status == RunStatus.WAITING_FOR_LISTING_TEXT
    assert "no URL given, waiting for pasted text" in messages(db, run_id)
    assert fake_llm.calls == []


async def test_a_fetched_listing_is_stored_and_parsed(db, settings, fake_llm, monkeypatch):
    page = httpx.MockTransport(lambda request: httpx.Response(200, content=PAGE.encode()))
    monkeypatch.setattr("mappe.steps.listing.fetch_listing", partial(fetch_listing, transport=page))
    run_id = add_run(db, add_cv(db), listing_url="https://example.com/job")

    await Engine(settings).drive(run_id)

    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.WAITING_FOR_APPLY_DECISION
        assert "Wir suchen Verstärkung." in run.listing_text
        fetched = run.state["fetch"]
        assert fetched["language"] == "de"
        assert fetched["final_url"] == "https://example.com/job"
        assert fetched["job_posting"]["title"] == "Senior Backend Engineer (m/w/d)"
    assert f"fetched {len(run.listing_text)} characters" in messages(db, run_id)
    assert "Wir suchen Verstärkung." in fake_llm.calls[0]["context"]


async def test_redirect_to_the_job_index_asks_for_pasted_text(db, settings, fake_llm, monkeypatch):
    def handler(request):
        if request.url.path == "/jobs/123":
            return httpx.Response(302, headers={"Location": "/jobs"})
        return httpx.Response(200, content=PAGE.encode())

    redirecting = httpx.MockTransport(handler)
    result = await fetch_listing("https://example.com/jobs/123", transport=redirecting)
    assert not result.ok
    assert result.error == (
        "redirected to https://example.com/jobs; the listing has probably been taken down"
    )

    monkeypatch.setattr(
        "mappe.steps.listing.fetch_listing", partial(fetch_listing, transport=redirecting)
    )
    run_id = add_run(db, add_cv(db), listing_url="https://example.com/jobs/123")
    await Engine(settings).drive(run_id)
    with Session(db) as session:
        assert session.get(Run, run_id).status == RunStatus.WAITING_FOR_LISTING_TEXT
    assert result.error in messages(db, run_id)


async def test_a_page_with_little_text_and_no_posting_is_not_a_listing():
    tiny = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"<html><body><p>Login</p></body></html>")
    )
    result = await fetch_listing("https://example.com/job", transport=tiny)
    assert result == FetchResult(
        ok=False,
        text=result.text,
        error="page contains too little text (login wall or JavaScript-only page?)",
    )
    assert len(result.text) < 300


async def test_a_very_long_listing_is_truncated(db, settings, fake_llm):
    text = LISTING + " " + "x" * (MAX_LISTING_CHARS + 5_000)
    run_id = add_run(db, add_cv(db), listing_text=text)
    await Engine(settings).drive(run_id)

    sent = fake_llm.calls[0]["blocks"][0].text
    assert sent == f"<listing>\n{text[:MAX_LISTING_CHARS]}\n</listing>"
    assert (
        f"listing is {len(text):,} characters; only the first {MAX_LISTING_CHARS:,} are used"
        in messages(db, run_id)
    )


async def test_demo_mode_adds_the_demo_contact_to_the_listing(db, settings, fake_llm):
    run_id = add_run(db, add_cv(db), listing_text=LISTING)
    await Engine(dataclasses.replace(settings, demo=True)).drive(run_id)
    with Session(db) as session:
        listing = session.get(Run, run_id).state["listing"]
    assert listing["contact_email"] == "bewerbung@beispiel-mobility.de"


async def test_without_demo_mode_an_unverified_contact_is_dropped(db, settings, fake_llm):
    run_id = add_run(db, add_cv(db), listing_text=LISTING)
    await Engine(settings).drive(run_id)
    with Session(db) as session:
        assert session.get(Run, run_id).state["listing"]["contact_email"] is None


# --- match ----------------------------------------------------------------------------------


async def test_match_reports_and_drops_unknown_fact_ids(db, settings, fake_llm):
    result = demo_match()
    fake_llm.results["match"] = result.model_copy(
        update={
            "strengths": [
                Evidence(point="Payments API", fact_ids=["pos1.resp1", "pos9.resp1"]),
                Evidence(point="Invented award", fact_ids=["award1"]),
            ]
        }
    )
    run_id = add_run(db, add_cv(db), listing_text=LISTING)
    await Engine(settings).drive(run_id)

    with Session(db) as session:
        state = session.get(Run, run_id).state
    assert [s["fact_ids"] for s in state["match"]["strengths"]] == [["pos1.resp1"]]
    assert len(state["match_warnings"]) == 2
    progress = messages(db, run_id)
    assert "Strength 'Payments API': unknown fact IDs ['pos9.resp1'] removed" in progress
    assert "Strength 'Invented award' dropped: not backed by any CV fact" in progress


# --- final review edits ---------------------------------------------------------------------


def test_edits_without_letter_changes_keep_the_letter():
    cv = to_parsed_cv(make_extracted())
    letter = demo_author_letter()
    doc, kept = apply_edits(cv, demo_author_cv(), letter, DocumentEdit(profile="Neues Profil."))
    assert kept is letter
    assert doc.profile == "Neues Profil."
    _, none = apply_edits(cv, demo_author_cv(), None, DocumentEdit(profile="x"))
    assert none is None


# --- review ---------------------------------------------------------------------------------


@pytest.mark.parametrize("document", ["cv", "letter"])
def test_render_failures_are_raised(tmp_path, monkeypatch, document):
    failed = RenderResult(ok=False, error="typst exploded")
    ok = RenderResult(ok=True)
    monkeypatch.setattr(review_steps, "render_cv", lambda data, out: ok)
    monkeypatch.setattr(review_steps, "render_letter", lambda data, out: ok)
    monkeypatch.setattr(review_steps, f"render_{document}", lambda data, out: failed)
    from mappe.domain.listing import merge_listing
    from mappe.llm.demo import demo_listing

    cv = to_parsed_cv(make_extracted())
    listing = merge_listing(demo_listing(), None, "de")
    draft = {
        "lang": "de",
        "cv": demo_author_cv().model_dump(mode="json"),
        "letter": demo_author_letter().model_dump(mode="json"),
    }
    label = "CV" if document == "cv" else "Cover letter"
    with pytest.raises(RuntimeError, match=f"{label} rendering failed: typst exploded"):
        review_steps.render_draft(cv, listing, draft, tmp_path / "draft")


def review_settings(settings, **review):
    return dataclasses.replace(settings, review=dataclasses.replace(ReviewConfig(), **review))


async def review_run(tmp_path, settings):
    db, run_id = make_authoring_run(tmp_path, cover_letter=False)
    await drive_to_documents(db, run_id, settings, cover_letter=False)
    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.WAITING_FOR_FINAL_REVIEW
        return run.state


async def test_a_failed_ats_check_becomes_cv_feedback(tmp_path, settings, fake_llm):
    sparse = demo_author_cv().model_copy(
        update={
            "profile": "Backend-Entwickler.",
            "skill_groups": [],
            "bullets": [
                AuthorBullet(position_id="pos1", text="Payments API", fact_ids=["pos1.resp1"])
            ],
        }
    )
    fake_llm.results["author_cv"] = [sparse]
    fake_llm.results["claims_check"] = [ClaimsResult(problems=[])]

    state = await review_run(tmp_path, review_settings(settings, max_iterations=1))

    (draft,) = state["drafts"]
    assert not draft["ats"]["passed"] and not draft["clean"] and draft["recruiter"] is None
    assert any("is supported by the CV but doesn't appear" in f for f in draft["feedback_cv"])
    assert state["review_stop_reason"] == "reached 1 drafts"


async def test_review_stops_at_the_cost_limit(tmp_path, settings, fake_llm):
    fake_llm.results["author_cv"] = [demo_author_cv()]
    fake_llm.results["claims_check"] = [ClaimsResult(problems=[])]
    fake_llm.results["recruiter"] = [
        demo_recruiter().model_copy(update={"invite": False, "feedback": ["CV: shorter"]})
    ]

    state = await review_run(tmp_path, review_settings(settings, cost_limit_usd=0.01))

    assert len(state["drafts"]) == 1 and state["drafts"][0]["feedback_cv"]
    assert state["review_stop_reason"] == "cost limit of $0.01 reached"
    assert state["final_draft"] == 1


async def test_review_stops_without_actionable_feedback(tmp_path, settings, fake_llm):
    fake_llm.results["author_cv"] = [demo_author_cv()]
    fake_llm.results["claims_check"] = [ClaimsResult(problems=[])]
    fake_llm.results["recruiter"] = [
        demo_recruiter().model_copy(update={"invite": False, "feedback": []})
    ]

    state = await review_run(tmp_path, settings)

    (draft,) = state["drafts"]
    assert draft["clean"] and not draft["accepted"]
    assert draft["feedback_cv"] == [] and draft["feedback_letter"] == []
    assert state["review_stop_reason"] == "no actionable feedback left"
