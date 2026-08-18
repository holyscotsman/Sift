// Destructive-approval modal — keyboard-operable (Escape cancels), explicit copy,
// scale-up entry over a fading backdrop.
//
// Focus lands on **Cancel**, not on the destructive button. This dialog stands in
// front of every irreversible action in the app, and a stray Enter or Space
// arriving on an autofocused Confirm approves a deletion nobody chose. The safe
// option is the one that should be one keypress away.
//
// Focus is trapped while open and returned to whatever opened the dialog on close
// — otherwise a keyboard user working down a queue lands back on <body> and has
// to Tab from the top of the page after every single decision.

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
  const cancelRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      // Without this, Tab walks straight out of the dialog and into the page
      // behind it, leaving a modal that is visually blocking but not actually.
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
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
        ref={panelRef}
        className="panel relative w-full max-w-md p-6"
        style={{ animation: "sift-modal var(--dur) var(--ease-spring) both" }}
      >
        <h2 className="font-display text-xl font-extrabold">{title}</h2>
        <div className="mt-3 text-sm text-fg2">{body}</div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
          >
            Cancel
          </button>
          <button
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
