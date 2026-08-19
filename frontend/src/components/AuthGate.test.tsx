// The gate is where the short-lived asset token gets minted. It used to kick that
// off without waiting and render immediately, so the first screenful of posters —
// sixty of them on the library page — went out carrying the thirty-day session
// token in a query string, on every single load. That is the exact leak the asset
// token exists to prevent.

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "@/components/AuthGate";
import { api, setToken } from "@/lib/api";
import { renderPage } from "@/test/harness";

beforeEach(() => {
  vi.restoreAllMocks();
  setToken("session-token");
});

describe("before the app is shown", () => {
  it("waits for the asset token to be minted", async () => {
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: true,
      username: "owner",
    } as never);
    vi.spyOn(api, "status").mockResolvedValue({} as never);

    // The mint, held open. Nothing behind the gate may render while it is.
    let release: (value: Response) => void = () => {};
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (input: RequestInfo | URL) => {
        if (String(input).includes("asset-token")) {
          return new Promise<Response>((resolve) => {
            release = resolve;
          });
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      },
    );

    renderPage(
      <AuthGate>
        <p>the library</p>
      </AuthGate>,
    );

    // Give the status checks time to settle; the app must still be waiting.
    await waitFor(() => expect(release).toBeTruthy());
    expect(screen.queryByText("the library")).not.toBeInTheDocument();

    release(
      new Response(JSON.stringify({ token: "asset-token", expires_in: 3600 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    expect(await screen.findByText("the library")).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a mint that never answers does not hold the app for ever", async () => {
    // This is the risk the wait introduces, and the reason the request carries a
    // timeout. A hung mint must give up and let the app render on the fallback —
    // the token is a convenience for URLs, not a condition of using Sift.
    //
    // The obvious control — "a *failed* mint still renders" — is vacuous here:
    // the gate already catches rejections, so no plausible mutation makes it
    // fail. A hang is the one that can actually strand someone.
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: true,
      username: "owner",
    } as never);
    vi.spyOn(api, "status").mockResolvedValue({} as never);
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          if (!String(input).includes("asset-token")) {
            _resolve(new Response("{}", { status: 200 }));
            return;
          }
          // Never answers. Only the client's own timeout can end this.
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );

    renderPage(
      <AuthGate>
        <p>the library</p>
      </AuthGate>,
    );

    expect(await screen.findByText("the library", undefined, { timeout: 8000 })).toBeInTheDocument();
  }, 12000);
});
