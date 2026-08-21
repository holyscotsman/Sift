// The half of Storage that answers "I need 500 GB back".
//
// The page was at 54%, and the uncovered part was the target planner and the
// tier board — the whole point of the screen. Everything under test was the
// confirm dialog.
//
// A note on the fixtures below: the ones in Storage.test.tsx were written with
// invented field names (`total_bytes`/`by_tier` for `LedgerResponse`,
// `excess_bytes`/`undersized` for `MovieSizeResponse`) and cast with `as never`,
// which silences the compiler. Every summary figure on the page rendered
// "undefined" and no test looked. These match the types field for field, and the
// first test below reads the numbers precisely so a mismatched fixture cannot
// pass again.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { Storage } from "@/pages/Storage";
import { renderPage } from "@/test/harness";

function finding(overrides: Record<string, unknown> = {}) {
  return {
    kind: "duplicate",
    target_kind: "movie",
    target_id: "603",
    title: "The Matrix",
    detail: "Two copies in Films.",
    bytes_reclaimable: 8_000_000_000,
    risk_tier: 0,
    reversible: true,
    reasons: ["Identical runtime and resolution."],
    ...overrides,
  };
}

function ledger(items = [finding()]) {
  const tiers = [0, 1, 2].map((tier) => {
    const mine = items.filter((i) => i.risk_tier === tier);
    return {
      tier,
      label: String(tier),
      bytes_reclaimable: mine.reduce((n, i) => n + i.bytes_reclaimable, 0),
      count: mine.length,
    };
  });
  return {
    items,
    total_reclaimable: items.reduce((n, i) => n + i.bytes_reclaimable, 0),
    tiers,
  };
}

function sizes(overrides: Record<string, unknown> = {}) {
  return {
    items: [],
    total_reclaimable: 12_000_000_000,
    oversized_count: 3,
    truncated_count: 2,
    bad_rip_count: 1,
    short_films_cleared: 7,
    ...overrides,
  };
}

const EMPTY_TV = {
  duplicates: [],
  duplicate_bytes: 0,
  seasons: [],
  season_excess_bytes: 0,
  inconsistencies: [],
};

function mount(over: Partial<Record<string, unknown>> = {}) {
  vi.spyOn(api, "getSettings").mockResolvedValue({ actions_dry_run: true } as never);
  vi.spyOn(api, "movieSizes").mockResolvedValue((over.sizes ?? sizes()) as never);
  vi.spyOn(api, "duplicates").mockResolvedValue({ items: [], total_surplus: 4 } as never);
  vi.spyOn(api, "baselines").mockResolvedValue({ buckets: [] } as never);
  vi.spyOn(api, "ledger").mockResolvedValue((over.ledger ?? ledger()) as never);
  vi.spyOn(api, "tvStorage").mockResolvedValue((over.tv ?? EMPTY_TV) as never);
}

describe("the summary figures", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("reads every headline number off the response, in its own units", async () => {
    // This is the test the old fixtures could not have passed. Sizes are TB above
    // a terabyte and GB below; counts are counts.
    mount({ sizes: sizes({ total_reclaimable: 1_400_000_000_000 }) });

    renderPage(<Storage />);

    await screen.findByText("1.40 TB"); // reclaimable, in TB
    expect(screen.getByText("4")).toBeTruthy(); // surplus copies
    expect(screen.getByText("3")).toBeTruthy(); // oversized
    expect(screen.getByText("2")).toBeTruthy(); // not the film
    expect(screen.getByText("7")).toBeTruthy(); // short films cleared
    // Nothing rendered as the string "undefined", which is what a fixture with
    // the wrong field names produces.
    expect(screen.queryByText("undefined")).toBeNull();
  });
});

describe("the target planner", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mount();
  });

  it("asks the server in bytes for a target typed in gigabytes", async () => {
    const plan = vi.spyOn(api, "reclaimPlan").mockResolvedValue({
      target_bytes: 500e9,
      steps: [{ finding: finding(), running_total: 8e9 }],
      reached: true,
      total: 8e9,
      highest_tier: 0,
    } as never);

    renderPage(<Storage />);
    await screen.findByRole("button", { name: /work out a plan/i });

    await userEvent.click(screen.getByRole("button", { name: /work out a plan/i }));

    await waitFor(() => expect(plan).toHaveBeenCalledWith(500_000_000_000));
  });

  it("NEGATIVE CONTROL: an empty or nonsense target asks for nothing", async () => {
    // The field is free text. Sending `NaN` bytes would either 422 or, worse, be
    // read as zero and return a plan that frees nothing while looking successful.
    const plan = vi.spyOn(api, "reclaimPlan");

    renderPage(<Storage />);
    const input = await screen.findByRole("spinbutton");

    await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: /work out a plan/i }));

    await waitFor(() => expect(screen.queryByText(/Working it out/)).toBeNull());
    expect(plan).not.toHaveBeenCalled();
  });

  it("says plainly when the library cannot reach the target", async () => {
    // The important half. A planner that silently returned its best effort would
    // let somebody free 200 GB believing they had freed 500 and act on it.
    vi.spyOn(api, "reclaimPlan").mockResolvedValue({
      target_bytes: 500e9,
      steps: [{ finding: finding(), running_total: 8e9 }],
      reached: false,
      total: 8e9,
      highest_tier: 0,
    } as never);

    renderPage(<Storage />);
    await screen.findByRole("button", { name: /work out a plan/i });
    await userEvent.click(screen.getByRole("button", { name: /work out a plan/i }));

    await screen.findByText(/which is short of that/);
    expect(screen.getByText(/Nothing here can free more/)).toBeTruthy();
  });

  it("names the riskiest tier the plan has to reach", async () => {
    // "8 GB, and you will have to make a quality judgement to get it" is a
    // different offer from "8 GB, nothing is lost". The number alone hides that.
    vi.spyOn(api, "reclaimPlan").mockResolvedValue({
      target_bytes: 8e9,
      steps: [{ finding: finding({ risk_tier: 2 }), running_total: 8e9 }],
      reached: true,
      total: 8e9,
      highest_tier: 2,
    } as never);

    renderPage(<Storage />);
    await screen.findByRole("button", { name: /work out a plan/i });
    await userEvent.click(screen.getByRole("button", { name: /work out a plan/i }));

    await screen.findByText(/a judgement call/);
  });

  it("narrows the list to the plan's steps once there is a plan", async () => {
    vi.restoreAllMocks();
    mount({
      ledger: ledger([
        finding({ target_id: "603", title: "The Matrix" }),
        finding({ target_id: "862", title: "Toy Story" }),
      ]),
    });
    vi.spyOn(api, "reclaimPlan").mockResolvedValue({
      target_bytes: 8e9,
      steps: [{ finding: finding({ target_id: "603", title: "The Matrix" }), running_total: 8e9 }],
      reached: true,
      total: 8e9,
      highest_tier: 0,
    } as never);

    renderPage(<Storage />);
    await screen.findByText("Toy Story"); // both, before planning

    await userEvent.click(screen.getByRole("button", { name: /work out a plan/i }));

    await waitFor(() => expect(screen.queryByText("Toy Story")).toBeNull());
    expect(screen.getByText("The Matrix")).toBeTruthy();
  });

  it("puts the message on screen when the planner itself fails", async () => {
    vi.spyOn(api, "reclaimPlan").mockRejectedValue(new Error("ledger is empty"));

    renderPage(<Storage />);
    await screen.findByRole("button", { name: /work out a plan/i });
    await userEvent.click(screen.getByRole("button", { name: /work out a plan/i }));

    await screen.findByText("ledger is empty");
    // And the button comes back, so it can be retried.
    expect(
      screen.getByRole("button", { name: /work out a plan/i }).hasAttribute("disabled"),
    ).toBe(false);
  });
});

describe("the tier board", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("orders the tiers safest first and says what each one costs you", async () => {
    // Safest-first is the entire claim the page makes about being dependable.
    // Sorted by size instead, tier 2 would usually lead.
    mount({
      ledger: ledger([
        finding({ risk_tier: 0, bytes_reclaimable: 1e9 }),
        finding({ target_id: "2", risk_tier: 2, bytes_reclaimable: 900e9 }),
      ]),
    });

    renderPage(<Storage />);

    // Matched on each tier's own note rather than its label: the labels also
    // appear as a pill on every ledger row below, so a label query counts rows
    // as well as the board.
    await screen.findByText(/Surplus copies and files that aren't the film/);
    const notes = screen
      .getAllByText(/Surplus copies and files|Re-encodes|Quality you can't get back/)
      .map((el) => el.textContent ?? "");
    expect(notes.length).toBe(3);
    expect(notes[0]).toContain("Surplus copies"); // tier 0, safest
    expect(notes[1]).toContain("Re-encodes"); // tier 1, reversible
    expect(notes[2]).toContain("Quality you can't get back"); // tier 2, last
  });

  it("counts one finding as a finding, not '1 findings'", async () => {
    mount({ ledger: ledger([finding()]) });

    renderPage(<Storage />);

    await screen.findByText(/1 finding ·/);
    expect(screen.queryByText(/1 findings/)).toBeNull();
  });

  it("stays off the page entirely when there is nothing to reclaim", async () => {
    // NEGATIVE CONTROL: an empty ledger must not render three tiers of zero. A
    // board of "0 findings" reads as a broken page rather than a clean library.
    mount({ ledger: ledger([]) });

    renderPage(<Storage />);

    await screen.findByText(/Nothing is out of place/);
    expect(screen.queryByText(/Surplus copies and files that aren't the film/)).toBeNull();
    expect(screen.queryByRole("button", { name: /work out a plan/i })).toBeNull();
  });
});

describe("whether the page can actually delete anything", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("says which mode the server is in, beside the heading", async () => {
    mount();
    vi.spyOn(api, "getSettings").mockResolvedValue({ actions_dry_run: false } as never);

    renderPage(<Storage />);

    await screen.findByText(/Live — deletes are real/);
  });

  it("assumes staged when it cannot find out", async () => {
    // NEGATIVE CONTROL, and the direction matters: a failed settings read that
    // defaulted to "Live" would tell somebody their deletes are real when nobody
    // knows either way. Wrong in the safe direction is the only acceptable wrong.
    mount();
    vi.spyOn(api, "getSettings").mockRejectedValue(new Error("down"));

    renderPage(<Storage />);

    await screen.findByText(/Staged — nothing is deleted/);
  });
});

describe("when the figures cannot be read", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the reason instead of a skeleton that never resolves", async () => {
    mount();
    vi.spyOn(api, "ledger").mockRejectedValue(new Error("database is asleep"));

    renderPage(<Storage />);

    await screen.findByText("database is asleep");
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it("refetches after a scan rather than reloading the page", async () => {
    // A scan rebuilds every figure here. Reloading would throw away scroll
    // position and anything half-armed; the page listens for the event instead.
    mount();
    const ledgerCall = vi.spyOn(api, "ledger").mockResolvedValue(ledger() as never);

    renderPage(<Storage />);
    await screen.findByText(/Surplus copies and files that aren't the film/);
    expect(ledgerCall).toHaveBeenCalledTimes(1);

    window.dispatchEvent(new Event("sift:scan-complete"));

    await waitFor(() => expect(ledgerCall).toHaveBeenCalledTimes(2));
  });
});

describe("the television sections", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  function season(overrides: Record<string, unknown> = {}) {
    return {
      tvdb_id: 76156,
      title: "Scrubs",
      season_number: 1,
      air_year: 2001,
      episode_count: 24,
      total_bytes: 60_000_000_000,
      bytes_per_hour: 5_000_000_000,
      per_episode: 2_500_000_000,
      resolution: "1080p",
      video_codec: "h264",
      excess: 20_000_000_000,
      bloated: true,
      ...overrides,
    };
  }

  it("lists only the seasons actually judged heavy", async () => {
    // `bloated` is the server's verdict, arrived at per hour of runtime. The page
    // must not re-derive it from `excess` or from raw size: a 24-episode season is
    // legitimately larger than a 10-episode one, and ranking on total bytes would
    // put every long season at the top of a list headed "heavier than their peers".
    mount({
      tv: {
        ...EMPTY_TV,
        seasons: [
          season(),
          season({ tvdb_id: 999, title: "Severance", excess: 90_000_000_000, bloated: false }),
        ],
      },
    });

    renderPage(<Storage />);

    await screen.findByText(/Seasons heavier than their peers/);
    expect(screen.getByText("Scrubs")).toBeTruthy();
    expect(screen.queryByText("Severance")).toBeNull(); // larger excess, not flagged
  });

  it("shows the rate it was judged on, not only the total", async () => {
    // The whole normalisation argument is invisible without it: "60 GB" is not an
    // accusation, "5.00 GB/h" is.
    mount({ tv: { ...EMPTY_TV, seasons: [season()] } });

    renderPage(<Storage />);

    await screen.findByText(/5\.00 GB\/h/);
    expect(screen.getByText(/60\.0 GB over 24 episodes/)).toBeTruthy();
    expect(screen.getByText("20.0 GB")).toBeTruthy(); // the excess, ranked on
  });

  it("keeps the heavy-season section off the page when none is flagged", async () => {
    // NEGATIVE CONTROL: a section headed "heavier than their peers" above an
    // empty panel reads as a fault. Nothing flagged means nothing to show.
    mount({ tv: { ...EMPTY_TV, seasons: [season({ bloated: false })] } });

    renderPage(<Storage />);

    await screen.findByText(/Nothing is out of place/);
    expect(screen.queryByText(/Seasons heavier than their peers/)).toBeNull();
  });

  it("reports a season that disagrees with itself separately, with its reasons", async () => {
    // Deliberately not in the reclaim list: fixing an odd SD episode among HD ones
    // usually costs space rather than saving it, so ranking it by bytes would put
    // it in a queue sorted by a number it does not have.
    mount({
      tv: {
        ...EMPTY_TV,
        inconsistencies: [
          {
            tvdb_id: 76156,
            title: "Scrubs",
            season_number: 1,
            common_resolution: "1080p",
            episodes_affected: 1,
            reasons: ["One episode is 480p among 23 at 1080p."],
          },
        ],
      },
    });

    renderPage(<Storage />);

    await screen.findByText(/Seasons that disagree with themselves/);
    expect(screen.getByText("One episode is 480p among 23 at 1080p.")).toBeTruthy();
    expect(screen.getByText("1 episode")).toBeTruthy(); // singular, not "1 episodes"
  });
});
