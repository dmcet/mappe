"""ATS check on the text extracted from the rendered PDF (what a simple ATS parser sees).

Blocking (sent back to the author or a template problem):
- contact data, section headings, employers and dates must be found in the text
- required listing skills that the CV supports must appear in the text
Advisory:
- keyword stuffing: a listing keyword repeated too often
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from mappe.checks.skills import SkillAnalysis, normalize_skill, skill_variants
from mappe.domain.models import ParsedCV

MAX_KEYWORD_REPEATS = 5
MIN_KEYWORD_COVERAGE = 0.8


@dataclass
class ATSReport:
    parse_problems: list[str] = field(default_factory=list)  # template / extraction issues
    keywords_found: list[str] = field(default_factory=list)
    keywords_missing: list[str] = field(default_factory=list)  # supported by the CV, not in text
    stuffing: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        total = len(self.keywords_found) + len(self.keywords_missing)
        return len(self.keywords_found) / total if total else 1.0

    @property
    def passed(self) -> bool:
        return not self.parse_problems and self.coverage >= MIN_KEYWORD_COVERAGE

    def feedback(self) -> list[str]:
        out = [
            f"ATS: the required skill '{k}' is supported by the CV but doesn't appear in the "
            "document. Mention it where it is true."
            for k in self.keywords_missing
        ]
        out += [f"ATS: '{k}' is repeated too often; reduce it." for k in self.stuffing]
        return out

    def to_dict(self) -> dict:
        return asdict(self) | {"coverage": round(self.coverage, 2), "passed": self.passed}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _norm_text(text: str) -> str:
    return f" {normalize_skill(_flat(text))} "


def _count_term(norm: str, term: str) -> int:
    """Whole-word mentions of term in normalized text. Lookarounds instead of counting
    " term ": a counted match must not use up the space the next mention starts with."""
    return len(re.findall(rf"(?<= ){re.escape(term)}(?= )", norm))


def check_ats(pdf_text: str, cv: ParsedCV, analysis: SkillAnalysis, labels: dict) -> ATSReport:
    report = ATSReport()
    flat = _flat(pdf_text)
    norm = _norm_text(pdf_text)

    c = cv.contact
    for what, value in [("name", c.name), ("email", c.email), ("phone number", c.phone)]:
        if value and _flat(value) not in flat:
            report.parse_problems.append(f"The {what} isn't found in the extracted text.")
    for key in ("experience", "skills", "education"):
        if labels[key] not in flat:
            report.parse_problems.append(f"Section heading '{labels[key]}' isn't found.")
    for p in cv.positions:
        if _flat(p.company) not in flat:
            report.parse_problems.append(f"Employer '{p.company}' isn't found.")

    for cov in analysis.coverage:
        if not cov.required or cov.coverage == "missing":
            continue
        forms = {normalize_skill(cov.skill)}
        if cov.cv_skill:
            forms.update(skill_variants(cov.cv_skill))
        if any(f" {f} " in norm for f in forms):
            report.keywords_found.append(cov.skill)
        else:
            report.keywords_missing.append(cov.skill)

    for cov in analysis.coverage:
        term = normalize_skill(cov.skill)
        if len(term) > 2 and _count_term(norm, term) > MAX_KEYWORD_REPEATS:
            report.stuffing.append(cov.skill)
    return report
