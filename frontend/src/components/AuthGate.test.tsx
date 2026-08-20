// The gate is where the short-lived asset token gets minted. It used to kick that
// off without waiting and render immediately, so the first screenful of posters —
// sixty of them on the library page — went out carrying the thirty-day session
// token in a query string, on every single load. That is the exact leak the asset
// token exists to prevent.

import { act, screen, waitFor } from "@testing-library/react";
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

// Everything below is about *which door opens*. The gate has four ways to decide
// and only one of them shows the app; getting any of the others wrong either
// locks the owner out or lets someone in.

function mintOk() {
  // The asset-token mint, answered immediately. Every path through the gate that
  // reaches "authed" waits on it, so nothing renders without this.
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ token: "asset", expires_in: 900 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
}

describe("a fresh install", () => {
  it("shows the front door instead of waving anyone through", async () => {
    // The API is open until an account exists — that is how the setup wizard
    // reaches it. So a successful /status probe here proves nothing, and
    // treating it as proof would drop a brand-new, unauthenticated instance
    // straight into the app with every endpoint answering.
    vi.spyOn(api, "authStatus").mockResolvedValue({ setup_complete: false } as never);
    const status = vi.spyOn(api, "status").mockResolvedValue({} as never);
    mintOk();

    renderPage(
      <AuthGate>
        <p>the app</p>
      </AuthGate>,
    );

    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText("the app")).not.toBeInTheDocument();
    expect(status).not.toHaveBeenCalled();
  });
});

describe("an existing session", () => {
  it("NEGATIVE CONTROL: goes straight through when the server accepts it", async () => {
    // Without this the test above passes on a gate that shows the login screen
    // to everyone, for ever.
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: true,
      username: "owner",
    } as never);
    vi.spyOn(api, "status").mockResolvedValue({} as never);
    mintOk();

    renderPage(
      <AuthGate>
        <p>the app</p>
      </AuthGate>,
    );

    expect(await screen.findByText("the app")).toBeInTheDocument();
  });

  it("drops to the login screen when the server rejects it", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: true,
      username: "owner",
    } as never);
    vi.spyOn(api, "status").mockRejectedValue(new ApiError("unauthorized", 401));
    mintOk();

    renderPage(
      <AuthGate>
        <p>the app</p>
      </AuthGate>,
    );

    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText("the app")).not.toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a server that is merely unreachable does not lock you out", async () => {
    // A booting instance, a dropped connection, a proxy hiccup. None of those are
    // "your session is invalid", and treating them as such means the owner is
    // shown a login form their password cannot get them past — because the thing
    // that would check it is the thing that is down.
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: true,
      username: "owner",
    } as never);
    vi.spyOn(api, "status").mockRejectedValue(new ApiError("bad gateway", 502));
    mintOk();

    renderPage(
      <AuthGate>
        <p>the app</p>
      </AuthGate>,
    );

    expect(await screen.findByText("the app")).toBeInTheDocument();
  });
});

describe("when the session dies mid-use", () => {
  it("drops to the login screen instead of letting every page fail quietly", async () => {
    // Secret rotation — which is exactly what changing the password does — or a
    // factory reset. The API client clears the token and fires this event. Without
    // the listener, every panel on screen just starts failing with no explanation.
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: true,
      username: "owner",
    } as never);
    vi.spyOn(api, "status").mockResolvedValue({} as never);
    mintOk();

    renderPage(
      <AuthGate>
        <p>the app</p>
      </AuthGate>,
    );
    await screen.findByText("the app");

    // In act(), because this is a state update from outside React. An
    // unwrapped one warns, and a warning everybody learns to scroll past is
    // how a real one gets missed.
    act(() => {
      window.dispatchEvent(new Event("sift:unauthorized"));
    });

    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText("the app")).not.toBeInTheDocument();
  });
});

describe("signing in", () => {
  async function arriveAtLogin() {
    vi.spyOn(api, "authStatus").mockResolvedValue({ setup_complete: true } as never);
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "status").mockRejectedValue(new ApiError("unauthorized", 401));
    mintOk();
    renderPage(
      <AuthGate>
        <p>the app</p>
      </AuthGate>,
    );
    await screen.findByRole("button", { name: /sign in/i });
  }

  it("tells you which kind of no it was", async () => {
    // Three failures that need three different responses from the person: try
    // again with a different password, wait, or go and check the server. One
    // message for all three sends them after the wrong one.
    const { ApiError } = await import("@/lib/api");
    const login = vi.spyOn(api, "authLogin");

    await arriveAtLogin();
    const userEvent = (await import("@testing-library/user-event")).default;

    login.mockRejectedValueOnce(new ApiError("nope", 401));
    await userEvent.type(screen.getByLabelText(/username/i), "owner");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/wrong username or password/i)).toBeInTheDocument();

    login.mockRejectedValueOnce(new ApiError("slow down", 429));
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/too many failed attempts/i)).toBeInTheDocument();

    login.mockRejectedValueOnce(new Error("network down"));
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/couldn't reach sift/i)).toBeInTheDocument();
  });

  it("clears the stored token when a sign-in fails", async () => {
    // A rejected sign-in leaves whatever was in the client before. Keeping a
    // token the server has already refused means every later request carries a
    // credential that cannot work, and the failures arrive one screen at a time
    // instead of here, where the person is standing.
    const { ApiError, getToken } = await import("@/lib/api");
    vi.spyOn(api, "authLogin").mockRejectedValue(new ApiError("nope", 401));

    await arriveAtLogin();
    const userEvent = (await import("@testing-library/user-event")).default;
    await userEvent.type(screen.getByLabelText(/username/i), "owner");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await screen.findByText(/wrong username or password/i);
    expect(getToken()).toBeNull();
  });

  it("NEGATIVE CONTROL: a successful sign-in opens the app", async () => {
    vi.spyOn(api, "authLogin").mockResolvedValue({
      token: "fresh",
      username: "owner",
    } as never);

    await arriveAtLogin();
    const userEvent = (await import("@testing-library/user-event")).default;
    await userEvent.type(screen.getByLabelText(/username/i), "owner");
    await userEvent.type(screen.getByLabelText(/password/i), "right");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("the app")).toBeInTheDocument();
  });
});
