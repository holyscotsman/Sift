// The library-health score and the "needs your attention" list.
//
// The score is the first number anybody sees, and the page's own comment calls it
// "deterministic, auditable" — start at 100, subtract named deductions, show
// every one. None of that had a test; Dashboard.test.tsx covers only the failed
// status read.
//
// The `COUNTS` fixture there also invents `watched`/`unwatched` and omits four
// real fields of `Counts`. The one below names every field as the interface does.

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { resetSharedCache } from "@/lib/hooks";
import { Dashboard } from "@/pages/Dashboard";
import { renderPage } from "@/test/harness";

function counts(overrides: Record<string, unknown> = {}) {
  return {
    movies: 1000,
    owned: 1000,
    monitored: 900,
    collections: 20,
    watch_records: 5000,
    watched_titles: 400,
    actions_pending: 0,
    upgrades: 0,
    junk_flagged: 0,
    musthave_pending: 0,
    ...overrides,
  };
}

function settings(overrides: Record<string, unknown> = {}) {
  return {
    connections: [],
    thresholds: {},
    ai_configured: true,
    ai_compare_available: false,
    actions_dry_run: true,
    database_kind: "postgres",
    ephemeral_risk: false,
    secrets_encrypted: true,
    scan_interval_hours: 0,
    ...overrides,
  };
}

function mount(over: { counts?: unknown; settings?: unknown; status?: unknown } = {}) {
  vi.spyOn(api, "health").mockResolvedValue({ services: [] } as never);
  vi.spyOn(api, "activity").mockResolvedValue([] as never);
  vi.spyOn(api, "movies").mockResolvedValue({ items: [], total: 0 } as never);
  vi.spyOn(api, "getSettings").mockResolvedValue((over.settings ?? settings()) as never);
  vi.spyOn(api, "status").mockResolvedValue({
    scanning: false,
    last_scan_id: 1,
    last_scan_status: "completed",
    last_scan_finished_at: null,
    counts: over.counts ?? counts(),
    ...(over.status ?? {}),
  } as never);
}

describe("the library health score", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetSharedCache();
  });

  it("names every point it takes off", async () => {
    // A score with unexplained deductions is a number somebody has to trust
    // rather than check, which is the opposite of what this screen is for.
    mount({ counts: counts({ junk_flagged: 100, upgrades: 100 }) });

    renderPage(<Dashboard />);

    await screen.findByText("100 junk candidates");
    expect(screen.getByText("−8")).toBeTruthy(); // 100/1000 × 80
    expect(screen.getByText("100 below quality cutoff")).toBeTruthy();
    expect(screen.getByText("−4")).toBeTruthy(); // 100/1000 × 40
  });

  it("scales the junk deduction to the size of the library", async () => {
    // Fifty junk candidates in a library of a hundred is a different problem from
    // fifty in five thousand. A raw count would score the small library the same.
    mount({ counts: counts({ movies: 100, owned: 100, junk_flagged: 50 }) });

    renderPage(<Dashboard />);

    // 50/100 × 80 = 40, and the cap is 40, so this is as bad as junk gets.
    await screen.findByText("−40");
    // 100 − 40 = 60. Against a thousand-title library the same fifty would cost
    // four points and still read "Excellent".
    expect(screen.getByText("Good standing")).toBeTruthy();
  });

  it("caps how far one problem can drag the score down", async () => {
    // NEGATIVE CONTROL for the scaling: uncapped, a library that is 90% junk
    // would deduct 72 points for that alone and leave no room for anything else
    // to register. The cap keeps every other signal visible.
    mount({ counts: counts({ movies: 100, owned: 100, junk_flagged: 90 }) });

    renderPage(<Dashboard />);

    await screen.findByText("90 junk candidates");
    expect(screen.getByText("−40")).toBeTruthy(); // not −72
  });

  it("says so plainly when there is nothing to deduct", async () => {
    mount();

    renderPage(<Dashboard />);

    await screen.findByText(/No deductions — nothing flagged, nothing missing/);
    expect(screen.getByText("Excellent standing")).toBeTruthy();
  });

  it("refuses to score an empty library rather than scoring it perfect", async () => {
    // NEGATIVE CONTROL, and the direction matters. With no titles there are no
    // deductions, so a naive 100 − 0 would tell somebody who has never scanned
    // that their library is in excellent health.
    mount({ counts: counts({ movies: 0, owned: 0 }) });

    renderPage(<Dashboard />);

    await screen.findByText("No data standing");
    expect(screen.queryByText("Excellent standing")).toBeNull();
  });

  it("counts one candidate as a candidate", async () => {
    // Twenty titles, not a thousand: one candidate in a thousand rounds to zero
    // points and never produces a line at all.
    mount({ counts: counts({ movies: 20, owned: 20, junk_flagged: 1 }) });

    renderPage(<Dashboard />);

    await screen.findByText("1 junk candidate");
    expect(screen.queryByText("1 junk candidates")).toBeNull();
  });
});

describe("needs your attention", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetSharedCache();
  });

  const OFF = { service: "tmdb", ok: false, detail: "not configured", latency_ms: null };
  const DOWN = { service: "tmdb", ok: false, detail: "connection refused", latency_ms: null };

  it("asks you to connect a service that was never set up", async () => {
    mount({ settings: settings({ connections: [OFF] }) });

    renderPage(<Dashboard />);

    await screen.findByText(/TMDB isn't connected/);
  });

  it("NEGATIVE CONTROL: a configured service that is merely down is not a setup task", async () => {
    // The page comment states this outright — "unconfigured ≠ unreachable". A
    // "connect TMDB" card shown every time the box is off is a card that teaches
    // people to ignore the panel, and the panel is how real problems surface.
    mount({ settings: settings({ connections: [DOWN] }) });

    renderPage(<Dashboard />);

    await screen.findByText("No deductions — nothing flagged, nothing missing.");
    expect(screen.queryByText(/TMDB isn't connected/)).toBeNull();
  });

  it("puts work you can do above setup you might do", async () => {
    // Reviewing a junk queue changes the library today. Connecting Tautulli is
    // housekeeping. Ordered the other way, the actionable item is below the fold.
    mount({
      counts: counts({ junk_flagged: 5 }),
      settings: settings({
        connections: [{ service: "tautulli", ok: false, detail: "disabled", latency_ms: null }],
      }),
    });

    renderPage(<Dashboard />);

    await screen.findByText(/5 titles flagged for review/);
    const texts = screen
      .getAllByText(/flagged for review|Tautulli isn't connected/)
      .map((el) => el.textContent ?? "");
    expect(texts[0]).toContain("flagged for review");
    expect(texts[1]).toContain("Tautulli");
  });

  it("flags an ephemeral database, because the symptom is losing your login", async () => {
    // SQLite on a disk that resets is not a performance note: it silently drops
    // the account and every stored key on the next redeploy, and the only visible
    // symptom is being logged out for no reason.
    mount({ settings: settings({ ephemeral_risk: true }) });

    renderPage(<Dashboard />);

    await screen.findByText(/login and settings reset on redeploy/);
  });
});

describe("snapshot freshness", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetSharedCache();
  });

  // Real timers, with the timestamp measured back from now: faking the clock here
  // fights the effects and the polling hooks for no gain, since the property is
  // relative and the fixture can be too.
  const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

  it("warns once the snapshot has outlived twice the rescan interval", async () => {
    mount({
      settings: settings({ scan_interval_hours: 6 }),
      status: { last_scan_finished_at: hoursAgo(13) },
    });

    renderPage(<Dashboard />);

    await screen.findByText(/snapshot may be stale/);
  });

  it("NEGATIVE CONTROL: one missed rescan is not yet stale", async () => {
    // Nine hours against a six-hour interval: past due, but inside the doubled
    // window. Deliberately not three hours — three is under the interval as well
    // as under twice it, so it would pass against a threshold of either, and the
    // "twice" is the whole point. One skipped rescan is a laptop that was asleep;
    // two is a snapshot worth doubting.
    mount({
      settings: settings({ scan_interval_hours: 6 }),
      status: { last_scan_finished_at: hoursAgo(9) },
    });

    renderPage(<Dashboard />);

    await screen.findByText(/refreshed 9 h ago/);
    expect(screen.queryByText(/may be stale/)).toBeNull();
  });

  it("never calls a snapshot stale when no rescan interval is set", async () => {
    // NEGATIVE CONTROL for the arithmetic: with the interval at 0, a naive
    // `hoursSince(finished) > interval * 2` is true for every snapshot ever
    // taken, and the warning would be permanent on any install that has not set
    // one. The guard is `interval > 0`.
    mount({
      settings: settings({ scan_interval_hours: 0 }),
      status: { last_scan_finished_at: hoursAgo(9000) },
    });

    renderPage(<Dashboard />);

    await screen.findByText(/refreshed/);
    expect(screen.queryByText(/may be stale/)).toBeNull();
  });
});
