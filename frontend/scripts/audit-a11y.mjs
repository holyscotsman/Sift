#!/usr/bin/env node
/**
 * Accessibility audit against a running Sift, every screen, via a real browser.
 *
 * The unit suite checks contrast as arithmetic (`frontend/src/test/contrast.test.ts`),
 * which is the half that can run in CI. This is the other half: jsdom has no
 * layout and no compositing, so it cannot see a label that is missing from a
 * rendered select, or the colour a translucent pill actually ends up sitting on.
 *
 * Both matter. The junk pill measured 5.83:1 against the page background and
 * 4.48:1 against the card it is really drawn on — a failure only a browser could
 * find, and the reason this script exists rather than being folded into the
 * unit tests.
 *
 * Usage:
 *   sift serve                       # or any running instance
 *   npm --prefix frontend run audit:a11y -- http://127.0.0.1:8756 owner mypassword
 *
 * Exits non-zero if anything is found, so it can gate a release if wanted.
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { chromium } from "playwright";

const require = createRequire(import.meta.url);
const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const [BASE = "http://127.0.0.1:8756", USER = "owner", PASS = ""] = process.argv.slice(2);
const SCREENS = ["/", "/library", "/missing", "/collections", "/junk", "/storage",
                 "/ask", "/profile", "/activity", "/settings"];

// Honour PLAYWRIGHT_CHROMIUM if the bundled browser version does not match the
// one installed on this machine.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM || undefined;
const browser = await chromium.launch({ executablePath, args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

await page.goto(BASE, { waitUntil: "networkidle" });
const signIn = page.getByRole("button", { name: /^sign in$/i });
if (await signIn.isVisible().catch(() => false)) {
  // AuthGate renders a "checking" phase first and swaps in the form after it has
  // probed /api/status. Filling before that swap types into a node that is about
  // to be replaced.
  await signIn.waitFor({ state: "visible", timeout: 15000 });
  await page.getByLabel("Username").fill(USER);
  await page.getByLabel("Password").fill(PASS);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/auth/login")),
    signIn.click(),
  ]);
  await signIn.waitFor({ state: "detached", timeout: 15000 });
}

const found = new Map();
for (const path of SCREENS) {
  await page.goto(BASE + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  await page.addScriptTag({ content: axeSource });
  const result = await page.evaluate(async () =>
    window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    }),
  );
  for (const v of result.violations) {
    if (!found.has(v.id)) found.set(v.id, { impact: v.impact, help: v.help, where: new Set(), nodes: [] });
    const entry = found.get(v.id);
    entry.where.add(path);
    for (const n of v.nodes.slice(0, 2)) {
      entry.nodes.push({ html: n.html.slice(0, 160), data: n.any?.[0]?.data ?? {} });
    }
  }
  console.log(`${path.padEnd(14)} ${result.violations.length} violation type(s)`);
}

const rank = { critical: 0, serious: 1, moderate: 2, minor: 3 };
const sorted = [...found.entries()].sort((a, b) => (rank[a[1].impact] ?? 9) - (rank[b[1].impact] ?? 9));
console.log("\n=== violations, worst first ===");
for (const [id, v] of sorted) {
  console.log(`\n[${v.impact}] ${id} — ${v.help}`);
  console.log(`  on: ${[...v.where].join(", ")}`);
  for (const n of v.nodes.slice(0, 3)) {
    const c = n.data.contrastRatio ? ` (${n.data.contrastRatio}:1, needs ${n.data.expectedContrastRatio})` : "";
    console.log(`    ${n.html}${c}`);
  }
}
if (!sorted.length) console.log("none");

await browser.close();
process.exit(sorted.length ? 1 : 0);
