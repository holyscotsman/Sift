// Shared UI primitives used across screens.

import type { ReactNode } from "react";

export function PageTitle({ title, subhead }: { title: string; subhead?: ReactNode }) {
  return (
    <div className="mb-5">
      <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
        {title}
      </h1>
      {subhead && <p className="mt-1 text-sm text-fg2">{subhead}</p>}
    </div>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "keep" | "borderline" | "junk" | "accent";
}) {
  const map: Record<string, { bg: string; fg: string }> = {
    neutral: { bg: "var(--bg-3)", fg: "var(--fg-2)" },
    keep: { bg: "color-mix(in srgb, var(--keep) 18%, transparent)", fg: "var(--keep)" },
    borderline: {
      bg: "color-mix(in srgb, var(--borderline) 20%, transparent)",
      fg: "var(--borderline)",
    },
    junk: { bg: "color-mix(in srgb, var(--junk) 18%, transparent)", fg: "var(--junk)" },
    accent: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  };
  const c = map[tone];
  return (
    <span
      className="inline-flex items-center rounded-pill px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: c.bg, color: c.fg }}
    >
      {children}
    </span>
  );
}

export function RingGauge({
  value,
  max = 100,
  size = 80,
  color = "var(--accent)",
  label,
  caption,
}: {
  value: number;
  max?: number;
  size?: number;
  color?: string;
  label?: ReactNode;
  caption?: string;
}) {
  const stroke = 6;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const pct = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-3)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - pct)}
          style={{ transition: "stroke-dashoffset .6s var(--ease-spring)" }}
        />
        <text
          x="50%"
          y="50%"
          dominantBaseline="central"
          textAnchor="middle"
          className="rotate-90 fill-fg font-display text-lg font-extrabold"
          style={{ transformOrigin: "center" }}
        >
          {label ?? value}
        </text>
      </svg>
      {caption && <span className="text-xs text-fg3">{caption}</span>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`relative overflow-hidden rounded-md bg-bg2 ${className}`}
      style={{ minHeight: 12 }}
    >
      <div
        className="absolute inset-0 -translate-x-full"
        style={{
          background:
            "linear-gradient(90deg, transparent, color-mix(in srgb, var(--fg) 8%, transparent), transparent)",
          animation: "sift-shimmer 1.4s infinite",
          animationPlayState: "var(--anim)",
        }}
      />
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <p className="font-display text-lg font-bold text-fg2">{title}</p>
      {hint && <p className="text-sm text-fg3">{hint}</p>}
    </div>
  );
}

export function PlaceholderPage({ title, note }: { title: string; note: string }) {
  return (
    <div className="page-enter">
      <PageTitle title={title} />
      <div className="panel p-8">
        <Pill tone="accent">Coming next</Pill>
        <p className="mt-3 max-w-xl text-sm text-fg2">{note}</p>
      </div>
    </div>
  );
}
