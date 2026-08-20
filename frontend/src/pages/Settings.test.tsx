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

// The Account tab. At 11% coverage this whole screen was effectively untested —
// including the panel that changes the password, which is the one place in the
// app where wrong copy has a security consequence rather than a cosmetic one.

async function openAccount() {
  renderPage(<Settings />);
  await userEvent.click(await screen.findByRole("button", { name: /^account$/i }));
}

describe("changing the password", () => {
  it("says the other devices were signed out, because they were", async () => {
    // Rotating the signing secret is the point of this feature: the reason
    // anyone changes a password on a reachable instance is that they think
    // someone else has access. The message used to say "your sessions stay
    // signed in" — true of the old behaviour, and read as "nothing was revoked"
    // by the one person who most needs to know that something was.
    const change = vi
      .spyOn(api, "changePassword")
      .mockResolvedValue({ token: "new", username: "owner" } as never);

    await openAccount();
    await userEvent.type(screen.getByLabelText(/current password/i), "oldpassword");
    await userEvent.type(screen.getByLabelText(/^new password/i), "newpassword");
    await userEvent.type(screen.getByLabelText(/confirm new password/i), "newpassword");
    await userEvent.click(screen.getByRole("button", { name: /change password/i }));

    expect(change).toHaveBeenCalledWith("oldpassword", "newpassword");
    expect(await screen.findByText(/other device has been signed out/i)).toBeInTheDocument();
    expect(screen.queryByText(/sessions stay signed in/i)).not.toBeInTheDocument();
  });

  it("clears the fields so the new password is not left on screen", async () => {
    vi.spyOn(api, "changePassword").mockResolvedValue({
      token: "new",
      username: "owner",
    } as never);

    await openAccount();
    const current = screen.getByLabelText(/current password/i) as HTMLInputElement;
    const next = screen.getByLabelText(/^new password/i) as HTMLInputElement;
    await userEvent.type(current, "oldpassword");
    await userEvent.type(next, "newpassword");
    await userEvent.type(screen.getByLabelText(/confirm new password/i), "newpassword");
    await userEvent.click(screen.getByRole("button", { name: /change password/i }));

    await screen.findByText(/signed out/i);
    expect(current.value).toBe("");
    expect(next.value).toBe("");
  });

  it("NEGATIVE CONTROL: mismatched confirmation never reaches the server", async () => {
    // Caught in the browser rather than by a round trip — and, more to the point,
    // a password nobody typed twice is a password nobody knows.
    const change = vi.spyOn(api, "changePassword").mockResolvedValue({} as never);

    await openAccount();
    await userEvent.type(screen.getByLabelText(/current password/i), "oldpassword");
    await userEvent.type(screen.getByLabelText(/^new password/i), "newpassword");
    await userEvent.type(screen.getByLabelText(/confirm new password/i), "different");
    await userEvent.click(screen.getByRole("button", { name: /change password/i }));

    expect(await screen.findByText(/don't match/i)).toBeInTheDocument();
    expect(change).not.toHaveBeenCalled();
  });

  it("NEGATIVE CONTROL: a short password never reaches the server", async () => {
    const change = vi.spyOn(api, "changePassword").mockResolvedValue({} as never);

    await openAccount();
    await userEvent.type(screen.getByLabelText(/current password/i), "oldpassword");
    await userEvent.type(screen.getByLabelText(/^new password/i), "short");
    await userEvent.type(screen.getByLabelText(/confirm new password/i), "short");
    await userEvent.click(screen.getByRole("button", { name: /change password/i }));

    expect(await screen.findByText(/needs 8\+ characters/i)).toBeInTheDocument();
    expect(change).not.toHaveBeenCalled();
  });

  it("reports a wrong current password instead of claiming success", async () => {
    // The server answers 401 here. Showing the success message anyway would tell
    // someone their password had changed when it had not — and they would find
    // out at the worst possible moment, which is the next time they sign in.
    vi.spyOn(api, "changePassword").mockRejectedValue(
      new Error("current password is wrong"),
    );

    await openAccount();
    await userEvent.type(screen.getByLabelText(/current password/i), "wrongpassword");
    await userEvent.type(screen.getByLabelText(/^new password/i), "newpassword");
    await userEvent.type(screen.getByLabelText(/confirm new password/i), "newpassword");
    await userEvent.click(screen.getByRole("button", { name: /change password/i }));

    const message = await screen.findByText(/current password is wrong/i);
    expect(message).toBeInTheDocument();
    expect(screen.queryByText(/signed out/i)).not.toBeInTheDocument();
    // Colour is the only thing that distinguishes the two outcomes at a glance,
    // and the `ok` flag drives nothing else. A failure rendered in the success
    // green is a failure most people would read straight past.
    expect(message).toHaveStyle({ color: "var(--junk)" });
  });
});
