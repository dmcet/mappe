# application-crew

A local web app that tailors ATS-friendly CVs and cover letters for IT jobs in the German market,
using Claude for reasoning and deterministic Python for everything else.

- Requirements: [docs/requirements.md](docs/requirements.md)
- Architecture: [docs/architecture.md](docs/architecture.md)

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up --build
```

Open http://127.0.0.1:8000. Data (SQLite DB, generated files) lives in the `crew-data` volume.

To explore the UI without an API key, start in demo mode. Claude is not called, and every
CV is parsed as the same sample data:

```bash
APP_DEMO=1 docker compose up --build
# optional: APP_DEMO_DELAY=4 makes every demo "Claude call" take 4 s, so the live status is visible
```

## Test

```bash
docker build --target test -t application-crew:test .
docker run --rm application-crew:test
```

## Local development (optional)

Backend: Python 3.12+, [uv](https://docs.astral.sh/uv/), `typst` and `pdftotext`.
Frontend: Node 24+.

```bash
uv sync
APP_DATA_DIR=./data uv run uvicorn application_crew.web.app:app --reload   # API on :8000
cd frontend && npm install && npm run dev                                 # UI on :5173, proxies /api
uv run pytest && (cd frontend && npm run typecheck && npm test)
```

The database schema is managed with Alembic (`application_crew/migrations/`); migrations
run automatically at startup. To add one, create a new file in `migrations/versions/`.

## Status

The full pipeline works end to end: CV parsing and confirmation, listing fetch and parsing,
requirement checks, matching with an apply decision, authoring of the tailored CV and
cover letter, the review loop (fact check, claims check, ATS check, recruiter review),
final review with an editor, and delivery of named PDFs plus a ZIP of all intermediates.

The UI is a React app (performative-ui components) with a live status indicator for every
running job and an always-visible model-cost meter; CVs and applications can be deleted
(their cost history is kept).

Known gaps:
- No AI repair of Typst errors: content is inserted as plain text, so a failed render
  points to a template bug and is shown as an error instead.
- Edits in the final review are checked by the fact and ATS checks only, not by the
  AI claims check or recruiter.
