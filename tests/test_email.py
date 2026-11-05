"""Application email: contact extraction, greeting, email body and .eml draft."""

import email
from datetime import date
from email import policy
from types import SimpleNamespace

import pytest

from mappe.domain.contact import choose_email, emails_in, resolve_contact
from mappe.domain.extraction import to_parsed_cv
from mappe.domain.listing import merge_listing
from mappe.llm.demo import DEMO_CONTACT_LINE, demo_author_letter, demo_listing, sample_cv
from mappe.mail.message import EmailUnavailable, body_text, build_eml, email_draft
from mappe.render.documents import addressee, letter_data, salutation

TEXT = """Senior Python Developer (m/w/d) bei der Beispiel Mobility GmbH.
Deine Ansprechpartnerin: Frau Dr. Anna  Schmidt
Bewerbungen bitte an bewerbung(at)beispiel-mobility.de.
Datenschutz: datenschutz@beispiel-mobility.de
Beispiel Mobility GmbH · Leopoldstraße 10 · 80802 München"""


def listing(text=TEXT, **overrides):
    extracted = demo_listing().model_copy(update=overrides)
    return merge_listing(extracted, None, "de", text=text)


# --- contact ----------------------------------------------------------------------------


def test_emails_in_text_including_obfuscated():
    assert emails_in(TEXT) == [
        "bewerbung@beispiel-mobility.de",
        "datenschutz@beispiel-mobility.de",
    ]
    assert emails_in("jobs [at] acme [dot] de oder Jobs@Acme.de.") == ["jobs@acme.de"]


def test_contact_is_kept_when_the_listing_shows_it():
    lst = listing()
    assert lst.contact_name == "Anna Schmidt"
    assert lst.contact_gender == "female"
    assert lst.contact_academic_title == "Dr."
    assert lst.contact_email == "bewerbung@beispiel-mobility.de"


def test_contact_claims_not_in_the_listing_are_dropped():
    text = "Wir suchen eine Python-Entwicklerin. Fragen an karriere@acme.de"
    lst = listing(text, contact_email="anna@acme.de", contact_name="Anna Schmidt")
    assert lst.contact_name is None and lst.contact_gender is None
    assert lst.contact_email == "karriere@acme.de"  # the address the listing really gives


def test_gender_needs_frau_or_herr_before_the_name():
    text = "Kontakt: Kim Weber, kim.weber@acme.de"
    lst = listing(text, contact_name="Kim Weber", contact_email="")
    assert lst.contact_name == "Kim Weber" and lst.contact_gender is None
    assert lst.contact_email == "kim.weber@acme.de"
    assert listing("Herr Kim Weber", contact_name="Herr Kim Weber").contact_gender == "male"


def test_choose_email_skips_unusable_and_ambiguous_addresses():
    assert choose_email(None, "noreply@acme.de, datenschutz@acme.de", None, None) is None
    assert choose_email(None, "info@a.de oder sales@a.de", None, None) is None
    assert choose_email(None, "info@a.de oder jobs@a.de", None, None) == "jobs@a.de"
    posting = {"applicationContact": {"email": "mailto:talent@a.de"}}
    assert choose_email(None, "info@a.de", posting, None) == "talent@a.de"


def test_demo_listing_contact_survives_verification():
    lst = merge_listing(demo_listing(), None, "de", text=f"Wir suchen ...\n{DEMO_CONTACT_LINE}")
    assert (lst.contact_name, lst.contact_email) == (
        "Anna Schmidt",
        "bewerbung@beispiel-mobility.de",
    )


# --- greeting ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("update", "de", "en"),
    [
        ({}, "Sehr geehrte Frau Dr. Schmidt,", "Dear Dr. Schmidt,"),
        ({"contact_academic_title": None}, "Sehr geehrte Frau Schmidt,", "Dear Ms Schmidt,"),
        (
            {"contact_gender": "male", "contact_academic_title": None},
            "Sehr geehrter Herr Schmidt,",
            "Dear Mr Schmidt,",
        ),
        ({"contact_gender": None}, "Guten Tag Dr. Anna Schmidt,", "Dear Dr. Schmidt,"),
        (
            {"contact_gender": None, "contact_academic_title": None},
            "Guten Tag Anna Schmidt,",
            "Dear Anna Schmidt,",
        ),
        ({"contact_name": None}, "Sehr geehrte Damen und Herren,", "Dear Hiring Team,"),
    ],
)
def test_salutation(update, de, en):
    lst = listing().model_copy(update=update)
    assert salutation(lst, "de") == de
    assert salutation(lst, "en") == en


def test_letter_pdf_uses_the_contact():
    cv = to_parsed_cv(sample_cv())
    data = letter_data(cv, listing(), demo_author_letter(), "de", date.today())
    assert data["salutation"] == "Sehr geehrte Frau Dr. Schmidt,"
    assert data["layout"] == "letter"
    assert data["recipient"] == [
        "Beispiel Mobility GmbH",
        "Frau Dr. Anna Schmidt",
        "Leopoldstraße 10",
        "80802 München",
    ]
    assert addressee(listing().model_copy(update={"contact_gender": None}), "de") == (
        "Dr. Anna Schmidt"
    )


# --- email ------------------------------------------------------------------------------


def delivered_run(tmp_path, lst, letter=True, text=TEXT):
    cv = to_parsed_cv(sample_cv())
    final = tmp_path / "7" / "final"
    final.mkdir(parents=True)
    (final / "Doe_Jane_Lebenslauf_Beispiel.pdf").write_bytes(b"%PDF-1.7 test")
    draft = {
        "iteration": 2,
        "lang": "de",
        "letter": demo_author_letter().model_dump(mode="json") if letter else None,
    }
    state = {
        "cv": cv.model_dump(mode="json"),
        "listing": lst.model_dump(mode="json"),
        "drafts": [{"iteration": 1, "lang": "de", "letter": None}, draft],
        "delivery": {
            "draft": 2,
            "files": {
                "Doe_Jane_Lebenslauf_Beispiel.pdf": "cv.pdf",
                "Doe_Jane_Anschreiben_Beispiel.pdf": "cover-letter.pdf",
            },
        },
    }
    return SimpleNamespace(id=7, state=state, listing_text=text)


def test_email_body_is_the_cover_letter():
    cv = to_parsed_cv(sample_cv())
    body = body_text(cv, listing(), demo_author_letter(), "de")
    assert body.startswith("Sehr geehrte Frau Dr. Schmidt,\n\nIhre Plattform")
    assert "Kündigungsfrist beträgt 3 Monate.\n\nMit freundlichen Grüßen\nJane Doe\n" in body
    assert body.endswith("jane@example.com\n")


def test_email_draft_and_eml(tmp_path):
    draft = email_draft(tmp_path, delivered_run(tmp_path, listing()))
    assert draft.to == "bewerbung@beispiel-mobility.de"
    assert draft.subject == "Bewerbung als Senior Python Developer (m/w/d)"
    assert draft.cv_name == "Doe_Jane_Lebenslauf_Beispiel.pdf"

    msg = email.message_from_bytes(build_eml(draft), policy=policy.default)
    assert msg["To"] == "bewerbung@beispiel-mobility.de"
    assert msg["From"] == "Jane Doe <jane@example.com>"
    assert msg["X-Unsent"] == "1"
    assert msg["Subject"] == draft.subject
    parts = list(msg.iter_attachments())
    assert [p.get_filename() for p in parts] == ["Doe_Jane_Lebenslauf_Beispiel.pdf"]
    assert parts[0].get_content() == b"%PDF-1.7 test"
    assert "Kündigungsfrist" in msg.get_body(("plain",)).get_content()


def test_older_runs_fall_back_to_a_text_scan(tmp_path):
    old = listing().model_copy(update={"contact_email": None, "contact_name": None})
    draft = email_draft(tmp_path, delivered_run(tmp_path, old))
    assert draft.to == "bewerbung@beispiel-mobility.de"
    assert draft.body.startswith("Sehr geehrte Damen und Herren,")


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"letter": False}, "no cover letter"),
        ({"text": "Kein Kontakt."}, "no email address"),
    ],
)
def test_email_unavailable(tmp_path, kwargs, reason):
    lst = listing().model_copy(update={"contact_email": None})
    run = delivered_run(tmp_path, lst, **kwargs)
    with pytest.raises(EmailUnavailable, match=reason):
        email_draft(tmp_path, run)


def test_email_unavailable_before_delivery(tmp_path):
    run = delivered_run(tmp_path, listing())
    del run.state["delivery"]
    with pytest.raises(EmailUnavailable, match="isn't finished"):
        email_draft(tmp_path, run)


def test_contact_resolution_without_any_contact():
    assert resolve_contact("", "", "Kein Kontakt.", None) == {
        "contact_name": None,
        "contact_gender": None,
        "contact_academic_title": None,
        "contact_email": None,
    }
