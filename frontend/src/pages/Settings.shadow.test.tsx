// The panel that lets the shadow scorer earn the right to replace the live one.
//
// `GET /api/junk/shadow-diff` has existed since the v2 scorer did and nothing
// consumed it, so the one decision it exists to inform — cut over, or don't —
// rested on a tool nobody could look at.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { resetSharedCache } from "@/lib/hooks";
import { Settings } from "@/pages/Settings";
import { renderPage } from "@/test/harness";

function diff(overrides: Record<string, unknown> = {}) {
  return {
    items: [
      {
        tmdb_id: 603,
        title: "The Matrix",
        year: 1999,
        v1_band: "junk",
        v1_score: 90,
        v2_band: "keep",
        v2_score: 10,
        v2_rule: "P3",
        v2_confidence: 0.8,
      },
    ],
    compared: 1200,
    disagreements: 40,
    v2_stricter: 12,
    v2_gentler: 25,
    v2_abstained: 3,
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetSharedCache();
  vi.spyOn(api, "getSettings").mockResolvedValue({
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
    ephemeral_risk: false,
    secrets_encrypted: true,
    scan_interval_hours: 24,
  } as never);
  vi.spyOn(api, "previewThresholds").mockResolvedValue({
    junk: 1,
    borderline: 1,
    total: 10,
  } as never);
});

async function openScoring() {
  renderPage(<Settings />);
  await userEvent.click(screen.getByRole("button", { name: "Scoring" }));
  await screen.findByText("Shadow scores");
}

describe("the shadow score panel", () => {
  it("asks for nothing until it is opened", async () => {
    // A comparison over the whole library on every visit to Settings, for a panel
    // most visits are not there for. It is behind a click on purpose.
    const shadow = vi.spyOn(api, "shadowDiff").mockResolvedValue(diff() as never);

    await openScoring();

    expect(shadow).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    await waitFor(() => expect(shadow).toHaveBeenCalled());
  });

  it("separates stricter from gentler, because they are opposite risks", async () => {
    // One number would hide the only thing that matters. v2 being stricter means
    // it queues films the live scorer keeps; gentler means it spares films the
    // live scorer flags. A single "40 disagreements" says nothing about which.
    vi.spyOn(api, "shadowDiff").mockResolvedValue(diff() as never);

    await openScoring();
    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    await screen.findByText("v2 stricter");
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("v2 gentler")).toBeTruthy();
    expect(screen.getByText("25")).toBeTruthy();
  });

  it("counts abstention as its own outcome, not as a verdict", async () => {
    // `insufficient` is v2 declining to answer. Folded into either direction it
    // would read as an opinion the scorer explicitly refused to give.
    vi.spyOn(api, "shadowDiff").mockResolvedValue(
      diff({ v2_stricter: 0, v2_gentler: 0, v2_abstained: 7, disagreements: 7 }) as never,
    );

    await openScoring();
    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    // Scoped to its own figure: "7" is also the disagreement count here, which is
    // the point — abstentions are the whole of the disagreement and neither
    // direction claimed any of it.
    const abstained = await screen.findByText("v2 abstained");
    expect(abstained.nextElementSibling?.textContent).toBe("7");
    const stricter = screen.getByText("v2 stricter");
    expect(stricter.nextElementSibling?.textContent).toBe("0");
    expect(screen.getByText("v2 gentler").nextElementSibling?.textContent).toBe("0");
  });

  it("shows each disagreement as a direction, not just a pair of numbers", async () => {
    vi.spyOn(api, "shadowDiff").mockResolvedValue(diff() as never);

    await openScoring();
    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    await screen.findByText("The Matrix");
    expect(screen.getByText("90 → 10")).toBeTruthy();
    expect(screen.getByText("P3")).toBeTruthy(); // which rule fired
  });

  it("offers no way to switch the live scorer over", async () => {
    // NEGATIVE CONTROL, and the reason the panel is worth having at all. The
    // cutover is a separate, deliberate act; a button here would turn "look at
    // the evidence" into "act on it", which is the opposite of what a shadow
    // eval is for.
    vi.spyOn(api, "shadowDiff").mockResolvedValue(diff() as never);

    await openScoring();
    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    await screen.findByText("The Matrix");
    expect(screen.queryByRole("button", { name: /switch|cut ?over|use v2|apply/i })).toBeNull();
    expect(screen.getByText(/Nothing here changes anything/)).toBeTruthy();
  });

  it("says why it is empty before a scan rather than claiming agreement", async () => {
    // NEGATIVE CONTROL: nothing compared and total agreement look identical if
    // you only print the disagreement count, and they mean opposite things —
    // "the scorer is ready" versus "the scorer has never run".
    vi.spyOn(api, "shadowDiff").mockResolvedValue(
      diff({ items: [], compared: 0, disagreements: 0 }) as never,
    );

    await openScoring();
    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    await screen.findByText(/fills in after the next one/);
    expect(screen.queryByText(/agree on every title/)).toBeNull();
  });

  it("distinguishes real agreement from having nothing to compare", async () => {
    vi.spyOn(api, "shadowDiff").mockResolvedValue(
      diff({ items: [], compared: 1200, disagreements: 0, v2_stricter: 0, v2_gentler: 0, v2_abstained: 0 }) as never,
    );

    await openScoring();
    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    await screen.findByText(/agree on every title they have both seen/);
  });

  it("says so when the comparison cannot be read", async () => {
    vi.spyOn(api, "shadowDiff").mockRejectedValue(new Error("scores_v2 is empty"));

    await openScoring();
    await userEvent.click(screen.getByRole("button", { name: /show the disagreements/i }));

    await screen.findByText("scores_v2 is empty");
  });
});
