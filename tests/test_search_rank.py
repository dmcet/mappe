"""Search queries, deduplication and ranking."""

from datetime import date

import pytest

from application_crew.domain.extraction import to_parsed_cv
from application_crew.domain.models import Requirement
from application_crew.search.dedupe import dedupe
from application_crew.search.models import JobHit
from application_crew.search.queries import clean_title, places_from, remote_only, suggest_titles
from application_crew.search.queries import title_variants as variants
from application_crew.search.rank import rank
from tests.conftest import make_extracted

TODAY = date(2026, 11, 3)
CV = to_parsed_cv(make_extracted())  # Senior Backend Engineer: Python, Kubernetes, PostgreSQL, ...


def hit(title, description="", **kw):
    data = dict(
        source="arbeitnow",
        external_id=title,
        url=f"https://example.com/{title.replace(' ', '-')}",
        view_url="https://example.com",
        title=title,
        description=description,
        posted_at=TODAY,
    )
    return JobHit(**(data | kw))


def test_clean_title():
    assert clean_title("Senior Backend Engineer (m/w/d)") == "Backend Engineer"
    assert clean_title("Softwareentwickler (w/m/d)") == "Softwareentwickler"
    assert clean_title("Senior Backend Engineer | Python & Cloud") == "Backend Engineer"
    assert clean_title("Tech Lead") == "Tech Lead"
    assert clean_title("Lead Android Developer") == "Android Developer"


def test_title_variants():
    assert variants("Backend Engineer") == ["Backend-Entwickler"]
    assert variants("Backend-Entwickler") == ["Backend Developer"]
    assert variants("Software Engineer") == ["Softwareentwickler"]
    assert "Software Engineer" in variants("Softwareentwickler")
    assert variants("Androidentwickler") == ["Android Developer"]
    assert variants("Scrum Master") == []
    assert variants("System Engineer") == ["Systemingenieur"]
    assert variants("Technical Architect") == []
    assert variants("Data Engineer") == []  # the same title in German job ads
    assert variants("Android Developer") == ["Android-Entwickler"]


def test_suggested_titles_from_cv():
    # Python is the CV's advanced skill and not in a title yet: it adds a skill title.
    assert suggest_titles(CV) == [
        "Backend Engineer",
        "Python Developer",
        "Backend-Entwickler",
        "Python-Entwickler",
    ]


def test_every_job_title_in_the_headline_is_used():
    cv = CV.model_copy(update={"headline": "Software Architect | System Engineer | Python & Cloud"})
    assert suggest_titles(cv) == [
        "Software Architect",
        "System Engineer",
        "Backend Engineer",
        "Python Developer",
        "Softwarearchitekt",
        "Systemingenieur",
        "Backend-Entwickler",
        "Python-Entwickler",
    ]


def test_abroad_detection():
    from application_crew.search.rank import abroad

    for place in ["Waardenburg, Gelderland, Netherlands", "Bern", "Bundesland: Wien", "Linz"]:
        assert abroad(place), place
    for place in ["Fürth, Bayern", "Munich, Bavaria, Germany", "Berlin", "Wien, Bayern"]:
        assert not abroad(place), place


def test_without_cities_radius_sources_are_checked_for_abroad_too():
    vienna = hit("Backend Engineer", "Python", location="Bundesland: Wien", source="ba")
    ranked = rank([vienna], CV, [], located={"ba"}, today=TODAY)
    assert ranked[0].hidden == "elsewhere"


def test_places_and_remote_from_requirements():
    reqs = [
        Requirement(kind="location", value="Berlin, Hamburg"),
        Requirement(kind="max_onsite_days", value="0", must_have=False),
    ]
    assert places_from(reqs) == ["Berlin", "Hamburg"]
    assert not remote_only(reqs)
    assert remote_only([Requirement(kind="max_onsite_days", value="0", must_have=True)])


def test_ranking_prefers_skill_and_title_fit():
    good = hit("Backend Engineer", "We use Python, FastAPI, PostgreSQL and Kubernetes.")
    meh = hit("Data Engineer", "Some Python.")
    off = hit("Health and Safety Engineer", "Workplace safety audits.")
    ranked = rank([off, meh, good], CV, [], today=TODAY)
    assert [r.hit.title for r in ranked] == [
        "Backend Engineer",
        "Data Engineer",
        "Health and Safety Engineer",
    ]
    top = ranked[0]
    assert top.score > 80 and set(top.matched_skills) >= {"Python", "PostgreSQL", "Kubernetes"}
    assert ranked[-1].hidden == "low_score"


def test_skill_matching_uses_synonyms_and_word_boundaries():
    ranked = rank(
        [hit("Backend Engineer", "Postgres and k8s, plus pythonic code")], CV, [], today=TODAY
    )
    assert set(ranked[0].matched_skills) == {"PostgreSQL", "Kubernetes"}  # not "pythonic"


def test_title_only_hits_are_scored_on_the_title():
    title_only = hit("Backend-Entwickler (m/w/d)", source="ba")
    read = hit("Backend Engineer", "Python, FastAPI, PostgreSQL and Kubernetes", external_id="r")
    by_basis = {r.basis: r for r in rank([title_only, read], CV, [], today=TODAY)}
    assert by_basis["title only"].score == pytest.approx(60 * 0.4 + 30 + 10, abs=1)
    # A listing that was read and fits beats the same title with unknown skills.
    assert by_basis["description"].score > by_basis["title only"].score


def test_must_have_requirements_hide_but_keep_hits():
    reqs = [
        Requirement(kind="salary_min", value="80000", must_have=True),
        Requirement(kind="location", value="Berlin", must_have=True),
        Requirement(kind="other", value="Jobrad", must_have=True),  # needs Claude: not checked
    ]
    low_pay = hit(
        "Backend Engineer",
        "Python",
        salary_min=50000,
        salary_max=60000,
        salary_currency="EUR",
        salary_period="year",
        location="Berlin",
    )
    unknown = hit("Backend Engineer 2", "Python", location="Berlin")
    munich = hit("Backend Engineer 3", "Python", location="München")
    remote = hit("Backend Engineer 4", "Python", location="Remote", remote="remote")
    by_title = {
        r.hit.title: r for r in rank([low_pay, unknown, munich, remote], CV, reqs, today=TODAY)
    }
    assert by_title["Backend Engineer"].hidden == "requirements"
    assert "salary_min" in by_title["Backend Engineer"].notes[0]
    assert by_title["Backend Engineer 2"].hidden is None  # unknown never fails
    assert by_title["Backend Engineer 3"].hidden == "requirements"
    assert by_title["Backend Engineer 4"].hidden is None


def test_old_and_dismissed_hits():
    old = hit("Backend Engineer", "Python", posted_at=date(2026, 8, 1))
    gone = hit("Backend Engineer 2", "Python")
    ranked = rank([old, gone], CV, [], dismissed={gone.key}, today=TODAY)
    assert [(r.hit.title, r.hidden) for r in ranked] == [("Backend Engineer 2", "dismissed")]


def test_dedupe_merges_across_sources_and_keeps_the_longest_text():
    a = hit(
        "Backend Engineer (m/w/d)",
        "",
        source="ba",
        external_id="1",
        company="Acme GmbH",
        location="Berlin",
    )
    b = hit(
        "Backend Engineer",
        "Full text here",
        source="arbeitnow",
        external_id="x",
        company="ACME",
        location="Berlin, Germany",
    )
    c = hit(
        "Backend Engineer",
        "Other city",
        source="arbeitnow",
        external_id="y",
        company="Acme",
        location="Hamburg",
        url="https://example.com/hamburg",
    )
    merged = dedupe([a, b, c])
    assert len(merged) == 2
    assert merged[0].source == "arbeitnow" and merged[0].also_on == ["ba"]


def test_onsite_jobs_outside_the_search_area_are_hidden():
    berlin = hit("Backend Engineer", "Python", location="Berlin, Germany")
    paris = hit("Backend Engineer 2", "Python", location="Paris")
    remote = hit("Backend Engineer 3", "Python", location="London", remote="remote")
    potsdam = hit("Backend Engineer 4", "Python", location="Potsdam", source="ba")

    def hidden(**kw):
        ranked = rank([berlin, paris, remote, potsdam], CV, [], today=TODAY, **kw)
        return {r.hit.title: r.hidden for r in ranked}

    # Searched around Berlin: Bundesagentur's radius search already found Potsdam.
    assert hidden(places=["Berlin"], located={"ba"}) == {
        "Backend Engineer": None,
        "Backend Engineer 2": "elsewhere",
        "Backend Engineer 3": None,
        "Backend Engineer 4": None,
    }
    # No cities: only jobs abroad are hidden.
    assert hidden()["Backend Engineer 2"] == "elsewhere"
    assert hidden()["Backend Engineer 4"] is None
