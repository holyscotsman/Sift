// This page rendered its loading skeletons for ever when the profile read
// failed — a spinner that never resolves, which is the least informative failure
// a screen can have and exactly what "the app is broken" looked like.

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { TasteProfile } from "@/pages/TasteProfile";
import { renderPage } from "@/test/harness";

const PROFILE = {
  genres: [{ name: "Drama", count: 12 }],
  keywords: [],
  directors: [],
  actors: [],
  eras: [{ name: "1990s", count: 4 }],
  library_size: 12,
  weights: { genre: 0.5, director: 0.5, cast: 0.5, keywords: 0.5, era: 0.5 },
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "missingRecommendations").mockResolvedValue({ items: [], note: null } as never);
});

describe("when the profile cannot be loaded", () => {
  it("says so instead of spinning for ever", async () => {
    vi.spyOn(api, "getProfile").mockRejectedValue(
      new Error("The database is not accepting queries right now."),
    );

    renderPage(<TasteProfile />);

    expect(await screen.findByText(/database is not accepting queries/i)).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("offers a retry that actually refetches", async () => {
    const profile = vi
      .spyOn(api, "getProfile")
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce(PROFILE as never);

    renderPage(<TasteProfile />);
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    expect(await screen.findByText(/Drama/)).toBeInTheDocument();
    expect(profile).toHaveBeenCalledTimes(2);
  });
});

describe("NEGATIVE CONTROL: a library with nothing in it yet", () => {
  it("says to run a scan rather than reporting a failure", async () => {
    vi.spyOn(api, "getProfile").mockResolvedValue({ ...PROFILE, library_size: 0 } as never);

    renderPage(<TasteProfile />);

    expect(await screen.findByText(/No library yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });
});
