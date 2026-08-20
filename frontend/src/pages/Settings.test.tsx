// The banner that answers "why are my keys not being saved?". They were saved —
// the key that decrypts them changed, and until now the field simply showed
// empty, which looks exactly like a failed save.

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Settings } from "@/pages/Settings";
import { renderPage } from "@/test/harness";

const SETTINGS = {
  connections: [],
  thresholds: {
    min_votes: 100,
    rating_floor: 5,
    unwatched_years: 2,
    junk_cutoff: 70,
    borderline_cutoff: 50,
  },
  ai_configured: false,
  ai_compare_available: false,
  actions_dry_run: true,
  database_kind: "postgres",
  scan_interval_hours: 24,
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getSettings").mockResolvedValue(SETTINGS as never);
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
});

describe("when saved credentials can no longer be read", () => {
  it("says so, and names them", async () => {
    vi.spyOn(api, "getConfig").mockResolvedValue({
      connections: { radarr: { base_url: "http://radarr:7878", api_key_set: false } },
      unreadable: { radarr: ["api_key"], plex: ["token"] },
    } as never);

    renderPage(<Settings />);
    // Connections is not the tab you land on — get there the way an owner does.
    await userEvent.click(screen.getByRole("button", { name: "Connections" }));

    expect(await screen.findByText(/2 saved credential\(s\) can no longer be read/i))
      .toBeInTheDocument();
    // Naming them is the point — "something is wrong" is what the empty field
    // already said.
    expect(await screen.findByText(/radarr \(api_key\)/)).toBeInTheDocument();
    expect(await screen.findByText(/plex \(token\)/)).toBeInTheDocument();
  });
});

describe("NEGATIVE CONTROL: credentials that are fine", () => {
  it("gets no banner at all", async () => {
    vi.spyOn(api, "getConfig").mockResolvedValue({
      connections: { radarr: { base_url: "http://radarr:7878", api_key_set: true } },
      unreadable: {},
    } as never);

    renderPage(<Settings />);
    await userEvent.click(screen.getByRole("button", { name: "Connections" }));

    // Wait for the tab to have rendered before asserting an absence.
    await screen.findByText(/Edit connections/i);
    expect(screen.queryByText(/can no longer be read/i)).not.toBeInTheDocument();
  });
});
