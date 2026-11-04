# Mappe

Named after the *Bewerbungsmappe*, the German application folder.

A local web app that turns your master CV and a job listing into a tailored, ATS-friendly CV
and cover letter (PDF) for IT jobs in the German market. Claude does the reasoning (reading,
assessing, writing, reviewing); deterministic Python does everything else (fetching, skill
matching, fact checks, ATS checks, rendering). Every statement in the generated documents is
traced back to your CV.

- Requirements: [docs/requirements.md](docs/requirements.md)
- Architecture: [docs/architecture.md](docs/architecture.md)

## Requirements

- Docker with Compose (Docker Desktop on macOS/Windows)
- An Anthropic API key (not needed for [demo mode](#demo-mode))

Everything else (Python, Node, Typst, the PDF tools and fonts) is inside the image.

## Build and start

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up -d --build
```

Open **http://127.0.0.1:8000**. The app listens on localhost only.

- The first build takes a few minutes; it also type-checks and tests the frontend.
- The database schema is migrated automatically at startup.
- All data lives in the Docker volume `mappe_data` and survives rebuilds.

Useful commands:

```bash
docker compose logs -f app        # follow the logs
docker compose down               # stop (data is kept)
docker compose up -d --build      # rebuild after pulling changes
```

### Demo mode

To explore the UI without an API key and without costs, start in demo mode. Claude is not
called; every CV and listing is parsed as the same sample data (a yellow banner says so).
The job search uses recorded sample responses instead of the live job APIs.

```bash
APP_DEMO=1 APP_DEMO_DELAY=4 docker compose up -d --build
```

`APP_DEMO_DELAY` (seconds) makes every sample "Claude call" take a while, so you can watch
the live status. Leave it out for instant answers.

## Using the app

### 1. Add your CV (once)

**CVs → Add a CV**: give it a label and paste your CV as Markdown. Claude extracts every
position, bullet, skill (with the level you state, e.g. "Fortgeschritten"), language,
certification and degree. Then check the result:

- **Warnings** list missing or unclear information (no phone number, a position without
  location, a language level that isn't CEFR, ...).
- **Quick fixes** fill in contact details, notice period, earliest start and similar fields.
- Anything else: edit the Markdown and **Save and parse again**.
- **Confirm CV** (or "Confirm anyway"). Only confirmed CVs can be used for applications.
- After confirmation, Claude suggests **other roles to consider** in the background: a
  realistic next step or a neighbouring field (e.g. "Platform Engineer" for a backend
  developer with a Kubernetes certificate). Each one names the CV facts it builds on;
  suggestions without real facts behind them are dropped. One small call (Sonnet, under a
  cent). **Suggest again** on the CV page asks for new ones.

The extracted data is the only source for everything that follows; nothing outside it is
used.

### 2. Start an application

**Applications → New application**:

- Choose the CV.
- Enter one or more job listing URLs (one per line; each becomes its own application),
  or paste the listing text.
- Set your **requirements**: minimum salary (EUR/year), maximum onsite days (0 = remote),
  acceptable cities, and free-text must-haves and nice-to-haves (e.g. "EGYM Wellpass").
  Mark a requirement as **must-have** to stop early if the listing clearly contradicts it;
  if the listing doesn't mention it, it never fails. The form remembers your last entries.
- **Start**.

### Or: find jobs

**Find jobs** searches free job APIs and ranks the listings against your CV. This step runs
in Python only and costs nothing; Claude is only called for the listings you pick.

- Choose the CV. Job titles are suggested from your headline and recent roles, with German
  and English variants ("Backend Engineer", "Backend-Entwickler"); edit them freely.
  The other roles suggested for your CV are listed below as chips: they are only searched
  when you click one (it adds the title in both languages; click again to remove it).
- The requirements are the same as for an application. Cities are searched with a radius
  (`radius_km`); a must-have hides listings that clearly contradict it.
- Sources: Bundesagentur für Arbeit, Arbeitnow, Remotive, Jobicy, Remote OK (off by default,
  mostly US jobs) and Adzuna (needs a free key, see [Configuration](#configuration)). A source
  that fails is reported and skipped.
- Each listing gets a score from 0 to 100 from skills from your CV found in the listing,
  title fit (against your CV's titles and the titles you searched for), **meaning** and freshness. Meaning comes from a local embedding model in the
  image (German and English, no API calls): it compares your CV with each listing, so a fit
  shows up even when the wording differs. Without the model, keywords decide. Bundesagentur
  listings have no text in the search, so they are scored mostly on the title. The same
  listing from several sources is shown once.
- The first search reads up to 200 listings with the model and takes about half a minute;
  later searches reuse what was read and only read new listings. The progress bar shows
  each source and the ranking step while it runs.
- Hidden, one click away: listings that fail a must-have, onsite jobs outside your cities
  (or abroad), low matches, and listings you dismissed (they stay hidden in later searches).
- **Save search** keeps the titles, requirements and sources. **Run** it again later from
  "Saved searches": listings none of its earlier runs found are marked **new**.
- Tick listings and **Start applications**. Listings with full text skip the download; the
  others are fetched as usual (Bundesagentur: the employer's page when the listing names one,
  otherwise you may be asked to paste the text).

### 3. Follow the progress

The bar under the header shows what is happening right now (for example
"Claude · Checking claims against your CV · 12s · Opus 5.5") and which applications are
waiting for you. Each application page shows the pipeline with the current stage, an
activity log and the model costs of every call.

The application stops where it needs you:

| You see | What to do |
|---|---|
| **Paste the listing** | The page couldn't be fetched (login wall, JavaScript-only page, listing taken down, no answer within `timeout_seconds`), or you clicked **Abort** while it was downloading. Copy the text from the browser and paste it. |
| **A must-have isn't met** | Decide: don't apply, or continue anyway. |
| **Your decision** | Read the assessment: verdict and score, strengths, gaps, transferable skills and the skill coverage table (fact IDs like `pos1.resp2` show the CV bullet on hover). Choose whether a cover letter should be written and click **Apply** or **Don't apply**. |
| **Your final review** | See below. |

### 4. Review loop (automatic)

After you apply, the documents are written and checked, draft by draft:

1. **Fact check**: every bullet cites CV facts of its own position; numbers and skills come
   from your CV; skills you don't have are never mentioned.
2. **Rendering** to PDF.
3. **Claims check**: Claude compares every statement with the facts it cites and flags
   embellishments ("shared" when your CV says "own", "led" when it says "worked in", ...).
4. **ATS check** on the text extracted from the PDF: contact data, headings and employers
   found, required skills you have are visible, no keyword stuffing.
5. **Recruiter review**: scores relevance, keywords, evidence, clarity, seniority and the
   cover letter, and decides whether it would invite you.

Problems go back to the author. The loop stops when everything passes, when the recruiter
score stops improving, at the cost limit, or after 4 drafts; the best clean draft is used.

### 5. Final review and download

On **Your final review** you see all checks of the final draft and can download the PDFs.

- **Edit text** opens an editor with your original CV next to each position. Saving creates
  a new draft that is rendered and checked again (fact and ATS checks only, no AI calls);
  problems are shown as warnings, you decide.
- If a draft still has open problems, a red note says so above the approve button.
- **Approve and finish** produces the final files, named like
  `Lastname_Firstname_CV_Company.pdf` (or `_Lebenslauf_` / `_Anschreiben_` for German
  listings), plus **a ZIP** with all drafts, the parsed CV, the listing and the assessment.

### 6. Export to pass on

Exports are for someone else to read and decide (for example a friend whose CV you used).
The report is a PDF in the Mappe look, with every link working:

- **Find jobs → Export list (PDF)**: the listings as shown (including the hidden groups you
  ticked), with scores, matched skills, an excerpt and a link to each listing.
- **Find jobs → Export with N applications (ZIP)**: one report (the same list, an overview
  of the applications, and per application the assessment, requirement checks, review
  checks, recruiter review, skill coverage and listing), plus the deliverables as separate
  files: each tailored CV and cover letter, exactly as delivered. With several applications,
  each has its own numbered folder. The report's buttons open the files next to it (in
  desktop PDF viewers, after unpacking). Applications still in the final review include
  their current draft, named `..._draft-N.pdf`.
- **Application page → Export ZIP**: the same for a single application: the report, the CV
  and the cover letter.

Exports cost nothing: no Claude calls, only rendering.

### Costs

The header always shows today's and the total model costs. **Costs** breaks them down by
day, model, step and application. A typical application (2 drafts, with cover letter)
costs roughly $0.40–0.70; parsing a CV about $0.10. Each application is capped at
`cost_limit_usd` (default $2) for the review loop.

### Deleting

Applications and CVs have a **Delete** button (a CV with applications deletes them too, after
confirmation). Running applications can't be deleted until they pause. The cost history is
always kept.

## Configuration

`config.toml` sets the model and reasoning effort per step and the review loop limits:

```toml
[review]
max_iterations = 4          # drafts per application
stop_after_no_improvement = 2
recruiter_pass_score = 3.5  # average rubric score (1-5); the recruiter must also invite
cost_limit_usd = 2.0        # per application; 0 = no limit

[llm.steps.author_cv]
model = "claude-opus-5-5"   # optional, defaults to [llm.default]
effort = "medium"           # low | medium | high | xhigh | max
```

Defaults: Opus 5.5 for CV parsing, matching, CV writing and the claims check; Haiku 5.5 for
listing parsing; Sonnet 5.5 for role suggestions, the cover letter and the recruiter review. After changing the
file, rebuild with `docker compose up -d --build`.

The `[fetch]` section limits listing downloads: `timeout_seconds` (default 30) for download
and text extraction together, and `max_mb` (default 5) for the page size. Past either limit,
the application asks for the pasted text.

The `[search]` section sets the job search: default sources, results per source, maximum
listing age, search radius, timeouts, the score below which listings are hidden, and the
semantic ranking (`semantic = false` turns it off). The model is baked into the image at
build time; to use another one, set `semantic_model` and rebuild with
`docker compose build --build-arg SEMANTIC_MODEL=<model>`.

Environment variables:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (required unless `APP_DEMO=1`) |
| `APP_DEMO` | `1` = demo mode with sample data, no API calls |
| `APP_DEMO_DELAY` | seconds per sample "Claude call" in demo mode |
| `APP_DATA_DIR` | data directory (default `/data` in the container) |
| `APP_CONFIG` | path to an alternative `config.toml` |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | optional: enables Adzuna in the job search ([free key](https://developer.adzuna.com/)) |

## Reset

Delete everything (CVs, applications, files, cost history) and start with an empty database:

```bash
docker compose down -v
docker compose up -d --build
```

This can't be undone. To keep the cost history, delete CVs and applications in the UI instead.

## Troubleshooting

- **The page is empty or shows "Frontend not built"**: rebuild with
  `docker compose up -d --build`.
- **"ANTHROPIC_API_KEY is not set" in the logs**: export the key in the same shell before
  `docker compose up`, or use demo mode.
- **A listing always asks for pasted text**: the site blocks automatic fetching or the
  listing is gone (a redirect to the job index is detected). Pasting always works.
- **The live status says "Connecting…"**: the browser lost the event stream; reload the page.

## Tests

```bash
docker build --target test -t mappe:test .   # also runs the frontend checks
docker run --rm mappe:test                    # backend tests
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on every pull request and push to `main`:
ruff lint and format check, then the same Docker test build and backend tests as above.
CI has no API key, so it never calls Claude. Dependabot opens weekly grouped update PRs
for GitHub Actions, Python and npm dependencies.

## Local development (optional)

Backend: Python 3.12+, [uv](https://docs.astral.sh/uv/), `typst` and `pdftotext`.
Frontend: Node 24+.

```bash
uv sync
APP_DATA_DIR=./data uv run uvicorn mappe.web.app:app --reload   # API on :8000
cd frontend && npm install && npm run dev                                 # UI on :5173, proxies /api
uv run pytest && (cd frontend && npm run typecheck && npm test)
```

The database schema is managed with Alembic (`mappe/migrations/`); migrations run
automatically at startup. To add one, create a new file in `migrations/versions/`.

## Known gaps

- No AI repair of Typst errors: content is inserted as plain text, so a failed render
  points to a template bug and is shown as an error instead.
- Edits in the final review are checked by the fact and ATS checks only, not by the AI
  claims check or recruiter.
- The recruiter's pass score was calibrated on Opus; with Sonnet it may need adjusting.
