"""The employer's postal address for the cover letter.

The letter uses the DIN 5008 letter layout only with a confirmed address; otherwise it's a
plain document without address blocks. Confirmed means complete (street, postal code, city)
and either taken from the page's schema.org data or found in the listing text: the street
and "postal code city" close together. Claude reads the address in the listing parse (no
extra call); Python decides whether it is confirmed.
"""

from __future__ import annotations

import re
from typing import Any

_POSTAL_CODE = re.compile(r"^\d{4,5}$")  # DE: 5 digits, AT/CH: 4
NEAR = 120  # max. characters between the street and "postal code city" in the text


def _flat(text: str) -> str:
    return " ".join(text.split())


def _complete(street: str, postal_code: str, city: str) -> bool:
    return (
        bool(street and city)
        and bool(_POSTAL_CODE.match(postal_code))
        and any(ch.isdigit() for ch in street)  # a house number
    )


def from_job_posting(posting: dict[str, Any] | None) -> list[str] | None:
    """The address of the hiring organization, or of the only job location."""
    if not posting:
        return None
    org = posting.get("hiringOrganization")
    candidates = [org.get("address")] if isinstance(org, dict) else []
    locations = posting.get("jobLocation")
    locations = locations if isinstance(locations, list) else [locations]
    if len(locations) == 1 and isinstance(locations[0], dict):
        candidates.append(locations[0].get("address"))
    for address in candidates:
        if not isinstance(address, dict):
            continue
        street, postal_code, city = (
            str(address.get(key) or "").strip()
            for key in ("streetAddress", "postalCode", "addressLocality")
        )
        if _complete(street, postal_code, city):
            return [street, f"{postal_code} {city}"]
    return None


def in_text(street: str, postal_code: str, city: str, text: str) -> list[str] | None:
    """Claude's address, if the listing text shows it: street and "postal code city" near
    each other (in either order, as in a footer or an imprint)."""
    street, postal_code, city = (_flat(x) for x in (street, postal_code, city))
    if not _complete(street, postal_code, city):
        return None
    flat = _flat(text).lower()
    street_at = [m.start() for m in re.finditer(re.escape(street.lower()), flat)]
    place = re.escape(postal_code) + r"[ ,]+" + re.escape(city.lower())
    place_at = [m.start() for m in re.finditer(place, flat)]
    if any(abs(s - p) <= NEAR for s in street_at for p in place_at):
        return [street, f"{postal_code} {city}"]
    return None


def confirmed_address(
    street: str, postal_code: str, city: str, text: str, job_posting: dict[str, Any] | None
) -> list[str] | None:
    """Address lines for the letter ("Musterstraße 1", "80331 München"), or None."""
    return from_job_posting(job_posting) or in_text(street, postal_code, city, text)
