// At 0% coverage — not a line of it had ever run under test.
//
// It is read-only and requests nothing, so the risk is not damage: it is a panel
// that renders an empty box on every failure and tells nobody why.

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShowSuggestions } from "@/components/ShowSuggestions";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

// Fields named as `ShowSuggestion` names them — `because_of`, not `because`.
function suggestion(overrides: Record<string, unknown> = {}) {
  return {
    tmdb_id: 1396,
    title: "Breaking Bad",
    year: 2008,
    overview: "A chemistry teacher turns to manufacturing.",
    poster_path: null,
    vote_average: 8.9,
    vote_count: 12000,
    because_of: ["The Wire", "The Sopranos"],
    ...overrides,
  };
}

describe("ShowSuggestions", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("names which of your shows led to each suggestion", async () => {
    // The module docstring's stated reason for existing: a suggestion you can
    // argue with rather than only accept or ignore.
    vi.spyOn(api, "showSuggestions").mockResolvedValue({
      items: [suggestion()],
      detail: "",
    });

    renderPage(<ShowSuggestions />);

    await screen.findByText("Breaking Bad");
    expect(screen.getByText(/Because you watched The Wire, The Sopranos/)).toBeTruthy();
    expect(screen.getByText("8.9")).toBeTruthy();
  });

  it("omits the reason line rather than printing an empty one", async () => {
    // NEGATIVE CONTROL: "Because you watched" with nothing after it is worse
    // than no line — it reads as a rendering fault in the one sentence that is
    // supposed to justify the suggestion.
    vi.spyOn(api, "showSuggestions").mockResolvedValue({
      items: [suggestion({ because_of: [], vote_average: null, overview: "" })],
      detail: "",
    });

    renderPage(<ShowSuggestions />);

    await screen.findByText("Breaking Bad");
    expect(screen.queryByText(/Because you watched/)).toBeNull();
  });

  it("links out to TMDB by id and never requests anything", async () => {
    // The panel's own footer promises this. A "Look it up" that quietly added a
    // show would be the one thing a suggestions list must not do.
    vi.spyOn(api, "showSuggestions").mockResolvedValue({
      items: [suggestion()],
      detail: "",
    });

    renderPage(<ShowSuggestions />);

    const link = (await screen.findByRole("link", { name: /look it up/i })) as HTMLAnchorElement;
    expect(link.href).toBe("https://www.themoviedb.org/tv/1396");
    expect(link.rel).toContain("noreferrer");
    expect(screen.getByText(/nothing is requested or added from here/i)).toBeTruthy();
  });

  it("passes the server's reason through when there is nothing to suggest", async () => {
    vi.spyOn(api, "showSuggestions").mockResolvedValue({
      items: [],
      detail: "Finish a show first.",
    });

    renderPage(<ShowSuggestions />);

    await screen.findByText("Nothing to suggest yet");
    expect(screen.getByText("Finish a show first.")).toBeTruthy();
  });

  it("still says something when the request fails outright", async () => {
    // NEGATIVE CONTROL for the empty case: a failed request and an empty result
    // are different, and rendering both as "nothing to suggest" would hide a
    // broken TMDB key behind a plausible-looking empty state.
    //
    // This is what found the bug. The catch wrote its message to `detail`, but
    // the render only consulted `detail` once `items` was non-null — so a failed
    // request left the loading skeleton shimmering permanently and the reason
    // reached nobody. Writing the test made the dead branch obvious.
    vi.spyOn(api, "showSuggestions").mockRejectedValue(new Error("no tmdb key"));

    renderPage(<ShowSuggestions />);

    await screen.findByText(/Couldn't load suggestions/);
    // And the server's own reason, not a generic one — a missing key is worth
    // saying out loud.
    expect(screen.getByText("no tmdb key")).toBeTruthy();
    // No skeleton left running behind it.
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it("announces that it is loading rather than showing a bare box", async () => {
    vi.spyOn(api, "showSuggestions").mockReturnValue(new Promise(() => {}));

    renderPage(<ShowSuggestions />);

    expect(screen.getByRole("status").textContent).toContain("Looking for shows");
  });
});
