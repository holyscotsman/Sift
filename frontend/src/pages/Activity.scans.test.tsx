// The scan history and the filters — the half of the trust surface that was not
// under test.
//
// Activity.test.tsx pins the two things the page must never say: that nothing
// happened when the fetch failed, and that a staged action was executed. What it
// does not touch is the scan panel (which is how anyone finds out *why* a scan
// produced the numbers it did), the type filters, or the growing window.

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Activity } from "@/pages/Activity";
import { renderPage } from "@/test/harness";

// Named as `ScanRun` names them.
function scan(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    status: "completed",
    started_at: "2026-08-21T10:00:00Z",
    finished_at: "2026-08-21T10:02:30Z",
    checkpoints: {
      plex: { status: "done", counts: { movies: 1200 } },
      radarr: { status: "done", counts: { movies: 1180 } },
    },
    stats: { total_movies: 1200, in_plex: 1150 },
    error: null,
    ...overrides,
  };
}

function action(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    type: "delete",
    status: "executed",
    actor: "user",
    dry_run: false,
    movie_tmdb_id: 603,
    payload: { title: "The Matrix" },
    created_at: "2026-08-21T11:00:00Z",
    error: null,
    ...overrides,
  };
}

describe("the scan panel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "activity").mockResolvedValue([] as never);
  });

  it("reports how long a run took and what it found", async () => {
    vi.spyOn(api, "scanList").mockResolvedValue([scan()] as never);

    renderPage(<Activity />);

    await screen.findByText("completed");
    expect(screen.getByText(/2m 30s/)).toBeTruthy();
    expect(screen.getByText(/1,200 titles · 1,150 in Plex/)).toBeTruthy();
  });

  it("marks a run still going rather than reporting a duration it does not have", async () => {
    // NEGATIVE CONTROL: `finished_at` is null while a scan runs. Subtracting from
    // null gives NaN, and "NaNm NaNs" beside a running scan reads as a crash.
    vi.spyOn(api, "scanList").mockResolvedValue([
      scan({ status: "running", finished_at: null }),
    ] as never);

    renderPage(<Activity />);

    await screen.findByText("running");
    expect(screen.getByText(/…/)).toBeTruthy();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("keeps the phase detail folded away until it is asked for", async () => {
    // A run has a phase line each for Plex, Radarr, Sonarr, Tautulli, TMDB and
    // more. Five runs unfolded is a wall; the summary is what is normally wanted.
    vi.spyOn(api, "scanList").mockResolvedValue([scan()] as never);

    renderPage(<Activity />);

    const row = await screen.findByRole("button", { expanded: false });
    expect(screen.queryByText("plex")).toBeNull();

    await userEvent.click(row);

    expect(await screen.findByText("plex")).toBeTruthy();
    expect(screen.getByText(/movies 1200/)).toBeTruthy();
  });

  it("shows why a run failed, in the run's own entry", async () => {
    vi.spyOn(api, "scanList").mockResolvedValue([
      scan({ status: "failed", error: "Radarr refused the connection", checkpoints: {} }),
    ] as never);

    renderPage(<Activity />);

    await userEvent.click(await screen.findByRole("button", { expanded: false }));

    expect(await screen.findByText("Radarr refused the connection")).toBeTruthy();
    // And says so plainly rather than showing an empty box where phases would be.
    expect(screen.getByText(/No phase details recorded/)).toBeTruthy();
  });

  it("leaves the panel out entirely when there are no runs", async () => {
    // NEGATIVE CONTROL: an empty "Scans" panel on a fresh install reads as a
    // fault. Nothing has run yet, which is not the same as something going wrong.
    vi.spyOn(api, "scanList").mockResolvedValue([] as never);

    renderPage(<Activity />);

    await screen.findByText(/No activity yet/i);
    expect(screen.queryByText("Scans")).toBeNull();
  });

  it("does not let a failed scan list take the activity log down with it", async () => {
    // The two fetches are independent and the log is the more important of them.
    // A scan-list failure that propagated would blank the audit trail.
    //
    // Mutation-checked: the `.catch(() => undefined)` on `scanList` is not what
    // delivers this — replacing it with a rethrow leaves the test green, because
    // an unhandled rejection in a detached promise inside an effect does not
    // reach the render. The independence of the two fetches is what protects the
    // log; the catch is there to keep the console clean. The pin is on the log
    // surviving, which is the property that matters.
    vi.spyOn(api, "scanList").mockRejectedValue(new Error("scan history unavailable"));
    vi.spyOn(api, "activity").mockResolvedValue([action()] as never);

    renderPage(<Activity />);

    await screen.findByText("delete");
    expect(screen.queryByText("Scans")).toBeNull();
  });
});

describe("the type filters", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "scanList").mockResolvedValue([] as never);
  });

  it("narrows the timeline to one kind of action", async () => {
    vi.spyOn(api, "activity").mockResolvedValue([
      action({ id: 1, type: "delete", movie_tmdb_id: 603 }),
      action({ id: 2, type: "add", movie_tmdb_id: 862 }),
    ] as never);

    renderPage(<Activity />);

    await screen.findByText("#603");
    expect(screen.getByText("#862")).toBeTruthy();

    const filters = screen.getAllByRole("button", { name: "delete" });
    await userEvent.click(filters[0]);

    expect(screen.getByText("#603")).toBeTruthy();
    expect(screen.queryByText("#862")).toBeNull();
  });

  it("says the filter matched nothing, not that nothing ever happened", async () => {
    // NEGATIVE CONTROL for the above, and it found a real defect. The empty
    // state was keyed on the *filtered* row count, so filtering to deletes on a
    // log with none of them produced "No activity yet" — on the trust surface,
    // the same sentence as "your delete was never recorded".
    //
    // Now the two cases have different words, and the way back is a button
    // rather than working out which chip to press.
    vi.spyOn(api, "activity").mockResolvedValue([action({ type: "add" })] as never);

    renderPage(<Activity />);
    await screen.findByText("#603");

    await userEvent.click(screen.getAllByRole("button", { name: "delete" })[0]);

    await screen.findByText(/No delete actions in this window/);
    expect(screen.getByText(/The log is not empty/)).toBeTruthy();
    expect(screen.queryByText(/No activity yet/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /show everything/i }));
    expect(await screen.findByText("#603")).toBeTruthy();
  });
});

describe("the payload", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "scanList").mockResolvedValue([] as never);
  });

  it("stays hidden until asked for, then shows what was actually sent", async () => {
    vi.spyOn(api, "activity").mockResolvedValue([
      action({ dry_run: true, payload: { delete_files: true, add_import_exclusion: false } }),
    ] as never);

    renderPage(<Activity />);

    await screen.findByRole("button", { name: "Payload" });
    expect(screen.queryByText(/delete_files/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Payload" }));

    const shown = await screen.findByText(/delete_files/);
    // dry_run is in the payload as well as the pill: the pill is a summary and
    // the payload is the record, and the record has to stand on its own.
    expect(shown.textContent).toContain('"dry_run": true');
    expect(shown.textContent).toContain('"movie": 603');
  });
});

describe("the history window", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "scanList").mockResolvedValue([] as never);
  });

  it("offers more only when the server filled the window it was given", async () => {
    // A full page means there is probably more behind it. A partial page is the
    // end of the history, and a "Show more" there fetches the same rows again.
    vi.spyOn(api, "activity").mockResolvedValue(
      Array.from({ length: 80 }, (_, i) => action({ id: i + 1 })) as never,
    );

    renderPage(<Activity />);

    expect(await screen.findByRole("button", { name: /show more/i })).toBeTruthy();
  });

  it("NEGATIVE CONTROL: a partial page is the end of the log", async () => {
    vi.spyOn(api, "activity").mockResolvedValue(
      Array.from({ length: 12 }, (_, i) => action({ id: i + 1 })) as never,
    );

    renderPage(<Activity />);

    await screen.findAllByText("delete");
    expect(screen.queryByRole("button", { name: /show more/i })).toBeNull();
  });
});
