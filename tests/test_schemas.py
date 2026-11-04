"""Guards for the Claude-facing models.

The API compiles each output schema into a grammar and rejects grammars that are too large
("The compiled grammar is too large"). Optional fields (anyOf with null) were the cause, so
Claude-facing models must not have any.
"""

import json

import pytest
from anthropic.lib._parse._transform import transform_schema
from pydantic import TypeAdapter

from mappe.domain.author import AuthorCV, AuthorLetter
from mappe.domain.extraction import ExtractedCV
from mappe.domain.listing import ExtractedListing
from mappe.domain.match import MatchResult
from mappe.domain.review import ClaimsResult, RecruiterResult


@pytest.mark.parametrize(
    "model",
    [
        ExtractedCV,
        ExtractedListing,
        MatchResult,
        AuthorCV,
        AuthorLetter,
        ClaimsResult,
        RecruiterResult,
    ],
)
def test_claude_facing_models_have_no_optional_fields(model):
    schema = json.dumps(transform_schema(TypeAdapter(model).json_schema()))
    assert "anyOf" not in schema
    assert '"null"' not in schema
