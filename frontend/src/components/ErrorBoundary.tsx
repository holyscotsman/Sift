// Route-level error boundary: a crash on one page keeps the shell (header, nav)
// alive and offers a way out. Resets when the route changes so the rest of the
// app stays usable. Errors are rethrown to the console for debugging.

import { Component } from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

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
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="panel p-8 text-center">
        <p className="font-display text-lg font-bold text-fg2">This page hit an error</p>
        <p className="mx-auto mt-2 max-w-md text-sm text-fg3">
          The rest of Sift is fine — try again, or reload if it keeps happening.
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <button
            onClick={() => this.setState({ error: null })}
            className="gradient-fill rounded-md px-4 py-2 text-sm font-bold shadow-glow"
          >
            Try again
          </button>
          <button
            onClick={() => window.location.reload()}
            className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
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
