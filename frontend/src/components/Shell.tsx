import { Aurora, GradientText, Sparkle, StickyBanner } from "performative-ui";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { useLive } from "../live";
import { CostMeter } from "./CostMeter";
import { LiveStatus } from "./LiveStatus";

// Navy and gray instead of the library's default violet, pink and cyan blobs.
const AURORA = [
  { color: "rgba(31, 58, 104, 0.5)", x: 20, y: 30, size: 60 },
  { color: "rgba(70, 76, 88, 0.3)", x: 80, y: 25, size: 50 },
  { color: "rgba(61, 95, 146, 0.25)", x: 50, y: 80, size: 55 },
];

export function Shell({ children }: { children: ReactNode }) {
  const { status } = useLive();
  return (
    <div className="shell pui-theme">
      <Aurora className="shell__aurora" blobs={AURORA} aria-hidden="true" />
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
