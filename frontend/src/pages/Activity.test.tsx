// The activity log is described in its own header as the trust surface. What it
// must never do is state that something did not happen.

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Activity } from "@/pages/Activity";
import { renderPage } from "@/test/harness";

beforeEach(() => {
  vi.spyOn(api, "scanList").mockResolvedValue([] as never);
});

describe("when the log cannot be loaded", () => {
  it("does not claim there has been no activity", async () => {
    vi.spyOn(api, "activity").mockRejectedValue(new Error("connection reset"));

    renderPage(<Activity />);

    expect(await screen.findByText(/connection reset/)).toBeInTheDocument();
    // If a delete has just executed and this request fails, "No activity yet"
    // tells the owner the delete never happened.
    expect(screen.queryByText(/No activity yet/i)).not.toBeInTheDocument();
  });
});

describe("NEGATIVE CONTROL: a genuinely empty log", () => {
  it("still says there is nothing yet", async () => {
    vi.spyOn(api, "activity").mockResolvedValue([] as never);

    renderPage(<Activity />);

    expect(await screen.findByText(/No activity yet/i)).toBeInTheDocument();
  });
});
