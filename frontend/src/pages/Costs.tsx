import { GlassCard, GradientText } from "performative-ui";
import { Link } from "react-router";
import { api } from "../api";
import { AnimatedNumber } from "../components/AnimatedNumber";
import { ErrorNote, Section } from "../components/ui";
import { STEP_NAMES, usd, when } from "../format";
import { useLive, useResource } from "../live";

function Bars({ rows }: { rows: { label: string; value: number; extra?: string; href?: string }[] }) {
  const max = Math.max(...rows.map((r) => r.value), 0.0001);
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="bars__row" key={r.label}>
          <span className="bars__label">{r.href ? <Link to={r.href}>{r.label}</Link> : r.label}</span>
          <span className="bars__track">
            <span className="bars__fill" style={{ width: `${(r.value / max) * 100}%` }} />
          </span>
          <span className="bars__value mono">
            {usd(r.value)}
            {r.extra && <span className="muted"> · {r.extra}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Costs() {
  const { version } = useLive();
  const costs = useResource(() => api.costs(), [version("any")]);
  const runs = useResource(() => api.runs(), [version("any")]);
  if (!costs.data) return <div className="page"><ErrorNote error={costs.error} /></div>;
  const c = costs.data;
  const days = c.last_30_days;
  const dayMax = Math.max(...days.map((d) => d.cost_usd), 0.0001);
  const topRuns = [...(runs.data ?? [])].sort((a, b) => b.cost_usd - a.cost_usd).slice(0, 8);

  return (
    <div className="page">
      <div className="hero">
        <h1>
          <GradientText>Model costs</GradientText>
        </h1>
        <p className="hero__sub">
          Every Claude call is recorded with model, step and tokens. Deleting applications keeps their costs here.
        </p>
      </div>

      <div className="stat-grid">
        {[
          ["Today", c.today_usd],
          ["This month", c.month_usd],
          ["Total", c.total_usd],
        ].map(([label, value]) => (
          <GlassCard key={label as string} className="stat" breathing={label === "Today"}>
            <span className="stat__label">{label}</span>
            <span className="stat__value">
              <AnimatedNumber value={value as number} format={(n) => usd(n, 2)} />
            </span>
          </GlassCard>
        ))}
        <GlassCard className="stat">
          <span className="stat__label">Last call</span>
          <span className="stat__small">
            {c.last_call ? (
              <>
                {STEP_NAMES[c.last_call.step] ?? c.last_call.step} · {c.last_call.model}
                <br />
                {usd(c.last_call.cost_usd)} · {when(c.last_call.at)}
              </>
            ) : (
              "none yet"
            )}
          </span>
        </GlassCard>
      </div>

      <Section title="Last 30 days">
        <div className="spark" role="img" aria-label="Daily cost, last 30 days">
          {days.map((d) => (
            <span key={d.date} className="spark__bar" style={{ height: `${Math.max(2, (d.cost_usd / dayMax) * 100)}%` }} title={`${d.date}: ${usd(d.cost_usd)}`} />
          ))}
        </div>
      </Section>

      <div className="grid-2">
        <Section title="By model">
          <Bars rows={c.by_model.map((m) => ({ label: m.name, value: m.cost_usd, extra: `${m.calls} calls` }))} />
        </Section>
        <Section title="By step">
          <Bars rows={c.by_step.map((s) => ({ label: STEP_NAMES[s.step] ?? s.step, value: s.cost_usd, extra: `${s.calls}×` }))} />
        </Section>
      </div>

      <Section title="Most expensive applications">
        <Bars rows={topRuns.map((r) => ({ label: r.title, value: r.cost_usd, href: `/runs/${r.id}` }))} />
        {!topRuns.length && <p className="hint">No applications yet.</p>}
      </Section>
    </div>
  );
}
