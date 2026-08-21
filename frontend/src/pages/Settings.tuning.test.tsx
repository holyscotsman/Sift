// The tabs of Settings that change how Sift behaves, rather than what it looks
// like.
//
// Settings.test.tsx covers the destructive and identity-bearing parts — the
// unreadable-credentials banner, the password change, the dry-run switch, the
// factory reset. This covers the tuning: scoring thresholds, the rescan schedule,
// the Radarr add defaults and the poster cache.

import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Settings } from "@/pages/Settings";
import { renderPage } from "@/test/harness";

const THRESHOLDS = {
  min_votes: 100,
  rating_floor: 5,
  unwatched_years: 2,
  junk_cutoff: 70,
  borderline_cutoff: 50,
};

function settings(overrides: Record<string, unknown> = {}) {
  return {
    connections: [],
    thresholds: THRESHOLDS,
    ai_configured: false,
    ai_compare_available: false,
    actions_dry_run: true,
    database_kind: "postgres",
    ephemeral_risk: false,
    secrets_encrypted: true,
    scan_interval_hours: 24,
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getSettings").mockResolvedValue(settings() as never);
  vi.spyOn(api, "authStatus").mockResolvedValue({
    setup_complete: true,
    username: "owner",
  } as never);
  vi.spyOn(api, "posterStats").mockResolvedValue({ count: 0, bytes: 0 } as never);
  vi.spyOn(api, "getActionsConfig").mockResolvedValue({ dry_run: true } as never);
  vi.spyOn(api, "versionStatus").mockResolvedValue({
    current: "0",
    latest: "0",
    behind: false,
  } as never);
  vi.spyOn(api, "radarrOptions").mockResolvedValue({
    root_folders: [],
    quality_profiles: [],
    default_root_folder: null,
    default_quality_profile_id: null,
  } as never);
});

async function openTab(name: string) {
  renderPage(<Settings />);
  await userEvent.click(screen.getByRole("button", { name }));
}

describe("the scoring thresholds", () => {
  it("says what a change would flag before it is saved", async () => {
    // The sliders move a number nobody can hold in their head. The preview is the
    // only thing that turns "junk cutoff 70" into "this would flag 412 titles",
    // and it has to arrive before the save, not after a re-score.
    const preview = vi.spyOn(api, "previewThresholds").mockResolvedValue({
      junk: 412,
      borderline: 88,
      total: 5000,
    } as never);
    const save = vi.spyOn(api, "saveThresholds");

    await openTab("Scoring");
    await screen.findByText("Scoring thresholds");

    await screen.findByText(/412 junk/);
    expect(screen.getByText(/88 borderline/)).toBeTruthy();
    expect(screen.getByText(/of 5000 titles/)).toBeTruthy();
    expect(preview).toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled(); // previewing is not saving
  });

  it("NEGATIVE CONTROL: a failed preview clears the count rather than leaving it stale", async () => {
    // A number left on screen from the previous slider position is worse than no
    // number: it describes a setting that is no longer selected, and the whole
    // purpose of the panel is to describe the one that is.
    //
    // The first version of this test only asserted that nothing was on screen
    // after a preview that always failed — there was never a stale value to
    // clear, so removing `setPreview(null)` left it green. This one lets a
    // preview land first and *then* breaks the next one.
    const preview = vi
      .spyOn(api, "previewThresholds")
      .mockResolvedValueOnce({ junk: 412, borderline: 88, total: 5000 } as never)
      .mockRejectedValue(new Error("preview failed"));

    await openTab("Scoring");
    await screen.findByText(/412 junk/);

    // `fireEvent.change`, not `userEvent.type`: arrow keys on a range input do
    // not move it under jsdom, so a typed keystroke fires no change event at all
    // and the second preview never happens.
    const slider = screen.getAllByRole("slider")[0] as HTMLInputElement;
    fireEvent.change(slider, { target: { value: String(Number(slider.value) + 10) } });

    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText(/412 junk/)).toBeNull());
    expect(screen.queryByText(/Would flag/)).toBeNull();
  });

  it("saves the thresholds actually on screen", async () => {
    vi.spyOn(api, "previewThresholds").mockResolvedValue({
      junk: 1,
      borderline: 1,
      total: 10,
    } as never);
    const save = vi.spyOn(api, "saveThresholds").mockResolvedValue({} as never);

    await openTab("Scoring");
    await screen.findByText("Scoring thresholds");

    await userEvent.click(screen.getByRole("button", { name: /save & re-score/i }));

    await waitFor(() => expect(save).toHaveBeenCalledWith(THRESHOLDS));
    expect(await screen.findByRole("button", { name: /saved/i })).toBeTruthy();
  });
});

describe("the rescan schedule", () => {
  it("marks the interval the server is actually on", async () => {
    await openTab("Autonomy");
    await screen.findByText("Automatic rescan");

    // 24 h is "Daily", and it is the one chip carrying the accent styling.
    const daily = screen.getByRole("button", { name: "Daily" });
    expect(daily.className).toContain("text-accent");
    expect(screen.getByRole("button", { name: "Off" }).className).not.toContain("text-accent");
  });

  it("puts the choice back when the save is refused", async () => {
    // The chip highlights immediately, which is right. What it must not do is
    // keep highlighting a schedule the server never accepted — the owner walks
    // away believing a rescan is booked and none is.
    vi.spyOn(api, "saveScanSchedule").mockRejectedValue(new Error("nope"));

    await openTab("Autonomy");
    await screen.findByText("Automatic rescan");

    const before = screen
      .getAllByRole("button")
      .filter((b) => b.className.includes("text-accent"))
      .map((b) => b.textContent);

    const off = screen.getByRole("button", { name: /^off$/i });
    await userEvent.click(off);

    await waitFor(() => {
      const after = screen
        .getAllByRole("button")
        .filter((b) => b.className.includes("text-accent"))
        .map((b) => b.textContent);
      expect(after).toEqual(before);
    });
  });

  it("cannot be changed before the current setting is known", async () => {
    // NEGATIVE CONTROL: clicking a chip while the interval is still null would
    // save a schedule chosen against nothing, silently replacing whatever is set.
    vi.spyOn(api, "getSettings").mockReturnValue(new Promise(() => {}) as never);
    const save = vi.spyOn(api, "saveScanSchedule");

    await openTab("Autonomy");
    await screen.findByText("Automatic rescan");

    const chips = screen.getAllByRole("button", { name: /^(off|every|daily|weekly)/i });
    expect(chips.every((c) => c.hasAttribute("disabled"))).toBe(true);
    expect(save).not.toHaveBeenCalled();
  });
});

describe("the Radarr add defaults", () => {
  it("stays off the page when Radarr has nothing to offer", async () => {
    // Unreachable or unconfigured Radarr returns empty lists, and the historical
    // default — first root folder, first profile — still applies. Two empty
    // selects would imply a choice that does not exist.
    await openTab("Autonomy");
    await screen.findByText("Automatic rescan");

    expect(screen.queryByText("Radarr add defaults")).toBeNull();
  });

  it("offers the real folders and profiles once Radarr answers", async () => {
    vi.spyOn(api, "radarrOptions").mockResolvedValue({
      root_folders: ["/films", "/films-4k"],
      quality_profiles: [
        { id: 4, name: "HD-1080p" },
        { id: 6, name: "Ultra-HD" },
      ],
      default_root_folder: "/films",
      default_quality_profile_id: 4,
    } as never);
    const save = vi.spyOn(api, "saveConfig").mockResolvedValue({} as never);

    await openTab("Autonomy");
    await screen.findByText("Radarr add defaults");

    await userEvent.selectOptions(screen.getByLabelText(/root folder/i), "/films-4k");
    await userEvent.selectOptions(screen.getByLabelText(/quality profile/i), "6");
    await userEvent.click(screen.getByRole("button", { name: /save defaults/i }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        radarr: { root_folder: "/films-4k", quality_profile_id: 6 },
      }),
    );
  });

  it("sends an empty profile rather than zero when nothing is chosen", async () => {
    // NEGATIVE CONTROL: `Number("")` is 0, and a profile id of 0 is a real value
    // that Radarr would reject. "Unset" has to stay unset all the way through.
    vi.spyOn(api, "radarrOptions").mockResolvedValue({
      root_folders: ["/films"],
      quality_profiles: [{ id: 4, name: "HD-1080p" }],
      default_root_folder: null,
      default_quality_profile_id: null,
    } as never);
    const save = vi.spyOn(api, "saveConfig").mockResolvedValue({} as never);

    await openTab("Autonomy");
    await screen.findByText("Radarr add defaults");
    await userEvent.click(screen.getByRole("button", { name: /save defaults/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toEqual({
      radarr: { root_folder: "", quality_profile_id: "" },
    });
  });
});

describe("the poster cache", () => {
  it("cannot be cleared when it is already empty", async () => {
    await openTab("Account");

    const clear = await screen.findByRole("button", { name: /^clear$/i });
    expect(clear.hasAttribute("disabled")).toBe(true);
  });

  it("clears, then re-reads the size rather than assuming zero", async () => {
    // The server decides what survives a clear. Assuming zero and printing it
    // would be the page inventing a number it was never told.
    const stats = vi
      .spyOn(api, "posterStats")
      .mockResolvedValueOnce({ count: 120, bytes: 4.2e7 } as never)
      .mockResolvedValueOnce({ count: 0, bytes: 0 } as never);
    const clear = vi.spyOn(api, "clearPosterCache").mockResolvedValue({} as never);

    await openTab("Account");
    await screen.findByText(/120 file\(s\) · 42 MB/);

    await userEvent.click(screen.getByRole("button", { name: /^clear$/i }));

    await waitFor(() => expect(clear).toHaveBeenCalled());
    await waitFor(() => expect(stats).toHaveBeenCalledTimes(2));
    await screen.findByText(/0 file\(s\) · 0 MB/);
  });
});
