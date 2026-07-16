import type { Config } from "tailwindcss";

// Colors reference CSS variables defined per-theme in src/styles/tokens.css, so
// utilities like `bg-panel` / `text-fg` re-theme automatically on theme switch.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg0: "var(--bg-0)",
        panel: "var(--bg-1s)",
        bg2: "var(--bg-2)",
        bg3: "var(--bg-3)",
        line: "var(--line)",
        line2: "var(--line-2)",
        fg: "var(--fg)",
        fg2: "var(--fg-2)",
        fg3: "var(--fg-3)",
        accent: "var(--accent)",
        accent2: "var(--accent2)",
        "accent-fg": "var(--accent-fg)",
        "accent-soft": "var(--accent-soft)",
        "accent-line": "var(--accent-line)",
        keep: "var(--keep)",
        borderline: "var(--borderline)",
        junk: "var(--junk)",
        chrome: "var(--chrome)",
      },
      fontFamily: {
        display: "var(--display)",
        sans: "var(--sans)",
        mono: "var(--mono)",
      },
      borderRadius: {
        sm: "9px",
        md: "12px",
        lg: "18px",
        xl: "26px",
        pill: "999px",
      },
      boxShadow: {
        elev: "var(--elev)",
        s1: "var(--shadow-1)",
        s2: "var(--shadow-2)",
        glow: "var(--glow)",
      },
      maxWidth: {
        page: "1320px",
      },
    },
  },
  plugins: [],
} satisfies Config;
