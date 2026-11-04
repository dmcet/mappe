"""PDF exports: data preparation (always) and the rendered PDFs (with typst)."""

import io
import subprocess
import zipfile
from datetime import date

import pytest
from pypdf import PdfReader

from mappe.db import Run
from mappe.export.data import (
    Document,
    application_data,
    excerpt,
    place_documents,
    ranking_text,
    requirement_line,
    salary,
    search_data,
    work_mode,
)
from mappe.render.typst import typst_available
from mappe.runner.states import RunStatus
from tests.test_search_web import search
from tests.test_web import confirmed_cv, status_is, wait_for

needs_typst = pytest.mark.skipif(not typst_available(), reason="typst not installed")


def test_formatting_helpers():
    assert salary(70000, 85000, "EUR", "year") == "70k–85k EUR / year"
    assert salary(None, 18, "EUR", "hour") == "18 EUR / hour"
    assert salary(None, None, None, None) == ""
    assert work_mode("hybrid", 2) == "Hybrid · 2 day(s) onsite"
    assert work_mode(None, None) == ""
    assert excerpt("word " * 300, 40).endswith(" …") and len(excerpt("word " * 300, 40)) <= 42
    assert requirement_line({"kind": "salary_min", "value": "75000", "must_have": True}) == {
        "label": "Minimum salary",
        "value": "75,000 EUR / year",
        "must": True,
    }
    assert requirement_line({"kind": "max_onsite_days", "value": "0"})["value"] == "remote only"
    assert ranking_text({"semantic": False, "note": "turned off."}) == (
        "Ranked by keywords only: turned off."
    )


def _item(hit_id, hidden=None, run_id=None, score=50.0):
    return {
        "score": score,
        "hidden": hidden,
        "is_new": True,
        "reasons": {"matched_skills": ["Python"], "title_fit": 0.8, "semantic_fit": None},
        "hit": {
            "id": hit_id,
            "run_id": run_id,
            "source": "arbeitnow",
            "source_label": "Arbeitnow",
            "external_id": str(hit_id),
            "url": f"https://jobs.test/{hit_id}",
            "view_url": f"https://jobs.test/{hit_id}",
            "title": f"Job {hit_id}",
            "excerpt": "short",
        },
    }


def _detail(results):
    return {
        "titles": ["Backend Engineer"],
        "places": [],
        "remote_only": False,
        "created_at": date(2026, 11, 4),
        "requirements": [],
        "sources": {"arbeitnow": {"label": "Arbeitnow", "count": 3, "error": None}},
        "total": len(results),
        "results": results,
    }


def test_search_data_keeps_what_the_list_shows():
    run = Run(
        id=7, cv_id=1, status=RunStatus.DONE, state={"match": {"verdict": "apply", "score": 81}}
    )
    detail = _detail(
        [
            _item(1),
            _item(2, hidden="low_score"),
            _item(3, hidden="dismissed"),
            _item(4, "low_score", 7),
        ]
    )

    data = search_data(detail, set(), {7: run}, "Ranked by keywords.", with_applications=False)
    assert [r["title"] for r in data["results"]] == ["Job 1"]
    assert data["not_included"] == "1 dismissed, 2 low match"
    assert data["places"] == ["all of Germany"]

    shown = search_data(detail, {"low_score"}, {7: run}, "", False, descriptions={1: "Full text"})
    assert [r["title"] for r in shown["results"]] == ["Job 1", "Job 2", "Job 4"]
    assert shown["results"][0]["excerpt"] == "Full text"
    assert shown["results"][1]["hidden"] == "low match"
    assert shown["results"][2]["application"]["verdict"] == "Apply"
    assert shown["results"][2]["application"]["anchor"] == ""  # no section to link to

    # The full export always lists the listings that have an application.
    full = search_data(detail, set(), {7: run}, "", with_applications=True)
    assert [r["title"] for r in full["results"]] == ["Job 1", "Job 4"]
    assert full["results"][1]["application"]["anchor"] == "run-7"


def test_application_data_before_the_assessment():
    run = Run(id=3, cv_id=1, status=RunStatus.FETCHING_LISTING, listing_url="https://x.test/a")
    data = application_data(run, [], links=True)
    assert data["title"] == "https://x.test/a"
    assert data["host"] == "x.test"
    assert data["verdict"] is None and data["review"] is None and data["documents"] == []
    assert data["status"] == "Fetching listing"


def test_documents_sit_next_to_the_report_or_in_one_folder_per_application(tmp_path):
    def run(i, company):
        return Run(id=i, cv_id=1, state={"listing": {"company": company}})

    def doc(i, name):
        return Document(i, "cv", "Tailored CV", name, tmp_path / name, True)

    one = [doc(1, "Doe_Jane_CV_Acme.pdf"), doc(1, "Doe_Jane_Cover_Letter_Acme.pdf")]
    place_documents([(run(1, "Acme"), one)])
    assert [d.file for d in one] == ["Doe_Jane_CV_Acme.pdf", "Doe_Jane_Cover_Letter_Acme.pdf"]

    # Folders are numbered, so two applications at the same company don't collide.
    a, b = [doc(1, "Doe_Jane_CV_Acme.pdf")], [doc(2, "Doe_Jane_CV_Acme.pdf")]
    place_documents([(run(1, "Acme & Co."), a), (run(3, "Other"), []), (run(2, "Acme & Co."), b)])
    assert [a[0].file, b[0].file] == [
        "01_Acme_Co/Doe_Jane_CV_Acme.pdf",
        "02_Acme_Co/Doe_Jane_CV_Acme.pdf",
    ]


# --- rendered PDFs ------------------------------------------------------------------------


def _links(reader: PdfReader) -> list[tuple[str, object]]:
    """("uri" | "file" | "dest", target) for every link annotation."""
    out = []
    for page in reader.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            action = annot.get("/A")
            if action is None:
                out.append(("dest", str(annot.get("/Dest"))))
                continue
            action = action.get_object()
            if action["/S"] == "/GoToR":
                out.append(("file", str(action["/F"]["/F"])))
            else:
                out.append(("uri", str(action["/URI"])))
    return out


def _text(content: bytes) -> str:
    proc = subprocess.run(["pdftotext", "-", "-"], input=content, capture_output=True, check=True)
    return proc.stdout.decode()


def _apply(client, search_id, hit_id, cover_letter, approve):
    resp = client.post(f"/api/searches/{search_id}/apply", json={"hit_ids": [hit_id]})
    run_id = resp.json()[0]["id"]
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_apply_decision"))
    client.post(f"/api/runs/{run_id}/apply", json={"cover_letter": cover_letter})
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_final_review"), 20)
    if approve:
        client.post(f"/api/runs/{run_id}/approve")
        wait_for(client, f"/api/runs/{run_id}", status_is("done"))
    return run_id


@needs_typst
def test_exports_of_a_search_with_applications(client, job_apis):
    cv_id = confirmed_cv(client)
    data = search(client, cv_id, sources=["ba", "arbeitnow"])
    hit = next(r["hit"] for r in data["results"] if r["hidden"] is None)
    # Arbeitnow has the full text, so the applications need no fetch.
    applied = [r for r in data["results"] if r["hit"]["source"] == "arbeitnow"][:2]
    done = _apply(client, data["id"], applied[0]["hit"]["id"], cover_letter=True, approve=True)
    draft = _apply(client, data["id"], applied[1]["hit"]["id"], cover_letter=False, approve=False)

    # (a) The search list only: one PDF.
    resp = client.get(f"/api/searches/{data['id']}/export.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert 'filename="Mappe_Jobs_' in resp.headers["content-disposition"]
    text = _text(resp.content)
    assert hit["title"].split()[0] in text and "Jane Doe" in text
    links = _links(PdfReader(io.BytesIO(resp.content)))
    assert ("uri", hit["view_url"]) in links
    assert not any(kind == "file" for kind, _ in links)
    if applied[0]["hidden"]:  # hidden listings are left out unless asked for
        assert applied[0]["hit"]["title"] not in text
        shown = client.get(f"/api/searches/{data['id']}/export.pdf?show={applied[0]['hidden']}")
        assert applied[0]["hit"]["title"][:20] in _text(shown.content)

    # (b) A ZIP: one report with the list and the reasoning, the documents as their own files.
    resp = client.get(f"/api/searches/{data['id']}/export.zip")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    stem = resp.headers["content-disposition"].split('filename="')[1].removesuffix('.zip"')
    assert stem.startswith("Mappe_Applications_")
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = archive.namelist()
    run = client.get(f"/api/runs/{done}").json()
    delivered = list(run["state"]["delivery"]["files"])  # CV, cover letter
    assert names[0] == f"{stem}_Report.pdf"
    assert all(n.startswith("01_") for n in names[1:3])
    assert [n.rsplit("/", 1)[1] for n in names[1:3]] == delivered
    assert len(names) == 4 and names[3].startswith("02_") and names[3].endswith("_draft-1.pdf")
    # The deliverables are the files as delivered.
    final = client.get(f"/api/runs/{done}/final/{delivered[0]}").content
    assert archive.read(names[1]) == final

    report = archive.read(names[0])
    text = _text(report)
    for expected in ("At a glance", "Strengths", "Skill coverage", "Checks of the final draft"):
        assert expected in text
    assert "not yet approved" in text  # the second application is still in final review
    links = _links(PdfReader(io.BytesIO(report)))
    # The buttons open the files next to the report; no placeholder link is left.
    assert sorted(t for kind, t in links if kind == "file") == sorted(names[1:])
    assert not any(kind == "uri" and t.startswith("mappe://") for kind, t in links)
    # Internal links (overview -> application section).
    assert ("dest", f"run-{done}") in links and ("dest", f"run-{draft}") in links

    # A single application: the report, the CV and the cover letter, side by side.
    resp = client.get(f"/api/runs/{done}/export.zip")
    assert resp.status_code == 200, resp.text
    assert "Mappe_Application_" in resp.headers["content-disposition"]
    single = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert len(single) == 3 and single[0].endswith("_Report.pdf") and single[1:] == delivered


@needs_typst
def test_export_of_a_run_without_documents(client):
    cv_id = confirmed_cv(client)
    run_id = client.post(
        "/api/runs", json={"cv_id": cv_id, "listing_text": "Wir suchen ..."}
    ).json()[0]["id"]
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_apply_decision"))
    resp = client.get(f"/api/runs/{run_id}/export.zip")
    assert resp.status_code == 200, resp.text
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert len(names) == 1
    text = _text(zipfile.ZipFile(io.BytesIO(resp.content)).read(names[0]))
    assert "Apply" in text and "Gaps" in text and "Documents" not in text


def test_exports_of_unknown_things(client):
    assert client.get("/api/searches/999/export.pdf").status_code == 404
    assert client.get("/api/searches/999/export.zip").status_code == 404
    assert client.get("/api/runs/999/export.zip").status_code == 404
