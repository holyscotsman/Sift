// The Junk queue is the screen where a mistake deletes a file, so these pin the
// moments where it previously said something untrue.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Junk } from "@/pages/Junk";
import { candidate, renderPage } from "@/test/harness";

beforeEach(() => {
  vi.spyOn(api, "getSettings").mockResolvedValue({ actions_dry_run: true } as never);
});

describe("when the queue cannot be loaded", () => {
  it("says so rather than reporting an empty queue", async () => {
    vi.spyOn(api, "junk").mockRejectedValue(new Error("Plex is unreachable"));

    renderPage(<Junk />);

    // The failure has to be visible...
    expect(await screen.findByText(/Plex is unreachable/)).toBeInTheDocument();
    // ...and must never be dressed up as good news. This screen's emptiness is
    // meant to mean "nothing is flagged", which is the opposite of what happened.
    expect(screen.queryByText(/All caught up/i)).not.toBeInTheDocument();
  });

  it("offers a retry that actually refetches", async () => {
    const junk = vi
      .spyOn(api, "junk")
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce({ items: [candidate()], total: 1 } as never);

    renderPage(<Junk />);
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    expect(await screen.findByText("The Matrix")).toBeInTheDocument();
    expect(junk).toHaveBeenCalledTimes(2);
  });
});

describe("NEGATIVE CONTROL: a genuinely empty queue", () => {
  it("still reads as good news", async () => {
    vi.spyOn(api, "junk").mockResolvedValue({ items: [], total: 0 } as never);

    renderPage(<Junk />);

    // A page that showed an error for every empty response would pass the tests
    // above and be a different, equally wrong screen.
    expect(await screen.findByText(/All caught up/i)).toBeInTheDocument();
  });
});

describe("staged versus live", () => {
  it("says which mode the server is in, before anything is clicked", async () => {
    vi.spyOn(api, "junk").mockResolvedValue({ items: [candidate()], total: 1 } as never);

    renderPage(<Junk />);

    expect(await screen.findByText(/Staged — nothing is deleted/i)).toBeInTheDocument();
  });

  it("says so just as plainly when deletes are real", async () => {
    vi.spyOn(api, "junk").mockResolvedValue({ items: [candidate()], total: 1 } as never);
    vi.spyOn(api, "getSettings").mockResolvedValue({ actions_dry_run: false } as never);

    renderPage(<Junk />);

    expect(await screen.findByText(/Live — deletes are real/i)).toBeInTheDocument();
  });
});

describe("keeping a title", () => {
  it("can be done from the keyboard", async () => {
    vi.spyOn(api, "junk").mockResolvedValue({ items: [candidate()], total: 1 } as never);
    const keep = vi.spyOn(api, "setKeepOverride").mockResolvedValue({} as never);

    renderPage(<Junk />);
    const row = await screen.findByRole("group", { name: "The Matrix" });
    row.focus();
    await userEvent.keyboard("k");

    await waitFor(() => expect(keep).toHaveBeenCalledWith(603, true));
    expect(await screen.findByText("kept")).toBeInTheDocument();
  });
});

describe("removing a title", () => {
  it("proposes nothing until the confirmation is answered", async () => {
    vi.spyOn(api, "junk").mockResolvedValue({ items: [candidate()], total: 1 } as never);
    const propose = vi.spyOn(api, "proposeAction");

    renderPage(<Junk />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve removal" }));

    // The dialog is up and the server has heard nothing. The engine refuses an
    // unapproved delete anyway, but a screen that fires first and asks second
    // would mean the dialog was decoration.
    expect(await screen.findByText(/Approve removal of 1 title/i)).toBeInTheDocument();
    expect(propose).not.toHaveBeenCalled();
  });

  it("removes the row you clicked, not everything that happens to be ticked", async () => {
    // Titles arrive ticked by default — that is deliberate, and it is exactly what
    // makes a per-row button dangerous if it reads the selection instead of its own
    // row. Clicking one row must propose one title.
    vi.spyOn(api, "junk").mockResolvedValue({
      items: [candidate(), candidate({ tmdb_id: 27205, title: "Inception" })],
      total: 2,
    } as never);
    const propose = vi
      .spyOn(api, "proposeAction")
      .mockImplementation(
        async (body: unknown) =>
          ({ id: (body as { movie_tmdb_id: number }).movie_tmdb_id }) as never,
      );
    const approve = vi.spyOn(api, "approveAction").mockResolvedValue({} as never);
    const execute = vi
      .spyOn(api, "executeAction")
      .mockResolvedValue({ dry_run: true } as never);

    renderPage(<Junk />);
    // Both rows are ticked, so the bulk control offers two. Click the first row's
    // own button instead — an exact name, because the bulk one is "Approve removal (2)".
    const rows = await screen.findAllByRole("button", { name: "Approve removal" });
    expect(rows).toHaveLength(2);
    await userEvent.click(rows[0]);
    await userEvent.click(await screen.findByRole("button", { name: /approve \(staged\)/i }));

    await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
    // Propose → approve → execute, per title, with the approval its own explicit
    // call rather than something propose is trusted to imply.
    expect(propose).toHaveBeenCalledTimes(1);
    expect(approve).toHaveBeenCalledTimes(1);
    expect(propose.mock.calls[0][0]).toMatchObject({ type: "delete", movie_tmdb_id: 603 });
    expect(approve).not.toHaveBeenCalledWith(27205);
  });

  it("NEGATIVE CONTROL: cancelling proposes nothing", async () => {
    vi.spyOn(api, "junk").mockResolvedValue({ items: [candidate()], total: 1 } as never);
    const propose = vi.spyOn(api, "proposeAction");

    renderPage(<Junk />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve removal" }));
    await userEvent.click(await screen.findByRole("button", { name: /cancel/i }));

    expect(propose).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByText(/Approve removal of 1 title/i)).not.toBeInTheDocument(),
    );
  });
});

describe("approving the whole queue at once", () => {
  function stubActions() {
    const propose = vi
      .spyOn(api, "proposeAction")
      .mockImplementation(
        async (body: unknown) =>
          ({ id: (body as { movie_tmdb_id: number }).movie_tmdb_id }) as never,
      );
    const approve = vi.spyOn(api, "approveAction").mockResolvedValue({} as never);
    const execute = vi
      .spyOn(api, "executeAction")
      .mockResolvedValue({ dry_run: true } as never);
    return { propose, approve, execute };
  }

  it("still approves every title individually", async () => {
    // The standing rule is per-item approval, and a bulk button is the obvious
    // place for that to quietly become one approval covering many files. Three
    // titles must be three proposals and three approvals — a convenience for the
    // person clicking, not a different kind of write.
    vi.spyOn(api, "junk").mockResolvedValue({
      items: [
        candidate(),
        candidate({ tmdb_id: 27205, title: "Inception" }),
        candidate({ tmdb_id: 78, title: "Blade Runner" }),
      ],
      total: 3,
    } as never);
    const { propose, approve, execute } = stubActions();

    renderPage(<Junk />);
    await userEvent.click(await screen.findByRole("button", { name: /select all and approve \(3\)/i }));
    await userEvent.click(await screen.findByRole("button", { name: /approve \(staged\)/i }));

    await waitFor(() => expect(execute).toHaveBeenCalledTimes(3));
    expect(propose).toHaveBeenCalledTimes(3);
    expect(approve).toHaveBeenCalledTimes(3);
    expect(
      propose.mock.calls
        .map((c) => (c[0] as { movie_tmdb_id: number }).movie_tmdb_id)
        // Numeric compare: a bare .sort() is lexicographic and puts 27205 first.
        .sort((a, b) => a - b),
    ).toEqual([78, 603, 27205]);
  });

  it("NEGATIVE CONTROL: the bulk button asks first, like every other removal", async () => {
    vi.spyOn(api, "junk").mockResolvedValue({
      items: [candidate(), candidate({ tmdb_id: 27205, title: "Inception" })],
      total: 2,
    } as never);
    const { propose } = stubActions();

    renderPage(<Junk />);
    await userEvent.click(await screen.findByRole("button", { name: /select all and approve \(2\)/i }));

    expect(await screen.findByText(/Approve removal of 2 titles\?/i)).toBeInTheDocument();
    expect(propose).not.toHaveBeenCalled();
  });

  it("stops at the first failure and says the rest are untouched", async () => {
    // A removal failing usually means the server or Radarr has gone away. Walking
    // on through two hundred more is not persistence, it is two hundred more ways
    // to be wrong — and the person needs to know where the walk stopped.
    vi.spyOn(api, "junk").mockResolvedValue({
      items: [
        candidate(),
        candidate({ tmdb_id: 27205, title: "Inception" }),
        candidate({ tmdb_id: 78, title: "Blade Runner" }),
      ],
      total: 3,
    } as never);
    const propose = vi
      .spyOn(api, "proposeAction")
      .mockResolvedValueOnce({ id: 1 } as never)
      .mockRejectedValue(new Error("Radarr refused"));
    vi.spyOn(api, "approveAction").mockResolvedValue({} as never);
    const execute = vi
      .spyOn(api, "executeAction")
      .mockResolvedValue({ dry_run: true } as never);

    renderPage(<Junk />);
    await userEvent.click(await screen.findByRole("button", { name: /select all and approve \(3\)/i }));
    await userEvent.click(await screen.findByRole("button", { name: /approve \(staged\)/i }));

    expect(await screen.findByText(/remaining titles are untouched/i)).toBeInTheDocument();
    // One succeeded, the second threw, the third was never attempted.
    expect(execute).toHaveBeenCalledTimes(1);
    expect(propose).toHaveBeenCalledTimes(2);
  });
});
