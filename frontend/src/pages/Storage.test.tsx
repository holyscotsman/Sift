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

describe("when there are more surplus files than the dialog can list", () => {
  function manyPaths(n: number) {
    const paths = Array.from({ length: n }, (_, i) => `/tv/scrubs/s01e${i}.sd.mkv`);
    vi.spyOn(api, "tvStorage").mockResolvedValue({
      ...tvStorage(),
      duplicates: [
        {
          ...tvStorage().duplicates[0],
          surplus: n,
          surplus_paths: paths,
        },
      ],
    } as never);
    return paths;
  }

  it("says how many it did not list", async () => {
    // The dialog caps the list at twenty. Showing twenty of forty-five under a
    // heading that says forty-five invites the reading that twenty is all of
    // them — and this is the dialog where that reading removes files. A
    // truncation nobody is told about is the same failure as no truncation,
    // only quieter.
    manyPaths(45);

    renderPage(<Storage />);
    await userEvent.click(await screen.findByRole("button", { name: /remove 45 surplus/i }));

    expect(await screen.findByText(/and 25 more not listed here/i)).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a list that fits says nothing about extras", async () => {
    // The counter must not appear when there is nothing it is counting. A dialog
    // that always warns is a dialog nobody reads.
    manyPaths(4);

    renderPage(<Storage />);
    await userEvent.click(await screen.findByRole("button", { name: /remove 4 surplus/i }));

    expect(await screen.findByText(/s01e0.sd.mkv/)).toBeInTheDocument();
    expect(screen.queryByText(/more not listed here/i)).not.toBeInTheDocument();
  });

  it("still sends every path, not just the ones it showed", async () => {
    // The cap is a display decision and must never become a scope decision. If
    // it ever leaked into the request, twenty-five duplicate files would sit on
    // disk after a removal that reported success.
    const paths = manyPaths(45);
    const act = vi
      .spyOn(api, "actOnFinding")
      .mockResolvedValue({ action_id: 1, job_ids: [], dry_run: true, detail: "Staged." } as never);

    renderPage(<Storage />);
    await userEvent.click(await screen.findByRole("button", { name: /remove 45 surplus/i }));
    await userEvent.click(await screen.findByRole("button", { name: /queue removal/i }));

    expect(act).toHaveBeenCalledTimes(1);
    expect((act.mock.calls[0][0] as { paths: string[] }).paths).toEqual(paths);
  });
});
