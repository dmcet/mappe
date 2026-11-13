import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { LiveContext } from "../live";
import {
  ExportButtons,
  RoleSuggestions,
  TitleChips,
  initialForm,
  toPrefs,
  SearchPage,
  SearchProgress,
  groupResults,
  hasRole,
  rankingText,
  salaryText,
  toggleRole,
  workMode,
} from "../pages/Search";
import type { JobHit, SearchDetail, SearchResultItem, SearchSource } from "../types";

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
  reasons: { score: 80, matched_skills: ["Python", "PostgreSQL"], title_fit: 1, semantic_fit: 0.8, basis: "description", hidden: null, notes: [] },
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

  it("explains how results were ranked", () => {
    expect(rankingText({ semantic: true, embedded: 3, reused: 40, note: null })).toBe(
      "Ranked by meaning and keywords (3 listings read now, 40 from earlier searches).",
    );
    expect(rankingText({ semantic: false, note: "turned off in config.toml" })).toBe(
      "Ranked by keywords only: turned off in config.toml.",
    );
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
    ranking: { semantic: true, model: "jinaai/jina-embeddings-v2-base-de", embedded: 2, reused: 0, note: null },
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
    // The export follows what is shown; without applications there is only the list.
    expect(screen.getByText("Export list (PDF)").closest("a")).toHaveAttribute(
      "href",
      "/api/searches/7/export.pdf?show=elsewhere",
    );
    expect(screen.queryByText(/Export with/)).not.toBeInTheDocument();
  });

  it("offers the full export once listings have applications", () => {
    const applied = {
      ...detail,
      results: [item(hit({ id: 1, status: "applied", run_id: 3 })), item(hit({ id: 2, run_id: 4 }))],
    };
    render(<ExportButtons search={applied} shown={new Set()} />);
    expect(screen.getByText("Export list (PDF)").closest("a")).toHaveAttribute("href", "/api/searches/7/export.pdf");
    expect(screen.getByText("Export with 2 applications (ZIP)").closest("a")).toHaveAttribute(
      "href",
      "/api/searches/7/export.zip",
    );
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

describe("role suggestions", () => {
  const sre = { title: "Site Reliability Engineer", title_alt: "", reason: "Latency work." };
  const arch = { title: "Software Architect", title_alt: "Softwarearchitekt", reason: "Design ownership." };

  it("adds a role in both languages and removes it again", () => {
    const added = toggleRole(["Backend Engineer"], arch);
    expect(added).toEqual(["Backend Engineer", "Software Architect", "Softwarearchitekt"]);
    expect(hasRole(added, arch)).toBe(true);
    expect(toggleRole(added, arch)).toEqual(["Backend Engineer"]);
    expect(hasRole(["site reliability engineer"], sre)).toBe(true);
  });

  it("shows opt-in chips that explain themselves on hover", () => {
    let titles = ["Backend Engineer"];
    const onChange = vi.fn((t: string[]) => (titles = t));
    const view = (t: string[]) => (
      <MemoryRouter>
        <RoleSuggestions cvId={1} roles={[sre, arch]} status="done" titles={t} onChange={onChange} />
      </MemoryRouter>
    );
    const { rerender } = render(view(titles));
    const chip = screen.getByRole("button", { name: /Site Reliability Engineer/ });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(chip).toHaveAccessibleDescription("Latency work.");
    fireEvent.click(chip);
    expect(titles).toEqual(["Backend Engineer", "Site Reliability Engineer"]);
    rerender(view(titles));
    expect(screen.getByRole("button", { name: /Site Reliability Engineer/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("explains where suggestions come from when there are none yet", () => {
    const { rerender } = render(
      <MemoryRouter>
        <RoleSuggestions cvId={4} roles={[]} status="suggesting" titles={[]} onChange={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Claude is suggesting other roles/)).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <RoleSuggestions cvId={4} roles={[]} status={null} titles={[]} onChange={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "CV page" })).toHaveAttribute("href", "/cvs/4");
  });
});

describe("title chips and saved form", () => {
  const sources: SearchSource[] = [
    { key: "ba", label: "BA", home: "", remote_only: false, default: true, missing_env: [] },
    { key: "remotive", label: "Remotive", home: "", remote_only: true, default: true, missing_env: [] },
    { key: "adzuna", label: "Adzuna", home: "", remote_only: false, default: true, missing_env: ["X"] },
  ];
  const base = { titles: ["Backend Engineer", "Python Developer"], roles: [], roles_status: null, sources };

  it("switches titles off, adds own ones and removes only those", () => {
    let titles = ["Backend Engineer"];
    const onChange = vi.fn((t: string[]) => (titles = t));
    const onRemove = vi.fn();
    const all = ["Backend Engineer", "Python Developer", "Tech Lead"];
    const view = () => (
      <TitleChips all={all} titles={titles} onChange={onChange} removable={(t) => t === "Tech Lead"} onRemove={onRemove} />
    );
    const { rerender } = render(view());
    expect(screen.getByRole("button", { name: "Python Developer" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("button", { name: "Remove Python Developer" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove Tech Lead" }));
    expect(onRemove).toHaveBeenCalledWith("Tech Lead");
    fireEvent.click(screen.getByRole("button", { name: "Backend Engineer" }));
    expect(titles).toEqual([]);
    rerender(view());
    fireEvent.change(screen.getByLabelText("Add a job title"), { target: { value: "SRE" } });
    fireEvent.keyDown(screen.getByLabelText("Add a job title"), { key: "Enter" });
    expect(titles).toEqual(["SRE"]);
  });

  it("starts from the CV and the last requirements, then from what was saved", () => {
    const last = [{ kind: "location" as const, value: "Berlin", must_have: false }];
    const fresh = initialForm({ ...base, prefs: null }, last);
    expect(fresh.titles).toEqual(base.titles);
    expect([...fresh.chosen]).toEqual(["ba", "remotive"]);
    expect(fresh.reqs.places).toEqual([{ name: "Berlin", km: 30 }]);

    const prefs = toPrefs({ ...fresh, titles: ["Backend Engineer", "SRE"], titlesOff: ["Python Developer"], chosen: new Set(["ba", "adzuna"]) });
    expect(prefs.sources).toEqual(["adzuna", "ba"]);
    const back = initialForm({ ...base, titles: [...base.titles, "Tech Lead"], prefs }, []);
    // A title the CV gained since is searched; switched-off ones stay off; unusable sources drop.
    expect(back.titles).toEqual(["Backend Engineer", "SRE", "Tech Lead"]);
    expect(back.titlesOff).toEqual(["Python Developer"]);
    expect([...back.chosen]).toEqual(["ba"]);
    expect(back.reqs.places).toEqual([{ name: "Berlin", km: 30 }]);
  });
});
