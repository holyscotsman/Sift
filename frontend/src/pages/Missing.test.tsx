// The Missing list has three ways to be quietly wrong, and all three look like a
// working page from across the room: a failed load that empties the list (which
// reads as "you own everything"), a request that never returns (which reads as
// "still loading" for ever), and a decision that does not stick (which reads as
// a working page right up until the same title comes back).

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Missing } from "@/pages/Missing";
import { renderPage } from "@/test/harness";

// The page asks for sixty at a time; a short page means "that was the last".
const PAGE_SIZE = 60;

let scrollToBottom: () => void = () => {};

function item(tmdb_id: number, title: string) {
  return {
    tmdb_id,
    title,
    year: 1999,
    tier: 1,
    reasons: ["criterion"],
    rating: 8.2,
    votes: 90_000,
  };
}

function page(titles: { id: number; title: string }[], total: number) {
  return {
    items: titles.map((t) => item(t.id, t.title)),
    total,
    requested_total: 0,
    ignored_total: 0,
  };
}

const fullPage = (lead: string) => [
  { id: 1000, title: lead },
  ...Array.from({ length: PAGE_SIZE - 1 }, (_, i) => ({ id: 2000 + i, title: `Film ${i}` })),
];

beforeEach(() => {
  vi.restoreAllMocks();
  // jsdom has no IntersectionObserver. Capturing the callback rather than
  // stubbing it into silence is the point: paging only happens when the sentinel
  // fires, so a stub that never fires tests nothing about paging.
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

describe("when the missing list cannot be loaded", () => {
  it("says so instead of reporting that nothing is missing", async () => {
    vi.spyOn(api, "suggestions").mockRejectedValue(
      new Error("The database is not accepting queries right now."),
    );

    renderPage(<Missing />);

    expect(await screen.findByText(/database is not accepting queries/i)).toBeInTheDocument();
    // The empty state offers to build the catalog. Offering that after a failed
    // read invites a rebuild of something that was never the problem.
    expect(screen.queryByText(/Nothing left on this list/i)).not.toBeInTheDocument();
  });

  it("offers a retry that actually refetches", async () => {
    const suggestions = vi
      .spyOn(api, "suggestions")
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce(page([{ id: 603, title: "The Matrix" }], 1) as never);

    renderPage(<Missing />);
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    expect(await screen.findByText(/The Matrix/)).toBeInTheDocument();
    expect(suggestions).toHaveBeenCalledTimes(2);
  });
});

describe("NEGATIVE CONTROL: a genuinely empty list", () => {
  it("still offers to build the catalog rather than reporting an error", async () => {
    vi.spyOn(api, "suggestions").mockResolvedValue(page([], 0) as never);

    renderPage(<Missing />);

    // A page that showed an error for every empty response would pass both tests
    // above and be a different, equally wrong screen.
    expect(await screen.findByText(/Nothing left on this list/i)).toBeInTheDocument();
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
    vi.spyOn(api, "suggestions").mockImplementation(
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

describe("the endless list", () => {
  it("keeps asking for the next page as the sentinel comes into view", async () => {
    const suggestions = vi
      .spyOn(api, "suggestions")
      // A *full* page: anything shorter tells the list it has reached the end and
      // the sentinel stops asking, which would make this test vacuous.
      .mockResolvedValueOnce(page(fullPage("Alien"), 500) as never)
      .mockResolvedValueOnce(page([{ id: 3000, title: "Arrival" }], 500) as never);

    renderPage(<Missing />);
    await screen.findByText(/Alien/);

    // `loadMore` refuses while a page is still in flight, so a single fire races
    // the first page finishing. Retry until the sentinel takes.
    await waitFor(() => {
      scrollToBottom();
      expect(suggestions).toHaveBeenCalledTimes(2);
    });

    expect(await screen.findByText(/Arrival/)).toBeInTheDocument();
    const offsets = suggestions.mock.calls.map((c) => (c[0] as { offset?: number })?.offset);
    expect(offsets).toEqual([0, PAGE_SIZE]);
  });

  it("retries the page that failed, not the one after it", async () => {
    const suggestions = vi
      .spyOn(api, "suggestions")
      .mockResolvedValueOnce(page(fullPage("Alien"), 500) as never)
      .mockRejectedValueOnce(new Error("dropped"))
      .mockResolvedValueOnce(page([{ id: 3000, title: "Arrival" }], 500) as never);

    renderPage(<Missing />);
    await screen.findByText(/Alien/);

    await waitFor(() => {
      scrollToBottom();
      expect(suggestions).toHaveBeenCalledTimes(2);
    });
    await screen.findByText(/dropped/);

    await userEvent.click(screen.getByRole("button", { name: /load the rest/i }));
    await screen.findByText(/Arrival/);

    const offsets = suggestions.mock.calls.map((c) => (c[0] as { offset?: number })?.offset);
    // A failing page that advanced the offset anyway would ask for 120 next, and
    // those sixty titles would be gone with nothing on screen to say so.
    expect(offsets).toEqual([0, PAGE_SIZE, PAGE_SIZE]);
  });

  it("stops asking after a page fails instead of hammering the server", async () => {
    // The sentinel stays on screen after a failed page, and a real browser
    // re-fires the observer on every scroll and resize — not once, the way this
    // harness does. Without the error guard in `loadMore` that is an unbounded
    // retry loop against a server that is already struggling, which is precisely
    // when it can least afford one.
    const suggestions = vi
      .spyOn(api, "suggestions")
      .mockResolvedValueOnce(page(fullPage("Alien"), 500) as never)
      .mockRejectedValue(new Error("dropped"));

    renderPage(<Missing />);
    await screen.findByText(/Alien/);
    await waitFor(() => {
      scrollToBottom();
      expect(suggestions).toHaveBeenCalledTimes(2);
    });
    await screen.findByText(/dropped/);

    scrollToBottom();
    scrollToBottom();
    scrollToBottom();
    await waitFor(() => expect(suggestions).toHaveBeenCalledTimes(2));

    // And the explicit retry still works — a guard that never clears is just a
    // dead list with an extra button on it.
    suggestions.mockResolvedValueOnce(page([{ id: 3000, title: "Arrival" }], 500) as never);
    await userEvent.click(screen.getByRole("button", { name: /load the rest/i }));
    expect(await screen.findByText(/Arrival/)).toBeInTheDocument();
  });

  it("says the list is incomplete rather than claiming to have reached the end", async () => {
    vi.spyOn(api, "suggestions")
      .mockResolvedValueOnce(page(fullPage("Alien"), 500) as never)
      .mockRejectedValueOnce(new Error("dropped"));

    renderPage(<Missing />);
    await screen.findByText(/Alien/);
    await waitFor(() => {
      scrollToBottom();
      expect(screen.queryByText(/dropped/)).toBeInTheDocument();
    });

    // The real end of the data says "That's everything". An incomplete list must
    // never borrow that sentence.
    expect(screen.queryByText(/That’s everything/)).not.toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a short page is the end, and says so", async () => {
    vi.spyOn(api, "suggestions").mockResolvedValue(
      page([{ id: 603, title: "The Matrix" }], 1) as never,
    );

    renderPage(<Missing />);

    expect(await screen.findByText(/That’s everything/)).toBeInTheDocument();
  });
});

describe("setting a title aside", () => {
  it("files the decision and offers to take it back", async () => {
    vi.spyOn(api, "suggestions").mockResolvedValue(
      page([{ id: 603, title: "The Matrix" }], 1) as never,
    );
    const ignore = vi.spyOn(api, "ignoreTitle").mockResolvedValue({
      tmdb_id: 603,
      title: "The Matrix",
      source: "missing",
    } as never);
    const unignore = vi.spyOn(api, "unignoreTitle").mockResolvedValue({ removed: true } as never);

    renderPage(<Missing />);
    await userEvent.click(await screen.findByRole("button", { name: /never suggest/i }));

    expect(ignore).toHaveBeenCalledWith(603, "The Matrix", "missing");
    // The card stays put rather than vanishing under the cursor — an endless list
    // that reflows on every click sends the next one somewhere unintended.
    const undo = await screen.findByRole("button", { name: /not for me · undo/i });
    await userEvent.click(undo);
    expect(unignore).toHaveBeenCalledWith(603);
  });

  it("NEGATIVE CONTROL: a refusal the server rejected is not shown as filed", async () => {
    vi.spyOn(api, "suggestions").mockResolvedValue(
      page([{ id: 603, title: "The Matrix" }], 1) as never,
    );
    vi.spyOn(api, "ignoreTitle").mockRejectedValue(new Error("write failed"));

    renderPage(<Missing />);
    await userEvent.click(await screen.findByRole("button", { name: /never suggest/i }));

    // Showing "not for me" on a failed write is the worst outcome here: the owner
    // believes the title is gone for good and it returns on the next load.
    await waitFor(() => expect(screen.getByText(/still be suggested/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /undo/i })).not.toBeInTheDocument();
  });
});
