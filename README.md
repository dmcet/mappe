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
```

## Test

```bash
docker build --target test -t application-crew:test .
docker run --rm application-crew:test
```

## Local development (optional)

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and for rendering `typst` and `pdftotext`.

```bash
uv sync
APP_DATA_DIR=./data uv run uvicorn application_crew.web.app:app --reload
uv run pytest
```

## Status

Scaffold only: the run engine, listing fetch and Typst rendering work; parsing, matching,
authoring, the review loop and the user gates are not implemented yet.
