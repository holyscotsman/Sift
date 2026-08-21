// @vitest-environment node
//
// Every control that suppresses its focus outline must put something visible
// back.
//
// `focus:outline-none` is how you stop the browser's default ring from clashing
// with a rounded design, and it is also how you make a control invisible to
// anyone navigating by keyboard: you tab into the field and nothing on screen
// says so. WCAG 2.4.7 (Focus Visible, Level AA).
//
// **axe cannot see this.** Focus appearance depends on computed styles in a
// state the page is not in while being scanned, so the browser audit came back
// clean across all ten screens while three inputs had no visible focus at all —
// the global search, the Ask box, and the Radarr defaults fields. This is the
// check that found them, and it is a grep rather than a render because that is
// what the problem actually is.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("..", import.meta.url));

function tsxFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...tsxFiles(path));
    else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx")) out.push(path);
  }
  return out;
}

/** A visible focus indicator, on the element itself or on its wrapper. */
const REPLACEMENT = /focus:ring|focus-visible:|focus-within:ring|focus:border/;

describe("focus visibility", () => {
  it("no control suppresses its outline without replacing it", () => {
    const offenders: string[] = [];
    for (const file of tsxFiles(SRC)) {
      const source = readFileSync(file, "utf8");
      if (!source.includes("focus:outline-none")) continue;
      for (const line of source.split("\n")) {
        if (!line.includes("focus:outline-none")) continue;
        // Same element, or the wrapper in the same file — the search box is
        // transparent inside a bordered pill, so its ring belongs on the parent
        // rather than drawing a second outline a pixel inside the first.
        if (REPLACEMENT.test(line) || REPLACEMENT.test(source)) continue;
        offenders.push(`${file.slice(SRC.length)}: ${line.trim().slice(0, 90)}`);
      }
    }
    expect(offenders, "controls with no visible focus state").toEqual([]);
  });

  it("NEGATIVE CONTROL: the rule would catch a real offender", () => {
    // Without this the test above passes on a regex that matches nothing, which
    // is the failure mode of every lint-shaped test.
    const bad = 'className="rounded-md border px-3 py-2 focus:outline-none"';
    expect(REPLACEMENT.test(bad)).toBe(false);
    const good = 'className="rounded-md border px-3 py-2 focus:outline-none focus:ring-1"';
    expect(REPLACEMENT.test(good)).toBe(true);
  });
});
