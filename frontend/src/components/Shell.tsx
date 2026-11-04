import { Aurora, GradientText, Sparkle, StickyBanner } from "performative-ui";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { useLive } from "../live";
import { CostMeter } from "./CostMeter";
import { LiveStatus } from "./LiveStatus";

export function Shell({ children }: { children: ReactNode }) {
  const { status } = useLive();
  return (
    <div className="shell pui-theme">
      <Aurora className="shell__aurora" aria-hidden="true" />
      {status?.demo && (
        <StickyBanner className="demo-banner">
          Demo mode: Claude is not called, every CV and listing is sample data.
        </StickyBanner>
      )}
      <header className="topbar">
        <div className="topbar__row">
          <NavLink to="/" className="brand">
            <Sparkle glyph="✦" />
            <GradientText className="brand__name">Mappe</GradientText>
          </NavLink>
          <nav className="topbar__nav">
            <NavLink to="/" end>
              Applications
            </NavLink>
            <NavLink to="/search">Find jobs</NavLink>
            <NavLink to="/cvs">CVs</NavLink>
            <NavLink to="/costs">Costs</NavLink>
          </nav>
          <CostMeter />
        </div>
        <LiveStatus />
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
