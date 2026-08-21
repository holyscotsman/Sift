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

// The other thing it must never do is make a staged action look like one that
// happened. This is the only screen that answers "did that file actually go?",
// and both wrong answers are bad in different ways: believing a file is gone when
// it is staged means re-running a removal that already succeeded; believing it is
// staged when it is gone means not looking for it until much later.

function action(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    type: "delete",
    status: "executed",
    actor: "user",
    dry_run: false,
    movie_tmdb_id: 603,
    payload: { title: "The Matrix", delete_files: true },
    created_at: new Date().toISOString(),
    error: null,
    ...overrides,
  };
}

describe("staged versus executed", () => {
  it("says so on the record when nothing actually left Sift", async () => {
    vi.spyOn(api, "activity").mockResolvedValue([action({ dry_run: true })] as never);

    renderPage(<Activity />);

    expect(await screen.findByText(/executed · staged/i)).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a live action is not labelled staged", async () => {
    vi.spyOn(api, "activity").mockResolvedValue([action({ dry_run: false })] as never);

    renderPage(<Activity />);

    expect(await screen.findByText("executed")).toBeInTheDocument();
    expect(screen.queryByText(/staged/i)).not.toBeInTheDocument();
  });

  it("marks a delete as needing approval, and an add as automatic", async () => {
    // The autonomy tier is the other half of the audit: it says whether the
    // person had to agree to this, or whether Sift did it on its own.
    vi.spyOn(api, "activity").mockResolvedValue([
      action({ id: 1, type: "delete" }),
      action({ id: 2, type: "add" }),
    ] as never);

    renderPage(<Activity />);

    expect(await screen.findByText("Approval")).toBeInTheDocument();
    expect(screen.getByText("Auto")).toBeInTheDocument();
  });

  it("keeps the dry-run flag in the payload, not only in the pill", async () => {
    // The pill is a summary; the payload is the record. Somebody reconstructing
    // what happened months later reads the second one.
    const userEvent = (await import("@testing-library/user-event")).default;
    vi.spyOn(api, "activity").mockResolvedValue([action({ dry_run: true })] as never);

    renderPage(<Activity />);
    await userEvent.click(await screen.findByRole("button", { name: /payload/i }));

    expect(await screen.findByText(/"dry_run": true/)).toBeInTheDocument();
    expect(screen.getByText(/"delete_files": true/)).toBeInTheDocument();
  });
});
