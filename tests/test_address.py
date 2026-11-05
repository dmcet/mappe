"""Employer address: confirmed or not, and the letter layout that follows from it."""

from datetime import date

import pytest

from mappe.domain.address import confirmed_address, from_job_posting, in_text
from mappe.domain.extraction import to_parsed_cv
from mappe.domain.listing import merge_listing
from mappe.llm.demo import demo_author_letter, demo_listing, sample_cv
from mappe.render.documents import letter_data, render_cv, render_letter
from mappe.render.typst import pdf_to_text, typst_available

FOOTER = "Beispiel Mobility GmbH | Leopoldstraße 10 | 80802 München | www.beispiel.de"


def test_address_in_the_text_is_confirmed():
    assert in_text("Leopoldstraße 10", "80802", "München", FOOTER) == [
        "Leopoldstraße 10",
        "80802 München",
    ]
    # Line breaks and case don't matter; "PLZ, city" is fine.
    text = "Kontakt:\nleopoldstraße 10\n80802, München"
    assert in_text("Leopoldstraße 10", "80802", "München", text) is not None


@pytest.mark.parametrize(
    ("street", "postal_code", "city", "text"),
    [
        ("Leopoldstraße 10", "80802", "München", "Standort München"),  # not in the text
        ("Leopoldstraße 10", "", "München", FOOTER),  # incomplete
        ("Leopoldstraße", "80802", "München", FOOTER),  # no house number
        ("Leopoldstraße 10", "8080", "München", FOOTER),  # postal code doesn't match
        (
            "Leopoldstraße 10",
            "80802",
            "München",
            "Leopoldstraße 10 ist unser Lager." + " x" * 100 + " 80802 München",  # far apart
        ),
    ],
)
def test_unconfirmed_addresses(street, postal_code, city, text):
    assert in_text(street, postal_code, city, text) is None


def test_job_posting_address_wins():
    posting = {
        "hiringOrganization": {
            "name": "Example SE",
            "address": {
                "streetAddress": "Hauptstr. 1",
                "postalCode": "10115",
                "addressLocality": "Berlin",
            },
        }
    }
    assert from_job_posting(posting) == ["Hauptstr. 1", "10115 Berlin"]
    only_location = {
        "jobLocation": {
            "address": {"streetAddress": "Ring 5", "postalCode": "1010", "addressLocality": "Wien"}
        }
    }
    assert from_job_posting(only_location) == ["Ring 5", "1010 Wien"]
    two_locations = {"jobLocation": [only_location["jobLocation"], only_location["jobLocation"]]}
    assert from_job_posting(two_locations) is None
    city_only = {"jobLocation": {"address": {"addressLocality": "Berlin"}}}
    assert confirmed_address("", "", "", "", city_only) is None


def listing(text):
    return merge_listing(demo_listing(), None, "de", text=text)


def test_letter_layout_follows_the_address():
    cv = to_parsed_cv(sample_cv())
    letter = demo_author_letter()
    with_address = letter_data(cv, listing(FOOTER), letter, "de", date(2026, 11, 3))
    assert with_address["layout"] == "letter"
    assert with_address["recipient"] == [
        "Beispiel Mobility GmbH",
        "Leopoldstraße 10",
        "80802 München",
    ]

    without = letter_data(cv, listing("Wir suchen ..."), letter, "de", date(2026, 11, 3))
    assert without["layout"] == "plain"
    assert without["recipient"] == [] and without["sender"]["address"] == ""
    assert without["subject"] == with_address["subject"]  # same text otherwise


@pytest.mark.skipif(not typst_available(), reason="typst not installed")
@pytest.mark.parametrize("text", [FOOTER, "Wir suchen ..."])
def test_both_letter_layouts_render(tmp_path, text):
    cv = to_parsed_cv(sample_cv(address="Musterweg 3, 10115 Berlin"))
    data = letter_data(cv, listing(text), demo_author_letter(), "de", date(2026, 11, 3))
    out = tmp_path / "letter.pdf"
    result = render_letter(data, out)
    assert result.ok, result.error
    pdf = pdf_to_text(out)
    assert "Bewerbung als Senior Python Developer" in pdf
    assert "Mit freundlichen Grüßen" in pdf
    if data["layout"] == "letter":
        assert "Leopoldstraße 10" in pdf and "Musterweg 3" in pdf
    else:
        assert "Leopoldstraße" not in pdf and "Musterweg" not in pdf and "München" not in pdf
        assert "jane@example.com" in pdf  # contact line, no postal address


@pytest.mark.skipif(not typst_available(), reason="typst not installed")
def test_documents_use_inter(tmp_path):
    import subprocess

    from mappe.llm.demo import demo_author_cv
    from mappe.render.documents import cv_data

    cv = to_parsed_cv(sample_cv())
    out = tmp_path / "cv.pdf"
    assert render_cv(cv_data(cv, demo_author_cv(), "de", translate_titles=True), out).ok
    fonts = subprocess.run(["pdffonts", str(out)], capture_output=True, text=True).stdout
    assert "Inter" in fonts and "NewCM" not in fonts and "Computer" not in fonts
