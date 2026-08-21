// The connection-health row, which is the app's most compressed piece of state:
// six 8px dots standing in for six services.
//
// Compressed to the point where colour was doing all the work. This project's
// standard is glyphs rather than colour alone, and six dots that differ only in
// hue are six identical dots to a colour-blind reader. The `title` and
// `aria-label` cover screen readers and hovering; somebody scanning the header
// with a mouse elsewhere got nothing.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HealthDots } from "@/components/shell/HealthDots";
import * as hooks from "@/lib/hooks";

function withHealth(services: { service: string; ok: boolean; detail?: string }[]) {
  vi.spyOn(hooks, "useHealth").mockReturnValue({
    data: { services },
  } as never);
  return render(
    <MemoryRouter>
      <HealthDots />
    </MemoryRouter>,
  );
}

function dotFor(label: RegExp): HTMLElement {
  return screen.getByLabelText(label);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("state is readable without colour", () => {
  it("a healthy service is round and a broken one is not", () => {
    withHealth([
      { service: "plex", ok: true },
      { service: "radarr", ok: false, detail: "connection refused" },
    ]);

    // Shape, not hue: this is the assertion that would fail if somebody
    // simplified these back to one class with a colour swap.
    expect(dotFor(/^Plex: ok/).style.borderRadius).toBe("9999px");
    expect(dotFor(/^Radarr: offline/).style.borderRadius).not.toBe("9999px");
  });

  it("an unconfigured service is hollow rather than merely grey", () => {
    // Nothing is wrong and nothing is connected. An empty outline says that
    // without relying on the reader distinguishing grey from green.
    withHealth([{ service: "tmdb", ok: false, detail: "not configured" }]);

    const dot = dotFor(/^TMDB/);
    expect(dot.style.background).toBe("transparent");
    expect(dot.style.border).toContain("solid");
  });

  it("an auth failure does not read as healthy", () => {
    // Amber is the easiest state to lose: it is a problem, and to anyone who
    // cannot see the hue a round amber dot is indistinguishable from a round
    // green one. It is square-ish for the same reason offline is.
    withHealth([{ service: "plex", ok: false, detail: "auth rejected" }]);

    expect(dotFor(/^Plex/).style.borderRadius).not.toBe("9999px");
  });

  it("NEGATIVE CONTROL: colour is still there for those who can use it", () => {
    // Shape is the addition, not the replacement. Removing the colour would be
    // its own regression — most people read these by hue and always will.
    withHealth([
      { service: "plex", ok: true },
      { service: "radarr", ok: false, detail: "connection refused" },
    ]);

    expect(dotFor(/^Plex: ok/).style.background).toContain("--keep");
    expect(dotFor(/^Radarr: offline/).style.background).toContain("--junk");
  });

  it("says which service and what happened, for anyone not reading pixels", () => {
    withHealth([{ service: "radarr", ok: false, detail: "connection refused" }]);

    expect(screen.getByLabelText(/Radarr: offline — connection refused/)).toBeInTheDocument();
  });
});
