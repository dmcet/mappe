# CLAUDE.md

Mappe (after the German *Bewerbungsmappe*) is a local, single-user web app that turns a master
CV and a job listing into a tailored, ATS-friendly CV and cover letter (PDF) for IT jobs in
Germany. Claude does the reasoning steps; deterministic Python does everything else.

Read before larger changes:
- `README.md`: usage, configuration, env vars, dev commands
- `docs/requirements.md`: what the app must do
- `docs/architecture.md`: decisions (D1–D14) and their rationale, state machine, fact-check rules
- `docs/job-search-plan.md`: the job search feature

## Stack

- Backend: Python 3.12, FastAPI, SQLModel on SQLite, Alembic, Anthropic SDK (async), httpx,
  trafilatura/extruct, lingua, rapidfuzz, fastembed (local embeddings), pypdf.
- Frontend: React 19 + TypeScript + Vite + `performative-ui`, react-router; tests with Vitest.
- Rendering: Typst (`typst/*.typ`, vendored templates and fonts in `typst/vendor`, `typst/fonts`);
  `pdftotext` (poppler) for ATS checks.
- Runs in one Docker container (`compose.yaml`, project name `mappe`, volume `mappe_data` → `/data`).

## Layout

```
mappe/
  web/        FastAPI JSON API under /api, SSE stream /api/stream, downloads, SPA fallback
  runner/     engine.py (queue + state machine driver), states.py (statuses, transitions), activity.py
  steps/      one module per pipeline step, registered with @step(RunStatus.X)
  llm/        client.py (all Claude calls), demo.py (canned answers), pricing.py
  domain/     Pydantic models: extraction (CV), listing, match, author, review
  checks/     facts, ats, requirements, skills, completeness (all deterministic)
  render/     content → Typst → PDF
  export/     PDF/ZIP exports of searches and applications
  mail/       application email (body, .eml draft); handed to the mail app, never sent
  fetch/      listing fetch: HTTP → JSON-LD → main text → paste fallback
  search/     job APIs (sources/), queries, dedupe, rank, semantic; no Claude calls
  migrations/ Alembic (versions/000N_*.py), run automatically at startup
prompts/      one Markdown prompt per Claude step (name = step name)
frontend/src/ pages/, pages/run/, components/, api.ts, types.ts, live.tsx (SSE)
frontend/e2e/ Playwright tests against the app in demo mode
tests/        pytest; conftest.py provides fake_llm and sample data
config.toml   per-step model/effort, review loop limits, search settings
```

## AI budget: Python first, Claude only when necessary

The AI budget is used carefully (`docs/requirements.md`: "As much work as possible is done in
Python; Claude is only used for reasoning workloads").

- Solve things in Python or by other deterministic means whenever possible. Use Claude only
  for real reasoning that code can't do; when adding a feature, prefer the deterministic
  approach and keep new Claude calls rare, cheap (smallest model/effort that works) and cacheable.
- **Test without real Claude API calls**: pytest with the `fake_llm` fixture, frontend tests,
  and demo mode (`APP_DEMO=1`) for trying the app end to end.
- **Never run anything that calls the real API (a real `ANTHROPIC_API_KEY`, a live run in the
  app) without asking the user first.** If in doubt whether a test needs the real API, ask.

## Core rules (do not break)

- **No agent framework.** The pipeline is a plain Python state machine (D1). Control flow
  lives in code; Claude only fills individual steps.
- **Steps are idempotent** `async (ctx: StepContext) -> RunStatus`. On restart, runs in a
  `WORKING` status are re-executed from that status. New statuses need entries in
  `runner/states.py` (`TRANSITIONS`, `WORKING`/`USER_GATES`) and `STEP_LABELS` in `engine.py`.
- **All Claude calls go through `mappe.llm.client.structured()`**, which applies per-step
  model/effort from `config.toml`, returns a validated Pydantic model and records usage in the
  cost ledger. Claude returns content as flat Pydantic models, never markup (D6).
- **Prompt caching layout matters**: shared blocks (CV, listing) come first and must be
  byte-identical across steps (`steps/common.shared_blocks`); per-call task text goes last.
  Read the `llm/client.py` docstring before changing block order or cache markers.
- **Fact safety**: every generated bullet cites CV fact IDs (e.g. `pos2.resp3`); the fact
  check (`checks/facts.py`) must stay strict. Nothing outside the parsed CV may appear in output.
- **Job search never calls Claude.** Ranking is Python + the local embedding model.
- **Demo mode** (`APP_DEMO=1`): every Claude step needs a canned answer in `llm/demo.py`,
  and job search uses `search/samples/*.json`. Add both when adding a step or a source.
- Schema changes need a new Alembic migration in `mappe/migrations/versions/`.
- Default models: Opus 5.5 (`claude-opus-5-5`) for parsing CV, match, author CV, claims check;
  Haiku 5.5 for listing parsing; Sonnet 5.5 for role suggestions, cover letter and recruiter.
- The cost ledger is kept even when runs or CVs are deleted.

## Commands

Local tooling: `uv` is not on PATH on this machine; use `.venv/bin/...` or Docker.
`typst` is not installed locally (tests that render need Docker).

```bash
docker compose up -d --build                 # build and start on http://127.0.0.1:8000
APP_DEMO=1 docker compose up -d --build      # demo mode, no API key or costs
docker build --target test -t mappe:test . && docker run --rm mappe:test   # full test suite

.venv/bin/pytest                             # backend tests (local)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
cd frontend && npm run typecheck && npm test # frontend checks
cd frontend && npm run e2e                   # Playwright; needs the app in demo mode on :8123 (README: Tests)
```

Tests never call the real API (see "AI budget" above): use the `fake_llm` fixture (set `fake_llm.results[step]`,
a list gives successive answers). Backend coverage must stay at 100% (`fail_under`). Ruff: line length 100, rules E, F, I, UP, B.

## Conventions

- User-facing text (UI, README, docs) is plain, short English; the app targets German listings
  and produces German or English documents depending on the listing language.
- Keep `README.md` and `docs/` in sync when behavior, config or env vars change.
- Commits: short imperative subject ("Add …", "Job search: …"); work on feature branches
  (`feat/…`, `chore/…`), merged into `main` via PR.
- `.idea/` shared settings are committed on purpose; per-machine files are gitignored.

## Dependabot PRs

At the start of each session, check whether the newest commit on `main` is from today:

```bash
git fetch -q origin && [ "$(git log -1 --format=%cd --date=short origin/main)" = "$(date +%F)" ]
```

If it is, we already worked on the project today and most likely did the check: skip it.
If not, check open Dependabot PRs (`gh pr list --author app/dependabot`) and merge the ones
that look logical. Dependabot opens weekly grouped PRs (`.github/dependabot.yml`) for
GitHub Actions, Python (uv) and npm.

- Merge (`gh pr merge <n> --squash --delete-branch`) when CI is green and the update is a
  patch or minor bump without breaking changes in the release notes.
- Don't merge, but tell the user, when: CI fails; a major version changes; the update touches
  something central (Anthropic SDK, FastAPI, SQLModel/SQLAlchemy, Alembic, React, Vite,
  `performative-ui`, Typst); or the release notes mention breaking changes, removals or
  security-relevant behavior changes. Suggest what would be needed (code changes, a test run).
- If a grouped PR mixes safe and risky updates, don't merge it; say which update is the risk.
- Never change code in a Dependabot branch to make it pass; do that on a `chore/…` branch.
