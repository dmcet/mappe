"""Small text helpers for job API payloads: HTML to text, salary strings, dates, encoding."""

from __future__ import annotations

import html
import re
from datetime import UTC, date, datetime

_BLOCK = re.compile(r"<\s*(br|/p|/div|/li|/h\d|/tr|/ul|/ol)\b[^>]*>", re.I)
_ITEM = re.compile(r"<\s*li\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]*(?:>|$)")  # also a tag cut off at the end


def html_to_text(markup: str | None) -> str:
    """Readable plain text: block elements become line breaks, list items get a dash."""
    if not markup:
        return ""
    text = re.sub(r"<\s*(script|style)\b.*?</\s*\1\s*>", " ", markup, flags=re.I | re.S)
    text = _ITEM.sub("\n- ", text)
    text = _BLOCK.sub("\n", text)
    text = html.unescape(_TAG.sub(" ", text)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_CURRENCIES = {"$": "USD", "€": "EUR", "£": "GBP", "usd": "USD", "eur": "EUR", "gbp": "GBP"}
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)*)\s*(k)?", re.I)


def _amount(number: str, k: str | None) -> int:
    if k:
        return int(float(number.replace(",", ".")) * 1000)
    return int(re.sub(r"[.,]", "", number))


def parse_salary_text(text: str | None) -> tuple[int | None, int | None, str | None, str | None]:
    """'$3.5k–$5k/month' -> (3500, 5000, 'USD', 'month'); unknown parts are None."""
    if not text or not re.search(r"\d", text):
        return None, None, None, None
    low = text.casefold()
    currency = next((c for s, c in _CURRENCIES.items() if s in low), None)
    period = "month" if re.search(r"month|monat|/mo\b", low) else None
    period = period or ("hour" if re.search(r"hour|stunde|/h(r)?\b", low) else None)
    found = _AMOUNT.findall(text)
    if any(k for _, k in found):  # "€100–140k": the "k" counts for the whole range
        found = [(n, k or ("k" if re.fullmatch(r"\d{2,3}", n) else "")) for n, k in found]
    amounts = [_amount(n, k) for n, k in found]
    amounts = [a for a in amounts if a >= 10]  # drops "/mo" noise, keeps hourly rates
    if not amounts:
        return None, None, currency, period
    return min(amounts), max(amounts), currency, period or "year"


_MOJIBAKE = re.compile(r"[ÂÃâ][\x80-\xbf]")


def fix_mojibake(text: str | None) -> str:
    """UTF-8 that was decoded as Latin-1 once too often ('MÃ¼nchen' -> 'München')."""
    if not text or not _MOJIBAKE.search(text):
        return text or ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text


def parse_date(value: str | int | float | None) -> date | None:
    """ISO strings ('2026-11-02', '2026-11-02T09:42:28+00:00') or a Unix timestamp (also as
    a string of digits)."""
    if value in (None, ""):
        return None
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC).date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
