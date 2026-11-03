import { Link } from "react-router";
import { usd } from "../format";
import { useLive } from "../live";
import { useAnimatedNumber } from "./AnimatedNumber";

/** The model costs, always visible in the header. Links to the cost breakdown. */
export function CostMeter() {
  const { status } = useLive();
  const total = useAnimatedNumber(status?.costs.total_usd ?? 0);
  const today = useAnimatedNumber(status?.costs.today_usd ?? 0);
  const busy = (status?.jobs ?? []).some((j) => j.model);
  return (
    <Link to="/costs" className={`cost-meter${busy ? " cost-meter--busy" : ""}`} title="Model costs: details">
      <span className="cost-meter__label">today</span>
      <span className="cost-meter__value">{usd(today, 2)}</span>
      <span className="cost-meter__sep" />
      <span className="cost-meter__label">total</span>
      <span className="cost-meter__value cost-meter__value--total">{usd(total, 2)}</span>
    </Link>
  );
}
