// @vitest-environment node
//
// Node rather than jsdom, because this reads the stylesheet off disk. The
// obvious alternative — importing it as `?raw` — comes back as an empty string:
// vitest stubs CSS imports, so the file would parse zero tokens and pass every
// assertion while checking nothing at all.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const css = readFileSync(
  fileURLToPath(new URL("../styles/tokens.css", import.meta.url)),
  "utf8",
);

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const chan = [0, 2, 4].map((i) => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2];
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** `color-mix(in srgb, fg pct%, transparent)` composited over `bg`. */
function tint(fg: string, bg: string, pct: number): string {
  const f = [0, 2, 4].map((i) => parseInt(fg.replace("#", "").slice(i, i + 2), 16));
  const b = [0, 2, 4].map((i) => parseInt(bg.replace("#", "").slice(i, i + 2), 16));
  const a = pct / 100;
  return (
    "#" +
    f
      .map((v, i) => Math.round(v * a + b[i] * (1 - a)).toString(16).padStart(2, "0"))
      .join("")
  );
}

/** Every `--token: #hex;` inside one theme block. */
function themeTokens(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`no theme block for ${selector}`);
  const body = css.slice(start, css.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2];
  return out;
}

const THEMES = [
  ':root[data-theme="dark"]',
  ':root[data-theme="light"]',
  ':root[data-theme="neon"]',
];
const AA_SMALL = 4.5;

// The two surfaces text is drawn on: the page, and a card. Everything else in
// the palette backs a shape rather than a sentence.
const TEXT_SURFACES = ["--bg-0", "--panel"];

describe.each(THEMES)("%s", (selector) => {
  const t = themeTokens(selector);

  it("body and secondary text are readable on the surfaces that carry it", () => {
    // The page and a card, which is where text actually sits. `--bg-3` is
    // deliberately not here: it backs dots, progress rings and the neutral
    // pill, and no caption is ever drawn on it. Asserting pairings the app
    // never renders would mean changing the palette to satisfy a test rather
    // than a reader — the first version of this file did exactly that and
    // failed on five combinations that do not exist.
    for (const surface of TEXT_SURFACES) {
      if (!t[surface]) continue;
      for (const text of ["--fg", "--fg-2", "--fg-3"]) {
        if (!t[text]) continue;
        expect(
          contrast(t[text], t[surface]),
          `${text} on ${surface} in ${selector}`,
        ).toBeGreaterThanOrEqual(AA_SMALL);
      }
    }
  });

  it("the neutral pill is readable on its own background", () => {
    if (t["--fg-2"] && t["--bg-3"]) {
      expect(contrast(t["--fg-2"], t["--bg-3"]), `neutral pill in ${selector}`)
        .toBeGreaterThanOrEqual(AA_SMALL);
    }
  });

  it("pill text is readable on its own tint", () => {
    // Over the page *and* over a card, because the pill appears on both and the
    // card is the harder of the two. That distinction is the whole reason the
    // junk pill failed at 4.48:1 in a browser while measuring 5.83:1 against
    // the page background alone.
    const pills: [string, string, number][] = [
      ["--keep-ink", "--keep", 18],
      ["--borderline-ink", "--borderline", 20],
      ["--junk-ink", "--junk", 18],
    ];
    for (const surface of TEXT_SURFACES) {
      if (!t[surface]) continue;
      for (const [inkTok, tintTok, pct] of pills) {
        const ink = t[inkTok] ?? t[tintTok];
        if (!ink || !t[tintTok]) continue;
        expect(
          contrast(ink, tint(t[tintTok], t[surface], pct)),
          `${inkTok} on a ${tintTok} pill over ${surface} in ${selector}`,
        ).toBeGreaterThanOrEqual(AA_SMALL);
      }
    }
  });
});

describe("the component that renders a pill", () => {
  it("reads the ink tokens, not the tint ones", () => {
    // This file measures the *stylesheet*, so it cannot see which token the
    // component chooses. Pointing `Pill` back at `var(--junk)` for its text
    // would undo the light-theme fix entirely and leave every assertion above
    // green — verified by mutation, which is how this check came to exist.
    const ui = readFileSync(
      fileURLToPath(new URL("../components/ui.tsx", import.meta.url)),
      "utf8",
    );
    for (const tone of ["keep", "borderline", "junk"]) {
      expect(ui, `${tone} pill text`).toContain(`fg: "var(--${tone}-ink)"`);
    }
  });
});

describe("NEGATIVE CONTROL", () => {
  it("the maths agrees with the values WCAG publishes", () => {
    // Without this the whole file could be measuring something else entirely and
    // passing. Black on white is 21:1 and white on white is 1:1, exactly.
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contrast("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    // And a pair known to fail: #777 on white is 4.48:1, just under the bar.
    expect(contrast("#777777", "#ffffff")).toBeLessThan(AA_SMALL);
  });

  it("a token nudged for looks would be caught", () => {
    // The guard is only worth having if it can fail. This is the value the dark
    // theme's caption colour had before this pass, and it must not pass.
    const dark = themeTokens(':root[data-theme="dark"]');
    expect(contrast("#6a7099", dark["--bg-0"])).toBeLessThan(AA_SMALL);
  });
});
