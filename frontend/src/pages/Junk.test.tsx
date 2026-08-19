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
