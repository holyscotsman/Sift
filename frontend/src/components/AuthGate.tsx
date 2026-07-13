// Access-token gate. When the backend requires a token (SIFT_SERVER__API_TOKEN
// set — the norm for a public deployment), the API returns 401 until a valid
// token is stored. This shows a small unlock screen; the token is kept in this
// browser's local storage and sent as X-Sift-Token on every request.

import { useCallback, useEffect, useState } from "react";

import { PlaneIcon } from "@/components/icons";
import { ApiError, api, setToken } from "@/lib/api";

type Phase = "checking" | "authed" | "needs-token";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    try {
      await api.status();
      setPhase("authed");
    } catch (e) {
      // Only a 401 means "token required". Any other failure (server starting,
      // a source offline) shouldn't block the app — it degrades gracefully.
      if (e instanceof ApiError && e.status === 401) setPhase("needs-token");
      else setPhase("authed");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    setError(null);
    setToken(value.trim());
    try {
      await api.status();
      setPhase("authed");
    } catch (err) {
      setToken(null);
      setError(err instanceof ApiError && err.status === 401 ? "That token wasn't accepted." : "Couldn't reach Sift.");
    } finally {
      setBusy(false);
    }
  }

  if (phase === "checking") {
    return <div className="grid h-full place-items-center text-fg3">Loading Sift…</div>;
  }
  if (phase === "authed") return <>{children}</>;

  return (
    <div className="grid h-full place-items-center p-6">
      <form onSubmit={submit} className="panel w-full max-w-sm p-6">
        <div className="flex items-center gap-2">
          <span
            className="grid h-7 w-7 place-items-center rounded-md text-[color:var(--accent-fg)]"
            style={{ background: "var(--grad)" }}
          >
            <PlaneIcon size={15} />
          </span>
          <span className="gradient-text font-display text-lg font-extrabold">Sift</span>
        </div>
        <h1 className="mt-4 font-display text-lg font-bold">Enter access token</h1>
        <p className="mt-1 text-sm text-fg2">
          This Sift instance is protected. Paste the access token (the
          <code className="mx-1 font-mono text-xs">SIFT_SERVER__API_TOKEN</code>
          you set when deploying).
        </p>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="access token"
          autoFocus
          className="mt-4 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none"
        />
        {error && <p className="mt-2 text-sm" style={{ color: "var(--junk)" }}>{error}</p>}
        <button
          type="submit"
          disabled={busy || !value.trim()}
          className="gradient-fill mt-4 w-full rounded-md py-2 text-sm font-bold shadow-glow disabled:opacity-60"
        >
          {busy ? "Checking…" : "Unlock"}
        </button>
      </form>
    </div>
  );
}
