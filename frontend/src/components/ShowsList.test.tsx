// The TV half of the Library, at 2% coverage.
//
// It is a read-only surface, so nothing here can delete a file — but it is the
// one place the app states a number about television, and a wrong number is
// worse than no number. Somebody deciding what to remove reads "4.2 TB" and
// acts on it.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShowsList } from "@/components/ShowsList";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

// Fields named as `ShowSummary` names them. The first version of this fixture
// invented `episode_file_count`, `size_on_disk` and `quality`, which the
// component does not read — so every row rendered "— " for its size and
// "undefined seasons", and the tests passed anyway. A fixture that does not
// match the type is a test of nothing in particular.
function show(overrides: Record<string, unknown> = {}) {
  return {
    tvdb_id: 121361,
    tmdb_id: null,
    title: "Game of Thrones",
    year: 2011,
    status: "Ended",
    network: "HBO",
    genres: ["Drama"],
    library_section: "TV",
    is_kids: false,
    monitored: true,
    in_plex: true,
    runtime: 60,
    season_count: 8,
    episode_count: 73,
    total_size: 1.2e12,
    resolution: "1080p",
    plays: 40,
    last_played_at: null,
    mean_completion: 0.9,
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "showSections").mockResolvedValue(["TV"] as never);
});

describe("the summary line", () => {
  it("adds up episodes and reports the library's own totals", async () => {
    // `total` and `total_size` come from the server and describe the whole
    // library; the episode count is summed from what arrived. Mixing those up
    // would report the size of one page as the size of the shelf.
    vi.spyOn(api, "shows").mockResolvedValue({
      items: [show(), show({ tvdb_id: 2, title: "The Wire", episode_count: 60 })],
      total: 240,
      total_size: 4.2e12,
    } as never);

    renderPage(<ShowsList query="" />);

    expect(await screen.findByText(/240 shows · 133 episodes · 4.20 TB/)).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: an empty shelf is not reported as 0 bytes of something", async () => {
    vi.spyOn(api, "shows").mockResolvedValue({
      items: [],
      total: 0,
      total_size: 0,
    } as never);

    renderPage(<ShowsList query="" />);

    expect(await screen.findByText(/0 shows · 0 episodes · —/)).toBeInTheDocument();
  });
});

describe("when the shows cannot be loaded", () => {
  it("says so rather than showing an empty shelf", async () => {
    // An empty TV list means "you own no television", which is a completely
    // different statement from "the server did not answer".
    vi.spyOn(api, "shows").mockRejectedValue(new Error("Sonarr is unreachable"));

    renderPage(<ShowsList query="" />);

    expect(await screen.findByText(/Sonarr is unreachable/)).toBeInTheDocument();
    expect(screen.queryByText(/0 shows/)).not.toBeInTheDocument();
  });
});

describe("filtering and sorting", () => {
  it("asks the server, rather than reordering what it happens to have", async () => {
    // The list is a page of a larger set. Sorting client-side would sort the
    // page and call it the shelf, which is wrong in a way nobody can see.
    const shows = vi.spyOn(api, "shows").mockResolvedValue({
      items: [show()],
      total: 1,
      total_size: 1e12,
    } as never);

    renderPage(<ShowsList query="" />);
    await screen.findByText("Game of Thrones");

    await userEvent.selectOptions(screen.getByLabelText(/sort/i), "last_played_at");

    await waitFor(() => {
      const last = shows.mock.calls.at(-1)?.[0] as { sort?: string; order?: string };
      expect(last.sort).toBe("last_played_at");
      // Most recently watched first — ascending would put the shows you have
      // not touched in years at the top of a "last watched" sort.
      expect(last.order).toBe("desc");
    });
  });

  it("NEGATIVE CONTROL: the other sorts stay ascending", async () => {
    const shows = vi.spyOn(api, "shows").mockResolvedValue({
      items: [show()],
      total: 1,
      total_size: 1e12,
    } as never);

    renderPage(<ShowsList query="" />);
    await screen.findByText("Game of Thrones");
    await userEvent.selectOptions(screen.getByLabelText(/sort/i), "year");

    await waitFor(() => {
      const last = shows.mock.calls.at(-1)?.[0] as { sort?: string; order?: string };
      expect(last.sort).toBe("year");
      expect(last.order).toBe("asc");
    });
  });

  it("passes the library filter through", async () => {
    const shows = vi.spyOn(api, "shows").mockResolvedValue({
      items: [show()],
      total: 1,
      total_size: 1e12,
    } as never);

    renderPage(<ShowsList query="" />);
    await screen.findByText("Game of Thrones");
    await userEvent.selectOptions(await screen.findByLabelText(/library/i), "TV");

    await waitFor(() =>
      expect((shows.mock.calls.at(-1)?.[0] as { section?: string }).section).toBe("TV"),
    );
  });
});

describe("how long ago you watched something", () => {
  it("reads in the units a person would use", async () => {
    const days = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString();
    vi.spyOn(api, "shows").mockResolvedValue({
      items: [
        show({ tvdb_id: 1, title: "Today Show", last_played_at: days(0) }),
        show({ tvdb_id: 2, title: "Fortnight Show", last_played_at: days(14) }),
        show({ tvdb_id: 3, title: "Season Show", last_played_at: days(90) }),
        show({ tvdb_id: 4, title: "Ancient Show", last_played_at: days(900) }),
        show({ tvdb_id: 5, title: "Untouched Show", plays: 0, last_played_at: null }),
      ],
      total: 5,
      total_size: 1e12,
    } as never);

    renderPage(<ShowsList query="" />);

    expect(await screen.findByText(/watched today/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp("watched 14 days ago"))).toBeInTheDocument();
    expect(screen.getByText(new RegExp("watched 3 months ago"))).toBeInTheDocument();
    expect(screen.getByText(new RegExp("watched 2.5 years ago"))).toBeInTheDocument();
    // Never watched is the one that matters most on this screen, and "0 plays"
    // would be a worse way to say it.
    expect(screen.getByText(new RegExp("watched never"))).toBeInTheDocument();
  });
});
