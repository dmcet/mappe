"""What a job source is, plus helpers the adapters share."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from mappe.search.models import JobHit, SearchQuery

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

Fetch = Callable[[httpx.AsyncClient, SearchQuery, "SourceOptions"], Awaitable[list[Any]]]
Parse = Callable[[Any], list[JobHit]]


@dataclass(frozen=True)
class SourceOptions:
    cache_minutes: int = 60
    pages: int = 3  # for sources that only list their newest jobs


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    home: str  # credited next to every hit, as the APIs' terms ask
    fetch: Fetch  # one payload per request
    parse: Parse  # one payload -> hits
    remote_only: bool = False
    searches_places: bool = False  # filters by the search's cities itself (with a radius)
    full_text: bool = True  # hits carry the whole listing, so the pipeline needn't fetch it

    def sample(self) -> Any:
        return json.loads((SAMPLES_DIR / f"{self.key}.json").read_text(encoding="utf-8"))


async def get_json(client: httpx.AsyncClient, url: str, **params: Any) -> Any:
    resp = await client.get(url, params={k: v for k, v in params.items() if v is not None})
    resp.raise_for_status()
    return resp.json()


_cache: dict[str, tuple[float, Any]] = {}


async def cached(key: str, minutes: int, load: Callable[[], Awaitable[Any]]) -> Any:
    """For sources without server-side search: the same list serves every search for a while."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < minutes * 60:
        return hit[1]
    value = await load()
    _cache[key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    _cache.clear()


def positive(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
