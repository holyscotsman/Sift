// One-at-a-time error toast. Errors only — success is already visible as a state
// change, so there is no success spam. Auto-dismisses; announced politely.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

const ToastContext = createContext<(message: string) => void>(() => undefined);

// `const toastError = useToast()` — call with a short, human sentence.
export function useToast(): (message: string) => void {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timerRef = useRef<number>();

  const show = useCallback((m: string) => {
    setMessage(m);
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setMessage(null), 4000);
  }, []);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      {message && (
        <div
          role="alert"
          className="glass fixed bottom-4 left-1/2 z-[100] max-w-[90vw] -translate-x-1/2 rounded-md px-4 py-2.5 text-sm text-fg shadow-s2"
          style={{ border: "1px solid color-mix(in srgb, var(--junk) 45%, transparent)" }}
        >
          {message}
        </div>
      )}
    </ToastContext.Provider>
  );
}
