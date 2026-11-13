import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { Pipeline } from "../components/Pipeline";
import {
  EMPTY_REQUIREMENTS,
  RequirementsEditor,
  type RequirementsForm,
  fromRequirements,
  toRequirements,
} from "../components/RequirementsEditor";
import { StatusBadge } from "../components/ui";
import { AbortFetch } from "../pages/run/RunPage";
import { duration, tone, usd } from "../format";
import type { Stage } from "../types";

describe("requirements form", () => {
  it("round-trips the API requirements", () => {
    const reqs = toRequirements({
      ...EMPTY_REQUIREMENTS,
      salary_min: 90000,
      salary_min_must: true,
      max_onsite_days: 2,
      remote_ok: false,
      work_must: true,
      places: [
        { name: "Nürnberg", km: 30 },
        { name: "Fürth", km: 10 },
      ],
      wishes: [
        { value: "30 days vacation", must: true, on: true },
        { value: "Hardware budget", must: false, on: true },
        { value: "Dog-friendly", must: false, on: false },
      ],
    });
    expect(reqs).toEqual([
      { kind: "salary_min", value: "90000", must_have: true },
      { kind: "max_onsite_days", value: "2", must_have: true },
      { kind: "remote", value: "no", must_have: true },
      { kind: "location", value: "Nürnberg (30 km), Fürth (10 km)", must_have: false },
      { kind: "other", value: "30 days vacation", must_have: true },
      { kind: "other", value: "Hardware budget", must_have: false },
    ]);
    const form = fromRequirements(reqs, [{ kind: "other", value: "Dog-friendly", must_have: false }]);
    expect(form.salary_min).toBe(90000);
    expect(form.remote_ok).toBe(false);
    expect(form.places).toEqual([
      { name: "Nürnberg", km: 30 },
      { name: "Fürth", km: 10 },
    ]);
    expect(form.wishes.map((w) => [w.value, w.must, w.on])).toEqual([
      ["30 days vacation", true, true],
      ["Hardware budget", false, true],
      ["Dog-friendly", false, false],
    ]);
  });

  it("reads older free-text values", () => {
    const form = fromRequirements([
      { kind: "salary_min", value: "250k", must_have: false },
      { kind: "max_onsite_days", value: "5", must_have: false },
      { kind: "location", value: "Berlin, Hamburg", must_have: true },
    ]);
    expect(form.salary_min).toBe(200000);
    expect(form.max_onsite_days).toBeNull();
    expect(form.places).toEqual([
      { name: "Berlin", km: 30 },
      { name: "Hamburg", km: 30 },
    ]);
    // Remote only: "remote not wanted" makes no sense and is left out.
    expect(toRequirements({ ...EMPTY_REQUIREMENTS, max_onsite_days: 0, remote_ok: false })).toEqual([
      { kind: "max_onsite_days", value: "0", must_have: false },
    ]);
  });

  it("adds wishes and cities as chips", () => {
    let value = EMPTY_REQUIREMENTS;
    const onChange = vi.fn((v: RequirementsForm) => (value = v));
    const { rerender } = render(<RequirementsEditor value={value} onChange={onChange} />);
    const again = () => rerender(<RequirementsEditor value={value} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Add a must-have or nice-to-have"), { target: { value: "Car" } });
    again();
    fireEvent.click(screen.getByRole("button", { name: "Must-have" }));
    again();
    expect(value.wishes).toEqual([{ value: "Car", must: true, on: true }]);
    fireEvent.click(screen.getByRole("button", { name: "Car" }));
    again();
    expect(value.wishes[0].on).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "must" }));
    again();
    expect(value.wishes[0].must).toBe(false);

    fireEvent.change(screen.getByLabelText("Add a city"), { target: { value: "Fürth, Erlangen" } });
    again();
    fireEvent.click(screen.getByRole("button", { name: "Add city" }));
    again();
    fireEvent.change(screen.getByLabelText("Radius around Fürth"), { target: { value: "10" } });
    again();
    fireEvent.click(screen.getByRole("button", { name: "Remove Erlangen" }));
    again();
    expect(value.places).toEqual([{ name: "Fürth", km: 10 }]);

    fireEvent.change(screen.getByLabelText("Min. salary"), { target: { value: "75000" } });
    again();
    expect(screen.getByText("75k EUR / year")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Onsite days"), { target: { value: "0" } });
    again();
    expect(screen.getByText("remote only", { selector: ".req-block__value" })).toBeInTheDocument();
    expect(screen.getByLabelText("Fully remote jobs are fine")).toBeDisabled();
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

describe("abort a listing download", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks the API to stop the download", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response("{}", { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AbortFetch runId={5} />);
    fireEvent.click(screen.getByRole("button", { name: "Abort" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBe("/api/runs/5/abort-fetch");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
  });
});
