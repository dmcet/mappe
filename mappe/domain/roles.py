"""Alternative roles Claude suggests for a confirmed CV (opt-in search titles)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SuggestedRole(BaseModel):
    title: str = Field(description="Job title as German job boards list it, no seniority words")
    title_alt: str = Field(
        description="The same title in the other language (German/English), or empty string"
    )
    reason: str = Field(description="One short English sentence: why this role fits the CV")
    fact_ids: list[str] = Field(description="IDs of the CV facts the suggestion builds on")


class RoleSuggestions(BaseModel):
    roles: list[SuggestedRole]
