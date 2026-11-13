"""The real Claude call path (with a fake SDK client: no network, no key), demo answers, prices."""

from contextlib import contextmanager
from types import SimpleNamespace

import anthropic
import pytest
from pydantic import BaseModel
from sqlmodel import Session, select

from mappe.config import DEFAULT_CONFIG_PATH, load_settings
from mappe.db import Usage as UsageRow
from mappe.db import init_engine
from mappe.domain.author import AuthorCVDraft, AuthorLetter, full_draft
from mappe.domain.extraction import ExtractedCV
from mappe.domain.listing import ExtractedListing
from mappe.domain.match import MatchResult
from mappe.domain.review import ClaimsResult, RecruiterResult
from mappe.domain.roles import RoleSuggestions
from mappe.llm import client, demo
from mappe.llm.client import COMMON_SYSTEM, Block, LLMError, Usage, structured
from mappe.llm.pricing import cost_usd
from mappe.runner import activity


class Answer(BaseModel):
    value: str


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def response(stop_reason="end_turn", parsed=None, cache_read=None, cache_write=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Settings outside demo mode, a fresh DB, and a fake Anthropic client."""
    monkeypatch.delenv("APP_DEMO", raising=False)
    monkeypatch.delenv("APP_CONFIG", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    db = init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    messages = FakeMessages(response(parsed=Answer(value="ok"), cache_read=200, cache_write=None))
    monkeypatch.setattr(client, "get_client", lambda: SimpleNamespace(messages=messages))
    return SimpleNamespace(settings=load_settings(DEFAULT_CONFIG_PATH), db=db, messages=messages)


@contextmanager
def job(kind, job_id):
    """Bind a job to the current task. Ended inside the test: an async test runs in its own
    context, so a fixture teardown couldn't end it and the job would leak into other tests."""
    activity.begin(kind, job_id, f"{kind} {job_id}")
    try:
        yield
    finally:
        activity.end()


def usage_rows(db):
    with Session(db) as session:
        return list(session.exec(select(UsageRow)))


async def test_structured_sends_the_cached_layout_and_records_usage(api):
    blocks = [Block("<cv>x</cv>", cache=True), Block("<listing>y</listing>")]
    with job("run", 7):
        answer, usage = await structured(api.settings, "recruiter", Answer, blocks, "Do it.")
    assert activity.snapshot() == []

    assert answer == Answer(value="ok")
    assert usage == Usage(1000, 500, 200, 0)  # a missing cache count becomes 0
    (call,) = api.messages.calls
    cfg = api.settings.llm_for("recruiter")
    assert call["model"] == cfg.model == "claude-sonnet-5-5"
    assert call["max_tokens"] == cfg.max_tokens
    assert call["output_config"] == {"effort": cfg.effort}
    assert call["output_format"] is Answer
    assert call["system"] == [{"type": "text", "text": COMMON_SYSTEM}]
    content = call["messages"][0]["content"]
    assert content == [
        {"type": "text", "text": "<cv>x</cv>", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "<listing>y</listing>"},
        {"type": "text", "text": "Do it."},
    ]

    (row,) = usage_rows(api.db)
    assert (row.run_id, row.cv_id, row.step, row.model) == (7, None, "recruiter", cfg.model)
    assert (row.input_tokens, row.output_tokens, row.cache_read_tokens) == (1000, 500, 200)
    assert row.cost_usd == pytest.approx(cost_usd(cfg.model, usage))


async def test_usage_is_attributed_to_the_cv_being_parsed(api):
    with job("cv", 3):
        await structured(api.settings, "parse_cv", Answer, [], "Extract.")
    (row,) = usage_rows(api.db)
    assert (row.run_id, row.cv_id, row.model) == (None, 3, "claude-opus-5-5")


async def test_at_most_four_cache_breakpoints_are_sent(api):
    blocks = [Block(f"b{i}", cache=True) for i in range(6)]
    await structured(api.settings, "match", Answer, blocks, "t")
    content = api.messages.calls[0]["messages"][0]["content"]
    assert sum("cache_control" in item for item in content) == 4
    assert "cache_control" not in content[4] and "cache_control" not in content[5]


@pytest.mark.parametrize(
    ("stop_reason", "parsed", "message"),
    [
        ("refusal", Answer(value="x"), "match: request was declined by the model"),
        ("max_tokens", Answer(value="x"), "match: output truncated at max_tokens=16000"),
        ("end_turn", None, "match: no parsable output"),
    ],
)
async def test_unusable_answers_raise_and_are_not_recorded(api, stop_reason, parsed, message):
    api.messages.response = response(stop_reason=stop_reason, parsed=parsed)
    with pytest.raises(LLMError) as exc:
        await structured(api.settings, "match", Answer, [], "t")
    assert str(exc.value) == message
    assert usage_rows(api.db) == []


def test_get_client_builds_one_sdk_client(monkeypatch):
    # The SDK reads the key at construction; a dummy one is never sent anywhere here.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
    client.get_client.cache_clear()
    try:
        first = client.get_client()
        assert isinstance(first, anthropic.AsyncAnthropic)
        assert client.get_client() is first
    finally:
        client.get_client.cache_clear()


@pytest.mark.parametrize(
    ("step", "output", "factory"),
    [
        ("parse_cv", ExtractedCV, demo.demo_cv),
        ("suggest_roles", RoleSuggestions, demo.demo_roles),
        ("parse_listing", ExtractedListing, demo.demo_listing),
        ("match", MatchResult, demo.demo_match),
        ("author_cv", AuthorCVDraft, lambda: full_draft(demo.demo_author_cv())),
        ("author_letter", AuthorLetter, demo.demo_author_letter),
        ("claims_check", ClaimsResult, demo.demo_claims),
        ("recruiter", RecruiterResult, demo.demo_recruiter),
    ],
)
def test_demo_has_an_answer_for_every_step(step, output, factory):
    answer = demo.demo_response(step, output)
    assert isinstance(answer, output)
    assert answer == factory()


@pytest.mark.parametrize(("step", "output"), [("unknown", Answer), ("match", RecruiterResult)])
def test_demo_refuses_unknown_steps_and_schemas(step, output):
    with pytest.raises(NotImplementedError, match=step):
        demo.demo_response(step, output)


def test_unknown_models_cost_nothing_known_ones_use_list_prices():
    usage = Usage(1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert cost_usd("some-future-model", usage) == 0.0
    assert cost_usd("claude-haiku-5-5", usage) == pytest.approx(0.10 + 0.50 + 0.01 + 0.125)
