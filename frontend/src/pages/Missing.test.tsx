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

  it("keeps the headline count when a later page does not measure it", async () => {
    // The server counts for the first page of a list and skips it for the pages
    // that continue it — the count walks twenty thousand rows while the page
    // reads sixty off an index. `null` means "not measured", so treating it as
    // zero empties the header the moment anyone scrolls, and "0 to go" on a list
    // with twenty thousand titles left reads as "you own everything".
    const suggestions = vi
      .spyOn(api, "suggestions")
      .mockResolvedValueOnce({
        items: fullPage("Alien").map((t) => item(t.id, t.title)),
        total: 500,
        requested_total: 7,
        ignored_total: 3,
      } as never)
      .mockResolvedValueOnce({
        items: [item(3000, "Arrival")],
        total: null,
        requested_total: null,
        ignored_total: null,
      } as never);

    renderPage(<Missing />);
    expect(await screen.findByText(/500 to go/)).toBeInTheDocument();

    await waitFor(() => {
      scrollToBottom();
      expect(suggestions).toHaveBeenCalledTimes(2);
    });
    await screen.findByText(/Arrival/);

    expect(screen.getByText(/500 to go/)).toBeInTheDocument();
    expect(screen.getByText(/7 already requested/)).toBeInTheDocument();
    expect(screen.getByText(/3 set aside/)).toBeInTheDocument();
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

describe("bringing a film back from Set aside", () => {
  it("reloads the Movies list so the film reappears in it", async () => {
    // Switching tabs does not remount this page, so nothing reloads on its own.
    // A restored film rejoins the list at its usual rank and its counts move —
    // and the first version of this clearing `items` without a reload trigger
    // would have left the Movies tab permanently, silently empty.
    const suggestions = vi
      .spyOn(api, "suggestions")
      .mockResolvedValue(page([{ id: 603, title: "The Matrix" }], 1) as never);
    vi.spyOn(api, "ignoredTitles").mockResolvedValue({
      items: [{ tmdb_id: 604, title: "Stalker", source: "missing" }],
      total: 1,
    } as never);
    vi.spyOn(api, "unignoreTitle").mockResolvedValue({ removed: true } as never);

    renderPage(<Missing />);
    await screen.findByText(/The Matrix/);
    expect(suggestions).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("tab", { name: /set aside/i }));
    await userEvent.click(await screen.findByRole("button", { name: /suggest Stalker again/i }));

    await userEvent.click(screen.getByRole("tab", { name: /^movies$/i }));
    await waitFor(() => expect(suggestions).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/The Matrix/)).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: opening the tab and leaving does not reload anything", async () => {
    // A page that refetched on every tab switch would pass the test above while
    // spending a request each time someone looked at a different tab.
    const suggestions = vi
      .spyOn(api, "suggestions")
      .mockResolvedValue(page([{ id: 603, title: "The Matrix" }], 1) as never);
    vi.spyOn(api, "ignoredTitles").mockResolvedValue({ items: [], total: 0 } as never);

    renderPage(<Missing />);
    await screen.findByText(/The Matrix/);

    await userEvent.click(screen.getByRole("tab", { name: /set aside/i }));
    await screen.findByText(/Nothing set aside/i);
    await userEvent.click(screen.getByRole("tab", { name: /^movies$/i }));
    await screen.findByText(/The Matrix/);

    expect(suggestions).toHaveBeenCalledTimes(1);
  });
});

describe("looking for more films", () => {
  it("extends the list and reloads it from the top", async () => {
    // Scrolled past the first page before pressing the button, which is the only
    // state where "reload from the top" and "fetch the next page" differ. With a
    // single page loaded the offset is zero either way and the assertion below
    // holds no matter what the code does.
    const suggestions = vi
      .spyOn(api, "suggestions")
      .mockResolvedValueOnce(page(fullPage("Alien"), 500) as never)
      .mockResolvedValueOnce(page([{ id: 3000, title: "Arrival" }], 500) as never)
      .mockResolvedValueOnce(page([{ id: 604, title: "Stalker" }], 501) as never);
    const topup = vi
      .spyOn(api, "topup")
      .mockResolvedValue({ added: 1, remaining: 501, ran: true, considered: 1, note: null } as never);

    renderPage(<Missing />);
    await screen.findByText(/Alien/);
    await waitFor(() => {
      scrollToBottom();
      expect(suggestions).toHaveBeenCalledTimes(2);
    });
    await screen.findByText(/Arrival/);

    await userEvent.click(screen.getByRole("button", { name: /find more/i }));

    expect(topup).toHaveBeenCalled();
    expect(await screen.findByText(/Stalker/)).toBeInTheDocument();
    // Reloaded from the top rather than appended at the current offset: the new
    // titles are ranked among the old ones, not stapled to the end. Appending at
    // offset 120 would also skip the sixty titles the new arrivals displaced.
    const offsets = suggestions.mock.calls.map((c) => (c[0] as { offset?: number })?.offset);
    expect(offsets).toEqual([0, PAGE_SIZE, 0]);
    expect(screen.queryByText(/Alien/)).not.toBeInTheDocument();
  });

  it("passes on the server's reason when it declined to look", async () => {
    vi.spyOn(api, "suggestions").mockResolvedValue(
      page([{ id: 603, title: "The Matrix" }], 1) as never,
    );
    vi.spyOn(api, "topup").mockResolvedValue({
      added: 0,
      remaining: 0,
      ran: false,
      considered: 0,
      note: "connect TMDB first",
    } as never);

    renderPage(<Missing />);
    await screen.findByText(/The Matrix/);
    await userEvent.click(screen.getByRole("button", { name: /find more/i }));

    // "Found 0 more" would be a true sentence describing the wrong situation.
    // Nothing was searched, and the fix is a connection, not another click.
    expect(await screen.findByText(/connect TMDB first/i)).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a real search that found nothing is not reported as a failure", async () => {
    vi.spyOn(api, "suggestions").mockResolvedValue(
      page([{ id: 603, title: "The Matrix" }], 1) as never,
    );
    vi.spyOn(api, "topup").mockResolvedValue({
      added: 0,
      remaining: 1,
      ran: true,
      considered: 40,
      note: null,
    } as never);

    renderPage(<Missing />);
    await screen.findByText(/The Matrix/);
    await userEvent.click(screen.getByRole("button", { name: /find more/i }));

    expect(await screen.findByText(/Nothing new this time/i)).toBeInTheDocument();
    expect(screen.queryByText(/connect TMDB/i)).not.toBeInTheDocument();
  });
});

describe("a card whose film the sources know nothing about", () => {
  it("renders anyway instead of taking the page down with it", async () => {
    // Not a hypothetical: a deploy serves the new page against the old API for
    // as long as the backend takes to roll, and IMDb genuinely records no genres
    // for a few hundred canon entries. The first version of this card read
    // `item.directors.slice(...)` and threw, which unmounted the whole Missing
    // page — every other suggestion gone because one film had no director.
    vi.spyOn(api, "suggestions").mockResolvedValue({
      items: [
        {
          tmdb_id: 1,
          title: "Zorns Lemma",
          year: 1970,
          tier: 1,
          reasons: [],
          rating: null,
          votes: null,
        } as never,
        {
          tmdb_id: 2,
          title: "Seven Samurai",
          year: 1954,
          tier: 1,
          reasons: ["You own 3 films by Akira Kurosawa"],
          rating: 8.6,
          votes: 400000,
          genres: ["Action", "Drama"],
          runtime: 207,
          directors: ["Akira Kurosawa"],
        } as never,
      ],
      total: 2,
      requested_total: 0,
      ignored_total: 0,
    } as never);

    renderPage(<Missing />);

    // Regex, because the card renders "{title} · {year}" as separate text
    // nodes and an exact match never sees a node equal to the title alone.
    expect(await screen.findAllByText(/Zorns Lemma/)).not.toHaveLength(0);
    // The complete one still shows everything it knows.
    expect(await screen.findAllByText(/Seven Samurai/)).not.toHaveLength(0);
    expect(screen.getByText(/Akira Kurosawa · Action, Drama · 207 min/)).toBeInTheDocument();
  });

  it("puts the reason from your own shelf on the card, not the tier", async () => {
    // "Widely regarded as essential" is already the tier label in the subtitle.
    // Repeating it in the accent colour says nothing new; the reason worth the
    // space is the one the person can check against their own library.
    vi.spyOn(api, "suggestions").mockResolvedValue({
      items: [
        {
          tmdb_id: 2,
          title: "Ran",
          year: 1985,
          tier: 1,
          reasons: ["Widely regarded as essential", "You own 3 films by Akira Kurosawa"],
          rating: 8.2,
          votes: 130000,
          genres: ["Drama"],
          runtime: 162,
          directors: ["Akira Kurosawa"],
        } as never,
      ],
      total: 1,
      requested_total: 0,
      ignored_total: 0,
    } as never);

    renderPage(<Missing />);

    expect(await screen.findByText(/You own 3 films by Akira Kurosawa/)).toBeInTheDocument();
    expect(screen.queryByText("Widely regarded as essential")).not.toBeInTheDocument();
  });
});
