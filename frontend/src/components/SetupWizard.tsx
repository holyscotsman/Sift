// First-run setup: create the login, connect services, then hand off to the app.
// Shown by AuthGate when the backend reports setup_complete=false.

import { useState } from "react";

import { ConnectionsForm } from "@/components/ConnectionsForm";
import { PlaneIcon } from "@/components/icons";
import { ApiError, api, setToken } from "@/lib/api";

type Step = "account" | "connect" | "done";

function Brand() {
  return (
    <div className="flex items-center gap-2">
      <span
        className="grid h-7 w-7 place-items-center rounded-md text-[color:var(--accent-fg)]"
        style={{ background: "var(--grad)" }}
      >
        <PlaneIcon size={15} />
      </span>
      <span className="gradient-text font-display text-lg font-extrabold">Sift</span>
    </div>
  );
}

function StepDots({ step }: { step: Step }) {
  const order: Step[] = ["account", "connect", "done"];
  const idx = order.indexOf(step);
  return (
    <div className="flex gap-1.5">
      {order.map((s, i) => (
        <span
          key={s}
          className="h-1.5 w-8 rounded-pill"
          style={{ background: i <= idx ? "var(--accent)" : "var(--bg-3)" }}
        />
      ))}
    </div>
  );
}

export function SetupWizard({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState<Step>("account");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function createAccount(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (username.trim().length < 3) return setError("Username must be at least 3 characters.");
    if (password.length < 8) return setError("Password must be at least 8 characters.");
    if (password !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    try {
      const res = await api.authSetup(username.trim(), password);
      setToken(res.token);
      setStep("connect");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't create the account — is Sift reachable?",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-full overflow-y-auto p-6">
      <div className="mx-auto w-full max-w-xl">
        <div className="mb-5 flex items-center justify-between">
          <Brand />
          <StepDots step={step} />
        </div>

        {step === "account" && (
          <form onSubmit={createAccount} className="panel p-6">
            <h1 className="font-display text-xl font-extrabold">Welcome to Sift</h1>
            <p className="mt-1 text-sm text-fg2">
              Create a login to protect your instance. This is stored only on your server.
            </p>
            <div className="mt-4 flex flex-col gap-3">
              <label className="text-xs text-fg3">
                Username
                <input
                  id="username"
                  name="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoFocus
                  autoComplete="username"
                  className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
                />
              </label>
              <label className="text-xs text-fg3">
                Password (8+ characters)
                <input
                  id="new-password"
                  name="new-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
                />
              </label>
              <label className="text-xs text-fg3">
                Confirm password
                <input
                  id="confirm-password"
                  name="confirm-password"
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
                />
              </label>
            </div>
            {error && <p className="mt-2 text-sm" style={{ color: "var(--junk)" }}>{error}</p>}
            <button
              type="submit"
              disabled={busy}
              className="gradient-fill mt-4 w-full rounded-md py-2.5 text-sm font-bold shadow-glow disabled:opacity-60"
            >
              {busy ? "Creating…" : "Create account"}
            </button>
          </form>
        )}

        {step === "connect" && (
          <div>
            <div className="panel mb-4 p-6">
              <h1 className="font-display text-xl font-extrabold">Connect your services</h1>
              <p className="mt-1 text-sm text-fg2">
                Enter your keys and hit <strong>Test</strong> to confirm each one. Plex, Radarr,
                and TMDB are the essentials; Tautulli and the AI providers are optional and can be
                added later in Settings. The moment Plex and Radarr test green, Sift quietly starts
                your first scan in the background — it'll be well underway by the time you land on
                the dashboard.
              </p>
            </div>
            <ConnectionsForm
              initial={{}}
              saveLabel="Save & continue"
              onSaved={() => setStep("done")}
              onEssentialsReady={() => {
                // Fire-and-forget: the server refuses to double-run, and the
                // dashboard joins this scan if the user asks for one later.
                void api.scanStart().catch(() => {});
              }}
            />
            <button
              onClick={() => setStep("done")}
              className="mt-3 w-full text-center text-xs font-semibold text-fg3 hover:text-fg"
            >
              Skip for now
            </button>
          </div>
        )}

        {step === "done" && (
          <div className="panel p-6 text-center">
            <div
              className="mx-auto grid h-12 w-12 place-items-center rounded-full text-2xl"
              style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
            >
              ✓
            </div>
            <h1 className="mt-3 font-display text-xl font-extrabold">You're all set</h1>
            <p className="mt-1 text-sm text-fg2">
              If Plex and Radarr tested green, your first scan is already running in the
              background. You can tweak connections anytime in Settings.
            </p>
            <button
              onClick={onComplete}
              className="gradient-fill mt-4 w-full rounded-md py-2.5 text-sm font-bold shadow-glow"
            >
              Go to dashboard
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
