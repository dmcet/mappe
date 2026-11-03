from application_crew.checks.requirements import check_requirements, failed_must_haves
from application_crew.domain.listing import FuzzyCheck, from_job_posting, merge_listing
from application_crew.domain.models import ParsedListing, Requirement
from application_crew.llm.demo import demo_listing
from application_crew.web.forms import form_defaults, requirements_from_form

POSTING = {
    "@type": "JobPosting",
    "title": "Platform Engineer",
    "hiringOrganization": {"@type": "Organization", "name": "Example SE"},
    "jobLocation": [
        {"@type": "Place", "address": {"addressLocality": "Berlin"}},
        {"@type": "Place", "address": {"addressLocality": "Hamburg"}},
    ],
    "jobLocationType": "TELECOMMUTE",
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "EUR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 6000,
            "maxValue": 7000,
            "unitText": "MONTH",
        },
    },
}

LISTING_TEXT = """Senior Python Developer (m/w/d). Wir bieten: 30 Urlaubstage, Jobrad
und ein Weiterbildungsbudget. Hybrid: 2 Tage pro Woche im Büro in München."""


def listing(**overrides) -> ParsedListing:
    return merge_listing(demo_listing(), None, "de").model_copy(update=overrides)


def req(kind, value, must=False):
    return Requirement(kind=kind, value=value, must_have=must)


def outcomes(reqs, lst=None, checks=()):
    results = check_requirements(reqs, lst or listing(), LISTING_TEXT, list(checks))
    return [(r.outcome, r.note) for r in results]


def test_job_posting_mapping():
    mapped = from_job_posting(POSTING)
    assert mapped == {
        "title": "Platform Engineer",
        "company": "Example SE",
        "location": "Berlin, Hamburg",
        "remote": "remote",
        "salary_min": 6000,
        "salary_max": 7000,
        "salary_currency": "EUR",
        "salary_period": "month",
    }
    assert from_job_posting(None) == {}
    assert from_job_posting({"@type": "JobPosting", "hiringOrganization": "ACME"}) == {
        "company": "ACME"
    }


def test_job_posting_wins_over_claude_and_language_is_set_by_python():
    merged = merge_listing(demo_listing(), POSTING, "en")
    assert merged.title == "Platform Engineer"
    assert merged.remote == "remote"
    assert merged.salary_period == "month"
    assert merged.required_skills == demo_listing().required_skills  # from Claude
    assert merged.language == "en"


def test_salary_requirement():
    assert outcomes([req("salary_min", "80000")])[0][0] == "passed"  # band 70-85k
    assert outcomes([req("salary_min", "90k")])[0][0] == "failed"
    assert outcomes([req("salary_min", "80000")], listing(salary_min=None, salary_max=None))[0] == (
        "unknown",
        "No salary stated",
    )
    monthly = listing(salary_min=6000, salary_max=7000, salary_period="month")
    assert outcomes([req("salary_min", "80.000")], monthly)[0][0] == "passed"  # 84k/year
    usd = listing(salary_currency="USD")
    assert outcomes([req("salary_min", "50000")], usd)[0][0] == "unknown"


def test_onsite_requirement():
    assert outcomes([req("max_onsite_days", "2")])[0] == (
        "passed",
        "Hybrid, 2 onsite day(s) per week",
    )
    assert outcomes([req("max_onsite_days", "1")])[0][0] == "failed"
    assert outcomes([req("max_onsite_days", "0")], listing(remote="remote"))[0][0] == "passed"
    assert outcomes([req("max_onsite_days", "3")], listing(remote="onsite"))[0][0] == "failed"
    assert outcomes([req("max_onsite_days", "2")], listing(onsite_days_per_week=None))[0][0] == (
        "unknown"
    )
    assert outcomes([req("max_onsite_days", "2")], listing(remote=None))[0][0] == "unknown"


def test_location_matching_normalises_umlauts_and_english_names():
    from application_crew.checks.requirements import normalize_place

    assert normalize_place("Nürnberg") == normalize_place("Nuernberg") == "nuernberg"
    assert normalize_place("Nuremberg, Germany") == "nuernberg, germany"
    assert outcomes([req("location", "Nürnberg, Fürth")], listing(location="Nuremberg"))[0][0] == (
        "passed"
    )
    assert outcomes([req("location", "Fuerth")], listing(location="Fürth (Bayern)"))[0][0] == (
        "passed"
    )
    assert outcomes([req("location", "Erlangen")], listing(location="Erlangenstadt"))[0][0] == (
        "failed"
    )


def test_sentence_like_skills_move_to_qualifications():
    extracted = demo_listing().model_copy(
        update={
            "required_skills": ["Kotlin", "5+ years of software engineering experience in teams"],
            "nice_to_have_skills": ["Some comfort with asking people to change how they work"],
            "qualifications": ["Excellent communication skills"],
        }
    )
    merged = merge_listing(extracted, None, "en")
    assert merged.required_skills == ["Kotlin"]
    assert merged.nice_to_have_skills == []
    assert merged.qualifications == [
        "Excellent communication skills",
        "5+ years of software engineering experience in teams",
        "Some comfort with asking people to change how they work",
    ]


def test_location_requirement():
    assert outcomes([req("location", "Berlin, München")])[0][0] == "passed"
    assert outcomes([req("location", "Berlin")])[0][0] == "failed"
    assert outcomes([req("location", "Berlin")], listing(remote="remote"))[0][0] == "passed"
    assert outcomes([req("location", "Berlin")], listing(location=None))[0][0] == "unknown"


def test_fuzzy_requirements_need_a_verifiable_quote():
    reqs = [req("other", "30 vacation days"), req("other", "Company car"), req("other", "Dog")]
    checks = [
        FuzzyCheck(index=0, outcome="met", evidence="30  Urlaubstage"),  # whitespace differs
        FuzzyCheck(index=1, outcome="met", evidence="Firmenwagen inklusive"),  # not in text
        FuzzyCheck(index=2, outcome="not_mentioned", evidence=""),
    ]
    results = outcomes(reqs, checks=checks)
    assert results[0] == ("passed", "Mentioned in the listing")
    assert results[1] == ("unknown", "No verifiable quote in the listing")
    assert results[2] == ("unknown", "Not mentioned in the listing")


def test_only_failed_must_haves_stop_the_run():
    reqs = [
        req("salary_min", "90000", must=True),
        req("location", "Berlin"),
        req("other", "Sauna", must=True),
    ]
    results = check_requirements(reqs, listing(), LISTING_TEXT, [])
    failed = failed_must_haves(results)
    assert [r.requirement.kind for r in failed] == ["salary_min"]  # unknown never fails


def test_requirement_form_round_trip():
    form = {
        "salary_min": "75000",
        "salary_min_must": "on",
        "max_onsite_days": "",
        "location": "Berlin",
        "must_other": "30 vacation days\n",
        "nice_other": "Jobrad\nTraining budget",
    }
    reqs = requirements_from_form(form)
    assert [(r.kind, r.value, r.must_have) for r in reqs] == [
        ("salary_min", "75000", True),
        ("location", "Berlin", False),
        ("other", "30 vacation days", True),
        ("other", "Jobrad", False),
        ("other", "Training budget", False),
    ]
    defaults = form_defaults([r.model_dump() for r in reqs])
    assert defaults["salary_min"] == "75000" and defaults["salary_min_must"] is True
    assert defaults["nice_other"] == "Jobrad\nTraining budget"
