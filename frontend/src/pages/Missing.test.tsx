// A failed load used to empty the list, which said "nothing is missing from your
// library" — both untrue and the most flattering possible lie. It also read
// identically to the database having stopped answering, which is exactly how a
// broken instance looked from the browser.

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Missing } from "@/pages/Missing";
import { renderPage } from "@/test/harness";

function item(tmdb_id: number, title: string) {
  return {
    tmdb_id,
    title,
    year: 1999,
    poster_url: null,
    vote_average: 8.2,
    vote_count: 90_000,
    sources: ["criterion"],
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("when the missing list cannot be loaded", () => {
  it("says so instead of reporting that nothing is missing", async () => {
    vi.spyOn(api, "canonMissing").mockRejectedValue(
      new Error("The database is not accepting queries right now."),
    );

    renderPage(<Missing />);

    expect(await screen.findByText(/database is not accepting queries/i)).toBeInTheDocument();
    // The empty state offers to build the catalog. Offering that after a failed
    // read invites a rebuild of something that was never the problem.
    expect(screen.queryByText(/No catalog yet/i)).not.toBeInTheDocument();
  });

  it("offers a retry that actually refetches", async () => {
    const missing = vi
      .spyOn(api, "canonMissing")
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce({
        items: [item(603, "The Matrix")],
        total: 1,
        requested_total: 0,
      } as never);

    renderPage(<Missing />);
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    expect(await screen.findByText(/The Matrix/)).toBeInTheDocument();
    expect(missing).toHaveBeenCalledTimes(2);
  });
});

describe("NEGATIVE CONTROL: a genuinely empty catalog", () => {
  it("still offers to build it rather than reporting an error", async () => {
    vi.spyOn(api, "canonMissing").mockResolvedValue({
      items: [],
      total: 0,
      requested_total: 0,
    } as never);

    renderPage(<Missing />);

    // A page that showed an error for every empty response would pass both tests
    // above and be a different, equally wrong screen.
    expect(await screen.findByText(/No catalog yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });
});

describe("when the request never comes back", () => {
  it("gives up and offers a retry instead of spinning for ever", async () => {
    // What the owner reported as "the Missing page times out". Without a bound
    // the page has no way to distinguish a slow answer from no answer, so it
    // shows the loading state until the tab is closed. A sleeping free-tier
    // instance takes about thirty seconds to wake, so the bound is generous —
    // what it catches is the case with no end.
    const { PAGE_LOAD_TIMEOUT_MS } = await import("@/lib/api");
    vi.useFakeTimers();
    vi.spyOn(api, "canonMissing").mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          setTimeout(() => reject(new Error("timed out")), PAGE_LOAD_TIMEOUT_MS);
        }),
    );

    renderPage(<Missing />);
    await vi.advanceTimersByTimeAsync(PAGE_LOAD_TIMEOUT_MS + 100);
    vi.useRealTimers();

    expect(await screen.findByText(/timed out/i)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
