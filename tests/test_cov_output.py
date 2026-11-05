"""Edge cases of the output side: export data and report, email, rendering, database."""

import subprocess

import pytest

from mappe import db
from mappe.db import Run
from mappe.domain.extraction import to_parsed_cv
from mappe.domain.models import Contact, Fact, ParsedCV
from mappe.export import pdf as export_pdf
from mappe.export.data import _fact_sources, application_data, tone, work_mode
from mappe.llm.demo import demo_author_letter, sample_cv
from mappe.mail.message import EmailUnavailable, email_draft
from mappe.render import typst
from mappe.render.documents import _links, _month
from mappe.render.typst import RenderResult, render
from mappe.runner.states import RunStatus

# --- export data -------------------------------------------------------------------------------


def test_tone_and_work_mode_labels():
    assert tone("failed") == "bad"
    assert tone("done") == "good"
    assert tone("declined") == "muted"
    assert tone("waiting_for_apply_decision") == "you"
    assert tone("matching") == "busy"
    assert work_mode("onsite", None) == "Onsite"
    assert work_mode(None, None) == ""


def test_fact_sources_cover_publications_and_volunteering():
    cv = ParsedCV(
        contact=Contact(name="Jane"),
        publications=[Fact(id="pub1", text="Paper")],
        volunteering=[Fact(id="vol1", text="Coach")],
    )
    assert _fact_sources(cv) == {"pub1": "Publications", "vol1": "Volunteering"}


def test_application_data_of_a_declined_run_with_requirements_and_hand_edits():
    state = {
        "requirement_results": [
            {
                "requirement": {"kind": "salary_min", "value": "70000", "must_have": True},
                "outcome": "passed",
                "note": "Band reaches 70,000 EUR/year",
            },
            {
                "requirement": {"kind": "benefit", "value": "Bike leasing"},
                "outcome": "unknown",
                "evidence": None,
            },
        ],
        "analysis": {
            "total_years": 6.5,
            "student_years": 1.5,
            "years_required": None,
            "required_matched": 1,
            "required_related": 0,
            "required_total": 1,
            "coverage": [
                {"skill": "Python", "required": True, "coverage": "match", "cv_skill": "Python"}
            ],
        },
        "drafts": [
            {
                "iteration": 1,
                "source": "user",
                "cv_report": {"violations": []},
                "letter_report": {"violations": []},
            }
        ],
    }
    run = Run(id=5, cv_id=1, status=RunStatus.DECLINED, listing_text="text", state=state)
    data = application_data(run, [], links=False)

    assert data["decision"] == "Declined"
    assert data["tone"] == "muted"
    salary_req, benefit = data["requirements"]
    assert salary_req["value"] == "70,000 EUR / year" and salary_req["must"] is True
    assert salary_req["tone"] == "good" and salary_req["note"] == "Band reaches 70,000 EUR/year"
    assert benefit["tone"] == "neutral" and benefit["evidence"] == ""
    assert data["coverage"]["years"] == (
        "6.5 years of experience (including 1.5 as working student)"
    )
    assert data["coverage"]["rows"][0]["years"] == ""
    claims = data["review"]["checks"][1]
    assert claims["name"] == "Claims check" and claims["outcome"] == "not run"
    assert data["review"]["edited"] is True


# --- export report ----------------------------------------------------------------------------


def test_render_report_raises_when_typst_fails(monkeypatch):
    monkeypatch.setattr(
        export_pdf, "render", lambda *a, **kw: RenderResult(ok=False, error="syntax error")
    )
    with pytest.raises(export_pdf.ExportError, match="Rendering the export failed: syntax error"):
        export_pdf.render_report({})


# --- email ---------------------------------------------------------------------------------------


def test_email_needs_the_final_cv_pdf(tmp_path):
    state = {
        "delivery": {"draft": 1, "files": {"Doe_Jane_CV.pdf": "cv.pdf"}},
        "drafts": [{"iteration": 1, "lang": "de", "letter": demo_author_letter().model_dump()}],
        "listing": {"title": "Dev", "company": "Acme", "contact_email": "jobs@acme.example"},
        "cv": to_parsed_cv(sample_cv()).model_dump(),
    }
    run = Run(id=9, cv_id=1, state=state)
    with pytest.raises(EmailUnavailable, match="The final CV PDF is missing."):
        email_draft(tmp_path, run)

    state["delivery"]["files"] = {}  # no CV among the delivered files at all
    with pytest.raises(EmailUnavailable, match="The final CV PDF is missing."):
        email_draft(tmp_path, run)


# --- rendering helpers ------------------------------------------------------------------------


def test_month_keeps_unparseable_values():
    assert _month("since spring") == "since spring"
    assert _month(None) == ""
    assert _month("2021-03") == "03/2021"
    assert _month("2021") == "2021"


def test_links_are_sorted_into_github_linkedin_and_site():
    cv = ParsedCV(
        contact=Contact(
            name="Jane",
            links=[
                "https://www.linkedin.com/in/jane/",
                "https://jane.dev",
                "https://github.com/jane",
                "https://other.example",
                "https://linkedin.com/in/second",
            ],
        )
    )
    assert _links(cv) == {
        "github": "github.com/jane",
        "linkedin": "www.linkedin.com/in/jane",
        "site": "jane.dev",
    }


def test_render_reports_a_missing_template(tmp_path):
    result = render("no-such-template", {}, tmp_path / "out.pdf")
    assert not result.ok and result.pdf_path is None
    assert result.error.startswith("template not found:")


def test_render_returns_the_typst_error(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error: unknown variable\n")

    monkeypatch.setattr(typst.subprocess, "run", fake_run)
    result = render("export", {"x": 1}, tmp_path / "out" / "report.pdf", app_fonts=True)
    assert result == RenderResult(ok=False, error="error: unknown variable")
    assert calls[0][:4] == ["typst", "compile", "--font-path", str(typst.FONTS_DIR)]


# --- database -------------------------------------------------------------------------------------


def test_get_engine_before_init_fails(monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    with pytest.raises(RuntimeError, match="Database not initialised"):
        db.get_engine()
