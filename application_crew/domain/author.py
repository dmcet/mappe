"""Author step: Claude-facing output models.

Claude writes content only. Employers, clients, dates, locations, education, certifications
and languages are rendered by Python from the CV, so they can't be changed or invented.
Nesting stays at two levels (document -> bullet -> fact IDs); no optional fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthorBullet(BaseModel):
    position_id: str = Field(description="ID of the position this bullet belongs to, e.g. 'pos1'")
    text: str
    fact_ids: list[str] = Field(description="IDs of the CV facts this bullet is based on")


class PositionTitle(BaseModel):
    position_id: str
    title: str = Field(description="Job title in the document language")


class SkillGroup(BaseModel):
    category: str
    skills: list[str] = Field(description="Skill names exactly as they appear in the CV")


class AuthorCV(BaseModel):
    profile: str = Field(description="2-3 sentences: target role, years of experience, top skills")
    profile_fact_ids: list[str]
    titles: list[PositionTitle] = Field(description="One entry per position, in CV order")
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
