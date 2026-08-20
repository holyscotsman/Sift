// The client every screen goes through.
//
// It was at 42% while carrying the two mechanisms behind the bugs that started
// all of this: the timeout that turns a hung page read into a visible error, and
// the 401 handling that drops a dead session back to the login screen instead of
// leaving every panel quietly broken. Both are the kind of code that is only
// ever exercised when something has already gone wrong, which is precisely when
// nobody is in a position to debug it.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, getToken, setToken } from "@/lib/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  setToken("session-token");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  setToken(null);
});

describe("credentials on a request", () => {
  it("sends the stored session token", async () => {
    fetchMock.mockResolvedValue(json({ ok: true }));
    await api.status();
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init.headers).get("X-Sift-Token")).toBe("session-token");
  });

  it("NEGATIVE CONTROL: an explicit credential is not overwritten by the stored one", async () => {
    // Setup carries the deploy token. On a fresh install a stale session token
    // left in storage would otherwise be sent in its place, and the request
    // would be rejected for using the wrong key entirely — which looks exactly
    // like the deploy token being wrong.
    fetchMock.mockResolvedValue(json({ ok: true }));
    await api.authSetup("owner", "hunter2hunter2", "deploy-token");
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init.headers).get("X-Sift-Token")).toBe("deploy-token");
  });
});

describe("a dead session", () => {
  it("clears the token and says so, once", async () => {
    // Secret rotation or a factory reset. Without this every panel on screen
    // just starts failing with no explanation and no way back to a login form.
    const heard: Event[] = [];
    const listener = (e: Event) => heard.push(e);
    window.addEventListener("sift:unauthorized", listener);
    fetchMock.mockResolvedValue(json({ detail: "unauthorized" }, 401));

    await expect(api.status()).rejects.toThrow(ApiError);

    expect(getToken()).toBeNull();
    expect(heard).toHaveLength(1);
    window.removeEventListener("sift:unauthorized", listener);
  });

  it("NEGATIVE CONTROL: a wrong password is not a dead session", async () => {
    // `/api/auth/*` is excluded on purpose. Signing out the caller because they
    // mistyped their password would clear the very token they are trying to
    // replace, and the login screen would then be unable to say what went wrong.
    const heard: Event[] = [];
    const listener = (e: Event) => heard.push(e);
    window.addEventListener("sift:unauthorized", listener);
    fetchMock.mockResolvedValue(json({ detail: "wrong password" }, 401));

    await expect(api.authLogin("owner", "wrong")).rejects.toThrow(ApiError);

    expect(heard).toHaveLength(0);
    window.removeEventListener("sift:unauthorized", listener);
  });

  it("NEGATIVE CONTROL: a 500 is not a dead session either", async () => {
    const heard: Event[] = [];
    const listener = (e: Event) => heard.push(e);
    window.addEventListener("sift:unauthorized", listener);
    fetchMock.mockResolvedValue(json({ detail: "boom" }, 500));

    await expect(api.status()).rejects.toThrow(ApiError);

    expect(getToken()).toBe("session-token");
    expect(heard).toHaveLength(0);
    window.removeEventListener("sift:unauthorized", listener);
  });
});

describe("errors", () => {
  it("carries the server's own explanation rather than the status text", async () => {
    fetchMock.mockResolvedValue(json({ detail: "Plex is unreachable" }, 502));
    await expect(api.status()).rejects.toThrow("Plex is unreachable");
  });

  it("NEGATIVE CONTROL: a non-JSON error body still produces a usable error", async () => {
    // A proxy 502 is an HTML page. Parsing it must not throw a second, different
    // error on top of the first — the page would then report a JSON parse
    // failure instead of the gateway being down.
    fetchMock.mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 }));
    await expect(api.status()).rejects.toBeInstanceOf(ApiError);
  });

  it("returns nothing at all for a 204 rather than trying to parse it", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.unignoreTitle(603)).resolves.toBeUndefined();
  });
});

describe("a request that never answers", () => {
  it("becomes a visible error instead of a page that hangs for ever", async () => {
    // This is the mechanism behind the "Missing page just doesn't load, it times
    // out" report. Without a bound, a read that never returns leaves a spinner
    // on screen indefinitely — indistinguishable from a slow library, and with
    // no way to retry because nothing ever said it had failed.
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
          );
        }),
    );

    const pending = api.suggestions({ limit: 60 });
    const assertion = expect(pending).rejects.toThrow(/Timed out/);
    await vi.advanceTimersByTimeAsync(46_000);
    await assertion;
  });

  it("reports a caller cancelling as a cancel, not as a timeout", async () => {
    // A timeout and a deliberate cancel look identical at the fetch layer —
    // both arrive as an AbortError — so the client has to tell them apart, or a
    // cancelled request reads as a dead connection and the page fills with
    // errors for things nobody was waiting for.
    //
    // Worth being exact about what this proves: `ask` is the only call that
    // takes a caller signal, and it sets no timeout, so this exercises the
    // cancel path rather than the discrimination between the two. No call site
    // currently passes both a timeout and a signal; when one does, the branch
    // at the `catch` in `request` is what needs its own pin.
    const controller = new AbortController();
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
          );
        }),
    );

    // `ask` is the one call that takes a caller signal, because it is the one
    // the user can visibly interrupt.
    const pending = api.ask("what should I watch", "single", controller.signal);
    controller.abort();

    await expect(pending).rejects.toThrow(/aborted/);
    await expect(pending).rejects.not.toThrow(/Timed out/);
  });

  it("NEGATIVE CONTROL: a request that answers in time is never called slow", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue(json({ items: [], total: 0 }));

    await expect(api.suggestions({ limit: 60 })).resolves.toMatchObject({ total: 0 });
    // And the timer it set is cleared rather than left to fire against a
    // finished request.
    expect(vi.getTimerCount()).toBe(0);
  });
});
