// Appearance preferences, and one of them is an accessibility control.
//
// `reduceMotion` does not animate anything itself: it writes
// `data-reduce-motion` onto <html>, and `tokens.css` is what actually collapses
// the transitions. The setting is therefore only as real as that attribute, and
// nothing checked it. Someone who turned motion off and kept getting animations
// would have no way to tell whether the toggle, the attribute or the CSS was at
// fault.
//
// The OS-level `prefers-reduced-motion` is honoured separately by the stylesheet,
// so this file is about the in-app toggle only.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { PrefsProvider, usePrefs } from "@/lib/prefs";

function Probe() {
  const { theme, setTheme, reduceMotion, setReduceMotion, accent, setAccent } = usePrefs();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="motion">{String(reduceMotion)}</span>
      <span data-testid="accent">{accent ?? "none"}</span>
      <button onClick={() => setTheme("light")}>light</button>
      <button onClick={() => setReduceMotion(true)}>calm</button>
      <button onClick={() => setReduceMotion(false)}>lively</button>
      <button onClick={() => setAccent("#ff6b5b")}>peach</button>
      <button onClick={() => setAccent("not-a-colour")}>nonsense</button>
      <button onClick={() => setAccent(null)}>clear</button>
    </div>
  );
}

const root = () => document.documentElement;

beforeEach(() => {
  localStorage.clear();
  root().removeAttribute("data-reduce-motion");
  root().removeAttribute("data-theme");
  root().style.removeProperty("--accent");
  root().style.removeProperty("--accent2");
  root().style.removeProperty("--grad");
});

function renderProbe() {
  return render(
    <PrefsProvider>
      <Probe />
    </PrefsProvider>,
  );
}

describe("reduce motion", () => {
  it("reaches the attribute the stylesheet actually reads", async () => {
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "calm" }));

    expect(root().dataset.reduceMotion).toBe("true");
    expect(localStorage.getItem("sift.reduceMotion")).toBe("true");
  });

  it("NEGATIVE CONTROL: turning it back on says false rather than going absent", async () => {
    // The CSS selector is `[data-reduce-motion="true"]`. Removing the attribute
    // would also work today, and would break silently the moment anyone wrote a
    // rule for the "false" case. Say the value.
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "calm" }));
    await userEvent.click(screen.getByRole("button", { name: "lively" }));

    expect(root().dataset.reduceMotion).toBe("false");
  });

  it("survives a reload", async () => {
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "calm" }));

    // A second mount, reading from storage exactly as a fresh page load does.
    const second = renderProbe();
    expect(second.getAllByTestId("motion").at(-1)).toHaveTextContent("true");
  });
});

describe("theme", () => {
  it("is written to the element and remembered", async () => {
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "light" }));

    expect(root().dataset.theme).toBe("light");
    expect(localStorage.getItem("sift.theme")).toBe("light");
  });

  it("NEGATIVE CONTROL: defaults to dark with nothing stored", () => {
    renderProbe();
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });
});

describe("a custom accent", () => {
  it("derives the whole duotone, not just the one colour", async () => {
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "peach" }));

    expect(root().style.getPropertyValue("--accent")).toBeTruthy();
    expect(root().style.getPropertyValue("--accent2")).toBeTruthy();
    expect(root().style.getPropertyValue("--grad")).toContain("linear-gradient");
  });

  it("NEGATIVE CONTROL: nonsense is ignored rather than applied", async () => {
    // A half-typed hex reaches this on every keystroke of a colour field. It must
    // not paint the app with `undefined`.
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "nonsense" }));

    expect(root().style.getPropertyValue("--accent")).toBe("");
  });

  it("clearing it puts the built-in palette back", async () => {
    // Removing the property rather than setting it to something empty: a
    // lingering `--accent: ` would override the stylesheet with nothing.
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "peach" }));
    await userEvent.click(screen.getByRole("button", { name: "clear" }));

    expect(root().style.getPropertyValue("--accent")).toBe("");
    expect(localStorage.getItem("sift.accent")).toBeNull();
  });
});
