import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { LiveContext } from "../live";
import { SearchPage, SearchProgress, groupResults, salaryText, workMode } from "../pages/Search";
import type { JobHit, SearchDetail, SearchResultItem } from "../types";

const hit = (over: Partial<JobHit> = {}): JobHit => ({
  id: 1,
  status: "new",
  run_id: null,
  source: "arbeitnow",
  source_label: "Arbeitnow",
  source_home: "https://www.arbeitnow.com/",
  full_text: true,
  first_seen_at: "2026-11-03T10:00:00",
  url: "https://example.com/job",
  view_url: "https://example.com/job",
  title: "Backend Engineer",
  company: "Acme",
  location: "Berlin",
  remote: null,
  onsite_days_per_week: null,
  salary_min: null,
  salary_max: null,
  salary_currency: null,
  salary_period: null,
  tags: [],
  posted_at: "2026-11-01",
  also_on: [],
  excerpt: "",
  ...over,
});

const item = (h: JobHit, over: Partial<SearchResultItem> = {}): SearchResultItem => ({
  score: 80,
  reasons: { score: 80, matched_skills: ["Python", "PostgreSQL"], title_fit: 1, basis: "description", hidden: null, notes: [] },
  hidden: null,
  is_new: true,
  hit: h,
  ...over,
});

describe("search helpers", () => {
  it("formats salary and work mode", () => {
    expect(salaryText(hit())).toBeNull();
    expect(salaryText(hit({ salary_min: 60000, salary_max: 75000, salary_currency: "EUR", salary_period: "year" }))).toBe("60k–75k EUR / year");
    expect(salaryText(hit({ salary_min: 18, salary_max: 18, salary_currency: "EUR", salary_period: "hour" }))).toBe("18 EUR / hour");
    expect(workMode(hit({ remote: "hybrid", onsite_days_per_week: 2 }))).toBe("Hybrid · 2 day(s) onsite");
    expect(workMode(hit())).toBeNull();
  });

  it("hides results per reason until shown", () => {
    const results = [item(hit({ id: 1 })), item(hit({ id: 2 }), { hidden: "elsewhere" }), item(hit({ id: 3 }), { hidden: "elsewhere" })];
    expect(groupResults(results, new Set()).visible).toHaveLength(1);
    expect(groupResults(results, new Set()).counts).toEqual({ elsewhere: 2 });
    expect(groupResults(results, new Set(["elsewhere"])).visible).toHaveLength(3);
  });
});

describe("search page", () => {
  const detail: SearchDetail = {
    id: 7,
    cv_id: 1,
    saved_id: null,
    titles: ["Backend Engineer"],
    places: ["Berlin"],
    remote_only: false,
    created_at: "2026-11-03T10:00:00",
    total: 2,
    shown: 1,
    new: 1,
    requirements: [],
    sources: {
      ba: { label: "Bundesagentur für Arbeit", count: 12, error: null, seconds: 0.3 },
      jobicy: { label: "Jobicy", count: 0, error: "HTTP 503", seconds: 0.1 },
    },
    results: [
      item(hit({ id: 1, title: "Backend Engineer" })),
      item(hit({ id: 2, title: "Engineer in Paris", location: "Paris" }), { hidden: "elsewhere" }),
    ],
  };

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const body = url.startsWith("/api/searches/7")
          ? detail
          : url.startsWith("/api/searches")
            ? []
            : url.startsWith("/api/cvs")
              ? []
              : [];
        return new Response(JSON.stringify(body), { status: 200 });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows ranked hits, source status and an apply bar on selection", async () => {
    render(
      <MemoryRouter initialEntries={["/search?id=7"]}>
        <SearchPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText("HTTP 503")).toBeInTheDocument();
    expect(screen.queryByText("Engineer in Paris")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/show 1 outside your area/));
    expect(screen.getByText("Engineer in Paris")).toBeInTheDocument();

    fireEvent.click(screen.getAllByLabelText("apply")[0]);
    expect(screen.getByText("Start 1 application")).toBeInTheDocument();
    expect(screen.getByText("Save search")).toBeInTheDocument();
  });

  it("shows each source's progress while a search runs", () => {
    const status = {
      jobs: [
        {
          kind: "search" as const,
          id: 1,
          title: "Job search: Backend Engineer",
          phase: "",
          detail: "Searching jobs · 1/2 sources · 12 listings",
          model: null,
          draft: null,
          elapsed_s: 1,
          detail_elapsed_s: 0,
          progress: {
            ba: { label: "Bundesagentur für Arbeit", state: "done" as const, count: 12, error: null },
            jobicy: { label: "Jobicy", state: "running" as const, count: 0, error: null },
          },
        },
      ],
      queued: [],
      waiting_for_you: [],
      demo: false,
      costs: { total_usd: 0, today_usd: 0, limit_per_run_usd: 2 },
    };
    render(
      <LiveContext.Provider value={{ status, connected: true, version: () => 0 }}>
        <SearchProgress />
      </LiveContext.Provider>,
    );
    expect(screen.getByText("Searching jobs · 1/2 sources · 12 listings")).toBeInTheDocument();
    expect(screen.getByText("12 listings")).toBeInTheDocument();
    expect(screen.getByText("searching…")).toBeInTheDocument();
  });
});
