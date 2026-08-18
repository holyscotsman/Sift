// The library list is paged by an intersection observer, which makes a dropped
// page invisible unless something says so.

import { act, screen } from "@testing-library/react";
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

    await act(async () => scrollToBottom());
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
