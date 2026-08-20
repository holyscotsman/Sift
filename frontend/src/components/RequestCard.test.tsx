// One click here spends someone else's disk and bandwidth, on a machine that is
// not this one. The failure mode is not a crash — it is six hundred films
// arriving, and an Overseerr queue to unpick by hand.

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RequestAllButton } from "@/components/RequestCard";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

function items(n: number) {
  return Array.from({ length: n }, (_, i) => ({ tmdb_id: 1000 + i, title: `Film ${i}` }));
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("requesting a whole set", () => {
  it("never sends more than the cap, however many are on screen", async () => {
    // The Missing list is endless: after a minute of scrolling "everything shown"
    // is hundreds of titles, and the caller has no bound of its own to offer.
    const request = vi.spyOn(api, "requestMovie").mockResolvedValue({} as never);

    renderPage(<RequestAllButton items={items(600)} />);
    await userEvent.click(screen.getByRole("button"));

    await screen.findByText(/requested/i);
    expect(request).toHaveBeenCalledTimes(25);
  });

  it("says the set was capped rather than truncating it silently", async () => {
    vi.spyOn(api, "requestMovie").mockResolvedValue({} as never);

    renderPage(<RequestAllButton items={items(600)} />);

    // "Request all 600 shown" over a set of 25 is a true-sounding sentence that
    // describes the wrong thing, and it is how someone finds out later that the
    // films they thought they had asked for were never requested.
    expect(screen.getByRole("button")).toHaveTextContent(/top 25 of 600/i);
  });

  it("NEGATIVE CONTROL: a set under the cap is sent whole and not described as capped", async () => {
    const request = vi.spyOn(api, "requestMovie").mockResolvedValue({} as never);

    renderPage(<RequestAllButton items={items(4)} />);
    expect(screen.getByRole("button")).not.toHaveTextContent(/top 25/i);

    await userEvent.click(screen.getByRole("button"));
    await screen.findByText(/All 4 requested/i);
    expect(request).toHaveBeenCalledTimes(4);
  });

  it("NEGATIVE CONTROL: one failure stops the walk instead of grinding on", async () => {
    // A failing target is usually a dead Overseerr or an exhausted disk. Firing
    // the remaining twenty-four requests at it helps nobody.
    const request = vi
      .spyOn(api, "requestMovie")
      .mockResolvedValueOnce({} as never)
      .mockRejectedValue(new Error("Overseerr refused"));

    renderPage(<RequestAllButton items={items(10)} />);
    await userEvent.click(screen.getByRole("button"));

    await screen.findByText(/1 requested/i);
    expect(request).toHaveBeenCalledTimes(2);
  });
});

describe("the two-step confirm", () => {
  it("arms on the first click and sends on the second", async () => {
    const request = vi.spyOn(api, "requestMovie").mockResolvedValue({} as never);

    renderPage(<RequestAllButton items={items(3)} confirmFirst />);
    await userEvent.click(screen.getByRole("button"));

    expect(request).not.toHaveBeenCalled();
    expect(screen.getByRole("button")).toHaveTextContent(/Send 3 requests\?/i);

    await userEvent.click(screen.getByRole("button"));
    await screen.findByText(/All 3 requested/i);
  });
});
