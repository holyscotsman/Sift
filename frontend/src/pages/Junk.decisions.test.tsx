// What the Junk queue does after you decide — the half that was not under test.
//
// Junk.test.tsx pins the moments where the screen said something untrue about a
// removal. This covers the moments where it could say something untrue about
// what is *stored*: a Keep that failed to save, a reset that quietly stripped
// protection set elsewhere, and a re-review that re-ticked rows somebody had
// just spared.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Junk } from "@/pages/Junk";
import { candidate, renderPage } from "@/test/harness";

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  vi.spyOn(api, "getSettings").mockResolvedValue({ actions_dry_run: true } as never);
});

afterEach(() => {
  localStorage.clear();
});

// Deliberately opposite orders: The Matrix scores higher, Toy Story is the bigger
// file. A fixture where score and size agree cannot tell the two sorts apart, and
// the whole point of the size sort is that it disagrees with the safety-relevant
// one — it serves a disk purge, not a junk review.
const MATRIX = candidate({ tmdb_id: 603, title: "The Matrix", file_size: 2e9, junk_score: 72 });
const TOY = candidate({ tmdb_id: 862, title: "Toy Story", file_size: 8e9, junk_score: 61 });

/** The rows on screen, in order. A row is a `role="group"` labelled by its title. */
function titles(): string[] {
  return screen
    .getAllByRole("group")
    .map((el) => el.getAttribute("aria-label") ?? "")
    .filter((label) => label === "The Matrix" || label === "Toy Story");
}

function queue(items = [MATRIX, TOY]) {
  vi.spyOn(api, "junk").mockResolvedValue({ items, total: items.length } as never);
}

describe("keeping a title", () => {
  it("persists the override so a rescan cannot bring it back", async () => {
    queue([MATRIX]);
    const keep = vi.spyOn(api, "setKeepOverride").mockResolvedValue({} as never);

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    await userEvent.click(screen.getByRole("button", { name: /keep it/i }));

    await waitFor(() => expect(keep).toHaveBeenCalledWith(603, true));
    expect(await screen.findByText(/kept/i)).toBeTruthy();
  });

  it("rolls the row back when the save fails, rather than showing a lie", async () => {
    // The row is marked kept immediately, which is right — the screen should feel
    // instant. What it must not do is leave that mark standing when the write
    // failed: the owner would move on believing a title is protected, and the
    // next scan would put it straight back in the queue.
    queue([MATRIX]);
    vi.spyOn(api, "setKeepOverride").mockRejectedValue(new Error("write failed"));

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    await userEvent.click(screen.getByRole("button", { name: /keep it/i }));

    // Back to undecided: the Keep button is available again.
    await waitFor(() => expect(screen.getByRole("button", { name: /keep it/i })).toBeTruthy());
    expect(screen.queryByText(/^kept$/i)).toBeNull();
  });

  it("can be done to everything selected at once", async () => {
    queue();
    const keep = vi.spyOn(api, "setKeepOverride").mockResolvedValue({} as never);

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    // Rows arrive ticked, so the toolbar is already there and both are selected.
    await userEvent.click(screen.getByRole("button", { name: /keep all selected/i }));

    await waitFor(() => expect(keep).toHaveBeenCalledTimes(2));
    expect(keep).toHaveBeenCalledWith(603, true);
    expect(keep).toHaveBeenCalledWith(862, true);
    // The toolbar goes once nothing is selected.
    await waitFor(() =>
      expect(screen.queryByRole("toolbar", { name: /selected titles/i })).toBeNull(),
    );
  });

  it("names the title it could not keep, one failure at a time", async () => {
    // NEGATIVE CONTROL for the bulk path: "some titles failed" is not actionable.
    // Each row rolls back on its own and says which one, because the owner has to
    // know exactly which title is still unprotected.
    queue();
    vi.spyOn(api, "setKeepOverride").mockImplementation((id: number) =>
      id === 862 ? Promise.reject(new Error("no")) : (Promise.resolve({}) as never),
    );

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    await userEvent.click(screen.getByRole("button", { name: /keep all selected/i }));

    await screen.findByText(/Couldn't save Keep for “Toy Story”/);
  });
});

describe("changing a decision", () => {
  it("releases the server-side override when undoing a Keep", async () => {
    queue([MATRIX]);
    const keep = vi.spyOn(api, "setKeepOverride").mockResolvedValue({} as never);

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    await userEvent.click(screen.getByRole("button", { name: /keep it/i }));
    await screen.findByRole("button", { name: /change/i });
    await userEvent.click(screen.getByRole("button", { name: /change/i }));

    await waitFor(() => expect(keep).toHaveBeenLastCalledWith(603, false));
  });

  it("NEGATIVE CONTROL: undoing a staged removal does not touch the override", async () => {
    // The comment beside this branch is the reason it exists. A reset that always
    // cleared the override would strip protection somebody set on the Library
    // page, silently, as a side effect of changing their mind about a removal.
    queue([MATRIX]);
    const keep = vi.spyOn(api, "setKeepOverride").mockResolvedValue({} as never);
    vi.spyOn(api, "proposeAction").mockResolvedValue({ id: 1 } as never);
    vi.spyOn(api, "approveAction").mockResolvedValue({} as never);
    vi.spyOn(api, "executeAction").mockResolvedValue({ dry_run: true } as never);

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    // The row's own button, not the bulk one ("Approve removal (1)").
    await userEvent.click(screen.getByRole("button", { name: "Approve removal" }));
    await userEvent.click(await screen.findByRole("button", { name: /approve \(staged\)/i }));
    await screen.findByRole("button", { name: /change/i });

    await userEvent.click(screen.getByRole("button", { name: /change/i }));

    expect(keep).not.toHaveBeenCalled();
  });
});

describe("the sort order", () => {
  it("survives leaving the page, because a disk purge is a session", async () => {
    queue();

    const first = renderPage(<Junk />);
    await screen.findByText("The Matrix");
    await userEvent.click(screen.getByRole("button", { name: "size" }));
    first.unmount();

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    // Sorted by size: Toy Story (8 GB) above The Matrix (2 GB) — the opposite of
    // the score order, which is what makes this a real check. A row is a
    // `role="group"` labelled by its title, because it is keyboard-operable.
    expect(titles()).toEqual(["Toy Story", "The Matrix"]);
    expect(localStorage.getItem("sift.junk.sort")).toBe("size");
  });

  it("NEGATIVE CONTROL: score is the default, not whatever was used last", async () => {
    // Score is the safety-relevant order — the titles most likely to be junk come
    // first. Size serves a disk purge, which is a deliberate choice, so it has to
    // be chosen rather than inherited from an empty localStorage.
    queue();

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    expect(localStorage.getItem("sift.junk.sort")).toBeNull();
    // The Matrix scores 72, Toy Story 61.
    expect(titles()).toEqual(["The Matrix", "Toy Story"]);
  });
});

describe("re-running the AI review", () => {
  it("refreshes the reasons without disturbing what is selected", async () => {
    // Re-running the explanation of a queue is not a reason to re-tick the dozen
    // titles somebody just spared. Losing the selection here means starting a
    // two-hundred-candidate pass again.
    queue();
    vi.spyOn(api, "runReview").mockResolvedValue({ reviewed: 2, provider: "ollama" } as never);

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    // Both arrive ticked; spare one, which is the state that must survive.
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Toy Story" }));
    await screen.findByText("1 selected");

    await userEvent.click(screen.getByRole("button", { name: /run ai review/i }));

    await screen.findByText(/Reviewed 2 title\(s\) via ollama/);
    expect(screen.getByText("1 selected")).toBeTruthy();
  });

  it("says the reason is the deterministic one when no AI is configured", async () => {
    // NEGATIVE CONTROL: without this the page reports "Reviewed 2 titles" and the
    // owner reads the deterministic rationale as an AI judgement. The whole point
    // of the review is that it is an explanation, not a verdict.
    queue();
    vi.spyOn(api, "runReview").mockResolvedValue({
      reviewed: 2,
      provider: "deterministic",
    } as never);

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    await userEvent.click(screen.getByRole("button", { name: /run ai review/i }));

    await screen.findByText(/no AI configured — showing the deterministic reason/);
  });

  it("says the review failed rather than leaving the button spinning", async () => {
    queue();
    vi.spyOn(api, "runReview").mockRejectedValue(new Error("ollama refused"));

    renderPage(<Junk />);
    await screen.findByText("The Matrix");

    await userEvent.click(screen.getByRole("button", { name: /run ai review/i }));

    await screen.findByText(/AI review failed/);
  });
});
