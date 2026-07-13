// Design System reference sheet: tokens, type scale, and a component gallery.
// Live against the current theme so it doubles as a visual-sign-off surface.

import { HealthOrb } from "@/components/HealthOrb";
import { Pill, RingGauge, Skeleton } from "@/components/ui";

const SWATCHES = [
  ["--accent", "Accent"],
  ["--accent2", "Accent 2"],
  ["--keep", "Keep"],
  ["--borderline", "Borderline"],
  ["--junk", "Junk"],
  ["--bg-2", "Surface 2"],
  ["--bg-3", "Surface 3"],
  ["--fg-2", "Text 2"],
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel p-6">
      <span className="eyebrow">{title}</span>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function DesignSystem() {
  return (
    <div className="page-enter flex flex-col gap-4">
      <div>
        <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
          Design System
        </h1>
        <p className="mt-1 text-sm text-fg2">
          Live tokens & components for the current theme — switch themes in the header to compare.
        </p>
      </div>

      <Section title="Color tokens">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {SWATCHES.map(([v, label]) => (
            <div key={v} className="flex items-center gap-3">
              <span
                className="h-10 w-10 rounded-md border border-line"
                style={{ background: `var(${v})` }}
              />
              <div>
                <div className="text-sm font-semibold">{label}</div>
                <code className="font-mono text-[11px] text-fg3">{v}</code>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <span className="h-10 w-40 rounded-md" style={{ background: "var(--grad)" }} />
          <code className="font-mono text-[11px] text-fg3">--grad (wordmark + Run scan only)</code>
        </div>
      </Section>

      <Section title="Type scale">
        <div className="flex flex-col gap-2">
          <div className="font-display text-[42px] font-extrabold leading-none">Display 42</div>
          <div className="font-display text-[28px] font-extrabold">H1 · Bricolage 28</div>
          <div className="font-display text-base font-bold">H2 · Bricolage 16</div>
          <div className="text-sm">Body · Hanken Grotesk 14</div>
          <div className="eyebrow">Caption · uppercase tracked 11</div>
          <div className="font-mono text-[12px] text-fg2">Mono · JetBrains 12 — /api/movies?q=matrix</div>
        </div>
      </Section>

      <Section title="Components">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex flex-col items-start gap-2">
            <span className="eyebrow">Buttons</span>
            <div className="flex items-center gap-2">
              <button className="gradient-fill rounded-pill px-4 py-1.5 text-xs font-bold shadow-glow">
                Run scan
              </button>
              <button className="rounded-pill border border-line px-4 py-1.5 text-xs font-semibold text-fg2">
                Secondary
              </button>
            </div>
          </div>
          <div className="flex flex-col items-start gap-2">
            <span className="eyebrow">Score badges</span>
            <div className="flex gap-2">
              <Pill tone="keep">Keep</Pill>
              <Pill tone="borderline">Borderline</Pill>
              <Pill tone="junk">Junk</Pill>
              <Pill tone="accent">Monitored</Pill>
            </div>
          </div>
          <div className="flex flex-col items-center gap-2">
            <span className="eyebrow">Ring gauge</span>
            <RingGauge value={72} color="var(--accent)" size={64} label={72} />
          </div>
          <div className="flex flex-col items-center gap-2">
            <span className="eyebrow">Health orb</span>
            <HealthOrb score={86} size={64} />
          </div>
          <div className="flex w-40 flex-col gap-2">
            <span className="eyebrow">Skeleton</span>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>
      </Section>
    </div>
  );
}
