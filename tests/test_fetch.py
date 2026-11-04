import json

from mappe.fetch.listing import detect_language, extract_job_posting

POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Senior Backend Engineer (m/w/d)",
    "hiringOrganization": {"@type": "Organization", "name": "Beispiel GmbH"},
    "description": "<p>Wir suchen eine erfahrene Entwicklerin oder einen Entwickler.</p>",
}


def test_extract_job_posting_from_json_ld():
    html = (
        "<html><head><script type='application/ld+json'>"
        f"{json.dumps(POSTING)}"
        "</script></head><body>x</body></html>"
    )
    posting = extract_job_posting(html, "https://example.com/job")
    assert posting is not None
    assert posting["title"] == "Senior Backend Engineer (m/w/d)"


def test_extract_job_posting_inside_graph():
    graph = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, POSTING]}
    html = f"<script type='application/ld+json'>{json.dumps(graph)}</script>"
    assert extract_job_posting(html, "https://example.com")["title"].startswith("Senior")


def test_no_job_posting():
    assert extract_job_posting("<html><body>Hello</body></html>", "https://example.com") is None


def test_detect_language():
    assert detect_language("Wir suchen ab sofort eine Softwareentwicklerin für unser Team.") == "de"
    assert detect_language("We are looking for a software engineer to join our team.") == "en"


def test_redirect_to_parent_path_is_detected():
    from mappe.fetch.listing import _is_parent_path

    assert _is_parent_path("/karriere/stellenangebote", "/karriere/stellenangebote/job/x-71096")
    assert _is_parent_path("/karriere/stellenangebote/", "/karriere/stellenangebote/job/x")
    assert not _is_parent_path("/jobs/123", "/jobs/123/")
    assert not _is_parent_path("/de/jobs/123", "/jobs/123")
