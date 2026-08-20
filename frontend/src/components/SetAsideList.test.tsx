// The only screen a set-aside film ever appears on. If it lies, the decision is
// unreviewable — and "remembered forever" was only ever a promise to the
// suggestion engine, not one made against the person using it.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SetAsideList } from "@/components/SetAsideList";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

function ignored(tmdb_id: number, title: string) {
  return { tmdb_id, title, source: "missing" };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("reviewing what you set aside", () => {
  it("lists the films and offers each one a way back", async () => {
    vi.spyOn(api, "ignoredTitles").mockResolvedValue({
      items: [ignored(603, "The Matrix"), ignored(604, "Stalker")],
      total: 2,
    } as never);

    renderPage(<SetAsideList />);

    expect(await screen.findByText("The Matrix")).toBeInTheDocument();
    expect(screen.getByText("Stalker")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /suggest .* again/i })).toHaveLength(2);
  });

  it("removes a restored film and tells the list behind it to reload", async () => {
    vi.spyOn(api, "ignoredTitles").mockResolvedValue({
      items: [ignored(603, "The Matrix"), ignored(604, "Stalker")],
      total: 2,
    } as never);
    const unignore = vi.spyOn(api, "unignoreTitle").mockResolvedValue({ removed: true } as never);
    const onRestored = vi.fn();

    renderPage(<SetAsideList onRestored={onRestored} />);
    await userEvent.click(await screen.findByRole("button", { name: /suggest The Matrix again/i }));

    expect(unignore).toHaveBeenCalledWith(603);
    await waitFor(() => expect(screen.queryByText("The Matrix")).not.toBeInTheDocument());
    // The film rejoins the Missing list at its usual rank, so the page behind
    // this one is a row and a count out of date until it hears about it.
    expect(onRestored).toHaveBeenCalled();
    expect(screen.getByText("Stalker")).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a refused restore leaves the film where it was", async () => {
    // Removing it here on a failed write would say the film is back on the list
    // when the server still has it set aside — and the only screen that could
    // correct that impression is this one.
    vi.spyOn(api, "ignoredTitles").mockResolvedValue({
      items: [ignored(603, "The Matrix")],
      total: 1,
    } as never);
    vi.spyOn(api, "unignoreTitle").mockRejectedValue(new Error("write failed"));
    const onRestored = vi.fn();

    renderPage(<SetAsideList onRestored={onRestored} />);
    await userEvent.click(await screen.findByRole("button", { name: /suggest .* again/i }));

    await waitFor(() => expect(screen.getByText(/Couldn't bring/i)).toBeInTheDocument());
    expect(screen.getByText("The Matrix")).toBeInTheDocument();
    expect(onRestored).not.toHaveBeenCalled();
  });

  it("says a failed read is a failed read, not an empty list", async () => {
    // "Nothing set aside" after a failed load is the most reassuring possible
    // lie: it says every decision you made is gone, and reads as good news.
    vi.spyOn(api, "ignoredTitles").mockRejectedValue(new Error("gateway timeout"));

    renderPage(<SetAsideList />);

    expect(await screen.findByText(/gateway timeout/)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing set aside/i)).not.toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a genuinely empty list says so without an error", async () => {
    vi.spyOn(api, "ignoredTitles").mockResolvedValue({ items: [], total: 0 } as never);

    renderPage(<SetAsideList />);

    expect(await screen.findByText(/Nothing set aside/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });
});
