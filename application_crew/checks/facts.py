"""Deterministic fact check of author output against the CV.

Violations go back to the author for rework; warnings are shown to the user.

Rules:
1. Every bullet cites at least one fact, and only facts of its own position.
2. Every number in a bullet appears in the facts it cites. Profile and cover letter may use
   numbers from anywhere in the CV, and the years of experience computed by Python.
3. Every listed skill exists in the CV (skills section or a position's technologies).
4. Single-word listing skills the CV doesn't have must not be mentioned anywhere
   (multi-word terms are left to the claims check, which can judge paraphrases).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from application_crew.checks.skills import SkillAnalysis, skill_variants
from application_crew.domain.author import AuthorBullet, AuthorCV, AuthorLetter
from application_crew.domain.match import fact_ids
from application_crew.domain.models import ParsedCV, Position

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
MAX_BULLETS = 5


@dataclass
class FactReport:
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER_RE.findall(text)}


def _fact_texts(cv: ParsedCV) -> dict[str, str]:
    texts: dict[str, str] = {}
    for p in cv.positions:
        texts[p.id] = f"{p.role} {p.company} {p.client or ''}"
        for f in p.responsibilities + p.achievements:
            texts[f.id] = f.text
    for e in cv.education:
        texts[e.id] = f"{e.qualification} {e.institution}"
    for c in cv.certifications:
        texts[c.id] = f"{c.name} {c.issuer or ''} {c.year or ''}"
    for f in cv.projects + cv.publications + cv.volunteering:
        texts[f.id] = f.text
    return texts


def _cv_skill_forms(cv: ParsedCV) -> set[str]:
    forms: set[str] = set()
    for s in cv.skills:
        forms.update(skill_variants(s.name))
    for p in cv.positions:
        for t in p.technologies:
            forms.update(skill_variants(t))
    return forms


def _skill_name_numbers(cv: ParsedCV) -> set[str]:
    """Numbers that are part of skill names ("Dagger 2", "Java 17") are not claims."""
    names = [s.name for s in cv.skills] + [t for p in cv.positions for t in p.technologies]
    return set().union(*(_numbers(n) for n in names)) if names else set()


def _experience_numbers(analysis: SkillAnalysis) -> set[str]:
    """Any whole number of years up to the computed experience ("10+ Jahre", "über 5 Jahre")."""
    top = int(analysis.total_years)
    for c in analysis.coverage:
        top = max(top, int(c.years))
    return {str(n) for n in range(1, top + 1)}


def _belongs(fact_id: str, position: Position) -> bool:
    return fact_id == position.id or fact_id.startswith(position.id + ".")


def _mentions(term: str, text: str) -> bool:
    return bool(re.search(rf"(?<![\w#+]){re.escape(term.casefold())}(?![\w#+])", text.casefold()))


class FactChecker:
    def __init__(self, cv: ParsedCV, analysis: SkillAnalysis) -> None:
        self.cv = cv
        self.texts = _fact_texts(cv)
        self.known = fact_ids(cv)
        self.positions = {p.id: p for p in cv.positions}
        self.skill_forms = _cv_skill_forms(cv)
        self.free_numbers = _skill_name_numbers(cv)
        all_fact_numbers = set().union(*(_numbers(t) for t in self.texts.values()))
        for extra in (cv.notice_period, cv.earliest_start, cv.salary_expectation):
            all_fact_numbers |= _numbers(extra or "")
        self.global_numbers = all_fact_numbers | self.free_numbers | _experience_numbers(analysis)
        cv_text = " ".join(self.texts.values())
        # Missing listing skills that the CV text doesn't mention under the same name either.
        # Single-word names (Kafka, Dagger, NodeJS) are banned outright. Multi-word terms
        # ("AI agents", "Background Services") may be described in other words or another
        # language, so the claims check judges them instead.
        missing = list(
            dict.fromkeys(
                c.skill
                for c in analysis.coverage
                if c.coverage == "missing" and not _mentions(c.skill, cv_text)
            )
        )
        self.forbidden = [s for s in missing if len(s.split()) == 1]
        self.unverified_terms = [s for s in missing if len(s.split()) > 1]

    # --- shared rules ---

    def _check_numbers(self, text: str, allowed: set[str], where: str, report: FactReport):
        unknown = sorted(_numbers(text) - allowed)
        if unknown:
            report.violations.append(
                f"{where}: the number(s) {', '.join(unknown)} don't appear in the cited CV facts. "
                "Use only numbers from the CV."
            )

    def _check_forbidden(self, text: str, where: str, report: FactReport):
        for skill in self.forbidden:
            if _mentions(skill, text):
                report.violations.append(
                    f"{where}: mentions '{skill}', which the CV doesn't contain. Remove it."
                )

    def _check_ids(self, ids: list[str], where: str, report: FactReport) -> list[str]:
        unknown = [i for i in ids if i not in self.known]
        if unknown:
            report.violations.append(f"{where}: unknown fact IDs {unknown}.")
        return [i for i in ids if i in self.known]

    # --- documents ---

    def check_cv(self, doc: AuthorCV) -> FactReport:
        report = FactReport()
        counts: dict[str, int] = dict.fromkeys(self.positions, 0)

        for n, b in enumerate(doc.bullets, 1):
            self._check_bullet(b, n, counts, report)

        for pid, count in counts.items():
            p = self.positions[pid]
            if count == 0:
                report.warnings.append(f"{p.role} at {p.company} has no bullets.")
            elif count > MAX_BULLETS:
                report.violations.append(
                    f"{p.role} at {p.company} has {count} bullets; use at most {MAX_BULLETS}."
                )

        self._check_ids(doc.profile_fact_ids, "Profile", report)
        self._check_numbers(doc.profile, self.global_numbers, "Profile", report)
        self._check_forbidden(doc.profile, "Profile", report)
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", doc.profile.strip()) if s]
        if len(sentences) > 3:
            report.warnings.append(f"Profile has {len(sentences)} sentences; 2-3 are recommended.")

        for group in doc.skill_groups:
            for skill in group.skills:
                if not set(skill_variants(skill)) & self.skill_forms:
                    report.violations.append(
                        f"Skills: '{skill}' is not in the CV. List only skills from the CV."
                    )

        extra_ids = {f.id for f in self.cv.projects + self.cv.publications + self.cv.volunteering}
        for b in doc.extra:
            where = f"Additional experience '{b.text[:50]}'"
            ids = self._check_ids(b.fact_ids, where, report)
            if not ids or not set(ids) <= extra_ids:
                report.violations.append(
                    f"{where}: must cite project/publication/volunteering IDs."
                )
            cited = set().union(*(_numbers(self.texts[i]) for i in ids)) if ids else set()
            self._check_numbers(b.text, cited | self.free_numbers, where, report)
            self._check_forbidden(b.text, where, report)
        return report

    def _check_bullet(self, b: AuthorBullet, n: int, counts: dict[str, int], report: FactReport):
        where = f"Bullet {n} ('{b.text[:50]}')"
        position = self.positions.get(b.position_id)
        if position is None:
            report.violations.append(f"{where}: unknown position '{b.position_id}'.")
            return
        counts[position.id] += 1
        if not b.fact_ids:
            report.violations.append(f"{where}: cites no CV facts.")
            return
        ids = self._check_ids(b.fact_ids, where, report)
        foreign = [i for i in ids if not _belongs(i, position)]
        if foreign:
            report.violations.append(
                f"{where}: cites {foreign}, which belong to another position than {position.id}."
            )
        cited = set().union(*(_numbers(self.texts[i]) for i in ids)) if ids else set()
        self._check_numbers(b.text, cited | self.free_numbers, where, report)
        self._check_forbidden(b.text, where, report)

    def check_letter(self, letter: AuthorLetter) -> FactReport:
        report = FactReport()
        for n, p in enumerate(letter.paragraphs, 1):
            where = f"Cover letter paragraph {n}"
            self._check_ids(p.fact_ids, where, report)
            self._check_numbers(p.text, self.global_numbers, where, report)
            self._check_forbidden(p.text, where, report)
        self._check_forbidden(letter.subject, "Cover letter subject", report)
        return report
