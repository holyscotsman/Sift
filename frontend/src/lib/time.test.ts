// Every relative timestamp in the app, at 36% coverage.
//
// Small, but it is the sentence under "Last scan" and beside every action in the
// activity log, and `hoursSince` gates whether the app offers to scan again.

import { afterEach, describe, expect, it, vi } from "vitest";

import { hoursSince, relativeTime } from "@/lib/time";

const NOW = new Date("2026-08-21T12:00:00Z");

function at(iso: string): string {
  return new Date(iso).toISOString();
}

describe("relativeTime", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function freeze() {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  }

  it("reads in the unit that fits the distance", () => {
    freeze();
    expect(relativeTime(at("2026-08-21T11:59:40Z"))).toBe("just now");
    expect(relativeTime(at("2026-08-21T11:30:00Z"))).toBe("30 min ago");
    expect(relativeTime(at("2026-08-21T09:00:00Z"))).toBe("3 h ago");
    expect(relativeTime(at("2026-08-18T12:00:00Z"))).toBe("3 d ago");
  });

  it("keeps hours up to two days rather than rounding to '1 d'", () => {
    // The boundary is 48 h, not 24. "36 h ago" is a more useful answer than
    // "2 d ago" for a scan that ran yesterday afternoon.
    freeze();
    expect(relativeTime(at("2026-08-20T00:00:00Z"))).toBe("36 h ago");
    // One hour past the boundary, and it switches.
    expect(relativeTime(at("2026-08-19T11:00:00Z"))).toBe("2 d ago");
  });

  it("never counts backwards when a clock is ahead", () => {
    // NEGATIVE CONTROL: server and browser clocks disagree, and a future
    // timestamp is routine rather than exceptional. Read literally this would say
    // "-5 min ago", which looks like a bug in the app rather than in a clock.
    //
    // Mutation-checked: the `Math.max(0, …)` clamp is *not* what delivers this.
    // Removing it alone leaves the test green, because any negative minute count
    // is also less than 1 and the "just now" branch catches it first. Removing
    // both does turn it red. The clamp is belt-and-braces; the pin is on the
    // output, not on which line produces it.
    freeze();
    expect(relativeTime(at("2026-08-21T12:05:00Z"))).toBe("just now");
  });
});

describe("hoursSince", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns a fraction, not a rounded count", () => {
    // Callers compare it against a threshold. Rounding to whole hours would make
    // a 90-minute-old scan and a 30-minute-old scan indistinguishable at any
    // cutoff between them.
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(hoursSince(at("2026-08-21T10:30:00Z"))).toBeCloseTo(1.5, 6);
    expect(hoursSince(at("2026-08-21T11:45:00Z"))).toBeCloseTo(0.25, 6);
  });

  it("goes negative for a future timestamp instead of clamping", () => {
    // NEGATIVE CONTROL, and the opposite choice from `relativeTime` on purpose:
    // this one feeds `>= threshold` comparisons, where a clamp to zero and a
    // genuine "just scanned" would be the same answer. Negative is honest and
    // reads as "not due".
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(hoursSince(at("2026-08-21T13:00:00Z"))).toBeCloseTo(-1, 6);
  });
});
