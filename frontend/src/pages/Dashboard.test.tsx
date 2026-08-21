// The home screen. When the database stopped answering, this page said "No
// snapshot yet — run a scan to build one" — advice that cannot work, offered at
// the exact moment nothing could. That is what "the app is completely broken"
// looked like from the browser.

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { resetSharedCache } from "@/lib/hooks";
import { Dashboard } from "@/pages/Dashboard";
import { renderPage } from "@/test/harness";

// Named as `Counts` names them. The first version invented `watched`/`unwatched`
// and omitted `collections`, `watch_records`, `watched_titles` and
// `actions_pending`; `as never` at the call site meant nothing complained.
const COUNTS = {
  movies: 0,
  owned: 0,
  monitored: 0,
  collections: 0,
  watch_records: 0,
  watched_titles: 0,
  actions_pending: 0,
  upgrades: 0,
  junk_flagged: 0,
  musthave_pending: 0,
};

beforeEach(() => {
  vi.restoreAllMocks();
  // `useStatus`/`useHealth` share results through a module-level window that
  // outlives a test, so without this the second test reads the first one's data.
  resetSharedCache();
  vi.spyOn(api, "health").mockResolvedValue({ services: [] } as never);
  vi.spyOn(api, "activity").mockResolvedValue([] as never);
  vi.spyOn(api, "getSettings").mockResolvedValue({
    connections: [],
    actions_dry_run: true,
    scan_interval_hours: 0,
  } as never);
  vi.spyOn(api, "movies").mockResolvedValue({ items: [], total: 0 } as never);
});

describe("when the status read fails", () => {
  it("names the failure instead of advising a scan", async () => {
    vi.spyOn(api, "status").mockRejectedValue(
      new Error("The database is not accepting queries right now."),
    );

    renderPage(<Dashboard />);

    expect(await screen.findByText(/database is not accepting queries/i)).toBeInTheDocument();
    expect(screen.queryByText(/run a scan to build one/i)).not.toBeInTheDocument();
  });
});

describe("NEGATIVE CONTROL: a genuinely empty library", () => {
  it("still says to run a scan", async () => {
    vi.spyOn(api, "status").mockResolvedValue({
      scanning: false,
      last_scan_id: null,
      last_scan_status: null,
      last_scan_finished_at: null,
      counts: COUNTS,
    } as never);

    renderPage(<Dashboard />);

    // A dashboard that showed an error whenever the library was empty would pass
    // the test above and be a different, equally wrong screen.
    expect(await screen.findByText(/run a scan to build one/i)).toBeInTheDocument();
  });
});
