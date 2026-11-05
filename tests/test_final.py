import email
import io
import zipfile
from email import policy

from mappe.domain.extraction import to_parsed_cv
from mappe.domain.listing import merge_listing
from mappe.llm.demo import DEMO_CONTACT_LINE, demo_author_cv, demo_author_letter, demo_listing
from mappe.steps.final import apply_edits, delivery_names, file_part
from tests.conftest import make_extracted
from tests.test_web import confirmed_cv, start_run, status_is, wait_for


def test_file_names():
    assert file_part("Müller-Lüdenscheidt GmbH & Co. KG") == "Mueller-Luedenscheidt_GmbH_Co_KG"
    assert file_part("Beispiel Mobility GmbH") == "Beispiel_Mobility_GmbH"
    cv = to_parsed_cv(make_extracted())
    listing = merge_listing(demo_listing(), None, "de")
    assert delivery_names(cv, listing, "de") == {
        "cv.pdf": "Doe_Jane_Lebenslauf_Beispiel_Mobility_GmbH.pdf",
        "cover-letter.pdf": "Doe_Jane_Anschreiben_Beispiel_Mobility_GmbH.pdf",
    }
    assert delivery_names(cv, listing, "en")["cv.pdf"] == "Doe_Jane_CV_Beispiel_Mobility_GmbH.pdf"


def test_edits_keep_fact_ids_of_kept_text():
    from mappe.domain.author import SkillGroup
    from mappe.steps.final import DocumentEdit, LetterEdit

    cv = to_parsed_cv(make_extracted())
    edit = DocumentEdit(
        profile="Neues Profil.",
        bullets={
            "pos1": [
                "Verantwortung für die Payments-API in Python und FastAPI (überarbeitet)",
                "- Komplett neue Zeile über Onboarding",
            ],
            "pos2": [],
        },
        skill_groups=[
            SkillGroup(category="Kern", skills=["Python", "FastAPI"]),
            SkillGroup(category="", skills=["Java"]),  # no category: dropped
        ],
        letter=LetterEdit(
            subject="Bewerbung",
            paragraphs=[
                "Erster Absatz.",
                "Bei der Acme GmbH verantworte ich die Payments-API und habe die "
                "p99-Latenz um 40 % gesenkt.",
            ],
        ),
    )
    doc, letter = apply_edits(cv, demo_author_cv(), demo_author_letter(), edit)
    first, second = doc.bullets
    assert first.fact_ids == ["pos1.resp1"]  # similar to the original bullet
    assert second.text == "Komplett neue Zeile über Onboarding"
    assert second.fact_ids == ["pos1", "pos1.resp1", "pos1.ach1"]  # new text: whole position
    assert [g.category for g in doc.skill_groups] == ["Kern"]
    assert letter.paragraphs[1].fact_ids == ["pos1.resp1", "pos1.ach1"]
    assert letter.paragraphs[0].fact_ids == []


def test_final_review_edit_approve_and_deliver(client):
    cv_id = confirmed_cv(client)
    run_id = start_run(client, cv_id, listing_text=f"Wir suchen ...\n{DEMO_CONTACT_LINE}")
    early = client.get(f"/api/runs/{run_id}/email").json()
    assert early == {"available": False, "reason": "The application isn't finished yet."}
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_apply_decision"))
    client.post(f"/api/runs/{run_id}/apply", json={"cover_letter": True})
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_final_review"), 20)

    data = client.get(f"/api/runs/{run_id}/edit-data").json()
    assert data["draft"]["iteration"] == 1 and data["cv"]["positions"][0]["id"] == "pos1"
    edit = {
        "profile": "Backend-Entwickler mit 25 Jahren Erfahrung.",  # invented number
        "titles": {"pos1": "Senior Backend Engineer"},
        "bullets": {
            "pos1": [
                "Verantwortung für die Payments-API in Python und FastAPI",
                "Senkung der p99-Latenz um 40 %",
            ],
            "pos2": ["Aufbau von Datenpipelines in Java"],
        },
        "skill_groups": [
            {"category": "Sprachen & Frameworks",
             "skills": ["Python", "FastAPI", "Java", "PostgreSQL", "Kubernetes"]}
        ],
        "letter": {"subject": "Bewerbung als Senior Python Developer (m/w/d)",
                   "paragraphs": ["Mein Interesse an Ihrer Plattform ist groß."]},
    }  # fmt: skip
    data = client.put(f"/api/runs/{run_id}/documents", json=edit).json()
    user_draft = data["state"]["drafts"][-1]
    assert user_draft["source"] == "user" and user_draft["based_on"] == 1
    assert data["state"]["final_draft"] == 2
    assert any("number(s) 25" in v for v in user_draft["cv_report"]["violations"])  # not blocking

    client.post(f"/api/runs/{run_id}/approve")
    data = wait_for(client, f"/api/runs/{run_id}", status_is("done"))
    assert all(s["state"] == "done" for s in data["pipeline"])
    files = data["state"]["delivery"]["files"]
    assert "Doe_Jane_Lebenslauf_Beispiel_Mobility_GmbH.pdf" in files
    pdf = client.get(f"/api/runs/{run_id}/final/Doe_Jane_Lebenslauf_Beispiel_Mobility_GmbH.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"/api/runs/{run_id}/final/cv.pdf").status_code == 404

    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/runs/{run_id}/bundle.zip").content))
    names = set(z.namelist())
    assert "final/Doe_Jane_Anschreiben_Beispiel_Mobility_GmbH.pdf" in names
    assert {"draft-1/cv.pdf", "draft-2/cv.pdf", "intermediates/assessment.json"} <= names
    assert "intermediates/listing.txt" in names

    mail = client.get(f"/api/runs/{run_id}/email").json()
    assert mail["available"] and mail["to"] == "bewerbung@beispiel-mobility.de"
    assert mail["body"].startswith("Sehr geehrte Frau Schmidt,\n\nMein Interesse")
    assert mail["cv_name"] == "Doe_Jane_Lebenslauf_Beispiel_Mobility_GmbH.pdf"
    assert mail["shortcut_url"].startswith("shortcuts://run-shortcut?name=Mappe%20Mail&input=text")
    assert client.get(mail["cv_url"]).content.startswith(b"%PDF")
    eml = client.get(f"/api/runs/{run_id}/email.eml")
    assert "Doe_Jane_Bewerbung_Beispiel_Mobility_GmbH.eml" in eml.headers["content-disposition"]
    msg = email.message_from_bytes(eml.content, policy=policy.default)
    assert msg["X-Unsent"] == "1"
    assert [p.get_filename() for p in msg.iter_attachments()] == [mail["cv_name"]]
