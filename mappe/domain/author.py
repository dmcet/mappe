"""Author step: Claude-facing output models.

Claude writes content only. Employers, clients, dates, locations, education, certifications
and languages are rendered by Python from the CV, so they can't be changed or invented.
Nesting stays at two levels (document -> bullet -> fact IDs); no optional fields.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AuthorBullet(BaseModel):
    position_id: str = Field(description="ID of the position this bullet belongs to, e.g. 'pos1'")
    text: str
    fact_ids: list[str] = Field(description="IDs of the CV facts this bullet is based on")


class Title(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _from_position_title(cls, value: Any) -> Any:
        # Drafts written before education/certification titles used "position_id".
        if isinstance(value, dict) and "id" not in value and "position_id" in value:
            return {"id": value["position_id"], "title": value.get("title", "")}
        return value

    id: str = Field(
        description="A position ('pos1'), education ('edu1') or certification ('cert1') ID"
    )
    title: str = Field(
        description="Job title, degree or certification name in the document language"
    )


class SkillGroup(BaseModel):
    category: str
    skills: list[str] = Field(description="Skill names exactly as they appear in the CV")


class AuthorCV(BaseModel):
    profile: str = Field(description="2-3 sentences: target role, years of experience, top skills")
    profile_fact_ids: list[str]
    titles: list[Title] = Field(
        description="One entry per position, education entry and certification, in CV order"
    )
    bullets: list[AuthorBullet] = Field(description="Grouped by position, most relevant first")
    skill_groups: list[SkillGroup]
    extra: list[AuthorBullet] = Field(
        description="Relevant projects, publications or volunteering; position_id is the fact ID"
    )


class BulletChange(BaseModel):
    action: Literal["add", "replace", "delete"]
    item: str = Field(
        description="replace/delete: label of the previous item ('B3', 'E1'); add: ''"
    )
    after: str = Field(
        description="add in a rework: label of the previous item to insert after ('B2'); "
        "'' puts it first in its position. Otherwise ''"
    )
    position_id: str = Field(description="As in AuthorBullet; '' for delete")
    text: str = Field(description="'' for delete")
    fact_ids: list[str] = Field(description="CV facts this bullet is based on; [] for delete")


class AuthorCVDraft(BaseModel):
    """What Claude returns for the CV: the full first draft, or only the changes of a rework.

    A rework repeats nothing that stays the same, which keeps the (Opus) output small.
    :func:`apply_draft` turns it into an :class:`AuthorCV`; the fact check runs on that result.
    """

    profile: str = Field(description="Rework: '' keeps the previous profile")
    profile_fact_ids: list[str]
    titles: list[Title] = Field(
        description="First draft: one per position, education entry and certification, in CV "
        "order. Rework: only changed titles"
    )
    bullets: list[BulletChange] = Field(
        description="First draft: every bullet as 'add', grouped by position, most relevant "
        "first. Rework: only the changes"
    )
    skill_groups: list[SkillGroup] = Field(
        description="Rework: [] keeps the previous skills section, otherwise the complete new one"
    )
    extra: list[BulletChange] = Field(
        description="Projects, publications or volunteering; position_id is the fact ID"
    )


def _bullet(change: BulletChange) -> AuthorBullet:
    return AuthorBullet(position_id=change.position_id, text=change.text, fact_ids=change.fact_ids)


def _apply_changes(
    previous: list[AuthorBullet], changes: list[BulletChange], prefix: str
) -> list[AuthorBullet]:
    """Apply bullet changes that refer to the previous items by label (B1, B2, ... / E1, ...).

    Unknown labels are tolerated: a replace becomes an add, a delete is ignored. Adding an
    item that is already there (same position and text) does nothing.
    """
    labels = [f"{prefix}{n}" for n in range(1, len(previous) + 1)]
    current: dict[str, AuthorBullet | None] = dict(zip(labels, previous, strict=True))
    after: dict[str, list[AuthorBullet]] = {}
    first: dict[str, list[AuthorBullet]] = {}
    appended: list[AuthorBullet] = []
    positions = {b.position_id for b in previous}

    for change in changes:
        if change.action == "delete":
            if change.item in current:
                current[change.item] = None
            continue
        new = _bullet(change)
        if change.action == "replace" and change.item in current:
            current[change.item] = new
            continue
        if any(b == new for b in current.values()):
            continue
        if change.after in current:
            after.setdefault(change.after, []).append(new)
        elif change.position_id in positions:
            first.setdefault(change.position_id, []).append(new)
        else:
            appended.append(new)

    result: list[AuthorBullet] = []
    for label, original in zip(labels, previous, strict=True):
        result += first.pop(original.position_id, [])
        if (item := current[label]) is not None:
            result.append(item)
        result += after.get(label, [])
    return result + appended


def apply_draft(previous: AuthorCV | None, draft: AuthorCVDraft) -> AuthorCV:
    """The CV content after ``draft``: a first draft as is, a rework applied to ``previous``."""
    if previous is None:
        previous = AuthorCV(
            profile="", profile_fact_ids=[], titles=[], bullets=[], skill_groups=[], extra=[]
        )
    titles = {t.id: t for t in previous.titles} | {t.id: t for t in draft.titles}
    return AuthorCV(
        profile=draft.profile or previous.profile,
        profile_fact_ids=draft.profile_fact_ids if draft.profile else previous.profile_fact_ids,
        titles=list(titles.values()),
        bullets=_apply_changes(previous.bullets, draft.bullets, "B"),
        skill_groups=draft.skill_groups or previous.skill_groups,
        extra=_apply_changes(previous.extra, draft.extra, "E"),
    )


def full_draft(doc: AuthorCV) -> AuthorCVDraft:
    """``doc`` as a first draft (demo answers and tests)."""

    def adds(items: list[AuthorBullet]) -> list[BulletChange]:
        return [BulletChange(action="add", item="", after="", **b.model_dump()) for b in items]

    return AuthorCVDraft(
        profile=doc.profile,
        profile_fact_ids=doc.profile_fact_ids,
        titles=doc.titles,
        bullets=adds(doc.bullets),
        skill_groups=doc.skill_groups,
        extra=adds(doc.extra),
    )


def render_for_rework(doc: AuthorCV) -> str:
    """The previous CV draft with item labels, shorter than its JSON."""

    def items(prefix: str, bullets: list[AuthorBullet]) -> list[str]:
        return [
            f"{prefix}{n} ({b.position_id}) [{', '.join(b.fact_ids)}]: {b.text}"
            for n, b in enumerate(bullets, 1)
        ] or ["(none)"]

    return "\n".join(
        [
            f"Profile [{', '.join(doc.profile_fact_ids)}]: {doc.profile}",
            "Titles: " + "; ".join(f"{t.id}: {t.title}" for t in doc.titles),
            "Bullets:",
            *items("B", doc.bullets),
            "Skills: "
            + " | ".join(f"{g.category}: {', '.join(g.skills)}" for g in doc.skill_groups),
            "Additional experience:",
            *items("E", doc.extra),
        ]
    )


class LetterParagraph(BaseModel):
    text: str
    fact_ids: list[str] = Field(description="CV facts this paragraph refers to; empty if none")


class AuthorLetter(BaseModel):
    subject: str
    paragraphs: list[LetterParagraph] = Field(
        description="Body only: no salutation, no closing formula, no signature"
    )
