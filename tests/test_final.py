import io
import zipfile

from application_crew.domain.extraction import to_parsed_cv
from application_crew.domain.listing import merge_listing
from application_crew.llm.demo import demo_author_cv, demo_author_letter, demo_listing
from application_crew.steps.final import apply_edits, delivery_names, file_part
from tests.conftest import make_extracted
from tests.test_web import confirmed_cv, wait_for


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
    cv = to_parsed_cv(make_extracted())
    form = {
        "profile": "Neues Profil.",
        "bullets_pos1": "Verantwortung für die Payments-API in Python und FastAPI (überarbeitet)\n"
        "- Komplett neue Zeile über Onboarding",
        "bullets_pos2": "",
        "skills_1_category": "Kern",
        "skills_1_items": "Python, FastAPI",
        "skills_2_category": "",
        "skills_2_items": "Java",
        "letter_subject": "Bewerbung",
        "letter_body": "Erster Absatz.\n\nBei der Acme GmbH verantworte ich die Payments-API und "
        "habe die p99-Latenz um 40 % gesenkt.",
    }
    doc, letter = apply_edits(cv, demo_author_cv(), demo_author_letter(), form)
    first, second = doc.bullets
    assert first.fact_ids == ["pos1.resp1"]  # similar to the original bullet
    assert second.text == "Komplett neue Zeile über Onboarding"
    assert second.fact_ids == ["pos1", "pos1.resp1", "pos1.ach1"]  # new text: whole position
    assert [g.category for g in doc.skill_groups] == ["Kern"]
    assert letter.paragraphs[1].fact_ids == ["pos1.resp1", "pos1.ach1"]
    assert letter.paragraphs[0].fact_ids == []


def test_final_review_edit_approve_and_deliver(client):
    cv_id = confirmed_cv(client)
    run_url = str(
        client.post("/runs", data={"cv_id": cv_id, "listing_text": "Wir suchen ..."}).url.path
    )
    wait_for(client, run_url, "waiting_for_apply_decision")
    client.post(f"{run_url}/apply", data={"cover_letter": "on"})
    wait_for(client, run_url, "waiting_for_final_review", timeout=20)

    edit = client.get(f"{run_url}/edit")
    assert edit.status_code == 200 and 'name="bullets_pos1"' in edit.text
    form = {
        "profile": "Backend-Entwickler mit 25 Jahren Erfahrung.",  # invented number
        "title_pos1": "Senior Backend Engineer",
        "bullets_pos1": "Verantwortung für die Payments-API in Python und FastAPI\n"
        "Senkung der p99-Latenz um 40 %",
        "bullets_pos2": "Aufbau von Datenpipelines in Java",
        "skills_1_category": "Sprachen & Frameworks",
        "skills_1_items": "Python, FastAPI, Java, PostgreSQL, Kubernetes",
        "letter_subject": "Bewerbung als Senior Python Developer (m/w/d)",
        "letter_body": "Mein Interesse an Ihrer Plattform ist groß.",
    }
    page = client.post(f"{run_url}/edit", data=form)
    assert "Your edit of draft 1" in page.text
    assert "number(s) 25" in page.text  # shown, not blocking
    assert "still has 1 open problem(s)" in page.text

    page = client.post(f"{run_url}/approve")
    page = wait_for(client, run_url, "Ready to send")
    assert "Doe_Jane_Lebenslauf_Beispiel_Mobility_GmbH.pdf" in page.text
    pdf = client.get(f"{run_url}/final/Doe_Jane_Lebenslauf_Beispiel_Mobility_GmbH.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"{run_url}/final/cv.pdf").status_code == 404

    z = zipfile.ZipFile(io.BytesIO(client.get(f"{run_url}/bundle.zip").content))
    names = set(z.namelist())
    assert "final/Doe_Jane_Anschreiben_Beispiel_Mobility_GmbH.pdf" in names
    assert {"draft-1/cv.pdf", "draft-2/cv.pdf", "intermediates/assessment.json"} <= names
    assert "intermediates/listing.txt" in names
