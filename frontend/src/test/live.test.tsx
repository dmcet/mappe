import { act, render, screen } from "@testing-library/react";
import { LiveProvider, STALE_MS, useLive } from "../live";

/** Minimal EventSource stand-in: tests drive open/error/messages by hand. */
class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, fn: (e: MessageEvent) => void) {
    (this.listeners[name] ??= []).push(fn);
  }
  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }
  fail(closed: boolean) {
    this.readyState = closed ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
    this.onerror?.();
  }
  send(runs: number[] = []) {
    const data = JSON.stringify({ jobs: [], changed: { runs, cvs: [] } });
    this.listeners.status?.forEach((fn) => fn({ data } as MessageEvent));
  }
}

function Probe() {
  const { version, connected } = useLive();
  return (
    <span data-testid="probe">
      {connected ? "on" : "off"} {version("run", 7)}
    </span>
  );
}

const probe = () => screen.getByTestId("probe").textContent;
const latest = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];

describe("live stream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    render(
      <LiveProvider>
        <Probe />
      </LiveProvider>,
    );
    act(() => latest().open());
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("bumps the version of a changed run", () => {
    act(() => latest().send([7]));
    expect(probe()).toBe("on 1");
    act(() => latest().send([8]));
    expect(probe()).toBe("on 1");
  });

  it("reconnects when the browser gives up, and refetches everything", () => {
    const before = probe();
    act(() => latest().fail(true)); // e.g. aborted by a click on a download link
    expect(probe()?.startsWith("off")).toBe(true);
    act(() => vi.advanceTimersByTime(1_000));
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => latest().open());
    expect(probe()).not.toBe(before);
    expect(probe()?.startsWith("on")).toBe(true);
  });

  it("leaves retrying to the browser while it is still connecting", () => {
    act(() => latest().fail(false));
    act(() => vi.advanceTimersByTime(5_000));
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("replaces a connection that went silent", () => {
    act(() => vi.advanceTimersByTime(STALE_MS - 5_000));
    act(() => latest().send());
    act(() => vi.advanceTimersByTime(STALE_MS - 5_000));
    expect(FakeEventSource.instances).toHaveLength(1); // messages keep it alive
    act(() => vi.advanceTimersByTime(STALE_MS));
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[0].readyState).toBe(FakeEventSource.CLOSED);
  });
});
