import type {
  ApplicationEmail,
  CostSummary,
  CVDetail,
  CVSummary,
  EditData,
  Requirement,
  RolesStatus,
  RunDetail,
  RunSummary,
  SavedSearch,
  SearchDetail,
  SearchSource,
  SearchSummary,
  SuggestedRole,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export interface DocumentEdit {
  profile: string;
  titles: Record<string, string>;
  bullets: Record<string, string[]>;
  skill_groups: { category: string; skills: string[] }[];
  letter: { subject: string; paragraphs: string[] } | null;
}

export const api = {
  cvs: () => request<CVSummary[]>("GET", "/api/cvs"),
  cv: (id: number) => request<CVDetail>("GET", `/api/cvs/${id}`),
  createCv: (label: string, markdown: string) =>
    request<CVDetail>("POST", "/api/cvs", { label, markdown }),
  updateCvFields: (id: number, values: Record<string, string>) =>
    request<CVDetail>("PATCH", `/api/cvs/${id}/fields`, values),
  reparseCv: (id: number, markdown: string) =>
    request<CVDetail>("PUT", `/api/cvs/${id}/markdown`, { markdown }),
  confirmCv: (id: number) => request<CVDetail>("POST", `/api/cvs/${id}/confirm`),
  suggestRoles: (id: number) => request<CVDetail>("POST", `/api/cvs/${id}/roles`),
  deleteCv: (id: number, cascade: boolean) =>
    request<void>("DELETE", `/api/cvs/${id}${cascade ? "?cascade=true" : ""}`),

  runs: () => request<RunSummary[]>("GET", "/api/runs"),
  run: (id: number) => request<RunDetail>("GET", `/api/runs/${id}`),
  lastRequirements: () => request<Requirement[]>("GET", "/api/runs/requirements/last"),
  createRuns: (body: {
    cv_id: number;
    urls: string[];
    listing_text: string;
    requirements: Requirement[];
  }) => request<RunSummary[]>("POST", "/api/runs", body),
  submitListingText: (id: number, listing_text: string) =>
    request<RunDetail>("POST", `/api/runs/${id}/listing-text`, { listing_text }),
  continueRun: (id: number) => request<RunDetail>("POST", `/api/runs/${id}/continue`),
  declineRun: (id: number) => request<RunDetail>("POST", `/api/runs/${id}/decline`),
  applyRun: (id: number, cover_letter: boolean) =>
    request<RunDetail>("POST", `/api/runs/${id}/apply`, { cover_letter }),
  editData: (id: number) => request<EditData>("GET", `/api/runs/${id}/edit-data`),
  saveDocuments: (id: number, edit: DocumentEdit) =>
    request<RunDetail>("PUT", `/api/runs/${id}/documents`, edit),
  abortFetch: (id: number) => request<RunDetail>("POST", `/api/runs/${id}/abort-fetch`),
  email: (id: number) => request<ApplicationEmail>("GET", `/api/runs/${id}/email`),
  approveRun: (id: number) => request<RunDetail>("POST", `/api/runs/${id}/approve`),
  deleteRun: (id: number) => request<void>("DELETE", `/api/runs/${id}`),

  costs: () => request<CostSummary>("GET", "/api/costs"),

  searchSuggestions: (cvId: number) =>
    request<{
      titles: string[];
      roles: SuggestedRole[];
      roles_status: RolesStatus;
      sources: SearchSource[];
    }>(
      "GET",
      `/api/search/suggestions?cv_id=${cvId}`,
    ),
  searches: () => request<SearchSummary[]>("GET", "/api/searches"),
  search: (id: number) => request<SearchDetail>("GET", `/api/searches/${id}`),
  createSearch: (body: {
    cv_id: number;
    titles: string[];
    requirements: Requirement[];
    sources: string[];
  }) => request<SearchDetail>("POST", "/api/searches", body),
  deleteSearch: (id: number) => request<void>("DELETE", `/api/searches/${id}`),
  dismissHit: (id: number) => request<{ status: string }>("POST", `/api/job-hits/${id}/dismiss`),
  restoreHit: (id: number) => request<{ status: string }>("POST", `/api/job-hits/${id}/restore`),
  savedSearches: () => request<SavedSearch[]>("GET", "/api/saved-searches"),
  saveSearch: (searchId: number, name = "") =>
    request<SavedSearch>("POST", "/api/saved-searches", { search_id: searchId, name }),
  runSaved: (id: number) => request<SearchDetail>("POST", `/api/saved-searches/${id}/run`),
  deleteSaved: (id: number) => request<void>("DELETE", `/api/saved-searches/${id}`),
  applyHits: (searchId: number, hitIds: number[]) =>
    request<RunSummary[]>("POST", `/api/searches/${searchId}/apply`, { hit_ids: hitIds }),
};

export const files = {
  draft: (run: number, iteration: number, name: string) =>
    `/api/runs/${run}/drafts/${iteration}/${name}`,
  final: (run: number, name: string) => `/api/runs/${run}/final/${encodeURIComponent(name)}`,
  bundle: (run: number) => `/api/runs/${run}/bundle.zip`,
  /** PDF of the search list: the listings shown, plus the hidden reasons in ``show``. */
  searchExport: (search: number, show: string[] = []) =>
    `/api/searches/${search}/export.pdf${show.length ? `?show=${show.join(",")}` : ""}`,
  /** ZIP: one report (list + each application's reasoning), plus every CV and cover letter. */
  searchArchive: (search: number, show: string[] = []) =>
    `/api/searches/${search}/export.zip${show.length ? `?show=${show.join(",")}` : ""}`,
  runExport: (run: number) => `/api/runs/${run}/export.zip`,
};
