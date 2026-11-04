"""Configuration: config.toml merged with environment overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


@dataclass(frozen=True)
class StepLLMConfig:
    model: str
    effort: str
    max_tokens: int


@dataclass(frozen=True)
class ReviewConfig:
    max_iterations: int = 4
    stop_after_no_improvement: int = 2
    recruiter_pass_score: float = 3.5
    cost_limit_usd: float = 2.0


@dataclass(frozen=True)
class SearchConfig:
    sources: tuple[str, ...] = ("ba", "arbeitnow", "remotive", "jobicy", "adzuna")
    max_results_per_source: int = 100
    max_age_days: int = 30
    radius_km: int = 30
    timeout_seconds: float = 20.0
    cache_minutes: int = 60
    list_pages: int = 3  # for sources without search (Arbeitnow): newest N pages
    min_score: float = 30.0  # hits below are hidden behind "show low matches"
    semantic: bool = True  # local embedding model (no API calls); off = keywords only
    semantic_model: str = "jinaai/jina-embeddings-v2-base-de"
    semantic_max_listings: int = 200  # best keyword candidates embedded per search
    semantic_chars: int = 800  # of each description; longer is slower, barely better


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_concurrent_runs: int
    review: ReviewConfig
    llm_default: StepLLMConfig
    llm_steps: dict[str, StepLLMConfig] = field(default_factory=dict)
    search: SearchConfig = field(default_factory=SearchConfig)
    demo: bool = False  # canned Claude responses, no API calls (APP_DEMO=1)
    demo_delay_s: float = 0.0  # pause per demo "Claude call" (APP_DEMO_DELAY), to see the status

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def llm_for(self, step: str) -> StepLLMConfig:
        return self.llm_steps.get(step, self.llm_default)


def load_settings(path: Path | None = None) -> Settings:
    path = Path(os.environ.get("APP_CONFIG", path or DEFAULT_CONFIG_PATH))
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    app = raw.get("app", {})
    data_dir = Path(os.environ.get("APP_DATA_DIR", app.get("data_dir", "/data")))

    llm = raw.get("llm", {})
    default_raw = {"model": "claude-opus-5-5", "effort": "medium", "max_tokens": 16000}
    default_raw |= llm.get("default", {})
    llm_default = StepLLMConfig(**default_raw)
    llm_steps = {
        name: StepLLMConfig(**(default_raw | overrides))
        for name, overrides in llm.get("steps", {}).items()
    }

    search_raw = dict(raw.get("search", {}))
    if "sources" in search_raw:
        search_raw["sources"] = tuple(search_raw["sources"])

    return Settings(
        data_dir=data_dir,
        max_concurrent_runs=int(app.get("max_concurrent_runs", 2)),
        review=ReviewConfig(**raw.get("review", {})),
        llm_default=llm_default,
        llm_steps=llm_steps,
        search=SearchConfig(**search_raw),
        demo=os.environ.get("APP_DEMO", "").strip().lower() in {"1", "true", "yes"},
        demo_delay_s=float(os.environ.get("APP_DEMO_DELAY", "0") or 0),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
