"""Registry of job sources."""

from __future__ import annotations

from mappe.search.sources import arbeitnow, ba, remote
from mappe.search.sources.base import Source

SOURCES: dict[str, Source] = {
    s.key: s
    for s in (
        ba.SOURCE,
        arbeitnow.SOURCE,
        remote.REMOTIVE_SOURCE,
        remote.JOBICY_SOURCE,
        remote.REMOTEOK_SOURCE,
    )
}

__all__ = ["SOURCES", "Source"]
