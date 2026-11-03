from datetime import date

from sqlmodel import Session

from application_crew.checks.facts import FactChecker
from application_crew.checks.skills import analyze_skills
from application_crew.config import DEFAULT_CONFIG_PATH, load_settings
from application_crew.db import CV, Run, init_engine
from application_crew.domain.author import AuthorBullet, SkillGroup
from application_crew.domain.extraction import to_parsed_cv
from application_crew.domain.listing import merge_listing
from application_crew.llm.demo import demo_author_cv, demo_author_letter, demo_listing
from application_crew.render.documents import cv_data, letter_data
from application_crew.render.typst import pdf_to_text
from application_crew.runner.engine import Engine
from application_crew.runner.states import CVStatus, RunStatus
from tests.conftest import make_extracted

TODAY = date(2026, 11, 3)


def setup():
    cv = to_parsed_cv(make_extracted())
    listing = merge_listing(demo_listing(), None, "de")  # requires Python, FastAPI, PostgreSQL, K8s
    return cv, listing, FactChecker(cv, analyze_skills(cv, listing, TODAY))


def bullet(pid, text, ids):
    return AuthorBullet(position_id=pid, text=text, fact_ids=ids)


def test_demo_content_passes_the_fact_check():
    _, _, checker = setup()
    assert checker.check_cv(demo_author_cv()).violations == []
    assert checker.check_letter(demo_author_letter()).violations == []


def test_fact_check_catches_invented_content():
    _, _, checker = setup()
    doc = demo_author_cv().model_copy(
        update={
            "bullets": [
                bullet("pos1", "Cut p99 latency by 60%", ["pos1.ach1"]),  # number not in fact
                bullet("pos1", "Owns the payments API", []),  # no source
                bullet("pos1", "Built data pipelines", ["pos2.resp1"]),  # other position's fact
                bullet("pos2", "Streams events with Kafka", ["pos2.resp1"]),  # missing skill
                bullet("pos9", "Something", ["pos9.resp1"]),  # unknown position
            ],
            "skill_groups": [SkillGroup(category="Tools", skills=["Python", "Terraform"])],
        }
    )
    violations = checker.check_cv(doc).violations
    text = "\n".join(violations)
    assert "number(s) 60" in text
    assert "cites no CV facts" in text
    assert "belong to another position" in text
    assert "mentions 'Kafka'" in text
    assert "unknown position 'pos9'" in text
    assert "'Terraform' is not in the CV" in text
    assert len(violations) == 6


def test_allowed_numbers_and_bullet_limit():
    _, _, checker = setup()
    doc = demo_author_cv().model_copy(
        update={
            "profile": "Backend engineer with 9+ years of experience.",  # computed years: 9.7
            "bullets": [bullet("pos1", f"Payments API work {n}", ["pos1.resp1"]) for n in "ABCDEF"]
            + [bullet("pos2", "Data pipelines", ["pos2.resp1"])],
        }
    )
    report = checker.check_cv(doc)
    assert report.violations == [
        "Senior Backend Engineer at Acme GmbH has 6 bullets; use at most 5."
    ]
    doc.profile = "Backend engineer with 12 years of experience."
    assert any("number(s) 12" in v for v in checker.check_cv(doc).violations)


def test_document_data_comes_from_the_cv():
    cv, listing, _ = setup()
    data = cv_data(cv, demo_author_cv(), "de", translate_titles=True)
    pos1, pos2 = data["positions"]
    assert pos1["dates"] == "04/2021 – heute"
    assert pos2["company"] == "Beta AG · Kundeneinsatz bei Gamma Bank"
    assert pos2["dates"] == "04/2017 – 03/2021"
    assert pos1["bullets"][1] == "Senkung der p99-Latenz um 40 %"
    assert data["languages"] == "Deutsch (Muttersprache) · Englisch (C1)"  # translated for "de"
    assert data["contact"]["github"] == "github.com/janedoe"
    assert data["certifications"][0]["name"] == "Certified Kubernetes Administrator (CKA)"

    en = cv_data(cv, demo_author_cv(), "en", translate_titles=False)
    assert en["positions"][0]["dates"] == "04/2021 – Present"
    assert en["positions"][1]["company"] == "Beta AG · client: Gamma Bank"

    letter = letter_data(cv, listing, demo_author_letter(), "de", TODAY)
    assert letter["date"] == "3. November 2026"
    assert letter["recipient"] == ["Beispiel Mobility GmbH", "München"]
    assert letter["sender"]["contact"] == ["+49 30 1234567", "jane@example.com"]
    assert letter_data(cv, listing, demo_author_letter(), "en", TODAY)["date"] == "3 November 2026"


def make_run(tmp_path, cover_letter):
    db = init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db) as session:
        parsed = to_parsed_cv(make_extracted()).model_dump(mode="json")
        cv = CV(label="t", markdown="#", status=CVStatus.CONFIRMED, parsed=parsed)
        session.add(cv)
        session.commit()
        run = Run(cv_id=cv.id, listing_text="Wir suchen ...", status=RunStatus.CREATED)
        session.add(run)
        session.commit()
        return db, run.id


async def drive_to_documents(db, run_id, settings, cover_letter):
    engine = Engine(settings)
    await engine.drive(run_id)  # -> waiting_for_apply_decision
    with Session(db) as session:
        run = session.get(Run, run_id)
        run.state = run.state | {"decision": {"cover_letter": cover_letter}}
        run.status = RunStatus.AUTHORING
        session.add(run)
        session.commit()
    await engine.drive(run_id)


async def test_review_loop_reworks_until_the_fact_check_passes(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    settings = load_settings(DEFAULT_CONFIG_PATH)
    bad = demo_author_cv().model_copy(
        update={"bullets": [bullet("pos1", "Cut p99 latency by 60%", ["pos1.ach1"])]}
    )
    fake_llm.results["author_cv"] = [bad, demo_author_cv()]
    db, run_id = make_run(tmp_path, cover_letter=True)

    await drive_to_documents(db, run_id, settings, cover_letter=True)

    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.WAITING_FOR_FINAL_REVIEW
        first, second = run.state["drafts"]
        assert any("60" in v for v in first["cv_report"]["violations"])
        assert second["cv_report"]["violations"] == []
        assert set(second["files"]) == {
            "cv.pdf",
            "cv.json",
            "cover-letter.pdf",
            "cover-letter.json",
        }

    # The rework request contains the problem and the previous draft.
    rework = [c for c in fake_llm.calls if c["step"] == "author_cv"][1]["task"]
    assert "60" in rework and "Previous CV draft (JSON)" in rework
    # The letter was written once and reused, since it had no problems.
    assert len([c for c in fake_llm.calls if c["step"] == "author_letter"]) == 1

    pdf = tmp_path / "runs" / str(run_id) / "draft-2" / "cv.pdf"
    text = pdf_to_text(pdf)
    assert "Senkung der p99-Latenz um 40 %" in text
    assert "Beta AG · Kundeneinsatz bei Gamma Bank" in text


async def test_loop_stops_after_max_iterations(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    settings = load_settings(DEFAULT_CONFIG_PATH)
    bad = demo_author_cv().model_copy(
        update={"bullets": [bullet("pos1", "Cut p99 latency by 60%", ["pos1.ach1"])]}
    )
    fake_llm.results["author_cv"] = [bad] * 10
    db, run_id = make_run(tmp_path, cover_letter=False)

    await drive_to_documents(db, run_id, settings, cover_letter=False)

    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.WAITING_FOR_FINAL_REVIEW
        assert len(run.state["drafts"]) == settings.review.max_iterations
        assert run.state["drafts"][-1]["letter"] is None


def test_list_sections_render_one_entry_per_line(tmp_path):
    from application_crew.domain.extraction import ExtractedCertification, ExtractedEducation
    from application_crew.render.documents import render_cv

    extracted = make_extracted(
        certifications=[
            ExtractedCertification(name="Cert Alpha", abbreviation="", issuer="Org A", year="2023"),
            ExtractedCertification(name="Cert Beta", abbreviation="", issuer="Org B", year="2024"),
        ],
        education=[
            ExtractedEducation(
                qualification="M.Sc. X",
                institution="Uni One",
                location="",
                start="2014-10",
                end="2017-03",
            ),
            ExtractedEducation(
                qualification="B.Sc. Y",
                institution="Uni Two",
                location="",
                start="2010-10",
                end="2014-03",
            ),
        ],
    )
    cv = to_parsed_cv(extracted)
    result = render_cv(cv_data(cv, demo_author_cv(), "en", False), tmp_path / "cv.pdf")
    assert result.ok, result.error
    lines = pdf_to_text(tmp_path / "cv.pdf").splitlines()
    for a, b in [("Cert Alpha", "Cert Beta"), ("Uni One", "Uni Two")]:
        assert not any(a in line and b in line for line in lines), f"{a} and {b} on one line"
