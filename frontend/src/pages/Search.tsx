import { Button, GlassCard, GradientText } from "performative-ui";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api } from "../api";
import {
  EMPTY_REQUIREMENTS,
  RequirementsEditor,
  fromRequirements,
  toRequirements,
} from "../components/RequirementsEditor";
import { ConfirmButton, ErrorNote, Section, useAction } from "../components/ui";
import { when } from "../format";
import { useLive, useResource } from "../live";
import type {
  HiddenReason,
  JobHit,
  SearchDetail,
  SearchResultItem,
  SearchSource,
  SourceStatus,
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
      <div className="hit__score" title={`title fit ${Math.round(reasons.title_fit * 100)}%`}>
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

function Results({ search, onChanged }: { search: SearchDetail; onChanged: () => void }) {
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
      <SourceLine sources={search.sources} />
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

function SearchForm({ onSearched }: { onSearched: (s: SearchDetail) => void }) {
  const { version } = useLive();
  const cvs = useResource(() => api.cvs(), [version("any")]);
  const confirmed = (cvs.data ?? []).filter((c) => c.status === "confirmed");
  const [cvId, setCvId] = useState<number | null>(null);
  const [titles, setTitles] = useState("");
  const [sources, setSources] = useState<SearchSource[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [reqs, setReqs] = useState(EMPTY_REQUIREMENTS);
  const action = useAction();

  useEffect(() => {
    api.lastRequirements().then((r) => setReqs(fromRequirements(r)));
  }, []);
  useEffect(() => {
    if (cvId === null && confirmed.length) setCvId(confirmed[0].id);
  }, [confirmed, cvId]);
  useEffect(() => {
    if (cvId === null) return;
    api.searchSuggestions(cvId).then((s) => {
      setTitles(s.titles.join("\n"));
      setSources(s.sources);
      setChosen(new Set(s.sources.filter((x) => x.default && !x.missing_env.length).map((x) => x.key)));
    });
  }, [cvId]);

  if (cvs.data && !confirmed.length) {
    return (
      <Section title="Search" eyebrow="Start here">
        <p>
          First add your CV and confirm it. <Link to="/cvs">Go to CVs →</Link>
        </p>
      </Section>
    );
  }

  return (
    <Section title="Search" eyebrow="No AI costs">
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          if (cvId === null) return;
          const result = await action.run(() =>
            api.createSearch({
              cv_id: cvId,
              titles: titles.split("\n").map((t) => t.trim()).filter(Boolean),
              requirements: toRequirements(reqs),
              sources: [...chosen],
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
        <label>
          Job titles (one per line, suggested from your CV)
          <textarea rows={4} value={titles} onChange={(e) => setTitles(e.target.value)} />
        </label>
        <RequirementsEditor value={reqs} onChange={setReqs} />
        <p className="hint">
          Cities are searched with a radius. A must-have hides listings that clearly contradict it;
          hidden listings stay one click away.
        </p>
        <fieldset className="requirements">
          <legend>Sources</legend>
          {sources.map((s) => (
            <label key={s.key} className="check" title={s.home}>
              <input
                type="checkbox"
                checked={chosen.has(s.key)}
                disabled={s.missing_env.length > 0}
                onChange={() =>
                  setChosen((c) => {
                    const next = new Set(c);
                    if (next.has(s.key)) next.delete(s.key);
                    else next.add(s.key);
                    return next;
                  })
                }
              />
              {s.label}
              {s.remote_only && <span className="muted">remote</span>}
              {s.missing_env.length > 0 && (
                <span className="muted">needs {s.missing_env.join(", ")}</span>
              )}
            </label>
          ))}
        </fieldset>
        <ErrorNote error={action.error} />
        <Button
          type="submit"
          variant="glow"
          sparkle
          loading={action.busy}
          disabled={!titles.trim() || chosen.size === 0}
        >
          Search
        </Button>
      </form>
    </Section>
  );
}

function History({ current, onDeleted }: { current: number | null; onDeleted: () => void }) {
  const searches = useResource(() => api.searches(), [current]);
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
          {search ? (
            <Results search={search} onChanged={() => setNonce((n) => n + 1)} />
          ) : (
            <p className="empty">Run a search to see listings ranked against your CV.</p>
          )}
        </div>
        <div className="stack">
          <SearchForm
            onSearched={(s) => {
              setSearch(s);
              setParams({ id: String(s.id) });
            }}
          />
          <History current={id} onDeleted={() => setParams({})} />
        </div>
      </div>
    </div>
  );
}
