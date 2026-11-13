"""Hacker News "Ask HN: Who is hiring?": the monthly thread, read through the Algolia HN API.

Each top-level comment is one company's post. By convention its first line reads
``Company | Role | Location | REMOTE/ONSITE | Salary | URL``; that line is split in Python
(no Claude). Only posts in Germany, or remote and open to Germany, are kept.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from mappe.search.models import JobHit, SearchQuery
from mappe.search.places import abroad, open_to_germany
from mappe.search.sources.base import Source, SourceOptions, cached, get_json
from mappe.search.text import html_to_text, parse_date, parse_salary_text

ALGOLIA = "https://hn.algolia.com/api/v1"
THREAD_TITLE = "Ask HN: Who is hiring?"
ITEM_URL = "https://news.ycombinator.com/item?id={}"


async def fetch(client: httpx.AsyncClient, query: SearchQuery, opts: SourceOptions) -> list[Any]:
    async def load() -> list[Any]:
        stories = await get_json(
            client, f"{ALGOLIA}/search_by_date", tags="story,author_whoishiring", hitsPerPage=5
        )
        thread = next(
            (
                s
                for s in stories.get("hits") or []
                if (s.get("title") or "").startswith(THREAD_TITLE)
            ),
            None,
        )
        if thread is None:
            return []
        # One request returns the whole thread with all comments.
        return [await get_json(client, f"{ALGOLIA}/items/{thread['objectID']}")]

    # A new thread starts once a month; the comments still grow for a few days.
    return await cached("hn", opts.cache_minutes, load)


_GERMAN_PLACE = re.compile(
    r"\b(germany|deutschland|berlin|munich|münchen|muenchen|hamburg|frankfurt|cologne|köln|"
    r"koeln|stuttgart|düsseldorf|duesseldorf|dusseldorf|leipzig|dresden|hannover|hanover|"
    r"nuremberg|nürnberg|nuernberg|erlangen|fürth|karlsruhe|heidelberg|mannheim|darmstadt|"
    r"freiburg|bonn|aachen|bremen|essen|dortmund|münster|muenster|potsdam|jena|ulm|"
    r"augsburg|regensburg|ingolstadt|wiesbaden|mainz|kiel|lübeck|rostock|magdeburg)\b",
    re.I,
)
# Parts of the first line that say where: work mode or a region.
_WHERE = re.compile(
    r"\b(remote|onsite|on-site|on site|hybrid|in-office|in office|europe|eu|eea|emea|"
    r"worldwide|anywhere|global|north america|americas|latam|apac)\b",
    re.I,
)
# Remote, but only from somewhere that isn't Germany: "REMOTE (US)", "Remote (Canada only)".
_ONLY_ELSEWHERE = re.compile(
    r"(?<!\w)(us|usa|u\.s\.?|united states|north america|americas|canada|latam|"
    r"south america|brazil|uk|united kingdom|india|apac|asia|japan|tokyo|australia|"
    r"est|pst|cst|nyc|new york|san francisco|sf|bay area|chicago|seattle|boston|austin|"
    r"los angeles|denver|detroit|toronto)(?!\w)",
    re.I,
)
_SALARY = re.compile(r"[$€£]|\b\d+\s?k\b|\b(eur|usd|gbp)\b", re.I)
_URL = re.compile(r"https?://|www\.|\.(com|io|ai|dev|co|de|app|org)\b", re.I)
_NOT_A_ROLE = re.compile(
    r"^(full[- ]?time|part[- ]?time|contract|freelance|intern(ship)?|(no )?visa|equity|"
    r"relocation|series [a-e]|seed|yc [a-z]\d+)\b",
    re.I,
)
_JOB_SEEKER = re.compile(r"^\s*(location:|seeking|looking for work)", re.I)


def _remote_mode(where: str) -> str | None:
    if re.search(r"hybrid|part(ly|ially)? remote", where, re.I):
        return "hybrid"
    if re.search(r"remote", where, re.I):
        return "remote"
    if re.search(r"onsite|on-site|on site|in-office|in office", where, re.I):
        return "onsite"
    return None


def _in_germany_or_open(where: str, mode: str | None) -> bool:
    if _GERMAN_PLACE.search(where):
        return True
    if mode != "remote":
        return False
    # "REMOTE (Europe)", "REMOTE (worldwide)" or plain "REMOTE" (no restriction stated)
    return open_to_germany(where) or not (_ONLY_ELSEWHERE.search(where) or abroad(where))


def parse_post(comment: dict) -> JobHit | None:
    markup = comment.get("text") or ""
    # HN separates paragraphs with a bare "<p>"; the first one is the header line.
    head = html_to_text(markup.split("<p>", 1)[0]).replace("\n", " ")
    if not head or not comment.get("id") or _JOB_SEEKER.match(head):
        return None
    text = html_to_text(markup.replace("<p>", "\n\n"))
    parts = [p.strip() for p in head.split("|") if p.strip()]
    if len(parts) < 3:  # not the "Company | Role | Location" format
        return None
    company = re.sub(r"\s*\(.*?\)\s*$", "", parts[0]).strip() or None
    rest = parts[1:]
    places = [
        p
        for p in rest
        if _WHERE.search(p) or _GERMAN_PLACE.search(p) or abroad(p) or _ONLY_ELSEWHERE.search(p)
    ]
    where = " | ".join(places)
    mode = _remote_mode(where)
    if not where or not _in_germany_or_open(where, mode):
        return None
    roles = [
        p
        for p in rest
        if p not in places
        and not _SALARY.search(p)
        and not _URL.search(p)
        and not _NOT_A_ROLE.match(p)
    ]
    salary = next((p for p in rest if _SALARY.search(p) and re.search(r"\d", p)), None)
    low, high, currency, period = parse_salary_text(salary)
    if currency is None or (low or 0) < 10 or (period == "year" and (low or 0) < 1000):
        low = high = currency = period = None  # "30k users", "0.5-1% equity"
    url = ITEM_URL.format(comment["id"])
    return JobHit(
        source="hn",
        external_id=str(comment["id"]),
        url=url,
        view_url=url,
        title=roles[0] if roles else f"Open roles at {company or 'a startup'}",
        company=company,
        location=where,
        remote=mode,
        salary_min=low,
        salary_max=high,
        salary_currency=currency,
        salary_period=period,
        description=text,
        tags=roles[1:],
        posted_at=parse_date(comment.get("created_at")),
    )


def parse(payload: Any) -> list[JobHit]:
    hits = []
    for comment in payload.get("children") or []:
        hit = parse_post(comment) if isinstance(comment, dict) else None
        if hit:
            hits.append(hit)
    return hits


SOURCE = Source(
    key="hn",
    label="Hacker News",
    home="https://news.ycombinator.com/submitted?id=whoishiring",
    fetch=fetch,
    parse=parse,
)
