// Posters, downloads and the scan socket carry their credential in the query
// string, because an <img>, a download link and a WebSocket cannot send a header.
// Query strings are recorded by every proxy they pass and kept in browser
// history — so what travels there must be the short-lived asset token, never the
// thirty-day session token that opens the whole API.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, posterUrl, refreshAssetToken, setToken, urlToken } from "@/lib/api";

const SESSION = "session-token-thirty-days";

beforeEach(() => {
  vi.restoreAllMocks();
  setToken(SESSION);
});

describe("what travels in a query string", () => {
  it("is the asset token once one has been minted", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ token: "asset-token", expires_in: 3600 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await refreshAssetToken();

    expect(urlToken()).toBe("asset-token");
    expect(posterUrl(603)).toBe("/api/poster/603?token=asset-token");
    expect(posterUrl(603)).not.toContain(SESSION);
  });

  it("NEGATIVE CONTROL: falls back to the session token when the mint fails", async () => {
    // A page of broken thumbnails is a worse failure than a stale credential in
    // a URL, so the fallback is deliberate. What matters is that it is reached
    // only when the mint actually failed — the auth gate awaits it, so this is
    // an exceptional path rather than every first paint.
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));

    await refreshAssetToken();

    expect(urlToken()).toBe(SESSION);
  });
});


describe("when the session it belongs to ends", () => {
  it("is not sent again after the password changes", async () => {
    // Changing the password rotates the server's signing secret, so every token
    // issued before it stops verifying — the asset token included. Left cached,
    // it would go on being sent for the rest of its nominal life: up to forty
    // minutes of 401s on every poster and a scan socket that will not open.
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ token: "asset-one", expires_in: 3600 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    await refreshAssetToken();
    expect(urlToken()).toBe("asset-one");

    fetchMock.mockImplementation(async (input: RequestInfo | URL) =>
      String(input).includes("asset-token")
        ? new Response(JSON.stringify({ token: "asset-two", expires_in: 3600 }), {
            status: 200,
            headers: { "content-type": "application/json" },
          })
        : new Response(JSON.stringify({ token: "new-session", username: "owner" }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
    );

    await api.changePassword("old-password", "new-password-8");

    expect(urlToken()).toBe("asset-two");
    expect(posterUrl(603)).not.toContain("asset-one");
  });

  it("NEGATIVE CONTROL: an unchanged session keeps its token", async () => {
    // Throwing the token away on every call would satisfy the test above and
    // re-mint constantly, which is a different waste.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ token: "asset-stable", expires_in: 3600 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await refreshAssetToken();
    expect(urlToken()).toBe("asset-stable");
    expect(urlToken()).toBe("asset-stable");
    expect(posterUrl(1)).toContain("asset-stable");
  });
});
