"""Registry of job sources."""

from __future__ import annotations

import os

from mappe.search.sources import adzuna, arbeitnow, ba, remote
from mappe.search.sources.base import Source

SOURCES: dict[str, Source] = {
    s.key: s
    for s in (
        ba.SOURCE,
        arbeitnow.SOURCE,
        remote.REMOTIVE_SOURCE,
        remote.JOBICY_SOURCE,
        remote.REMOTEOK_SOURCE,
        adzuna.SOURCE,
    )
}


def missing_env(source: Source) -> list[str]:
    return [name for name in source.needs if not os.environ.get(name)]


__all__ = ["SOURCES", "Source", "missing_env"]
