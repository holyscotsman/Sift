// What happens to an open tab when Sift updates underneath it.
//
// Every page is a lazy import, so navigating fetches a hashed chunk. Press Update
// on Settings — which is a supported, in-app action — and those hashes are gone
// from the server. The next navigation throws, and until now the boundary offered
// "Try again" as its primary button: re-rendering the same dead import, failing
// again, every time.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RouteErrorBoundary } from "@/components/ErrorBoundary";

function Boom({ message }: { message: string }): never {
  throw new Error(message);
}

function mount(message: string) {
  return render(
    <MemoryRouter>
      <RouteErrorBoundary>
        <Boom message={message} />
      </RouteErrorBoundary>
    </MemoryRouter>,
  );
}

const STALE = "Failed to fetch dynamically imported module: /assets/Ask-3g0KhPpm.js";

let reload: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear();
  reload = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, reload },
  });
  // React logs caught errors; the boundary logs its own. Neither is a failure.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("a page that threw", () => {
  it("offers a retry, because re-rendering might well work", () => {
    mount("Cannot read properties of undefined");

    expect(screen.getByText("This page hit an error")).toBeTruthy();
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
  });
});

describe("a chunk that no longer exists on the server", () => {
  it("reloads by itself, once", () => {
    // The page never mounted, so there is nothing unsaved to lose — and a manual
    // reload is the only thing that can work.
    mount(STALE);

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not loop when the reload fails to fix it", () => {
    // NEGATIVE CONTROL, and the reason this is guarded at all. If the new chunk
    // is also unreachable — a half-finished deploy, a proxy serving a stale
    // index — an unguarded auto-reload spins forever and the app is unusable.
    sessionStorage.setItem("sift.reloadedForStaleChunk", "1");

    mount(STALE);

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText("Sift has been updated")).toBeTruthy();
  });

  it("does not offer a retry that cannot possibly work", () => {
    // The file is gone from the server. "Try again" re-renders the same dead
    // import and fails identically, which teaches the owner that the buttons on
    // this screen do nothing.
    sessionStorage.setItem("sift.reloadedForStaleChunk", "1");

    mount(STALE);

    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
    expect(screen.getByRole("button", { name: /reload sift/i })).toBeTruthy();
  });

  it("says what actually happened rather than 'this page hit an error'", () => {
    sessionStorage.setItem("sift.reloadedForStaleChunk", "1");

    mount(STALE);

    expect(screen.getByText(/running the previous version/)).toBeTruthy();
    expect(screen.queryByText("This page hit an error")).toBeNull();
  });

  it("recognises the wording of every browser, not just Chrome's", async () => {
    // Chrome says "Failed to fetch dynamically imported module", Firefox "error
    // loading dynamically imported module", Safari "Importing a module script
    // failed". Matching one vendor's string means the other two get the retry
    // button that cannot work.
    for (const message of [
      "error loading dynamically imported module",
      "Importing a module script failed.",
    ]) {
      sessionStorage.clear();
      const view = mount(message);
      expect(screen.getByText("Sift has been updated")).toBeTruthy();
      view.unmount();
    }
  });

  it("shows the error rather than reloading when storage is unavailable", async () => {
    // NEGATIVE CONTROL: private windows and blocked site data make sessionStorage
    // throw. Without somewhere to record that a reload has happened there is no
    // way to stop a loop, so the safe answer is not to start one.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });

    mount(STALE);

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText("Sift has been updated")).toBeTruthy();
  });
});
