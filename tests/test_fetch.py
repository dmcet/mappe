import asyncio
import json

import httpx
import pytest

from mappe.fetch.listing import detect_language, extract_job_posting, fetch_listing

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


# --- download: total timeout, size cap ---------------------------------------------------

PAGE = (
    "<html><head><script type='application/ld+json'>"
    f"{json.dumps(POSTING)}"
    "</script></head><body><p>" + "Wir suchen Verstärkung. " * 30 + "</p></body></html>"
)


def transport(body):
    return httpx.MockTransport(lambda request: httpx.Response(200, content=body))


class Trickle(httpx.AsyncByteStream):
    """A server that keeps sending a byte now and then: each read is fast, the page never ends."""

    async def __aiter__(self):
        while True:
            await asyncio.sleep(0.02)
            yield b"x"


async def test_fetch_extracts_the_listing():
    result = await fetch_listing("https://example.com/job", transport=transport(PAGE.encode()))
    assert result.ok and result.job_posting["title"].startswith("Senior")


async def test_fetch_has_a_total_timeout():
    slow = httpx.MockTransport(lambda request: httpx.Response(200, stream=Trickle()))
    result = await fetch_listing("https://example.com/job", timeout=0.2, transport=slow)
    assert not result.ok and result.error == "fetch timed out after 0.2 seconds"


async def test_fetch_refuses_huge_pages():
    big = transport(b"x" * 2_000_000)
    result = await fetch_listing("https://example.com/job", max_bytes=1_000_000, transport=big)
    assert not result.ok and "larger than 1 MB" in result.error


@pytest.mark.parametrize("status", [404, 500])
async def test_fetch_reports_http_errors(status):
    failing = httpx.MockTransport(lambda request: httpx.Response(status))
    result = await fetch_listing("https://example.com/job", transport=failing)
    assert not result.ok and str(status) in result.error
