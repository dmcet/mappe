"""Guards for the Claude-facing models.

The API compiles each output schema into a grammar and rejects grammars that are too large
("The compiled grammar is too large"). Optional fields (anyOf with null) were the cause, so
Claude-facing models must not have any.
"""

import json

import pytest
from anthropic.lib._parse._transform import transform_schema
from pydantic import TypeAdapter

from application_crew.domain.extraction import ExtractedCV
from application_crew.domain.listing import ExtractedListing
from application_crew.domain.match import MatchResult


@pytest.mark.parametrize("model", [ExtractedCV, ExtractedListing, MatchResult])
def test_claude_facing_models_have_no_optional_fields(model):
    schema = json.dumps(transform_schema(TypeAdapter(model).json_schema()))
    assert "anyOf" not in schema
    assert '"null"' not in schema
