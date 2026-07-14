// The front door. Decides between: the first-run Setup Wizard (no account yet),
// a username/password login (account exists, not signed in), or the app (signed in).
// Falls back gracefully: a non-auth error (server starting, a source offline) never
// blocks the app.

import { useCallback, useEffect, useState } from "react";

import { PlaneIcon } from "@/components/icons";
import { SetupWizard } from "@/components/SetupWizard";
import { ApiError, api, setToken } from "@/lib/api";

type Phase = "checking" | "wizard" | "login" | "authed";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    try {
      const status = await api.authStatus();
      if (!status.setup_complete) {
        // First run — always show the setup wizard (the API is open until an account
        // or static token exists, so we can't rely on /status here).
        setPhase("wizard");
        return;
      }
      // Account exists — do we have a valid session?
      try {
        await api.status();
        setPhase("authed");
      } catch (e) {
        setPhase(e instanceof ApiError && e.status === 401 ? "login" : "authed");
      }
    } catch {
      // Couldn't even read auth status (server booting) — don't hard-block.
      setPhase("authed");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  async function login(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.authLogin(username.trim(), password);
      setToken(res.token);
      setPhase("authed");
    } catch (err) {
      setToken(null);
      setError(
        err instanceof ApiError && err.status === 401
          ? "Wrong username or password."
          : "Couldn't reach Sift.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (phase === "checking") {
    return <div className="grid h-full place-items-center text-fg3">Loading Sift…</div>;
  }
  if (phase === "wizard") return <SetupWizard onComplete={() => setPhase("authed")} />;
  if (phase === "authed") return <>{children}</>;

  // Login
  return (
    <div className="grid h-full place-items-center p-6">
      <form onSubmit={login} className="panel w-full max-w-sm p-6">
        <div className="flex items-center gap-2">
          <span
            className="grid h-7 w-7 place-items-center rounded-md text-[color:var(--accent-fg)]"
            style={{ background: "var(--grad)" }}
          >
            <PlaneIcon size={15} />
          </span>
          <span className="gradient-text font-display text-lg font-extrabold">Sift</span>
        </div>
        <h1 className="mt-4 font-display text-lg font-bold">Sign in</h1>
        <p className="mt-1 text-sm text-fg2">Enter your Sift username and password.</p>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="username"
          autoFocus
          autoComplete="username"
          className="mt-4 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
          autoComplete="current-password"
          className="mt-2 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
        />
        {error && <p className="mt-2 text-sm" style={{ color: "var(--junk)" }}>{error}</p>}
        <button
          type="submit"
          disabled={busy || !username.trim() || !password}
          className="gradient-fill mt-4 w-full rounded-md py-2 text-sm font-bold shadow-glow disabled:opacity-60"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
