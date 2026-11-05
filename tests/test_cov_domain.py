"""Edge cases of the domain models: extraction, listing mapping, prompt rendering, summary."""

from datetime import date

from mappe.domain.author import AuthorBullet
from mappe.domain.extraction import ExtractedSkill, _skills
from mappe.domain.listing import _clean, _to_int, from_job_posting
from mappe.domain.match import render_cv
from mappe.domain.models import Contact, Fact, ParsedCV, Position
from mappe.domain.review import render_claims
from mappe.domain.summary import merged_months
from mappe.llm.demo import demo_author_cv, demo_listing


def test_skills_without_a_name_are_dropped():
    skills = _skills(
        [
            ExtractedSkill(name="  ", level="Gut"),
            ExtractedSkill(name="Python", level="Fortgeschritten"),
        ]
    )
    assert [(s.name, s.level) for s in skills] == [("Python", "advanced")]


def test_job_posting_salary_as_a_plain_number():
    out = from_job_posting({"baseSalary": {"currency": "EUR", "value": "65000"}})
    assert out == {"salary_min": 65000, "salary_max": 65000, "salary_currency": "EUR"}


def test_job_posting_salary_that_is_not_a_number_is_ignored():
    assert from_job_posting({"baseSalary": {"currency": "EUR", "value": "competitive"}}) == {}
    assert _to_int(None) is None
    assert _to_int("12.5") == 12


def test_clean_maps_zero_numbers_to_not_stated():
    extracted = demo_listing().model_copy(
        update={"salary_min": 0, "salary_max": -1, "onsite_days_per_week": 0}
    )
    data = _clean(extracted)
    assert data["salary_min"] is None
    assert data["salary_max"] is None
    assert data["onsite_days_per_week"] is None
    assert data["cover_letter_requested"] is extracted.cover_letter_requested


def _cv(**kw) -> ParsedCV:
    return ParsedCV(
        contact=Contact(name="Jane Doe"),
        positions=[
            Position(
                id="pos1",
                company="Acme",
                role="Engineer",
                start="2020-01",
                responsibilities=[Fact(id="pos1.resp1", text="Built APIs")],
            )
        ],
        **kw,
    )


def test_render_cv_lists_soft_skills():
    text = render_cv(_cv(soft_skills=["Teamwork", "Ownership"]))
    assert "  soft skills: Teamwork, Ownership" in text.splitlines()


def test_render_claims_includes_extra_items_with_their_facts():
    cv = _cv(projects=[Fact(id="proj1", text="Open-source CLI tool")])
    doc = demo_author_cv().model_copy(
        update={
            "bullets": [],
            "extra": [AuthorBullet(position_id="proj1", text="Built a CLI", fact_ids=["proj1"])],
        }
    )
    lines = render_claims(cv, doc, None).splitlines()
    i = lines.index("E1: Built a CLI")
    assert lines[i + 1] == "    [proj1] Open-source CLI tool"


def test_merged_months_skips_positions_without_a_valid_start():
    positions = [
        Position(id="pos1", company="A", role="X", start="unknown"),
        Position(id="pos2", company="B", role="Y", start="2020-01", end="2020-03"),
    ]
    assert merged_months(positions, date(2026, 1, 1)) == 3
