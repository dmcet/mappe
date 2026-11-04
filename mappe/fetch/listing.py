"""Deterministic job listing fetch: HTTP -> schema.org JobPosting JSON-LD -> main text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import extruct
import httpx
import trafilatura
from lingua import Language, LanguageDetectorBuilder

USER_AGENT = "Mozilla/5.0 (compatible; mappe/0.1; personal job search tool)"
MIN_TEXT_LENGTH = 300  # below this we assume a login wall / JS-only page

_detector = LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.GERMAN).build()


@dataclass
class FetchResult:
    ok: bool
    text: str = ""
    job_posting: dict[str, Any] | None = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def extract_job_posting(html: str, url: str) -> dict[str, Any] | None:
    """Return the first schema.org JobPosting found in JSON-LD or microdata."""
    data = extruct.extract(html, base_url=url, syntaxes=["json-ld", "microdata"], uniform=True)
    for item in data.get("json-ld", []) + data.get("microdata", []):
        for candidate in item.get("@graph", [item]):
            types = candidate.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                return candidate
    return None


def extract_text(html: str, url: str) -> str:
    return trafilatura.extract(html, url=url, include_tables=True, favor_recall=True) or ""


def detect_language(text: str) -> str:
    """Return 'de' or 'en' (default 'en' when undecidable)."""
    lang = _detector.detect_language_of(text)
    # lingua returns a new enum object per call, so compare by value, not identity.
    return "de" if lang == Language.GERMAN else "en"


def _is_parent_path(candidate: str, path: str) -> bool:
    """True if ``candidate`` is a strict parent of ``path`` (e.g. a redirect to the job index)."""
    candidate, path = candidate.rstrip("/"), path.rstrip("/")
    return candidate != path and path.startswith(candidate + "/")


async def fetch_listing(url: str, timeout: float = 20.0) -> FetchResult:
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return FetchResult(ok=False, error=f"fetch failed: {exc}")

    original, final = httpx.URL(url), response.url
    if final.host == original.host and _is_parent_path(final.path, original.path):
        return FetchResult(
            ok=False,
            error=f"redirected to {final}; the listing has probably been taken down",
        )

    html = response.text
    posting = extract_job_posting(html, str(response.url))
    text = extract_text(html, str(response.url))
    if posting and posting.get("description"):
        description = extract_text(str(posting["description"]), str(response.url))
        text = description or text

    if len(text) < MIN_TEXT_LENGTH and posting is None:
        return FetchResult(
            ok=False,
            text=text,
            error="page contains too little text (login wall or JavaScript-only page?)",
        )
    return FetchResult(
        ok=True, text=text, job_posting=posting, meta={"final_url": str(response.url)}
    )
