from datetime import date

from sqlmodel import Session

from application_crew.checks.completeness import check_cv, parse_month
from application_crew.config import DEFAULT_CONFIG_PATH, load_settings
from application_crew.db import CV, init_engine
from application_crew.domain.extraction import ExtractedLanguage, to_parsed_cv
from application_crew.domain.summary import experience_months, summarize
from application_crew.runner.states import CVStatus
from application_crew.steps.cv import parse_cv
from tests.conftest import make_extracted

TODAY = date(2026, 11, 1)


def test_fact_ids_are_assigned_deterministically():
    cv = to_parsed_cv(make_extracted())
    pos1, pos2 = cv.positions
    assert (pos1.id, pos2.id) == ("pos1", "pos2")
    assert [f.id for f in pos1.responsibilities] == ["pos1.resp1"]  # blank bullet dropped
    assert [f.id for f in pos1.achievements] == ["pos1.ach1"]
    assert cv.certifications[0].id == "cert1"
    assert cv.education[0].id == "edu1"
    assert cv.projects[0].id == "proj1"


def test_current_position_has_no_end_and_lists_are_deduplicated():
    cv = to_parsed_cv(make_extracted())
    assert cv.positions[0].end is None  # is_current wins over a bogus end date
    assert cv.positions[0].technologies == ["Python", "FastAPI"]
    assert cv.skills == ["Python", "Kubernetes", "PostgreSQL"]


def test_complete_cv_has_no_warnings():
    assert check_cv(to_parsed_cv(make_extracted()), today=TODAY) == []


def test_missing_and_invalid_data_is_reported():
    extracted = make_extracted(
        email=None,
        phone=None,
        languages=[ExtractedLanguage(name="Spanish", level="good")],
    )
    extracted.positions[1].start = "April 2017"
    extracted.positions[1].location = None
    warnings = check_cv(to_parsed_cv(extracted), today=TODAY)

    assert "Contact: no email found." in warnings
    assert "Contact: no phone number found." in warnings
    assert any("Spanish" in w and "CEFR" in w for w in warnings)
    assert any("Beta AG has no valid start date" in w for w in warnings)
    assert any("Beta AG has no location" in w for w in warnings)


def test_parse_month():
    assert parse_month("2021-04") == date(2021, 4, 1)
    assert parse_month("2021") == date(2021, 1, 1)
    assert parse_month("2021-13") is None
    assert parse_month("04/2021") is None
    assert parse_month(None) is None


def test_experience_merges_overlapping_positions():
    extracted = make_extracted()
    # Second position overlaps the first by a year: 2017-04..2022-03
    extracted.positions[1].end = "2022-03"
    cv = to_parsed_cv(extracted)
    # 2017-04 .. 2026-11 inclusive = 9 years 8 months = 116 months
    assert experience_months(cv, today=TODAY) == 116
    summary = summarize(cv, today=TODAY)
    assert summary.years_of_experience == 9.7
    assert summary.current_role == "Senior Backend Engineer at Acme GmbH"


async def test_parse_cv_job_success(tmp_path, fake_llm):
    db = init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db) as session:
        cv = CV(label="Main", markdown="# Jane Doe\n...")
        session.add(cv)
        session.commit()
        cv_id = cv.id

    await parse_cv(cv_id, load_settings(DEFAULT_CONFIG_PATH))

    with Session(db) as session:
        cv = session.get(CV, cv_id)
        assert cv.status == CVStatus.WAITING_FOR_CONFIRMATION
        assert cv.parsed["positions"][0]["id"] == "pos1"
        assert cv.cost_usd > 0
    assert fake_llm.calls[0]["step"] == "parse_cv"
    assert "# Jane Doe" in fake_llm.calls[0]["context"]


async def test_parse_cv_job_failure_is_stored(tmp_path, fake_llm):
    fake_llm.error = RuntimeError("API unavailable")
    db = init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db) as session:
        cv = CV(label="Main", markdown="# Jane")
        session.add(cv)
        session.commit()
        cv_id = cv.id

    await parse_cv(cv_id, load_settings(DEFAULT_CONFIG_PATH))

    with Session(db) as session:
        cv = session.get(CV, cv_id)
        assert cv.status == CVStatus.FAILED
        assert cv.error == "API unavailable"
