// What the Library remembers, and what it refuses to.
//
// Library.test.tsx pins the paging failure — a dropped page that used to vanish
// without trace. This covers the rest: the view and sort that survive
// navigation, the section filter, the empty state that has to tell two different
// stories, and the observer guard that stops a failed page being asked for over
// and over as the sentinel sits on screen.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Library } from "@/pages/Library";
import { renderPage } from "@/test/harness";

let scrollToBottom: () => void = () => {};

const PAGE_SIZE = 60;
const fullPage = (lead: string) => [
  lead,
  ...Array.from({ length: PAGE_SIZE - 1 }, (_, i) => `Film ${i}`),
];

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
  vi.restoreAllMocks();
  localStorage.clear();
  vi.spyOn(api, "movieSections").mockResolvedValue([] as never);
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

afterEach(() => {
  localStorage.clear();
});

describe("what survives navigating away", () => {
  it("remembers the sort field", async () => {
    // Somebody sorting by size is working through their largest files. Coming
    // back to alphabetical after opening one title restarts that job.
    vi.spyOn(api, "movies").mockResolvedValue(page(["The Matrix"], 1) as never);

    const first = renderPage(<Library />);
    await screen.findByText("The Matrix");
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "file_size");
    first.unmount();

    // Clear the history rather than re-spying: `vi.spyOn` on an already-spied
    // method hands back the same spy, calls and all, so `calls[0]` would still be
    // the first mount's request.
    const movies = vi.spyOn(api, "movies");
    movies.mockClear();
    renderPage(<Library />);

    await waitFor(() => expect(movies).toHaveBeenCalled());
    expect(movies.mock.calls[0][0]).toMatchObject({ sort: "file_size" });
  });

  it("remembers grid or table", async () => {
    vi.spyOn(api, "movies").mockResolvedValue(page(["The Matrix"], 1) as never);

    const first = renderPage(<Library />);
    await screen.findByText("The Matrix");
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    first.unmount();

    renderPage(<Library />);
    await screen.findByText("The Matrix");

    expect(localStorage.getItem("sift.library.view")).toBe("table");
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("NEGATIVE CONTROL: a stored value it does not recognise falls back", async () => {
    // localStorage is writable by anything on the origin and survives upgrades
    // that rename a sort field. A stored value taken on trust goes into the query
    // string and the server answers 422 — a blank library with no explanation.
    localStorage.setItem("sift.library.sort", "junk_score_v3");
    const movies = vi.spyOn(api, "movies").mockResolvedValue(page(["The Matrix"], 1) as never);

    renderPage(<Library />);

    await waitFor(() => expect(movies).toHaveBeenCalled());
    expect(movies.mock.calls[0][0]).toMatchObject({ sort: "title" });
  });
});

describe("the empty state", () => {
  it("offers a scan when the library has never been populated", async () => {
    vi.spyOn(api, "movies").mockResolvedValue(page([], 0) as never);

    renderPage(<Library />);

    await screen.findByText(/No movies match these filters/);
    expect(screen.getByText(/Run a scan to populate the library/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /run scan/i })).toBeTruthy();
  });

  it("offers to clear the filters instead when a search found nothing", async () => {
    // NEGATIVE CONTROL for the above, and the distinction is the point: "run a
    // scan" is useless advice to somebody who has a full library and mistyped a
    // title, and running one is the most expensive thing the app does.
    vi.spyOn(api, "movies").mockResolvedValue(page([], 0) as never);

    renderPage(<Library />, "/library?q=zzzz");

    await screen.findByText(/Try a different search or clear filters/);
    expect(screen.queryByRole("button", { name: /run scan/i })).toBeNull();
  });
});

describe("the section filter", () => {
  it("stays hidden when there is only one library to choose from", async () => {
    // A select with one option is a control that cannot do anything, sitting in
    // the row where the controls that can are.
    vi.spyOn(api, "movieSections").mockResolvedValue(["Films"] as never);
    vi.spyOn(api, "movies").mockResolvedValue(page(["The Matrix"], 1) as never);

    renderPage(<Library />);
    await screen.findByText("The Matrix");

    expect(screen.queryByLabelText("Plex library section")).toBeNull();
  });

  it("appears once there is a real choice, and narrows the query", async () => {
    vi.spyOn(api, "movieSections").mockResolvedValue(["Films", "4K Films"] as never);
    const movies = vi.spyOn(api, "movies").mockResolvedValue(page(["The Matrix"], 1) as never);

    renderPage(<Library />);
    await screen.findByText("The Matrix");

    await userEvent.selectOptions(screen.getByLabelText("Plex library section"), "4K Films");

    await waitFor(() =>
      expect(movies.mock.calls.at(-1)?.[0]).toMatchObject({ section: "4K Films" }),
    );
  });

  it("survives the section list failing to load", async () => {
    // NEGATIVE CONTROL: the list of sections is a nicety. Losing it must not take
    // the library with it.
    //
    // Mutation-checked, and the same result as the Activity page's scan list:
    // replacing `.catch(() => setSections([]))` with a rethrow leaves this green,
    // because an unhandled rejection in a detached promise inside an effect never
    // reaches the render. The catch keeps the console clean and pins `sections`
    // at empty; the independence of the two fetches is what protects the list.
    // The pin is on the library still rendering, which is the property that
    // matters.
    vi.spyOn(api, "movieSections").mockRejectedValue(new Error("no sections"));
    vi.spyOn(api, "movies").mockResolvedValue(page(["The Matrix"], 1) as never);

    renderPage(<Library />);

    await screen.findByText("The Matrix");
    expect(screen.queryByLabelText("Plex library section")).toBeNull();
  });
});

describe("paging", () => {
  it("stops asking once the server returns a short page", async () => {
    // The end of the data. Without this the sentinel keeps firing at the bottom
    // of a finished list and the server is asked for page after empty page.
    const movies = vi
      .spyOn(api, "movies")
      .mockResolvedValueOnce(page(fullPage("The Matrix"), 90) as never)
      .mockResolvedValueOnce(page(["Toy Story"], 90) as never);

    renderPage(<Library />);
    await screen.findByText("The Matrix");

    scrollToBottom();
    await screen.findByText("Toy Story");
    expect(movies).toHaveBeenCalledTimes(2);

    scrollToBottom();
    scrollToBottom();
    await waitFor(() => expect(movies).toHaveBeenCalledTimes(2));
  });

  it("does not re-fire into the same failure while the sentinel sits on screen", async () => {
    // The sentinel stays visible when a page fails, so without the guard the
    // observer retries continuously — a request storm against a server that is
    // already refusing, with nothing on screen changing.
    const movies = vi
      .spyOn(api, "movies")
      .mockResolvedValueOnce(page(fullPage("The Matrix"), 200) as never)
      .mockRejectedValue(new Error("page failed"));

    renderPage(<Library />);
    await screen.findByText("The Matrix");

    scrollToBottom();
    await screen.findByText(/page failed/);
    const after = movies.mock.calls.length;

    scrollToBottom();
    scrollToBottom();
    scrollToBottom();

    await waitFor(() => expect(movies.mock.calls.length).toBe(after));
  });
});
