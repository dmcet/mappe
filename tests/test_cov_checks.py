"""Edge cases of the deterministic checks (ATS, completeness, facts, requirements, skills)."""

from datetime import date

import pytest

from mappe.checks.ats import MAX_KEYWORD_REPEATS, check_ats
from mappe.checks.completeness import check_cv
from mappe.checks.facts import FactChecker
from mappe.checks.requirements import check_requirements
from mappe.checks.skills import analyze_skills
from mappe.domain.author import AuthorBullet, AuthorCV
from mappe.domain.models import (
    Certification,
    Contact,
    Education,
    Fact,
    Language,
    ParsedCV,
    ParsedListing,
    Position,
    Requirement,
    Skill,
)

TODAY = date(2026, 1, 1)
LABELS = {"experience": "Experience", "skills": "Skills", "education": "Education"}


def _cv(**kw) -> ParsedCV:
    data = {
        "contact": Contact(name="Jane Doe", email="jane@example.com", phone="+49 1", city="Berlin"),
        "skills": [Skill(name="Python")],
        "languages": [Language(name="German", level="C1")],
        "positions": [
            Position(
                id="pos1",
                company="Acme",
                role="Engineer",
                location="Berlin",
                start="2020-01",
                end="2022-12",
                responsibilities=[Fact(id="pos1.resp1", text="Built 3 services in Python")],
                technologies=["Python"],
            )
        ],
    }
    data.update(kw)
    return ParsedCV(**data)


# --- ATS -----------------------------------------------------------------------------------


def test_ats_reports_missing_name_employer_and_keyword_stuffing():
    cv = _cv()
    analysis = analyze_skills(cv, ParsedListing(required_skills=["Python"]), TODAY)
    text = "jane@example.com +49 1 Experience Skills Education " + "Python and " * (
        MAX_KEYWORD_REPEATS + 1
    )
    report = check_ats(text, cv, analysis, LABELS)
    assert "The name isn't found in the extracted text." in report.parse_problems
    assert "Employer 'Acme' isn't found." in report.parse_problems
    assert report.stuffing == ["Python"]
    assert report.keywords_found == ["Python"]


@pytest.mark.parametrize("sep", [" ", ", ", " / "])
def test_ats_counts_adjacent_repeats_as_stuffing(sep):
    # Mentions right next to each other (a stuffed skills line) count one by one.
    cv = _cv()
    analysis = analyze_skills(cv, ParsedListing(required_skills=["Python"]), TODAY)
    base = "Jane Doe jane@example.com +49 1 Experience Acme Skills Education "
    over = check_ats(base + sep.join(["Python"] * (MAX_KEYWORD_REPEATS + 1)), cv, analysis, LABELS)
    assert over.stuffing == ["Python"]
    at_limit = check_ats(base + sep.join(["Python"] * MAX_KEYWORD_REPEATS), cv, analysis, LABELS)
    assert at_limit.stuffing == []


def test_ats_clean_text_has_no_problems():
    cv = _cv()
    analysis = analyze_skills(cv, ParsedListing(required_skills=["Python"]), TODAY)
    text = "Jane Doe jane@example.com +49 1 Experience Acme Skills Python Education"
    report = check_ats(text, cv, analysis, LABELS)
    assert report.parse_problems == [] and report.stuffing == []


# --- completeness ----------------------------------------------------------------------------


def test_completeness_flags_empty_cv_sections():
    cv = ParsedCV(contact=Contact(name="Jane", email="a@b.c", phone="1", city="Berlin"))
    assert check_cv(cv, TODAY) == [
        "Experience: no positions found.",
        "Skills: no skills found.",
        "Languages: no languages found.",
    ]


def test_completeness_flags_implausible_positions_education_and_certifications():
    bad = Position(id="pos1", company="Acme", role="Dev", start="2021-05", end="2020-01")
    invalid_end = Position(
        id="pos2",
        company="Beta",
        role="Ops",
        location="Köln",
        start="2020-01",
        end="someday",
        responsibilities=[Fact(id="pos2.resp1", text="x")],
    )
    future = Position(
        id="pos3",
        company="Gamma",
        role="Lead",
        location="Bonn",
        start="2027-01",
        achievements=[Fact(id="pos3.ach1", text="y")],
    )
    cv = _cv(
        positions=[bad, invalid_end, future],
        education=[Education(id="edu1", qualification="BSc", institution="TU")],
        certifications=[Certification(id="cert1", name="CKA")],
    )
    warnings = check_cv(cv, TODAY)
    assert warnings == [
        "Experience: Dev at Acme ends before it starts.",
        "Experience: Dev at Acme has no location.",
        "Experience: Dev at Acme has no responsibilities or achievements.",
        "Experience: Ops at Beta has an invalid end date 'someday'.",
        "Experience: Lead at Gamma starts in the future.",
        "Education: BSc (TU) has no dates.",
        "Certifications: CKA has no issuer or year.",
    ]


# --- facts -----------------------------------------------------------------------------------


def _checker(cv: ParsedCV) -> FactChecker:
    return FactChecker(cv, analyze_skills(cv, ParsedListing(), TODAY))


def test_fact_check_profile_ids_and_length():
    cv = _cv()
    doc = AuthorCV(
        profile="One. Two. Three. Four.",
        profile_fact_ids=["pos1", "nope"],
        titles=[],
        bullets=[AuthorBullet(position_id="pos1", text="Built services", fact_ids=["pos1.resp1"])],
        skill_groups=[],
        extra=[],
    )
    report = _checker(cv).check_cv(doc)
    assert report.violations == ["Profile: unknown fact IDs ['nope']."]
    assert report.warnings == ["Profile has 4 sentences; 2-3 are recommended."]


def test_fact_check_extra_items_must_cite_projects_and_their_numbers():
    cv = _cv(projects=[Fact(id="proj1", text="Wrote a 12 module tool")])
    doc = AuthorCV(
        profile="Engineer.",
        profile_fact_ids=[],
        titles=[],
        bullets=[AuthorBullet(position_id="pos1", text="Built services", fact_ids=["pos1.resp1"])],
        skill_groups=[],
        extra=[
            AuthorBullet(position_id="proj1", text="Wrote a 12 module tool", fact_ids=["proj1"]),
            AuthorBullet(position_id="pos1", text="Ran 99 things", fact_ids=["pos1.resp1"]),
            AuthorBullet(position_id="x", text="Nothing cited", fact_ids=[]),
        ],
    )
    report = _checker(cv).check_cv(doc)
    assert report.violations == [
        "Additional experience 'Ran 99 things': must cite project/publication/volunteering IDs.",
        "Additional experience 'Ran 99 things': the number(s) 99 don't appear in the cited CV "
        "facts. Use only numbers from the CV.",
        "Additional experience 'Nothing cited': must cite project/publication/volunteering IDs.",
    ]


# --- requirements ------------------------------------------------------------------------------


def test_requirements_with_non_numeric_values_are_unknown():
    listing = ParsedListing(remote="onsite", salary_max=90000)
    results = check_requirements(
        [
            Requirement(kind="salary_min", value="a lot"),
            Requirement(kind="max_onsite_days", value="few"),
        ],
        listing,
        "",
        [],
    )
    assert [(r.outcome, r.note) for r in results] == [
        ("unknown", "'a lot' is not a number"),
        ("unknown", "'few' is not a number"),
    ]


def test_onsite_position_passes_when_five_days_are_allowed():
    listing = ParsedListing(remote="onsite")
    reqs = [
        Requirement(kind="max_onsite_days", value="5"),
        Requirement(kind="max_onsite_days", value="3"),
    ]
    results = check_requirements(reqs, listing, "", [])
    assert [(r.outcome, r.note) for r in results] == [
        ("passed", "Onsite position"),
        ("failed", "Onsite position (5 days)"),
    ]


# --- skills ------------------------------------------------------------------------------------


def test_listing_skill_containing_a_cv_skill_is_related():
    cv = _cv(skills=[Skill(name="Android")], positions=[])
    a = analyze_skills(cv, ParsedListing(required_skills=["Android animations"]), TODAY)
    cov = a.coverage[0]
    assert cov.coverage == "related"
    assert cov.cv_skill == "Android"


def test_skill_used_in_a_bullet_counts_the_position_and_skips_short_parts():
    pos = Position(
        id="pos1",
        company="Acme",
        role="Engineer",
        start="2020-01",
        end="2020-12",
        responsibilities=[Fact(id="pos1.resp1", text="Wrote drivers in C++ and Docker")],
    )
    cv = _cv(skills=[Skill(name="C/C++"), Skill(name="Docker")], positions=[pos])
    a = analyze_skills(cv, ParsedListing(required_skills=["Docker", "C/C++"]), TODAY)
    docker, cpp = a.coverage
    assert docker.coverage == "match" and docker.positions == ["pos1"]
    assert docker.years == 1.0
    # "C" (one letter) is skipped as a search term; "C++" is found in the bullet.
    assert cpp.coverage == "match" and cpp.positions == ["pos1"]


def test_skill_not_used_in_any_position_has_no_years():
    pos = Position(
        id="pos1",
        company="Acme",
        role="Engineer",
        start="2020-01",
        responsibilities=[Fact(id="pos1.resp1", text="Wrote code")],
    )
    cv = _cv(skills=[Skill(name="Rust")], positions=[pos])
    cov = analyze_skills(cv, ParsedListing(required_skills=["Rust"]), TODAY).coverage[0]
    assert cov.coverage == "match" and cov.positions == [] and cov.years == 0.0
