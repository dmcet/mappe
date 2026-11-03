from datetime import date

from application_crew.checks.skills import analyze_skills, normalize_skill
from application_crew.domain.extraction import ExtractedPosition, ExtractedSkill, to_parsed_cv
from application_crew.domain.match import (
    Evidence,
    render_analysis,
    render_cv,
    validate_fact_ids,
)
from application_crew.domain.models import ParsedListing
from application_crew.llm.demo import demo_match
from tests.conftest import make_extracted

TODAY = date(2026, 11, 1)


def cv_with(**overrides):
    return to_parsed_cv(make_extracted(**overrides))


def listing(required, nice=(), qualifications=()):
    return ParsedListing(
        required_skills=list(required),
        nice_to_have_skills=list(nice),
        qualifications=list(qualifications),
    )


def test_normalisation_and_synonyms():
    assert normalize_skill("Kotlin Coroutines") == normalize_skill("Coroutines") == "coroutine"
    assert normalize_skill("Kotlin Flow") == normalize_skill("Flows")
    assert normalize_skill("JUnit") == normalize_skill("Unit-Tests") == "unit test"
    assert normalize_skill("K8s") == "kubernetes"
    assert normalize_skill("C#") == "c#"
    assert normalize_skill("CI/CD") == "ci/cd"


def test_coverage_levels_years_and_related():
    cv = cv_with()  # Python (advanced) in pos1 and the skills list, Kubernetes basic
    a = analyze_skills(cv, listing(["Python", "FastAPI", "K8s", "Go"], nice=["Java"]), TODAY)
    by_skill = {c.skill: c for c in a.coverage}

    python = by_skill["Python"]
    assert (python.coverage, python.level, python.positions) == ("match", "advanced", ["pos1"])
    assert python.years == 5.7  # 2021-04 .. 2026-11, months counted inclusively
    assert by_skill["FastAPI"].coverage == "match"  # technology of pos1
    assert (by_skill["K8s"].coverage, by_skill["K8s"].level) == ("match", "basic")
    assert by_skill["Go"].coverage == "missing"
    assert by_skill["Java"].coverage == "match" and not by_skill["Java"].required
    assert (a.required_matched, a.required_total, a.nice_matched, a.nice_total) == (3, 4, 1, 1)


def test_slash_names_and_mentions_in_bullets():
    cv = cv_with(skills=[ExtractedSkill(name="Protocol Buffers/gRPC", level="Fortgeschritten")])
    cv.positions[1].responsibilities[0].text = "Eigenständige Entwicklung von Unit-Tests"
    a = analyze_skills(cv, listing(["gRPC", "JUnit"]), TODAY)
    grpc, junit = a.coverage
    assert (grpc.coverage, grpc.cv_skill, grpc.level) == (
        "match",
        "Protocol Buffers/gRPC",
        "advanced",
    )
    assert (junit.coverage, junit.positions, junit.note) == (
        "related",
        ["pos2"],
        "mentioned in experience",
    )


def test_student_years_count_fully_and_are_shown_as_share():
    student = ExtractedPosition(
        company="Uni",
        client="",
        role="Werkstudent Entwicklung",
        location="Nürnberg",
        start="2013-01",
        end="2016-12",
        is_current=False,
        responsibilities=["Java Swing UI"],
        achievements=[],
        technologies=["Java"],
    )
    extracted = make_extracted()
    extracted.positions.append(student)
    a = analyze_skills(
        to_parsed_cv(extracted), listing(["Java"], qualifications=["5+ Jahre"]), TODAY
    )
    java = a.coverage[0]
    assert java.years == 8.0  # Beta AG 2017-04..2021-03 + student role 2013-01..2016-12
    assert java.student_years == 4.0
    assert a.total_years == 13.7 and a.student_years == 4.0
    assert a.years_required == 5


def test_validate_fact_ids_drops_unknown_ids_and_unbacked_points():
    cv = cv_with()
    result = demo_match().model_copy(
        update={
            "strengths": [
                Evidence(point="Real", fact_ids=["pos1.resp1", "pos9.resp1"]),
                Evidence(point="Invented", fact_ids=["pos7.ach2"]),
            ],
            "score": 140,
        }
    )
    cleaned, warnings = validate_fact_ids(result, cv)
    assert [(e.point, e.fact_ids) for e in cleaned.strengths] == [("Real", ["pos1.resp1"])]
    assert cleaned.score == 100
    assert len(warnings) == 2
    assert any("Invented" in w and "dropped" in w for w in warnings)


def test_rendered_context_contains_ids_levels_and_analysis():
    cv = cv_with()
    text = render_cv(cv)
    assert "[pos1] Senior Backend Engineer | Acme GmbH | Berlin | 2021-04–present" in text
    assert "[pos1.ach1] (achievement) Cut p99 latency by 40%" in text
    assert "[pos2] Backend Engineer | Beta AG (client: Gamma Bank)" in text
    assert "advanced: Python" in text and "basic: Kubernetes" in text
    analysis = analyze_skills(cv, listing(["Python", "Go"]), TODAY)
    rendered = render_analysis(analysis, [])
    assert "Python (required): match, level advanced" in rendered
    assert "Go (required): missing" in rendered
