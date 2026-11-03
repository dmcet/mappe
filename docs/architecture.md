# Application Crew — Architecture

Companion to [requirements.md](requirements.md). This document records the technical decisions and their rationale.

## 1. Decisions

| # | Topic | Decision | Rationale |
|---|---|---|---|
| D1 | Orchestration | **Plain Python state machine + Anthropic Python SDK.** No CrewAI/LangGraph. | The workflow is a fixed pipeline with user gates and bounded loops. Control flow belongs in code; Claude only fills individual steps. A framework would add a dependency, version churn and debugging indirection without solving the hard part (pause/resume across restarts), which we need to persist ourselves anyway. |
| D2 | Deployment | Local, single-user, one Docker container, one mounted volume | No auth, no multi-tenancy. GDPR scope is limited to data sent to the Anthropic API. |
| D3 | Persistence | SQLite (via SQLModel) + files on the volume | A single file DB is enough for one user; survives container rebuilds. |
| D4 | Web UI | React + TypeScript (Vite) SPA with performative-ui (MIT), served by FastAPI; JSON API under `/api`, one SSE stream (`/api/stream`) for live status, costs and change notifications | A live status indicator and an always-visible cost meter need a real client; the SSE stream avoids polling. The frontend is built in a Node stage of the Docker build, so the container stays self-contained. |
| D10 | Migrations | Alembic, run at startup; databases from before migrations are stamped at the baseline revision | Schema changes no longer need a fresh volume. |
| D11 | Cost tracking | Usage ledger: one row per Claude call (model, step, tokens, cost), kept when runs or CVs are deleted | Exact cost per model, step, run and day; the header shows today's and total spend. |
| D5 | Rendering | **Typst**; CV via RenderCV-based single-column template, cover letter via a DIN 5008 Typst template | Small image, fast compiles, readable errors, ATS-friendly single-column layouts. |
| D6 | LLM output | Claude produces **content** as flat Pydantic models (`client.messages.parse()` structured outputs), never markup | No syntax/escaping errors; deterministic checks on fixed structure. |
| D7 | Listing fetch | `httpx` → JSON-LD `JobPosting` (`extruct`) → `trafilatura` main text → paste fallback in UI | Covers career pages/ATS portals (Personio, Greenhouse, Workday, ...) cheaply; no headless browser in v1. Playwright can be added later if needed. |
| D8 | Fact safety | Source fact IDs + deterministic fact check after every author iteration | Main defense against invented content. |
| D9 | Loops | One combined review loop, max. 4 iterations, rubric scoring, early stop, best version kept | Quality plateaus after ~3 passes; more iterations increase cost and drift. |

## 2. Component overview

```
┌──────────────────────────── Docker container ────────────────────────────┐
│                                                                          │
│  React SPA (frontend/dist, built with Vite)                               │
│  FastAPI app                                                             │
│   ├── web/        JSON API (/api), SSE stream, downloads, SPA fallback   │
│   ├── runner/     run queue (asyncio, 2 workers), state machine,         │
│   │               activity registry (what each job is doing right now)   │
│   ├── migrations/ Alembic migrations                                     │
│   ├── steps/      one module per pipeline step (pure functions of state) │
│   ├── llm/        Anthropic client wrapper, prompts, usage/cost tracking │
│   ├── domain/     Pydantic models (CV, Listing, Match, Draft, Reports)   │
│   ├── checks/     fact check, ATS rules, requirement checks              │
│   ├── render/     Typst templates + compile wrapper                      │
│   └── fetch/      HTTP fetch, JSON-LD, text extraction, language detect  │
│                                                                          │
│  Binaries: typst, pdftotext (poppler-utils)                              │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │ volume: /data (app.db, runs/<id>/...)
```

## 3. Run state machine

Each run (one job listing) is a row with a `status` and a JSON state blob. Every step reads the state, does its work, writes results + intermediates, and sets the next status. Steps are idempotent, so on startup the runner re-queues every run that was in a working status.

```
created
  → fetching_listing ──(fetch failed)──→ waiting_for_listing_text [user gate]
  → parsing_listing
  → checking_requirements ──(must-have failed)──→ stopped_by_requirements [user may override]
  → matching
  → waiting_for_apply_decision [user gate]          ──(user declines)──→ declined
  → authoring ⇄ reviewing   (fact check → render → ATS → recruiter; ≤ 4 iterations)
  → waiting_for_final_review [user gate]
  → delivering
  → done
(any) → failed   (error stored, step can be retried from the UI)
```

CV parsing is a separate, per-CV flow (`parsing → waiting_for_confirmation → confirmed`); runs can only be created with a confirmed CV.

**Live status:** steps emit events (`step_started`, `step_progress`, `iteration_result`, `step_finished`, `usage`) into an `events` table; the SSE endpoint streams them to the browser.

## 4. Steps: Python vs. Claude

All steps default to `claude-opus-5-5`; effort is set explicitly per step (Opus 5.5's default is `medium`). Model and effort are configurable per step in `config.toml`, so cheaper models (e.g. `claude-haiku-5-5` for parsing) can be tried once a small eval set exists — measure first, then switch.

| Step | Python | Claude | Effort |
|---|---|---|---|
| Parse CV | Markdown pre-split into sections, completeness check, fact ID assignment | Extract fields into `ParsedCV` | `low` |
| Fetch listing | HTTP, JSON-LD, text extraction, language detection (`lingua`) | — | — |
| Parse listing | Map JSON-LD fields directly when present | Extract remaining fields into `ParsedListing` | `low` |
| Requirements | Must-have / nice-to-have checks (salary, onsite days, remote, location keywords) | Fuzzy items only (e.g. "benefit X mentioned?") folded into listing parse | — |
| Match | Skill normalization + overlap, years of experience per skill | Transferable skills, verdict, score, highlight points | `high` |
| Author | Assemble input (CV facts with IDs, listing, highlights, feedback) | Write `CVContent` / `CoverLetterContent` with source IDs | `high` |
| Fact check | Source-ID validation, number/date/skill presence | — | — |
| Render | Content → Typst → PDF | — | — |
| ATS check | `pdftotext`, section/contact detection, keyword coverage, rule checks | Natural keyword use judgment | `low` |
| Recruiter review | Rubric aggregation, threshold, stop criteria | Score rubric criteria + concrete feedback | `medium` |
| Deliver | Final render, file naming, packaging | Repair fallback only if Typst fails | `low` |

**API usage notes**
- Structured outputs: `client.messages.parse()` with a Pydantic model (validated against the schema by the SDK); models stay flat (lists of strings, ≤ 2 levels).
- Streaming for author calls (long outputs), using `.get_final_message()`.
- Prompt caching: system prompt + source CV + listing form a stable prefix across the review loop; per-iteration feedback goes after the last cache breakpoint. Verify via `usage.cache_read_input_tokens`.
- Check `stop_reason` (`refusal`, `max_tokens`) before reading content; retries handled by the SDK (`max_retries`).
- Usage per call is stored and aggregated per run; an optional per-run cost limit stops the loop and keeps the best version.

## 5. Domain models (sketch)

```python
class Fact(BaseModel):          # every CV fact has a stable ID, e.g. "pos2.ach3"
    id: str
    text: str

class Position(BaseModel):
    id: str
    company: str
    role: str
    location: str | None
    start: str                   # "YYYY-MM"
    end: str | None              # None = present
    responsibilities: list[Fact]
    achievements: list[Fact]
    technologies: list[str]

class ParsedListing(BaseModel):
    company: str | None
    domain: str | None
    language: str                # set by Python, not Claude
    responsibilities: list[str]
    required_skills: list[str]
    nice_to_have_skills: list[str]
    location: str | None
    remote: str | None           # "remote" | "hybrid" | "onsite"
    onsite_days_per_week: int | None
    salary_min: int | None
    salary_max: int | None
    benefits: list[str]
    cover_letter_requested: bool

class Bullet(BaseModel):         # author output
    text: str
    source_ids: list[str]
```

## 6. Fact check rules

1. Every `Bullet.source_ids` is non-empty and refers to existing fact IDs.
2. Every number/percentage/year in the output (regex) appears in the referenced source facts or position metadata.
3. Every skill listed in the output exists in the source CV (after normalization).
4. Employer names, titles and dates match the source exactly.

Translation (English CV → German listing) is allowed; rules 2–4 work on numbers, normalized skills and metadata, which are language-independent.

## 7. Skill normalization

- v1: curated synonym file (`k8s → Kubernetes`, `JS → JavaScript`, ...) + `rapidfuzz` for near matches
- v2: ESCO skills taxonomy (EU, English + German labels) shipped as a data file in the image

## 8. Project layout

```
application_crew/
  web/ runner/ steps/ llm/ domain/ checks/ render/ fetch/
  templates/          # Jinja2 (UI)
  typst/              # CV + cover letter templates (open source, licenses kept)
  prompts/            # one prompt file per Claude step
tests/
  fixtures/           # sample CVs and listings (EN + DE)
docs/
Dockerfile
pyproject.toml
config.toml
```

## 9. Docker

- Base: `python:3.12-slim`
- Adds: `typst` binary (pinned version), `poppler-utils`, fonts used by the templates
- Runtime: `ANTHROPIC_API_KEY` via env, `/data` volume, port 8000
- Image size: ~1.1 GB, accepted. Most of it is `lingua` (~300 MB), kept for reliable language detection

## 10. Open points / risks

- **Template licenses:** verify the licenses of the chosen RenderCV theme and DIN 5008 Typst template before vendoring them.
- **Fetch coverage:** measure how many real listings from the user's target sources work via HTTP fetch; add Playwright only if the paste fallback is used too often.
- **Eval set:** collect ~10 CV/listing pairs (EN + DE) early to tune prompts, effort levels and the recruiter rubric threshold.
