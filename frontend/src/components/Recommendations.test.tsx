// A short recommendation list is indistinguishable from a broken one unless it
// says what it is made of. The server reports the composition; this pins that
// the shelf actually shows it.

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationsSection } from "@/components/Recommendations";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

function movie(tmdb_id: number, title: string) {
  return {
    tmdb_id,
    title,
    year: 1999,
    poster_url: null,
    vote_average: 8.1,
    reason: "canon",
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("the recommendation shelf", () => {
  it("says how much of the list came from the canon", async () => {
    vi.spyOn(api, "missingRecommendations").mockResolvedValue({
      items: [movie(603, "The Matrix"), movie(27205, "Inception")],
      note: "Showing 2 of 200. 180 from the validated canon, 20 from your taste graph.",
    } as never);

    renderPage(<RecommendationsSection />);

    expect(await screen.findByText(/The Matrix/)).toBeInTheDocument();
    // The composition, not a fixed sentence about the taste graph: the list is
    // canon-first now, and claiming otherwise was wrong as well as unhelpful.
    expect(
      await screen.findByText(/180 from the validated canon, 20 from your taste graph/),
    ).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: claims no composition when there is nothing to show", async () => {
    vi.spyOn(api, "missingRecommendations").mockResolvedValue({
      items: [],
      note: null,
    } as never);

    renderPage(<RecommendationsSection />);

    expect(await screen.findByText(/No recommendations yet/)).toBeInTheDocument();
    expect(screen.queryByText(/from the validated canon/)).not.toBeInTheDocument();
  });
});
