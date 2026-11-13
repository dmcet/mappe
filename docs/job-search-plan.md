# Job search: plan

Find job listings that fit a confirmed CV, rank them without AI costs, and turn the ones the
user picks into applications. Status: phases 1 and 2 implemented; from phase 3 saved searches, live progress and
semantic ranking (scheduled searches are not built).

**Changes during implementation:**
- Titles are chips (the CV's titles, on by default, plus the user's own); places and remote
  come from the requirements form, so there is one place to enter cities. Each city has its
  own radius (`"Nürnberg (30 km), Fürth (10 km)"` in the `location` requirement; without one,
  `radius_km`). A `remote: "no"` requirement excludes fully remote jobs; as a must-have it also
  skips the remote-only sources.
- The search form is stored per CV (`cv.search_prefs`, migration 0007): searched and
  switched-off titles, requirements, switched-off wishes and sources. CV titles that are in
  neither list (new after a CV edit) are searched.
- `RunCreate` is unchanged: `POST /api/searches/{id}/apply` creates the runs itself (URL plus
  text when the source has the full listing).
- New filter "outside your area": onsite/hybrid hits from sources that can't search by place
  (Arbeitnow, the remote boards) are hidden when their location isn't one of the searched
  cities, or, without cities, when it names a place abroad. Bundesagentur and Adzuna search
  around the cities themselves (radius) and are exempt.
- Bundesagentur's `homeofficemoeglich: false` is treated as *unknown*, not onsite: it's often
  just an unticked box, and unknown must never fail a must-have.
- Hits from Bundesagentur use the employer's page (`externeURL`, ~1/3 of hits) as the
  application URL when given; otherwise the BA detail page (likely the paste gate).
- Skill score scales with the CV: full marks at matched weight 6 or 60 % of the CV's total,
  whichever is lower, so short CVs aren't penalised.

## 1. Goals and non-goals

- **Goal:** one search over all free job APIs, driven by the parsed CV and the requirements
  the user already maintains (cities, onsite days, salary).
- **Goal:** search, deduplication, filtering and ranking are deterministic Python. **No Claude
  calls** until the user starts an application from a result.
- **Goal:** chosen results start the existing pipeline unchanged (`POST /api/runs`).
- **Non-goal:** scraping sites that forbid it (LinkedIn, StepStone, Indeed, XING).
- **Non-goal (v1):** scheduled searches and notifications (see phase 3).
- **Non-goal:** per-company job board feeds (Personio, Greenhouse, Lever, Ashby); dropped.

## 2. Sources

All sources were checked on 2026-11-03 unless marked *unverified*.

| Source | Access | Search | What a hit contains | Notes |
|---|---|---|---|---|
| **Bundesagentur für Arbeit** | `GET rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs`, header `X-API-Key: jobboerse-jobsuche` (public key) | Server side: `was`, `wo`, `umkreis`, `arbeitszeit`, `veroeffentlichtseit`, `page`, `size` | Title, employer, address + coordinates, `homeofficemoeglich`, `referenznummer`, dates, occupation. **No description.** | Largest German source. Unofficial API (documented on bund.dev); `v4` now returns 403, `v6` works, so versions can change. |
| **Arbeitnow** | `GET arbeitnow.com/api/job-board-api?page=N`, no key | None: 300 newest jobs per page, filter locally | Title, company, HTML description, tags, `remote`, location, URL, `created_at` | Germany-focused tech jobs. Terms: "please do not abuse", link back. Updated hourly → cache. |
| **Remotive** | `GET remotive.com/api/remote-jobs?search=&category=&limit=` | Server side (keyword, category) | Title, company, HTML description, tags, `candidate_required_location`, salary text | Remote only. Terms forbid republishing to other job sites; local personal use is fine. Keep the link to the original. |
| **Jobicy** | `GET jobicy.com/api/v2/remote-jobs?geo=germany&tag=&count=` | Server side (`geo`, `tag`, `industry`) | Title, company, description, geo, salary when given | Remote only. Must credit Jobicy and link to the original URL. |
| **Remote OK** | `GET remoteok.com/api` (needs a User-Agent) | None, filter locally | Title, company, tags, description, location, salary | Mostly US/worldwide, so it's mostly noise here. Must link back and name Remote OK. Disabled by default. |
| **Adzuna** | `GET api.adzuna.com/v1/api/jobs/de/search/{page}?app_id=&app_key=&what=&where=` | Server side | Title, company, description snippet, location, salary (also estimated) | Free key (registration). Enabled only when `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` are set. *Unverified* (needs a key). |

Every result shows its source and links to the original listing, which covers the attribution
terms above.

## 3. Flow

```
confirmed CV + requirements
  → build queries (Python, editable by the user)
  → query all enabled sources in parallel (httpx, per-source timeout, failures don't stop the search)
  → normalise to JobHit, deduplicate
  → filter by requirements (unknown never fails)
  → rank by CV fit
  → results page: tick listings, dismiss the rest
  → "Start applications" → POST /api/runs (existing pipeline, Claude from here on)
```

### 3.1 Queries from the CV

Built in `search/queries.py` from `ParsedCV`, shown to the user as editable chips before searching:

- **Titles:** the `headline` and the roles of the last two positions, cleaned of seniority words
  and gender suffixes (`(m/w/d)`), plus German/English variants from a small map
  (`Software Engineer ↔ Softwareentwickler`, `Android Developer ↔ Android-Entwickler`, ...).
- **Keywords:** the top skills: level `advanced` first, then the skills used most recently
  (reuse the years-per-skill logic from `checks/skills.py`).
- **Other roles (opt-in):** after the CV is confirmed, one small Claude call (`suggest_roles`,
  Sonnet, low effort) suggests up to 6 roles the person hasn't held but that fit: a realistic
  next step or a neighbouring field. It runs once per confirmed CV, not per search, so the
  search itself still makes no Claude calls. Each suggestion cites CV fact IDs; Python drops
  unknown IDs, suggestions left without any, and titles the CV already yields. They are not
  in the default titles: the search page shows them as chips that add the title (and its
  other-language form) when clicked. A separate call rather than a field of `parse_cv`,
  because that prompt forbids inference, runs before the user corrects the data, and
  couldn't be repeated without parsing again.
- **Places:** cities from the `location` requirement; with `max_onsite_days = 0`, remote sources
  only and no city filter.

Sources with server-side search get `title` queries (BA: `was=<title>`, `wo=<city>`,
`umkreis` from config). Sources without it are fetched once per search and filtered locally.

### 3.2 Normalised model

```python
class JobHit(BaseModel):
    source: str               # "ba" | "arbeitnow" | "remotive" | "jobicy" | "remoteok" | "adzuna"
    external_id: str          # BA referenznummer, Arbeitnow slug, ...
    url: str                  # original listing (BA: jobdetail URL or the employer's external URL)
    title: str
    company: str | None
    location: str | None
    remote: RemoteMode | None # mapped from homeofficemoeglich / remote flags / source type
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    salary_period: SalaryPeriod | None
    description: str          # plain text (HTML stripped); empty for BA
    tags: list[str]
    posted_at: date | None
    language: str             # lingua, as in fetch/listing.py
```

**Deduplication:** same URL, or the same normalised `(company, title, city)`. Matching uses
`normalize_place` and rapidfuzz `token_set_ratio ≥ 92` on the title. Keep the hit with the
longest description and note the other sources on it.

### 3.3 Filtering

Map each `JobHit` to a partial `ParsedListing` and reuse `checks/requirements.py`
(`salary_min`, `max_onsite_days`, `location`). Hits that **fail a must-have** are hidden
behind a "show filtered (n)" toggle, not deleted. `unknown` never filters, as in the pipeline.
`benefit`/`other` requirements are not checked here (they need Claude) and are only checked
once an application runs.

Also filtered: listings older than `max_age_days`, and listings the user dismissed in earlier
searches (remembered by `source + external_id`).

### 3.4 Ranking (no AI)

`score` from 0 to 100, with the reasons shown next to each hit:

| Signal | Weight | How |
|---|---|---|
| Skill overlap | 60 | CV skills found in title + description + tags, via `normalize_skill` / `SYNONYMS` and word-boundary matching. Weighted by level (advanced 1.0, intermediate 0.7, basic 0.4) and recency. Normalised by the number of the CV's top skills. |
| Title fit | 30 | rapidfuzz `token_set_ratio` between the hit title and the CV's headline and recent roles plus the searched titles (and their DE/EN variants), so a chosen alternative role isn't ranked down |
| Freshness | 10 | Linear decay over `max_age_days` |

BA hits have no description, so they score on title, occupation (`hauptberuf`, `alleBerufe`)
and freshness only. Those scores get rescaled and the hit is labelled "title only" so it isn't
ranked unfairly. The hit card shows matched skills, e.g. "Kotlin, Compose, Coroutines (+4)".

Phase 3 option: a local multilingual embedding model (`multilingual-e5-small` via
`sentence-transformers`) for semantic similarity between the CV and the description. This adds
roughly 0.5 GB to the image, which is acceptable per the image-size decision. Add it only if
keyword ranking proves too weak on real searches.

## 4. Persistence

Migration `0003_job_search`:

- `search`: `id`, `cv_id`, `queries` (JSON), `requirements` (JSON), `sources` (JSON: per-source
  count / error / duration), `created_at`.
- `job_hit`: `id`, unique `(source, external_id)`, the `JobHit` fields, `first_seen_at`,
  `last_seen_at`, `status` (`new` | `dismissed` | `applied`), `run_id` (nullable).
- `search_result`: `search_id`, `job_hit_id`, `score`, `reasons` (JSON), `filtered` (bool).

A hit is stored once even when it shows up in many searches. That's what lets the app mark
results as "new since last search" and keep dismissed hits hidden. Searches are deleted with
their CV, but hits linked to runs are kept.

## 5. API

| Endpoint | Purpose |
|---|---|
| `GET /api/search/queries?cv_id=` | Suggested queries for a CV |
| `POST /api/searches` | `{cv_id, queries, requirements, sources}` → runs the search (async, `asyncio.gather`, ~5–15 s), returns the search with ranked results and per-source status |
| `GET /api/searches` / `GET /api/searches/{id}` | History / one search again (no re-query) |
| `POST /api/job-hits/{id}/dismiss` / `.../restore` | Hide or show a hit |
| `POST /api/searches/{id}/apply` | `{job_hit_ids, requirements}` → creates runs, marks hits `applied`, returns the runs |

Runs created from hits that have a description pass **both URL and text**, so the pipeline
skips the fetch and the paste gate. This needs a small change to `RunCreate`: an optional
`listings: [{url, text}]` next to `urls` / `listing_text` (backwards compatible). BA hits pass
only the URL (see open point 1).

Progress over SSE (one event per finished source) is nice to have. v1 shows a spinner and
per-source results when the request returns.

## 6. Frontend

New route `/search` (nav entry "Search"):

1. **Form:** CV select, query chips (suggested, editable), the existing
   `RequirementsEditor` (pre-filled from `/api/runs/requirements/last`), source toggles, and
   "Search".
2. **Per-source status line:** "Bundesagentur 48 · Arbeitnow 12 · Remotive 3 · Jobicy failed (timeout)".
3. **Results list:** score badge, title, company, location / remote, salary if known, posted
   date, source badge + "open original" link, matched skills, a "new" marker, a checkbox and
   a dismiss button. "Show filtered (n)" toggle with the failed requirement as reason.
4. **Sticky footer:** "Start n applications". An estimated cost line is optional.
5. **Search history** on the same page (last searches, reopen without re-querying).

## 7. Code layout

```
mappe/search/
  __init__.py
  models.py        # JobHit, SearchRequest, SourceStatus
  queries.py       # queries from ParsedCV, DE/EN title variants
  sources/
    base.py        # Source protocol: async search(queries, places, client) -> list[JobHit]
    ba.py  arbeitnow.py  remotive.py  jobicy.py  remoteok.py  adzuna.py
  dedupe.py
  rank.py          # filtering (reuses checks/requirements.py) + scoring
  service.py       # orchestrates one search, persists results
mappe/web/search.py        # routes
mappe/migrations/versions/0003_job_search.py
frontend/src/pages/Search.tsx (+ components)
tests/test_search_*.py, tests/fixtures/search/*.json   # recorded API responses
```

Config (`config.toml`):

```toml
[search]
sources = ["ba", "arbeitnow", "remotive", "jobicy", "adzuna"]  # adzuna only with keys
max_results_per_source = 100
max_age_days = 30
radius_km = 30
timeout_seconds = 15
cache_minutes = 60            # for sources without server-side search (Arbeitnow, Remote OK)
```

## 8. Tests

- One test per source adapter against a **recorded response** in `tests/fixtures/search/`,
  using `httpx.MockTransport`. Tests never hit the network.
- Adapter robustness: missing fields, HTML descriptions, salary text parsing
  ("$3.5k–$5k/month", "60.000 – 75.000 €"), non-JSON or error responses → source status `failed`.
- `queries.py`: titles, DE/EN variants, gender suffix removal.
- `dedupe.py`, `rank.py`: overlap with synonyms, title fit, filtering with `unknown`.
- Web: search → apply creates runs with URL + text; dismissed hits stay hidden in the next search.
- Frontend: component test for the results list (selection, dismiss, filtered toggle).
- Demo mode: sources return fixture data when `APP_DEMO=1`, so the page works offline.

## 9. Phases

1. **Core:** models, BA + Arbeitnow adapters, queries, dedupe, filtering, ranking, migration,
   API, Search page, apply → runs. Covers most German listings.
2. **More sources:** Remotive, Jobicy, Remote OK (off by default), Adzuna (with keys).
3. **Later:** saved searches with "new since last time" (done), embeddings ranking (done, see
   below), SSE progress per source (done, via the activity registry), scheduled searches
   (open).

### Semantic ranking (phase 3)

Measured on 227 live listings (Berlin, sample CV), 8-core laptop CPU:

| Model | Size | Time for 227 | Top 10 |
|---|---|---|---|
| `jinaai/jina-embeddings-v2-base-de` (DE/EN) | 0.64 GB | 86 s at 1,500 chars; ~38 s at 800 | all backend / platform roles |
| `minishlab/potion-multilingual-128M` (static) | 0.5 GB | 0.1 s | some noise (e.g. "System Engineer (Token Factory)") |

Chosen: Jina, at 800 characters (vectors 97 % identical to 1,500), via fastembed (ONNX, no
PyTorch). Speed comes from storing each listing's vector (`job_hit.embedding`, float16,
keyed by model + text hash): the first search pays, later ones read only new listings. Only
the best 200 candidates that passed the filters are embedded. Score with meaning: skills 40,
title 20, meaning 30, freshness 10. Title-only hits use the same weights with their skills
counted as average (0.4): in the first real run (Fürth), separate title-heavy weights put
29 Bundesagentur listings with generic titles into the top 30. Cosine similarity
is mapped to 0..1 with a per-model calibration (Jina: 0.40 → 0, 0.70 → 1; measured: unrelated
jobs ~0.20, generic tech jobs ~0.50, close matches 0.65–0.73).

## 10. Open points

1. **BA listing text.** BA search hits have no description, and the detail endpoints
   (`/pc/v*/jobdetails/...`) returned 403 in a first probe. The `jobdetail` web page
   redirected to the search start page, so it is likely JavaScript-only. To try in phase 1:
   the external employer URL in the hit (when present), the detail page's JSON-LD with a
   proper request, or the documented detail endpoint with the right ID encoding. Fallback:
   the existing paste gate, which already handles this case.
2. **API stability.** The BA API is unofficial and versions change (v4 → v6). Keep each
   adapter isolated, report failures per source and never fail the whole search.
3. **Terms.** Attribution and links are fine for every source above. Remotive forbids
   republishing; this app is local and single-user, so that doesn't apply.
4. **Rate limits.** Make at most ~5 queries per source per search, cache list-only sources,
   send a descriptive User-Agent (the one in `fetch/listing.py`).
5. **Ranking quality.** Check against ~5 real searches with the user's CV before phase 3
   decides on embeddings.
