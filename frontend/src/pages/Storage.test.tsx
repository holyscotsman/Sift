// The Storage page is the one screen that can propose deleting files. What it
// must never do is propose one without being asked twice, and what it must never
// say is that anything has been removed — a finding becomes a *proposal*, and the
// owner still approves it on Activity before an agent touches a byte.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Storage } from "@/pages/Storage";
import { renderPage } from "@/test/harness";

const SURPLUS = ["/tv/scrubs/s01e01.sd.mkv", "/tv/scrubs/s01e02.sd.mkv"];

function tvStorage() {
  return {
    duplicates: [
      {
        tvdb_id: 76156,
        title: "Scrubs",
        library_section: "TV",
        episodes: [],
        surplus: 2,
        bytes_reclaimable: 2_000_000_000,
        surplus_paths: SURPLUS,
      },
    ],
    duplicate_bytes: 2_000_000_000,
    seasons: [],
    season_excess_bytes: 0,
    inconsistencies: [],
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getSettings").mockResolvedValue({ actions_dry_run: true } as never);
  vi.spyOn(api, "movieSizes").mockResolvedValue({
    items: [],
    excess_bytes: 0,
    undersized: [],
  } as never);
  vi.spyOn(api, "duplicates").mockResolvedValue({ items: [], total_surplus: 0 } as never);
  vi.spyOn(api, "baselines").mockResolvedValue({ buckets: [] } as never);
  vi.spyOn(api, "ledger").mockResolvedValue({
    items: [],
    total_bytes: 0,
    by_tier: {},
  } as never);
  vi.spyOn(api, "tvStorage").mockResolvedValue(tvStorage() as never);
});

describe("removing surplus episode copies", () => {
  it("asks before it proposes anything", async () => {
    const act = vi.spyOn(api, "actOnFinding");

    renderPage(<Storage />);
    await userEvent.click(await screen.findByRole("button", { name: /Remove 2 surplus files/i }));

    // The dialog names the files. Nothing has been sent.
    expect(await screen.findByText(SURPLUS[0])).toBeInTheDocument();
    expect(act).not.toHaveBeenCalled();
  });

  it("sends exactly the files it showed, once confirmed", async () => {
    const act = vi.spyOn(api, "actOnFinding").mockResolvedValue({
      action_id: 7,
      job_ids: [1, 2],
      detail: "Proposed — approve it on Activity to queue the removal.",
    } as never);

    renderPage(<Storage />);
    await userEvent.click(await screen.findByRole("button", { name: /Remove 2 surplus files/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Queue removal/i }));

    await waitFor(() => expect(act).toHaveBeenCalledTimes(1));
    expect(act.mock.calls[0][0]).toMatchObject({
      target_kind: "show",
      target_id: "76156",
      paths: SURPLUS,
    });
    // And it reports a proposal, not a deletion.
    expect(await screen.findByText(/approve it on Activity/i)).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: cancelling sends nothing at all", async () => {
    const act = vi.spyOn(api, "actOnFinding");

    renderPage(<Storage />);
    await userEvent.click(await screen.findByRole("button", { name: /Remove 2 surplus files/i }));
    await userEvent.click(await screen.findByRole("button", { name: /cancel/i }));

    expect(act).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByText(SURPLUS[0])).not.toBeInTheDocument());
  });
});
