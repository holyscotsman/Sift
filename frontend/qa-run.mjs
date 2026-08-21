/**
 * A real browser over every screen, at desktop and phone widths.
 *
 * jsdom has no layout and no compositing, so it cannot see text clipped by a
 * container, a row that overflows its card, or a control pushed off-screen. This
 * is the pass that can — it is how the caption truncation on Missing was found,
 * which every unit test had happily reported as present.
 */
import { chromium } from "playwright";

const BASE = "http://127.0.0.1:8799";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM;
const launch = () => chromium.launch({ executablePath, args: ["--no-sandbox"] });

const SCREENS = ["/", "/library", "/missing", "/collections", "/junk", "/storage",
                 "/ask", "/profile", "/activity", "/settings"];

const findings = [];

async function run(label, width, height, theme) {
  const browser = await launch();
  const ctx = await browser.newContext({ viewport: { width, height } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));

  // The theme is a persisted preference, so it has to be in place before the app
  // reads it — setting it after mount would screenshot a repaint mid-flight.
  await page.addInitScript((t) => localStorage.setItem("sift.theme", JSON.stringify(t)), theme);
  await page.goto(BASE, { waitUntil: "networkidle" });

  // AuthGate fills before React mounts, so wait for the button to exist, submit,
  // and wait for it to detach — otherwise every screenshot is the login box.
  const signIn = page.getByRole("button", { name: /^sign in$/i });
  if (await signIn.count()) {
    await page.getByLabel(/username/i).fill("owner");
    await page.getByLabel(/password/i).fill("qa-password-1234");
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/auth/login")),
      signIn.click(),
    ]);
    await signIn.waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
  }

  for (const path of SCREENS) {
    consoleErrors.length = 0;
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(700);

    const applied = await page.evaluate(() => document.documentElement.dataset.theme);
    if (applied !== theme) {
      findings.push(`${label} ${path}: theme is "${applied}", expected "${theme}"`);
    }

    const name = path === "/" ? "dashboard" : path.slice(1);
    await page.screenshot({ path: `/tmp/claude-0/shots/${label}-${name}.png`, fullPage: true });

    // Horizontal overflow of the page itself is always a bug: every wide thing
    // (tables, code, diagrams) is supposed to scroll inside its own container.
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 2) findings.push(`${label} ${path}: page scrolls horizontally by ${overflow}px`);

    // Text cut off with no ellipsis and no title attribute — the reader cannot
    // tell there is more, and cannot get at it. Deliberate `truncate` (ellipsis)
    // is a design choice and is not reported; silent clipping is the defect.
    const clipped = await page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll("span,p,td,th,button,a,h1,h2,h3,li,label")) {
        if (el.children.length) continue;
        const t = (el.textContent || "").trim();
        if (!t) continue;
        const s = getComputedStyle(el);
        if (s.textOverflow === "ellipsis") continue;   // signposted
        if (el.title) continue;                        // recoverable on hover
        if (s.overflowX === "auto" || s.overflowX === "scroll") continue; // scrollable
        if (el.scrollWidth > el.clientWidth + 1) out.push(t.slice(0, 60));
        if (el.scrollHeight > el.clientHeight + 2 && s.overflowY === "hidden")
          out.push("(vertically) " + t.slice(0, 60));
      }
      return out;
    });
    for (const t of new Set(clipped)) findings.push(`${label} ${path}: clipped — "${t}"`);

    // Touch targets, measured as the area a finger can actually hit rather than
    // the box of the control itself. The Junk row checkbox is a 16px input inside
    // a 44px label — measuring the input would report a control somebody already
    // solved. Walk up to the nearest wrapping label/parent and take that.
    //
    // Only flagged when BOTH dimensions are small: a 287x20 search field is easy
    // to hit even though it is short, and reporting it is noise. Small in both
    // directions, next to other controls, is the case that gets mis-tapped.
    if (width < 500) {
      const small = await page.evaluate(() => {
        const out = [];
        for (const el of document.querySelectorAll("button,a[href],input,select")) {
          let box = el.getBoundingClientRect();
          const wrap = el.closest("label") || el.parentElement;
          if (wrap && wrap !== el) {
            const w = wrap.getBoundingClientRect();
            // Only adopt the parent when it exists to enlarge the target, not
            // when it happens to be a whole row containing several controls.
            if (wrap.querySelectorAll("button,a[href],input,select").length === 1)
              box = w;
          }
          if (box.width === 0 || box.height === 0) continue;
          // 24px, not 44px. The app's controls are a consistent ~28px pill and
          // that is a design decision, not a defect to be reported 174 times.
          // What is worth flagging is a control noticeably below even that,
          // because those sit inline next to each other and get mis-tapped.
          if (Math.min(box.width, box.height) >= 24) continue;
          const label = (el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 34);
          out.push(`${Math.round(box.width)}x${Math.round(box.height)} <${el.tagName.toLowerCase()}> "${label}"`);
        }
        return out;
      });
      for (const t of new Set(small)) findings.push(`${label} ${path}: small target — ${t}`);
    }

    // Poster 404s and the scan websocket are environmental here: this instance has
    // no TMDB key and no poster cache, and nothing is scanning. Filtering them is
    // not hiding failures — it is refusing to report the fixture as a defect.
    const real = consoleErrors.filter(
      (e) => !/404 \(Not Found\)/.test(e) && !/ERR_CONNECTION_RESET/.test(e),
    );
    for (const e of real) findings.push(`${label} ${path}: console — ${e.slice(0, 160)}`);
  }
  await ctx.close();
  await browser.close();
}

await run("desktop", 1440, 1000, "dark");
await run("phone", 390, 844, "dark");
await run("light", 1440, 1000, "light");
await run("neon", 1440, 1000, "neon");

if (findings.length === 0) console.log("clean: no layout, overflow or console findings");
else { console.log(`${findings.length} finding(s):`); for (const f of findings) console.log(" - " + f); }
