"""Author step: Claude-facing output models.

Claude writes content only. Employers, clients, dates, locations, education, certifications
and languages are rendered by Python from the CV, so they can't be changed or invented.
Nesting stays at two levels (document -> bullet -> fact IDs); no optional fields.
"""

from __future__ import annotations

from typing import Any

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


class LetterParagraph(BaseModel):
    text: str
    fact_ids: list[str] = Field(description="CV facts this paragraph refers to; empty if none")


class AuthorLetter(BaseModel):
    subject: str
    paragraphs: list[LetterParagraph] = Field(
        description="Body only: no salutation, no closing formula, no signature"
    )
