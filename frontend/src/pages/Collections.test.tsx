// An empty collections list means "every set you own part of is complete". A
// failed read must never borrow that sentence.

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Collections } from "@/pages/Collections";
import { renderPage } from "@/test/harness";

const GAP = {
  collection_id: 1,
  name: "The Matrix Collection",
  owned_count: 1,
  total_count: 2,
  members: [
    { tmdb_id: 603, title: "The Matrix", year: 1999, owned: true, poster_url: null },
    { tmdb_id: 604, title: "The Matrix Reloaded", year: 2003, owned: false, poster_url: null },
  ],
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("when the collections cannot be loaded", () => {
  it("says so rather than reporting a complete shelf", async () => {
    vi.spyOn(api, "missingCollections").mockRejectedValue(new Error("gateway timeout"));

    renderPage(<Collections />);

    expect(await screen.findByText(/gateway timeout/)).toBeInTheDocument();
    expect(screen.queryByText(/No collection gaps/i)).not.toBeInTheDocument();
  });

  it("offers a retry that actually refetches", async () => {
    const gaps = vi
      .spyOn(api, "missingCollections")
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce({ collections: [GAP] } as never);

    renderPage(<Collections />);
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    expect(await screen.findByText(/The Matrix Collection/)).toBeInTheDocument();
    expect(gaps).toHaveBeenCalledTimes(2);
  });
});

describe("NEGATIVE CONTROL: a genuinely complete shelf", () => {
  it("still reads as good news", async () => {
    vi.spyOn(api, "missingCollections").mockResolvedValue({ collections: [] } as never);

    renderPage(<Collections />);

    expect(await screen.findByText(/No collection gaps/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });
});
