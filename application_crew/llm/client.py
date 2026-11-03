"""Thin wrapper around the Anthropic SDK.

All Claude calls go through :func:`structured`, which applies the per-step model and
effort from config, caches the stable prefix and returns a validated Pydantic model
together with usage information.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import anthropic
from pydantic import BaseModel
from sqlmodel import Session

from application_crew.config import PROJECT_ROOT, Settings
from application_crew.runner import activity

PROMPTS_DIR = PROJECT_ROOT / "prompts"


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int


@lru_cache
def get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic()


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


async def structured[T: BaseModel](
    settings: Settings,
    step: str,
    output: type[T],
    stable_context: str,
    task: str,
    system_prompt: str | None = None,
) -> tuple[T, Usage]:
    """Call Claude for ``step`` and parse the answer into ``output``.

    ``stable_context`` (source CV, listing, ...) stays identical across loop iterations
    and is cached; ``task`` holds the per-call part (e.g. reviewer feedback).
    """
    if settings.demo:
        import asyncio

        from application_crew.llm.demo import demo_response

        activity.update(f"Claude · {activity.LABELS.get(step, step)} (demo)", model="demo")
        await asyncio.sleep(settings.demo_delay_s)  # so the live status is visible in demo
        return demo_response(step, output), Usage(0, 0, 0, 0)  # type: ignore[return-value]

    cfg = settings.llm_for(step)
    system = system_prompt if system_prompt is not None else load_prompt(step)
    activity.update(f"Claude · {activity.LABELS.get(step, step)}", model=cfg.model)

    response = await get_client().messages.parse(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=[{"type": "text", "text": system}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": stable_context,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": task},
                ],
            }
        ],
        output_config={"effort": cfg.effort},
        output_format=output,
    )

    if response.stop_reason == "refusal":
        raise LLMError(f"{step}: request was declined by the model")
    if response.stop_reason == "max_tokens":
        raise LLMError(f"{step}: output truncated at max_tokens={cfg.max_tokens}")
    if response.parsed_output is None:
        raise LLMError(f"{step}: no parsable output")

    u = response.usage
    usage = Usage(
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_input_tokens=u.cache_read_input_tokens or 0,
        cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
    )
    record_usage(step, cfg.model, usage)
    activity.update("Processing the answer")
    return response.parsed_output, usage


def record_usage(step: str, model: str, usage: Usage) -> None:
    """Write one row to the usage ledger, attributed to the current run or CV."""
    from application_crew.db import Usage as UsageRow
    from application_crew.db import get_engine
    from application_crew.llm.pricing import cost_usd

    job = activity.current()
    row = UsageRow(
        run_id=job[1] if job and job[0] == "run" else None,
        cv_id=job[1] if job and job[0] == "cv" else None,
        step=step,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens,
        cache_write_tokens=usage.cache_creation_input_tokens,
        cost_usd=cost_usd(model, usage),
    )
    with Session(get_engine()) as session:
        session.add(row)
        session.commit()
