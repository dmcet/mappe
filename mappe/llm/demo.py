"""Demo mode: canned Claude responses so the UI can be explored without an API key.

The sample data never depends on the input (CV or listing).
The UI shows a banner while demo mode is on.
"""

from __future__ import annotations

from pydantic import BaseModel

from mappe.domain.author import (
    AuthorBullet,
    AuthorCV,
    AuthorCVDraft,
    AuthorLetter,
    LetterParagraph,
    SkillGroup,
    Title,
    full_draft,
)
from mappe.domain.extraction import (
    ExtractedCertification,
    ExtractedCV,
    ExtractedEducation,
    ExtractedLanguage,
    ExtractedPosition,
    ExtractedSkill,
)
from mappe.domain.listing import ExtractedListing
from mappe.domain.match import Evidence, MatchResult, TransferableSkill
from mappe.domain.review import ClaimsResult, RecruiterResult
from mappe.domain.roles import RoleSuggestions, SuggestedRole


def sample_cv(**overrides) -> ExtractedCV:
    """A complete sample CV (produces no completeness warnings)."""
    data = dict(
        name="Jane Doe",
        city="Berlin",
        address="",
        email="jane@example.com",
        phone="+49 30 1234567",
        links=["https://github.com/janedoe"],
        languages=[
            ExtractedLanguage(name="German", level="native"),
            ExtractedLanguage(name="English", level="C1"),
        ],
        headline="Senior Backend Engineer | Python & Cloud",
        skills=[
            ExtractedSkill(name="Python", level="Fortgeschritten"),
            ExtractedSkill(name="Kubernetes", level="Grundlagen"),
            ExtractedSkill(name="python", level=""),
            ExtractedSkill(name="PostgreSQL", level=""),
        ],
        soft_skills=[],
        certifications=[
            ExtractedCertification(
                name="Certified Kubernetes Administrator",
                abbreviation="CKA",
                issuer="CNCF",
                year="2023",
            )
        ],
        education=[
            ExtractedEducation(
                qualification="M.Sc. Computer Science",
                institution="TU Berlin",
                location="Berlin",
                start="2014-10",
                end="2017-03",
            )
        ],
        positions=[
            ExtractedPosition(
                company="Acme GmbH",
                client="",
                role="Senior Backend Engineer",
                location="Berlin",
                start="2021-04",
                end="2099-01",
                is_current=True,
                responsibilities=["Own the payments API", " "],
                achievements=["Cut p99 latency by 40%"],
                technologies=["Python", "FastAPI", "Python"],
            ),
            ExtractedPosition(
                company="Beta AG",
                client="Gamma Bank",
                role="Backend Engineer",
                location="Hamburg",
                start="2017-04",
                end="2021-03",
                is_current=False,
                responsibilities=["Built data pipelines"],
                achievements=[],
                technologies=["Java"],
            ),
        ],
        projects=["Open-source contributor to httpx (2022)"],
        publications=[],
        volunteering=[],
        notice_period="3 months",
        earliest_start="",
        salary_expectation="",
        work_permit="",
    )
    data.update(overrides)
    return ExtractedCV(**data)


def demo_cv() -> ExtractedCV:
    """The sample CV with a few gaps, so the demo shows warnings and quick fixes."""
    cv = sample_cv(
        phone="",
        languages=[
            ExtractedLanguage(name="German", level="native"),
            ExtractedLanguage(name="English", level="fluent"),
        ],
    )
    cv.positions[1].location = ""
    return cv


def demo_listing() -> ExtractedListing:
    """A German hybrid backend role. Requirement checks are left empty ("not mentioned")."""
    return ExtractedListing(
        title="Senior Python Developer (m/w/d)",
        company="Beispiel Mobility GmbH",
        domain="automotive",
        responsibilities=[
            "Weiterentwicklung unserer Flottenmanagement-Plattform",
            "Design und Betrieb von Microservices auf Kubernetes",
        ],
        required_skills=["Python", "FastAPI", "PostgreSQL", "Kubernetes"],
        nice_to_have_skills=["Kafka", "Terraform"],
        qualifications=["5+ Jahre Erfahrung in der Backend-Entwicklung", "Sehr gutes Deutsch"],
        location="München",
        remote="hybrid",
        onsite_days_per_week=2,
        salary_min=70000,
        salary_max=85000,
        salary_currency="EUR",
        salary_period="year",
        benefits=["30 Urlaubstage", "Jobrad", "Weiterbildungsbudget"],
        cover_letter_requested=False,
        contact_name="Anna Schmidt",
        contact_email="bewerbung@beispiel-mobility.de",
        company_street="Leopoldstraße 10",
        company_postal_code="80802",
        company_city="München",
        requirement_checks=[],
    )


# The demo listing's contact and address are checked against the real listing text, which
# doesn't contain them. In demo mode this line is added to the text used for that check, so
# the email and the letter layout show up.
DEMO_CONTACT_LINE = (
    "Ihre Ansprechpartnerin: Frau Anna Schmidt, bewerbung@beispiel-mobility.de, "
    "Beispiel Mobility GmbH, Leopoldstraße 10, 80802 München"
)


def demo_match() -> MatchResult:
    """Uses fact IDs of the demo CV (sample_cv)."""
    return MatchResult(
        verdict="apply",
        score=78,
        rationale=(
            "Your Python backend experience and ownership of a payments API match the core of "
            "this role. Kubernetes is only listed at a basic level, and FastAPI isn't named in "
            "your CV, but both are close to what you already do. Salary and hybrid model fit "
            "your requirements."
        ),
        strengths=[
            Evidence(point="Owns a production payments API in Python", fact_ids=["pos1.resp1"]),
            Evidence(
                point="Measurable performance work (p99 latency -40%)", fact_ids=["pos1.ach1"]
            ),
        ],
        gaps=["FastAPI not named in the CV", "Kubernetes only at basic level", "No Kafka"],
        transferable=[
            TransferableSkill(
                missing="FastAPI",
                related_experience="Several years of Python API development",
                fact_ids=["pos1.resp1"],
            )
        ],
        highlights=[
            Evidence(
                point="Lead with the payments API and its latency result",
                fact_ids=["pos1.resp1", "pos1.ach1"],
            ),
            Evidence(
                point="Show data pipeline work for the platform side", fact_ids=["pos2.resp1"]
            ),
        ],
    )


def demo_author_cv() -> AuthorCV:
    """German CV content for the demo listing, using demo CV fact IDs."""
    return AuthorCV(
        profile=(
            "Senior Backend Engineer mit 9+ Jahren Erfahrung in der Backend-Entwicklung. "
            "Schwerpunkt auf Python-APIs mit FastAPI und PostgreSQL."
        ),
        profile_fact_ids=["pos1", "pos2"],
        titles=[
            Title(id="pos1", title="Senior Backend Engineer"),
            Title(id="pos2", title="Backend Engineer"),
            Title(id="edu1", title="M.Sc. Informatik"),
            Title(id="cert1", title="Certified Kubernetes Administrator"),
        ],
        bullets=[
            AuthorBullet(
                position_id="pos1",
                text="Verantwortung für die Payments-API in Python und FastAPI",
                fact_ids=["pos1.resp1"],
            ),
            AuthorBullet(
                position_id="pos1",
                text="Senkung der p99-Latenz um 40 %",
                fact_ids=["pos1.ach1"],
            ),
            AuthorBullet(
                position_id="pos2",
                text="Aufbau von Datenpipelines in Java",
                fact_ids=["pos2.resp1"],
            ),
        ],
        skill_groups=[
            SkillGroup(category="Sprachen & Frameworks", skills=["Python", "FastAPI", "Java"]),
            SkillGroup(category="Datenbanken & Plattformen", skills=["PostgreSQL", "Kubernetes"]),
        ],
        extra=[],
    )


def demo_author_letter() -> AuthorLetter:
    return AuthorLetter(
        subject="Bewerbung als Senior Python Developer (m/w/d)",
        paragraphs=[
            LetterParagraph(
                text="Ihre Plattform für Flottenmanagement passt genau zu meinem Schwerpunkt: "
                "Backend-Services in Python, die zuverlässig im Betrieb laufen.",
                fact_ids=[],
            ),
            LetterParagraph(
                text="Bei der Acme GmbH verantworte ich die Payments-API und habe die "
                "p99-Latenz um 40 % gesenkt.",
                fact_ids=["pos1.resp1", "pos1.ach1"],
            ),
            LetterParagraph(
                text="Über die Einladung zu einem persönlichen Gespräch freue ich mich. "
                "Meine Kündigungsfrist beträgt 3 Monate.",
                fact_ids=[],
            ),
        ],
    )


def demo_claims() -> ClaimsResult:
    return ClaimsResult(problems=[])


def demo_recruiter() -> RecruiterResult:
    return RecruiterResult(
        relevance=4,
        keywords=4,
        evidence=4,
        clarity=5,
        seniority=4,
        cover_letter=4,
        invite=True,
        summary="Clear backend profile with a concrete payments result; a good first call.",
        feedback=[],
    )


def demo_roles() -> RoleSuggestions:
    """Uses fact IDs of the demo CV (sample_cv)."""
    return RoleSuggestions(
        roles=[
            SuggestedRole(
                title="Platform Engineer",
                title_alt="",
                reason="You hold the CKA and run Python services in production.",
                fact_ids=["cert1", "pos1.resp1"],
            ),
            SuggestedRole(
                title="Data Engineer",
                title_alt="",
                reason="You built data pipelines for a bank and know PostgreSQL.",
                fact_ids=["pos2.resp1"],
            ),
            SuggestedRole(
                title="Tech Lead",
                title_alt="",
                reason="You own the payments API end to end and delivered measurable results.",
                fact_ids=["pos1.resp1", "pos1.ach1"],
            ),
            SuggestedRole(
                title="Site Reliability Engineer",
                title_alt="",
                reason="Your latency work and Kubernetes certificate are core SRE skills.",
                fact_ids=["pos1.ach1", "cert1"],
            ),
        ]
    )


def demo_response(step: str, output: type[BaseModel]) -> BaseModel:
    if step == "parse_cv" and output is ExtractedCV:
        return demo_cv()
    if step == "suggest_roles" and output is RoleSuggestions:
        return demo_roles()
    if step == "parse_listing" and output is ExtractedListing:
        return demo_listing()
    if step == "match" and output is MatchResult:
        return demo_match()
    if step == "author_cv" and output is AuthorCVDraft:
        # Also fine for a rework: re-adding unchanged bullets does nothing.
        return full_draft(demo_author_cv())
    if step == "author_letter" and output is AuthorLetter:
        return demo_author_letter()
    if step == "claims_check" and output is ClaimsResult:
        return demo_claims()
    if step == "recruiter" and output is RecruiterResult:
        return demo_recruiter()
    raise NotImplementedError(f"demo mode has no sample response for step '{step}'")
