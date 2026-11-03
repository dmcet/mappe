import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { Pipeline } from "../components/Pipeline";
import { fromRequirements, toRequirements, EMPTY_REQUIREMENTS } from "../components/RequirementsEditor";
import { StatusBadge } from "../components/ui";
import { duration, tone, usd } from "../format";
import type { Stage } from "../types";

describe("requirements form", () => {
  it("round-trips the API requirements", () => {
    const reqs = toRequirements({
      ...EMPTY_REQUIREMENTS,
      salary_min: " 90000 ",
      salary_min_must: true,
      location: "Nürnberg, Fürth",
      must_other: "30 days vacation\n",
      nice_other: "Hardware budget\nEGYM Wellpass",
    });
    expect(reqs).toEqual([
      { kind: "salary_min", value: "90000", must_have: true },
      { kind: "location", value: "Nürnberg, Fürth", must_have: false },
      { kind: "other", value: "30 days vacation", must_have: true },
      { kind: "other", value: "Hardware budget", must_have: false },
      { kind: "other", value: "EGYM Wellpass", must_have: false },
    ]);
    const form = fromRequirements(reqs);
    expect(form.salary_min_must).toBe(true);
    expect(form.nice_other).toBe("Hardware budget\nEGYM Wellpass");
  });
});

describe("pipeline", () => {
  const stages: Stage[] = [
    { key: "parse", label: "Read listing", state: "done", hint: "" },
    { key: "review", label: "Review loop", state: "active", hint: "draft 2" },
    { key: "final", label: "Your review", state: "pending", hint: "" },
  ];

  it("shows the live job detail on the active stage", () => {
    render(
      <Pipeline
        stages={stages}
        job={{ kind: "run", id: 1, title: "x", phase: "reviewing", detail: "Claude · Recruiter review", model: "claude-opus-5-5", draft: 2, elapsed_s: 3, detail_elapsed_s: 1 }}
      />,
    );
    expect(screen.getByText("Claude · Recruiter review")).toBeInTheDocument();
    expect(screen.getByText("Review loop").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("✓")).toBeInTheDocument();
  });

  it("falls back to the stage hint without a job", () => {
    render(<Pipeline stages={stages} />);
    expect(screen.getByText("draft 2")).toBeInTheDocument();
  });
});

describe("formatting", () => {
  it("formats money, durations and status tones", () => {
    expect(usd(0.0421)).toBe("$0.042");
    expect(usd(1.8)).toBe("$1.80");
    expect(duration(75)).toBe("1m 15s");
    expect(tone("stopped_by_requirements")).toBe("you");
    expect(tone("failed")).toBe("bad");
    render(
      <MemoryRouter>
        <StatusBadge status="waiting_for_final_review" />
      </MemoryRouter>,
    );
    expect(screen.getByText("Your final review")).toBeInTheDocument();
  });
});
