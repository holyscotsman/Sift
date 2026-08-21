// The size formatter, and the reason it exists.
//
// There were six copies of this across the app and five of them went straight
// from bytes to `(bytes / 1e9).toFixed(1) + " GB"`. A 40 MB sample file rendered
// as "0.0 GB" — and samples, trailers and part-downloads are *by definition*
// small, so the Storage page could not name the sizes of the exact category it
// exists to reclaim.
//
// Found by looking at a rendered page, not here: jsdom has no opinion about
// whether "0.0 GB" is a sensible thing to print.

import { describe, expect, it } from "vitest";

import { fmtSize } from "@/lib/format";

describe("fmtSize", () => {
  it("names a small file in megabytes rather than rounding it to nothing", () => {
    expect(fmtSize(40_000_000)).toBe("40 MB");
    expect(fmtSize(847_000_000)).toBe("847 MB");
  });

  it("NEGATIVE CONTROL: the old behaviour would have said 0.0 GB", () => {
    // Written as a guard against a well-meaning simplification back to a single
    // gigabyte branch. 40 MB in gigabytes to one decimal is 0.0, which on the
    // Storage page reads as "there is nothing here to reclaim".
    expect(fmtSize(40_000_000)).not.toBe("0.0 GB");
    expect(fmtSize(40_000_000)).not.toContain("GB");
  });

  it("switches unit at each threshold, not before", () => {
    expect(fmtSize(999_000_000)).toBe("999 MB"); // still MB
    expect(fmtSize(1_000_000_000)).toBe("1.0 GB"); // now GB
    expect(fmtSize(999_000_000_000)).toBe("999.0 GB"); // still GB
    expect(fmtSize(1_000_000_000_000)).toBe("1.00 TB"); // now TB
  });

  it("keeps more precision the larger the number gets", () => {
    // A terabyte is the unit a whole library is measured in, so the second
    // decimal is a real 10 GB. Below a gigabyte a decimal is three digits nobody
    // reads on a row that is one of two hundred.
    expect(fmtSize(1_420_000_000_000)).toBe("1.42 TB");
    expect(fmtSize(8_400_000_000)).toBe("8.4 GB");
    expect(fmtSize(42_000_000)).toBe("42 MB");
  });

  it("falls back to kilobytes rather than printing 0 MB", () => {
    // A `.partial` leftover or a truncated download is genuinely this small, and
    // it is a tier-0 finding — the page has to be able to say how big it is.
    expect(fmtSize(4_096)).toBe("4 KB");
    expect(fmtSize(512_000)).toBe("512 KB");
  });

  it("says nothing at all when there is nothing to say", () => {
    // NEGATIVE CONTROL: zero and absent are the same answer here — an em dash,
    // never "0 KB", which reads as a real measurement of an empty file.
    expect(fmtSize(0)).toBe("—");
    expect(fmtSize(null)).toBe("—");
    expect(fmtSize(undefined)).toBe("—");
  });
});
