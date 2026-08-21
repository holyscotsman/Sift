// The library list is paged by an intersection observer, which makes a dropped
// page invisible unless something says so.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Library } from "@/pages/Library";
import { renderPage } from "@/test/harness";

let scrollToBottom: () => void = () => {};

// The list view asks for sixty at a time; a short page means "that was the last".
const PAGE_SIZE = 60;
const fullPage = (lead: string) => [lead, ...Array.from({ length: PAGE_SIZE - 1 }, (_, i) => `Film ${i}`)];

function page(titles: string[], total: number) {
  return {
    items: titles.map((title, i) => ({
      tmdb_id: 1000 + i,
      title,
      year: 2000,
      poster_url: null,
      library_section: "Films",
      quality: "1080p",
      file_size: 1e9,
      in_plex: true,
      monitored: false,
      is_kids: false,
      junk_score: null,
      band: null,
    })),
    total,
    total_size: 1e9,
  };
}

beforeEach(() => {
  vi.spyOn(api, "movieSections").mockResolvedValue([] as never);
  // jsdom has no IntersectionObserver. Capturing the callback rather than
  // stubbing it into silence is the whole point: paging only happens when the
  // sentinel fires, so a stub that never fires tests nothing about paging.
  scrollToBottom = () => {};
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        scrollToBottom = () => cb([{ isIntersecting: true }]);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  );
});

describe("when a page fails to load", () => {
  it("says the list is incomplete instead of looking finished", async () => {
    vi.spyOn(api, "movies").mockRejectedValue(new Error("gateway timeout"));

    renderPage(<Library />);

    expect(await screen.findByText(/gateway timeout/)).toBeInTheDocument();
    // The real end of the data says "That's everything". An incomplete list must
    // never borrow that sentence.
    expect(screen.queryByText(/That’s everything/)).not.toBeInTheDocument();
  });

  it("retries the page that failed, not the one after it", async () => {
    const movies = vi
      .spyOn(api, "movies")
      // A *full* page: anything shorter tells the list it has reached the end,
      // and the sentinel stops asking — which would make this test vacuous.
      .mockResolvedValueOnce(page(fullPage("Alien"), 200) as never)
      .mockRejectedValueOnce(new Error("dropped"))
      .mockResolvedValueOnce(page(["Arrival", "Akira"], 200) as never);

    renderPage(<Library />);
    await screen.findByText("Alien");

    // `loadMore` refuses while the list is still loading, so a single fire races
    // page one finishing — which is exactly how this test passed locally and on
    // one CI run before failing on the next. Retry until the sentinel takes.
    await waitFor(() => {
      scrollToBottom();
      expect(movies).toHaveBeenCalledTimes(2);
    });
    await screen.findByText(/dropped/);

    await userEvent.click(screen.getByRole("button", { name: /load the rest/i }));
    await screen.findByText("Arrival");

    const requested = movies.mock.calls.map((c) => (c[0] as { page?: number }).page);
    // Failing page two used to advance the counter anyway, so the next request
    // asked for page three and page two's titles were gone for good.
    expect(requested).toEqual([1, 2, 2]);
  });
});

describe("NEGATIVE CONTROL: a healthy list", () => {
  it("renders its titles and does not claim an error", async () => {
    vi.spyOn(api, "movies").mockResolvedValue(page(["Alien"], 1) as never);

    renderPage(<Library />);

    expect(await screen.findByText("Alien")).toBeInTheDocument();
    expect(screen.queryByText(/incomplete/i)).not.toBeInTheDocument();
  });
});

// The quick filters, and the download that is supposed to match them.
//
// `routes_export` says the CSV "shares the exact filters/sort of /api/movies …
// so the download always matches the visible set". That promise lives in one
// `useMemo` reading the same `buildQuery` the list does, and nothing checked it.
// A download that quietly differs from the screen is worse than one that fails:
// the file looks right, and the difference is only discoverable by counting rows.

function lastQuery(movies: ReturnType<typeof vi.spyOn>) {
  return movies.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

describe("the quick filters", () => {
  it("ask for exactly what each one means, and nothing else", async () => {
    // Each filter maps to a different set of params. A stray `in_plex` on the
    // kids view would silently hide every kids film that is not owned yet, and
    // the view would look correct while being wrong.
    const movies = vi.spyOn(api, "movies").mockResolvedValue(page(["Alien"], 1) as never);

    renderPage(<Library />);
    await screen.findByText("Alien");

    await userEvent.click(screen.getByRole("button", { name: /^kids$/i }));
    await waitFor(() => {
      const q = lastQuery(movies);
      expect(q.is_kids).toBe(true);
      expect(q.in_plex).toBeUndefined();
      expect(q.monitored).toBeUndefined();
      expect(q.cutoff_unmet).toBeUndefined();
    });

    await userEvent.click(screen.getByRole("button", { name: /^monitored$/i }));
    await waitFor(() => {
      const q = lastQuery(movies);
      expect(q.monitored).toBe(true);
      expect(q.is_kids).toBeUndefined();
    });
  });

  it("narrows upgrades to things you actually own", async () => {
    // "Below cutoff" is a library view narrowed by Radarr's opinion. An upgrade
    // for a film nobody has is not an upgrade, it is a suggestion — and that is
    // the Missing page's job, not this one's.
    const movies = vi.spyOn(api, "movies").mockResolvedValue(page(["Alien"], 1) as never);

    renderPage(<Library />);
    await screen.findByText("Alien");
    await userEvent.click(screen.getByRole("button", { name: /below cutoff|upgrades/i }));

    await waitFor(() => {
      const q = lastQuery(movies);
      expect(q.cutoff_unmet).toBe(true);
      expect(q.in_plex).toBe(true);
    });
  });

  it("goes back to the first page when the filter changes", async () => {
    // Otherwise a filter change lands you at the offset of the list you just
    // left, and the top of the new list is never shown.
    const movies = vi
      .spyOn(api, "movies")
      .mockResolvedValue(page(fullPage("Alien"), 200) as never);

    renderPage(<Library />);
    await screen.findByText("Alien");
    await waitFor(() => {
      scrollToBottom();
      expect(movies.mock.calls.length).toBeGreaterThan(1);
    });
    expect(lastQuery(movies).page).toBe(2);

    await userEvent.click(screen.getByRole("button", { name: /^kids$/i }));
    await waitFor(() => expect(lastQuery(movies).page).toBe(1));
  });
});

describe("the CSV download", () => {
  it("carries the same filters as the list on screen", async () => {
    vi.spyOn(api, "movies").mockResolvedValue(page(["Alien"], 1) as never);

    renderPage(<Library />);
    await screen.findByText("Alien");
    await userEvent.click(screen.getByRole("button", { name: /^kids$/i }));

    const link = await screen.findByRole("link", { name: /csv|export|download/i });
    await waitFor(() => {
      const href = link.getAttribute("href") ?? "";
      expect(href).toContain("is_kids=true");
      // And not the filters it is *not* showing.
      expect(href).not.toContain("monitored=true");
      // Paging is a property of the screen, not of the export: the file is the
      // whole set, capped server-side, not the sixty rows currently rendered.
      expect(href).not.toContain("page=");
      expect(href).not.toContain("page_size=");
    });
  });
});
