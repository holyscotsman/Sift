// The front door. Login is the default screen; the first-run Setup Wizard is
// reached from a "New user" link that only appears while no account exists yet.
// Falls back gracefully: a non-auth error (server starting, a source offline) never
// blocks the app.

import { useCallback, useEffect, useState } from "react";

import { PlaneIcon } from "@/components/icons";
import { SetupWizard } from "@/components/SetupWizard";
import { ApiError, api, setToken } from "@/lib/api";

type Phase = "checking" | "wizard" | "login" | "authed";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [canSetup, setCanSetup] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    try {
      const status = await api.authStatus();
      // The server only allows account creation while none exists.
      setCanSetup(!status.setup_complete);
      if (!status.setup_complete) {
        // Fresh install: the API is open until an account exists, so don't let a
        // successful /status probe wave anyone through — show the front door.
        setPhase("login");
        return;
      }
      // Signed in already? A valid session goes straight through.
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

  // Mid-session token death (secret rotation, DB reset): the API client clears
  // the token and fires this event — drop to the login screen instead of letting
  // every page fail silently.
  useEffect(() => {
    const onUnauthorized = () => setPhase("login");
    window.addEventListener("sift:unauthorized", onUnauthorized);
    return () => window.removeEventListener("sift:unauthorized", onUnauthorized);
  }, []);

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
          : err instanceof ApiError && err.status === 429
            ? "Too many failed attempts — wait a minute and try again."
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
        {/* id + name matter: password managers key on them — without them most
            browsers never offer to save the login. */}
        <input
          id="username"
          name="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="username"
          autoFocus
          autoComplete="username"
          className="mt-4 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
        />
        <input
          id="password"
          name="password"
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
        {canSetup && (
          <button
            type="button"
            onClick={() => setPhase("wizard")}
            className="mt-3 w-full text-center text-xs font-semibold text-fg3 hover:text-fg"
          >
            New user? Set up Sift →
          </button>
        )}
      </form>
    </div>
  );
}
