import { Button, GlassCard, GradientText } from "performative-ui";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, files } from "../api";
import {
  type RequirementsForm,
  RequirementsEditor,
  fromRequirements,
  parkedWishes,
  toRequirements,
} from "../components/RequirementsEditor";
import { ConfirmButton, ErrorNote, Section, useAction } from "../components/ui";
import { when } from "../format";
import { useLive, useResource } from "../live";
import type {
  HiddenReason,
  JobHit,
  Requirement,
  RolesStatus,
  SearchDetail,
  SearchPrefs,
  SearchResultItem,
  SearchSource,
  SourceStatus,
  SuggestedRole,
} from "../types";

export const HIDDEN_LABELS: Record<HiddenReason, string> = {
  requirements: "fail a must-have",
  elsewhere: "outside your area",
  low_score: "low match",
  dismissed: "dismissed",
};
const HIDDEN_ORDER: HiddenReason[] = ["requirements", "elsewhere", "low_score", "dismissed"];

export function salaryText(hit: JobHit): string | null {
  const low = hit.salary_min ?? hit.salary_max;
  const high = hit.salary_max ?? hit.salary_min;
  if (low === null || high === null) return null;
  const fmt = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`);
  const amount = low === high ? fmt(low) : `${fmt(low)}–${fmt(high)}`;
  const period = { year: "/ year", month: "/ month", hour: "/ hour" }[hit.salary_period ?? "year"];
  return `${amount} ${hit.salary_currency ?? ""} ${period}`.replace(/\s+/g, " ");
}

export function workMode(hit: JobHit): string | null {
  if (hit.remote === "remote") return "Remote";
  if (hit.remote === "hybrid")
    return hit.onsite_days_per_week !== null
      ? `Hybrid · ${hit.onsite_days_per_week} day(s) onsite`
      : "Hybrid";
  if (hit.remote === "onsite") return "Onsite";
  return null;
}

/** Visible results plus the hidden ones per reason (for the "show …" toggles). */
export function groupResults(results: SearchResultItem[], shown: Set<HiddenReason>) {
  const counts = {} as Record<HiddenReason, number>;
  for (const r of results) if (r.hidden) counts[r.hidden] = (counts[r.hidden] ?? 0) + 1;
  const visible = results.filter((r) => r.hidden === null || shown.has(r.hidden));
  return { visible, counts };
}

export function rankingText(r: SearchDetail["ranking"]): string {
  if (r.semantic) {
    const reused = r.reused ? `, ${r.reused} from earlier searches` : "";
    return `Ranked by meaning and keywords (${r.embedded ?? 0} listings read now${reused}).`;
  }
  return r.note ? `Ranked by keywords only: ${r.note}.` : "Ranked by keywords.";
}

function SourceLine({ sources }: { sources: Record<string, SourceStatus> }) {
  return (
    <p className="source-line">
      {Object.entries(sources).map(([key, s]) => (
        <span key={key} className={s.error ? "source-line__item--bad" : undefined}>
          {s.label} {s.error ? <em>{s.error}</em> : <strong className="mono">{s.count}</strong>}
        </span>
      ))}
    </p>
  );
}

/** Per-source progress of a running search, from the live status stream. */
export function SearchProgress() {
  const { status } = useLive();
  const job = status?.jobs.find((j) => j.kind === "search");
  if (!job?.progress) return null;
  return (
    <GlassCard className="search-progress" aria-live="polite">
      <p className="search-progress__head">{job.detail}</p>
      <ul>
        {Object.entries(job.progress).map(([key, p]) => (
          <li key={key} className={`search-progress__item search-progress__item--${p.state}`}>
            <span className="search-progress__dot" aria-hidden="true" />
            {p.label}
            <span className="muted">
              {p.state === "running" ? "searching…" : p.error ?? `${p.count} listings`}
            </span>
          </li>
        ))}
      </ul>
    </GlassCard>
  );
}

function HitCard({
  item,
  selected,
  onToggle,
  onChanged,
}: {
  item: SearchResultItem;
  selected: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const { hit, reasons } = item;
  const action = useAction();
  const salary = salaryText(hit);
  const mode = workMode(hit);
  const applied = hit.status === "applied" && hit.run_id !== null;
  const dismissed = hit.status === "dismissed";
  return (
    <GlassCard className={`hit${selected ? " hit--selected" : ""}${item.hidden ? " hit--hidden" : ""}`}>
      <div
        className="hit__score"
        title={[
          `title fit ${Math.round(reasons.title_fit * 100)}%`,
          reasons.semantic_fit !== null && `meaning ${Math.round(reasons.semantic_fit * 100)}%`,
        ]
          .filter(Boolean)
          .join(" · ")}
      >
        <span className="mono">{Math.round(item.score)}</span>
      </div>
      <div className="hit__body">
        <div className="hit__top">
          <a href={hit.view_url} target="_blank" rel="noreferrer" className="hit__title">
            {hit.title}
          </a>
          {item.is_new && !item.hidden && <span className="hit__new">new</span>}
        </div>
        <p className="hit__meta">
          {[hit.company, hit.location, mode, salary, hit.posted_at && `posted ${hit.posted_at}`]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {reasons.matched_skills.length > 0 && (
          <div className="tags">
            {reasons.matched_skills.slice(0, 8).map((s) => (
              <span key={s}>{s}</span>
            ))}
            {reasons.matched_skills.length > 8 && (
              <span className="muted">+{reasons.matched_skills.length - 8}</span>
            )}
          </div>
        )}
        {item.hidden && (
          <p className="hint">
            Hidden: {HIDDEN_LABELS[item.hidden]}
            {reasons.notes.length > 0 && ` (${reasons.notes.join("; ")})`}
          </p>
        )}
        <p className="hit__source">
          via{" "}
          <a href={hit.source_home ?? hit.view_url} target="_blank" rel="noreferrer">
            {hit.source_label}
          </a>
          {hit.also_on.length > 0 && <> · also on {hit.also_on.join(", ")}</>}
          {reasons.basis === "title only" && <> · scored on the title only</>}
          {!hit.full_text && <> · listing is fetched when you apply</>}
        </p>
        <ErrorNote error={action.error} />
      </div>
      <div className="hit__actions">
        {applied ? (
          <Link to={`/runs/${hit.run_id}`}>Application →</Link>
        ) : (
          <>
            <label className="check">
              <input type="checkbox" checked={selected} onChange={onToggle} disabled={dismissed} />
              apply
            </label>
            <Button
              variant="ghost"
              size="sm"
              loading={action.busy}
              onClick={async () => {
                const done = await action.run(() =>
                  dismissed ? api.restoreHit(hit.id) : api.dismissHit(hit.id),
                );
                if (done) onChanged();
              }}
            >
              {dismissed ? "Restore" : "Dismiss"}
            </Button>
          </>
        )}
      </div>
    </GlassCard>
  );
}

/** Exports to pass on: the list as shown (PDF), or the list with every application (ZIP). */
export function ExportButtons({ search, shown }: { search: SearchDetail; shown: Set<HiddenReason> }) {
  const applied = search.results.filter((r) => r.hit.run_id !== null).length;
  const show = HIDDEN_ORDER.filter((r) => shown.has(r));
  return (
    <>
      <Button
        as="a"
        href={files.searchExport(search.id, show)}
        download
        variant="ghost"
        size="sm"
        title="The listings as shown here, with links, as a PDF"
      >
        Export list (PDF)
      </Button>
      {applied > 0 && (
        <Button
          as="a"
          href={files.searchArchive(search.id, show)}
          download
          variant="ghost"
          size="sm"
          title="ZIP: a report with the list and each application's assessment and review, plus each tailored CV and cover letter as its own PDF"
        >
          Export with {applied} application{applied > 1 ? "s" : ""} (ZIP)
        </Button>
      )}
    </>
  );
}

function Results({
  search,
  onChanged,
  onSaved,
}: {
  search: SearchDetail;
  onChanged: () => void;
  onSaved: () => void;
}) {
  const save = useAction();
  const [shown, setShown] = useState<Set<HiddenReason>>(new Set());
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const action = useAction();
  const navigate = useNavigate();
  const { visible, counts } = useMemo(
    () => groupResults(search.results, shown),
    [search.results, shown],
  );
  useEffect(() => setSelected(new Set()), [search.id]);

  const toggle = (set: Set<number>, id: number) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };

  return (
    <div className="stack">
      <div className="results-head">
        <SourceLine sources={search.sources} />
        <div className="panel__actions">
          {search.saved_id === null ? (
            <Button
              variant="ghost"
              size="sm"
              loading={save.busy}
              onClick={async () => {
                if (await save.run(() => api.saveSearch(search.id))) onSaved();
              }}
            >
              Save search
            </Button>
          ) : (
            <span className="muted">Saved search</span>
          )}
          <ExportButtons search={search} shown={shown} />
        </div>
      </div>
      <p className="hint ranking-note">{rankingText(search.ranking)}</p>
      <ErrorNote error={save.error} />
      <div className="hidden-toggles">
        <span className="muted">
          {visible.length} shown{search.new > 0 && ` · ${search.new} new`}
        </span>
        {HIDDEN_ORDER.filter((r) => counts[r]).map((reason) => (
          <label key={reason} className="check">
            <input
              type="checkbox"
              checked={shown.has(reason)}
              onChange={() =>
                setShown((s) => {
                  const next = new Set(s);
                  if (next.has(reason)) next.delete(reason);
                  else next.add(reason);
                  return next;
                })
              }
            />
            show {counts[reason]} {HIDDEN_LABELS[reason]}
          </label>
        ))}
      </div>
      {visible.length === 0 && <p className="empty">No matching listings. Try other titles.</p>}
      {visible.map((item) => (
        <HitCard
          key={item.hit.id}
          item={item}
          selected={selected.has(item.hit.id)}
          onToggle={() => setSelected((s) => toggle(s, item.hit.id))}
          onChanged={onChanged}
        />
      ))}
      {selected.size > 0 && (
        <div className="apply-bar">
          <span>
            {selected.size} listing{selected.size > 1 ? "s" : ""} selected. Claude reads and
            assesses each one; you decide before any documents are written.
          </span>
          <ErrorNote error={action.error} />
          <Button
            variant="glow"
            sparkle
            loading={action.busy}
            onClick={async () => {
              const runs = await action.run(() => api.applyHits(search.id, [...selected]));
              if (runs) navigate(runs.length === 1 ? `/runs/${runs[0].id}` : "/");
            }}
          >
            Start {selected.size} application{selected.size > 1 ? "s" : ""}
          </Button>
        </div>
      )}
    </div>
  );
}

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
const includes = (list: string[], t: string) => list.some((x) => same(x, t));
const without = (list: string[], drop: string[]) => list.filter((x) => !includes(drop, x));
const roleTitles = (role: SuggestedRole) => [role.title, role.title_alt].filter(Boolean);

/** Whether the role's main title is searched (case-insensitive). */
export function hasRole(titles: string[], role: SuggestedRole): boolean {
  return includes(titles, role.title);
}

/** Add the role's titles (both languages) to the searched titles, or remove them again. */
export function toggleRole(titles: string[], role: SuggestedRole): string[] {
  const kept = without(titles, roleTitles(role));
  return hasRole(titles, role) ? kept : [...kept, ...roleTitles(role)];
}

/** Title chips: the CV's titles plus the user's own, each switched on or off. */
export function TitleChips({
  all,
  titles,
  onChange,
  removable,
  onRemove,
  children,
}: {
  children?: ReactNode;
  all: string[];
  titles: string[];
  onChange: (titles: string[]) => void;
  removable: (title: string) => boolean;
  onRemove: (title: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const title = draft.trim();
    if (title && !includes(titles, title)) onChange([...titles, title]);
    setDraft("");
  };
  return (
    <fieldset className="requirements">
      <legend>Job titles</legend>
      <p className="hint">From your CV. Click a title to leave it out of the search, or add your own.</p>
      <ul className="chips">
        {all.map((t) => {
          const on = includes(titles, t);
          return (
            <li key={t} className={`chip${on ? " chip--on" : ""}`}>
              <button
                type="button"
                className="chip__toggle"
                aria-pressed={on}
                onClick={() => onChange(on ? without(titles, [t]) : [...titles, t])}
              >
                {t}
              </button>
              {!on && removable(t) && (
                <button type="button" className="chip__remove" aria-label={`Remove ${t}`} onClick={() => onRemove(t)}>
                  ×
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <div className="chip-input">
        <input
          aria-label="Add a job title"
          value={draft}
          placeholder="Add a title"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="chip-btn" onClick={add} disabled={!draft.trim()}>
          Add
        </button>
      </div>
      {children}
    </fieldset>
  );
}

export function RoleSuggestions({
  cvId,
  roles,
  status,
  titles,
  onChange,
}: {
  cvId: number;
  roles: SuggestedRole[];
  status: RolesStatus;
  titles: string[];
  onChange: (titles: string[]) => void;
}) {
  if (status === "suggesting") return <p className="hint">Claude is suggesting other roles that fit your CV…</p>;
  if (!roles.length) {
    return status === "done" ? null : (
      <p className="hint">
        Other roles that fit your CV can be suggested on the <Link to={`/cvs/${cvId}`}>CV page</Link>.
      </p>
    );
  }
  return (
    <div className="role-suggestions">
      <p className="hint">Other roles that fit your CV, suggested by Claude. Hover for why; click to search for one too.</p>
      <ul className="chips">
        {roles.map((role) => {
          const added = hasRole(titles, role);
          return (
            <li key={role.title} className={`chip chip--role${added ? " chip--on" : ""}`} data-tip={role.reason}>
              <button
                type="button"
                className="chip__toggle"
                aria-pressed={added}
                aria-describedby={`role-${slug(role.title)}`}
                onClick={() => onChange(toggleRole(titles, role))}
              >
                {added ? "✓" : "+"} {role.title}
                {role.title_alt && <span className="muted"> / {role.title_alt}</span>}
              </button>
              <span id={`role-${slug(role.title)}`} role="tooltip" className="chip__tip">
                {role.reason}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");

interface Suggestions {
  titles: string[];
  roles: SuggestedRole[];
  roles_status: RolesStatus;
  sources: SearchSource[];
  prefs: SearchPrefs | null;
}

interface FormState {
  titles: string[];
  titlesOff: string[];
  reqs: RequirementsForm;
  chosen: Set<string>;
}

/** The form for a CV: its saved prefs, or the CV's titles and the last used requirements. */
export function initialForm(s: Suggestions, lastReqs: Requirement[]): FormState {
  const available = new Set(s.sources.filter((x) => !x.missing_env.length).map((x) => x.key));
  const defaults = s.sources.filter((x) => x.default && available.has(x.key)).map((x) => x.key);
  const p = s.prefs;
  if (!p) {
    return { titles: s.titles, titlesOff: [], reqs: fromRequirements(lastReqs), chosen: new Set(defaults) };
  }
  // CV titles the user never switched off are searched (e.g. after the CV changed).
  const fresh = without(s.titles, [...p.titles, ...p.titles_off]);
  return {
    titles: [...p.titles, ...fresh],
    titlesOff: p.titles_off,
    reqs: fromRequirements(p.requirements, p.requirements_off),
    chosen: new Set(p.sources === null ? defaults : p.sources.filter((k) => available.has(k))),
  };
}

export function toPrefs(f: FormState): SearchPrefs {
  return {
    titles: f.titles,
    titles_off: f.titlesOff,
    requirements: toRequirements(f.reqs),
    requirements_off: parkedWishes(f.reqs),
    sources: [...f.chosen].sort(),
  };
}

function SearchForm({ onSearched }: { onSearched: (s: SearchDetail) => void }) {
  const { version } = useLive();
  const cvs = useResource(() => api.cvs(), [version("any")]);
  const confirmed = (cvs.data ?? []).filter((c) => c.status === "confirmed");
  const [cvId, setCvId] = useState<number | null>(null);
  const [cvTitles, setCvTitles] = useState<string[]>([]);
  const [form, setForm] = useState<FormState | null>(null);
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  const saved = useRef("");
  const [roles, setRoles] = useState<{ roles: SuggestedRole[]; status: RolesStatus }>({ roles: [], status: null });
  const [sources, setSources] = useState<SearchSource[]>([]);
  const action = useAction();

  useEffect(() => {
    if (cvId === null && confirmed.length) setCvId(confirmed[0].id);
  }, [confirmed, cvId]);
  useEffect(() => {
    if (cvId === null) return;
    let stale = false;
    setLoadedFor(null);
    Promise.all([api.searchSuggestions(cvId), api.lastRequirements()]).then(([s, last]) => {
      if (stale) return;
      const initial = initialForm(s, last);
      setCvTitles(s.titles);
      setSources(s.sources);
      setForm(initial);
      saved.current = s.prefs ? JSON.stringify(toPrefs(initial)) : "";
      setLoadedFor(cvId);
    });
    return () => {
      stale = true;
    };
  }, [cvId]);
  // Role suggestions arrive in the background after confirmation: reload them on CV
  // updates without touching the form the user is editing.
  const cvVersion = version("cv", cvId ?? undefined);
  useEffect(() => {
    if (cvId === null) return;
    api.searchSuggestions(cvId).then((s) => setRoles({ roles: s.roles, status: s.roles_status }));
  }, [cvId, cvVersion]);
  // Keep the form per CV: save shortly after each change.
  useEffect(() => {
    if (form === null || cvId === null || loadedFor !== cvId) return;
    const prefs = toPrefs(form);
    const json = JSON.stringify(prefs);
    if (json === saved.current) return;
    const timer = setTimeout(() => {
      saved.current = json;
      api.saveSearchPrefs(cvId, prefs).catch(() => (saved.current = ""));
    }, 600);
    return () => clearTimeout(timer);
  }, [form, cvId, loadedFor]);

  if (cvs.data && !confirmed.length) {
    return (
      <Section title="Search" eyebrow="Start here">
        <p>
          First add your CV and confirm it. <Link to="/cvs">Go to CVs →</Link>
        </p>
      </Section>
    );
  }

  const update = (patch: Partial<FormState>) => setForm((f) => (f ? { ...f, ...patch } : f));
  const roleSet = roles.roles.flatMap(roleTitles);
  const ready = form !== null && loadedFor === cvId;
  // Chips: the CV's titles and the user's own; roles have their own chips below.
  const allTitles = form
    ? without([...new Map([...cvTitles, ...form.titles, ...form.titlesOff].map((t) => [t.toLowerCase(), t])).values()], roleSet)
    : [];
  const noRemote = form !== null && !form.reqs.remote_ok && form.reqs.max_onsite_days !== 0 && form.reqs.work_must;

  return (
    <Section title="Search" eyebrow="No AI costs">
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          if (cvId === null || !form) return;
          const result = await action.run(() =>
            api.createSearch({
              cv_id: cvId,
              titles: form.titles,
              requirements: toRequirements(form.reqs),
              sources: [...form.chosen],
            }),
          );
          if (result) onSearched(result);
        }}
      >
        <label>
          CV
          <select value={cvId ?? ""} onChange={(e) => setCvId(Number(e.target.value))}>
            {confirmed.map((cv) => (
              <option key={cv.id} value={cv.id}>
                {cv.label}
              </option>
            ))}
          </select>
        </label>
        {ready && form && cvId !== null && (
          <>
            <TitleChips
              all={allTitles}
              titles={form.titles}
              onChange={(titles) =>
                update({ titles, titlesOff: without([...form.titlesOff, ...without(allTitles, titles)], titles) })
              }
              removable={(t) => !includes(cvTitles, t)}
              onRemove={(t) => update({ titlesOff: without(form.titlesOff, [t]) })}
            >
              <RoleSuggestions
                cvId={cvId}
                roles={roles.roles}
                status={roles.status}
                titles={form.titles}
                onChange={(titles) => update({ titles })}
              />
            </TitleChips>
            <RequirementsEditor value={form.reqs} onChange={(reqs) => update({ reqs })} />
            <p className="hint">
              {form.reqs.places.length
                ? "Bundesagentur and Adzuna search within each city's radius; other sources match the city names."
                : "No cities: all of Germany is searched (jobs abroad are hidden). Add cities to search near you."}{" "}
              A must-have hides listings that clearly contradict it; hidden listings stay one click
              away.
            </p>
            <fieldset className="requirements">
              <legend>Sources</legend>
              {sources.map((s) => (
                <label key={s.key} className="check" title={s.home}>
                  <input
                    type="checkbox"
                    checked={form.chosen.has(s.key)}
                    disabled={s.missing_env.length > 0}
                    onChange={() => {
                      const next = new Set(form.chosen);
                      if (next.has(s.key)) next.delete(s.key);
                      else next.add(s.key);
                      update({ chosen: next });
                    }}
                  />
                  {s.label}
                  {s.remote_only && <span className="muted">remote{noRemote && ", skipped"}</span>}
                  {s.missing_env.length > 0 && (
                    <span className="muted check__note">needs {s.missing_env.join(", ")}</span>
                  )}
                </label>
              ))}
            </fieldset>
          </>
        )}
        <ErrorNote error={action.error} />
        <Button
          type="submit"
          variant="glow"
          sparkle
          loading={action.busy}
          disabled={!ready || !form?.titles.length || !form?.chosen.size}
        >
          Search
        </Button>
      </form>
    </Section>
  );
}

function SavedSearches({
  version,
  onRun,
  onChanged,
}: {
  version: number;
  onRun: (s: SearchDetail) => void;
  onChanged: () => void;
}) {
  const saved = useResource(() => api.savedSearches(), [version]);
  const action = useAction();
  const [running, setRunning] = useState<number | null>(null);
  if (!saved.data?.length) return null;
  return (
    <Section title="Saved searches" eyebrow="Run again">
      <ErrorNote error={action.error} />
      <ul className="search-history">
        {saved.data.map((s) => (
          <li key={s.id}>
            <span className="saved-name">{s.name}</span>
            <span className="muted">
              {s.last_run
                ? `${when(s.last_run.created_at)} · ${s.last_run.new} new`
                : "not run yet"}
            </span>
            <Button
              variant="ghost"
              size="sm"
              loading={running === s.id}
              disabled={running !== null}
              onClick={async () => {
                setRunning(s.id);
                const result = await action.run(() => api.runSaved(s.id));
                setRunning(null);
                if (result) {
                  onRun(result);
                  onChanged();
                }
              }}
            >
              Run
            </Button>
            <ConfirmButton
              label="×"
              title="Delete this saved search?"
              body={<p>Its earlier results stay in your search history.</p>}
              onConfirm={async () => {
                await api.deleteSaved(s.id);
                onChanged();
              }}
            />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function History({
  current,
  version,
  onDeleted,
}: {
  current: number | null;
  version: number;
  onDeleted: () => void;
}) {
  const searches = useResource(() => api.searches(), [current, version]);
  if (!searches.data?.length) return null;
  return (
    <Section title="Earlier searches">
      <ul className="search-history">
        {searches.data.map((s) => (
          <li key={s.id} className={s.id === current ? "current" : undefined}>
            <Link to={`/search?id=${s.id}`}>
              {s.titles.slice(0, 2).join(", ")}
              {s.places.length > 0 && ` · ${s.places.join(", ")}`}
            </Link>
            <span className="muted">
              {when(s.created_at)} · {s.shown} shown
            </span>
            <ConfirmButton
              label="×"
              title="Delete this search?"
              body={<p>The results of this search are removed. Applications stay.</p>}
              onConfirm={async () => {
                await api.deleteSearch(s.id);
                searches.reload();
                if (s.id === current) onDeleted();
              }}
            />
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const id = params.get("id") ? Number(params.get("id")) : null;
  const [search, setSearch] = useState<SearchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [savedVersion, setSavedVersion] = useState(0);
  const show = (s: SearchDetail) => {
    setSearch(s);
    setParams({ id: String(s.id) });
  };
  const savedChanged = () => {
    setSavedVersion((v) => v + 1);
    setNonce((n) => n + 1);
  };

  useEffect(() => {
    if (id === null) {
      setSearch(null);
      return;
    }
    if (search?.id === id && nonce === 0) return;
    api
      .search(id)
      .then((s) => {
        setSearch(s);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, nonce]);

  return (
    <div className="page">
      <div className="hero">
        <h1>
          <GradientText>Find jobs</GradientText>
        </h1>
        <p className="hero__sub">
          Searches free job APIs and ranks the listings against your CV, in Python. Claude only
          runs for the listings you choose.
        </p>
      </div>
      <div className="dashboard">
        <div>
          <ErrorNote error={error} />
          <SearchProgress />
          {search ? (
            <Results
              search={search}
              onChanged={() => setNonce((n) => n + 1)}
              onSaved={savedChanged}
            />
          ) : (
            <p className="empty">Run a search to see listings ranked against your CV.</p>
          )}
        </div>
        <div className="stack">
          <SearchForm onSearched={show} />
          <SavedSearches version={savedVersion} onRun={show} onChanged={savedChanged} />
          <History current={id} version={savedVersion} onDeleted={() => setParams({})} />
        </div>
      </div>
    </div>
  );
}
