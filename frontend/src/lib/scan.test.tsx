// Scan progress has two independent sources, and the comment in `scan.tsx` says
// which one is load-bearing:
//
//   "A socket error/close is NOT the end — the poller below is the source of
//    truth, so progress still completes even if the WS is blocked."
//
// That was untested. A websocket is the first thing a corporate proxy, a
// tunnel, or a hosted platform's edge will drop, and if the fallback does not
// carry the scan on its own the bar sits still — which reads as a crash, and
// gets reported as one.

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { api } from "@/lib/api";
import { ScanProvider, useScan } from "@/lib/scan";

// Captured so a test can decide what the socket does — including nothing at all,
// which is the case that matters most.
let sockets: FakeSocket[] = [];

class FakeSocket {
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    sockets.push(this);
  }
  deliver(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function Probe() {
  const { scanning, pct, phaseStates, error, start } = useScan();
  return (
    <div>
      <button onClick={() => void start()}>go</button>
      <span data-testid="pct">{pct}</span>
      <span data-testid="scanning">{String(scanning)}</span>
      <span data-testid="error">{error ?? ""}</span>
      <span data-testid="plex">{phaseStates.plex}</span>
    </div>
  );
}

function renderProbe() {
  return render(
    <MemoryRouter>
      <ScanProvider>
        <Probe />
      </ScanProvider>
    </MemoryRouter>,
  );
}

function run(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    status: "running",
    error: null,
    checkpoints: {},
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  sockets = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.spyOn(api, "scanStart").mockResolvedValue({ scan_run_id: 1, resume: false } as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("when the websocket never delivers anything", () => {
  it("still finishes the scan from the poller alone", async () => {
    // The whole reason the fallback exists. The socket opens and stays silent,
    // which is exactly what a proxy that swallows upgrades looks like.
    const get = vi
      .spyOn(api, "scanGet")
      .mockResolvedValueOnce(run({ checkpoints: { preflight: { status: "done" } } }) as never)
      .mockResolvedValue(run({ status: "completed" }) as never);

    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "go" }));

    await waitFor(() => expect(get).toHaveBeenCalled());
    // Deliberately waiting past the 1.5s poll interval: the first poll reports
    // the scan still running, so reaching "completed" requires the interval to
    // have fired again. A shorter wait would pass on a single poll and prove
    // nothing about the loop that carries a blocked-websocket scan to the end.
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(1), { timeout: 4000 });
    await waitFor(() => expect(screen.getByTestId("scanning").textContent).toBe("false"));
    expect(screen.getByTestId("pct").textContent).toBe("100");
    // And the socket really was silent — otherwise this proves nothing about
    // the poller.
    expect(sockets).toHaveLength(1);
    expect(sockets[0].onmessage).toBeTypeOf("function");
  });

  it("NEGATIVE CONTROL: a failed poll does not end the scan", async () => {
    // Transient failures are expected — a free-tier instance waking up returns
    // errors for a few seconds. Treating one as terminal would abandon a scan
    // that is still running perfectly well.
    vi.spyOn(api, "scanGet").mockRejectedValue(new Error("502"));

    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "go" }));

    await waitFor(() => expect(screen.getByTestId("scanning").textContent).toBe("true"));
    expect(screen.getByTestId("error").textContent).toBe("");
  });
});

describe("when the websocket is working", () => {
  it("moves the phase and the dial as events arrive", async () => {
    vi.spyOn(api, "scanGet").mockResolvedValue(run() as never);

    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(sockets).toHaveLength(1));

    act(() => {
      sockets[0].deliver({
        event: "progress",
        phase: "plex",
        phase_index: 1,
        total_phases: 10,
        status: "running",
        counts: {},
      });
    });

    await waitFor(() => expect(screen.getByTestId("plex").textContent).toBe("active"));
    expect(Number(screen.getByTestId("pct").textContent)).toBeGreaterThan(0);
  });

  it("never lets the dial go backwards", async () => {
    // Two sources write to the same number and they do not agree moment to
    // moment. A bar that jumps back looks broken even while everything is fine,
    // which is why both writers clamp with Math.max.
    vi.spyOn(api, "scanGet").mockResolvedValue(run() as never);

    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(sockets).toHaveLength(1));

    act(() => {
      sockets[0].deliver({
        event: "progress",
        phase: "score",
        phase_index: 8,
        total_phases: 10,
        status: "done",
        counts: {},
      });
    });
    await waitFor(() => expect(Number(screen.getByTestId("pct").textContent)).toBeGreaterThan(80));
    const high = Number(screen.getByTestId("pct").textContent);

    act(() => {
      sockets[0].deliver({
        event: "progress",
        phase: "plex",
        phase_index: 1,
        total_phases: 10,
        status: "running",
        counts: {},
      });
    });

    expect(Number(screen.getByTestId("pct").textContent)).toBe(high);
  });

  it("reports a terminal failure rather than leaving the scan running", async () => {
    vi.spyOn(api, "scanGet").mockResolvedValue(run() as never);

    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(sockets).toHaveLength(1));

    act(() => {
      sockets[0].deliver({ event: "terminal", status: "failed", error: "Plex refused" });
    });

    await waitFor(() => expect(screen.getByTestId("error").textContent).toBe("Plex refused"));
    expect(screen.getByTestId("scanning").textContent).toBe("false");
  });
});

describe("starting a scan twice", () => {
  it("joins the one already running instead of racing a second", async () => {
    // The wizard auto-starts a scan silently and the dashboard button is right
    // there. Two scans against one library is not a thing anyone wants.
    const start = vi.spyOn(api, "scanStart");
    vi.spyOn(api, "scanGet").mockResolvedValue(run() as never);

    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: "go" }));
    expect(start).toHaveBeenCalledTimes(1);
  });
});
