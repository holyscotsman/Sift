// Destructive-approval modal — keyboard-operable (Escape cancels, autofocus on the
// confirm), explicit copy. Scale-up entry over a fading backdrop.

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

export function ConfirmModal({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  tone = "junk",
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  tone?: "junk" | "accent";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  const confirmBg = tone === "junk" ? "var(--junk)" : "var(--accent)";

  return (
    <div
      className="fixed inset-0 z-[100] grid place-items-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="absolute inset-0 bg-black/60"
        style={{ animation: "sift-backdrop var(--dur) ease both" }}
        onClick={onCancel}
      />
      <div
        className="panel relative w-full max-w-md p-6"
        style={{ animation: "sift-modal var(--dur) var(--ease-spring) both" }}
      >
        <h2 className="font-display text-xl font-extrabold">{title}</h2>
        <div className="mt-3 text-sm text-fg2">{body}</div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            disabled={busy}
            className="rounded-md px-4 py-2 text-sm font-bold disabled:opacity-60"
            style={{ background: confirmBg, color: "var(--accent-fg)" }}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
