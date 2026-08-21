// Route-level error boundary: a crash on one page keeps the shell (header, nav)
// alive and offers a way out. Resets when the route changes so the rest of the
// app stays usable. Errors are rethrown to the console for debugging.

import { Component } from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

// A stale chunk is a different failure from a page that threw, and it needs a
// different answer.
//
// Every page is a lazy import, so navigating fetches a hashed chunk. Update Sift
// while a tab is open — which is exactly what the Update button on Settings does —
// and those hashes are gone from the server. The next navigation fails, and the
// boundary offers "Try again", which re-renders the same dead import and fails
// again. The only button that can work is Reload, sitting second.
//
// Browsers word it differently: Chrome says "Failed to fetch dynamically imported
// module", Firefox "error loading dynamically imported module", Safari "Importing
// a module script failed".
const STALE_CHUNK = /dynamically imported module|Importing a module script failed/i;

// Reload at most once. A failed lazy import means the page never mounted, so
// there is nothing unsaved to lose — but if the reload does not fix it, looping
// forever is far worse than showing the error.
const RELOAD_KEY = "sift.reloadedForStaleChunk";

function isStale(error: Error): boolean {
  return STALE_CHUNK.test(error.message || "");
}

function reloadOnce(): boolean {
  try {
    if (sessionStorage.getItem(RELOAD_KEY)) return false;
    sessionStorage.setItem(RELOAD_KEY, "1");
  } catch {
    return false; // storage blocked — show the error rather than risk a loop
  }
  window.location.reload();
  return true;
}

class Boundary extends Component<
  { children: ReactNode; resetKey: string },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("page crashed:", error);
    if (isStale(error)) reloadOnce();
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    // A stale chunk cannot be retried — the file is gone from the server — so it
    // does not get a "Try again" that is guaranteed to fail. It gets the reason
    // and the one button that works.
    const stale = isStale(error);
    return (
      <div className="panel p-8 text-center">
        <p className="font-display text-lg font-bold text-fg2">
          {stale ? "Sift has been updated" : "This page hit an error"}
        </p>
        <p className="mx-auto mt-2 max-w-md text-sm text-fg3">
          {stale
            ? "This tab is running the previous version. Reload to pick up the new one — nothing is lost."
            : "The rest of Sift is fine — try again, or reload if it keeps happening."}
        </p>
        <div className="mt-4 flex justify-center gap-2">
          {!stale && (
            <button
              onClick={() => this.setState({ error: null })}
              className="gradient-fill rounded-md px-4 py-2 text-sm font-bold shadow-glow"
            >
              Try again
            </button>
          )}
          <button
            onClick={() => window.location.reload()}
            className={
              stale
                ? "gradient-fill rounded-md px-4 py-2 text-sm font-bold shadow-glow"
                : "rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
            }
          >
            Reload Sift
          </button>
        </div>
      </div>
    );
  }
}

export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <Boundary resetKey={location.pathname}>{children}</Boundary>;
}
