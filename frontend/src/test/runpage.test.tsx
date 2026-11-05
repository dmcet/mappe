import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { LiveContext } from "../live";
import { POLL_MS, RunPage } from "../pages/run/RunPage";

const run = (status: string, active: boolean) => ({
  id: 7,
  cv_id: 1,
  title: "Python Developer · Acme",
  company: "Acme",
  listing_url: null,
  status,
  error: null,
  verdict: null,
  score: null,
  cost_usd: 0,
  created_at: "2026-11-05T19:00:00",
  updated_at: "2026-11-05T19:00:00",
  pipeline: [{ key: "deliver", label: "Deliver", state: active ? "active" : "done", hint: "" }],
  requirements: [],
  has_listing_text: true,
  previous_status: null,
  state: {},
  facts: {},
  events: [],
  usage: [],
});

function page(connected: boolean) {
  return (
    <LiveContext.Provider value={{ status: null, connected, version: () => 0 }}>
      <MemoryRouter initialEntries={["/runs/7"]}>
        <Routes>
          <Route path="/runs/:id" element={<RunPage />} />
        </Routes>
      </MemoryRouter>
    </LiveContext.Provider>
  );
}

describe("run page without the live stream", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("polls a working run until it is done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const answers = [run("delivering", true), run("done", false)];
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(answers.shift() ?? run("done", false))));
    vi.stubGlobal("fetch", fetchMock);
    render(page(false));
    expect(await screen.findByText("Python Developer · Acme")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {}); // let the polling effect start
    await act(async () => vi.advanceTimersByTime(POLL_MS));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTime(POLL_MS * 3));
    expect(fetchMock).toHaveBeenCalledTimes(2); // done: polling stopped
  });

  it("doesn't poll while the stream is connected", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(run("delivering", true))));
    vi.stubGlobal("fetch", fetchMock);
    render(page(true));
    await screen.findByText("Python Developer · Acme");
    await act(async () => {});
    await act(async () => vi.advanceTimersByTime(POLL_MS * 3));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
