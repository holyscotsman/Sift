// The one signature dimensional moment: a soft radial-gradient sphere with a
// gentle float (no spinning sheen — minimalist). Pauses under reduce-motion.

import { useMotionAllowed } from "@/lib/prefs";

export function HealthOrb({ score, size = 96 }: { score: number; size?: number }) {
  const motion = useMotionAllowed();
  const hue = score >= 80 ? 152 : score >= 55 ? 168 : 8; // green → cyan → coral
  return (
    <div
      className="relative grid shrink-0 place-items-center rounded-full"
      style={{
        width: size,
        height: size,
        background: `radial-gradient(circle at 34% 30%, hsl(${hue} 80% 62%), hsl(${hue} 70% 30%) 46%, hsl(${hue} 60% 14%) 100%)`,
        boxShadow: "inset -6px -8px 18px rgba(0,0,0,.45), inset 4px 5px 10px rgba(255,255,255,.18)",
        animation: motion ? "sift-float 7s ease-in-out infinite" : "none",
        animationPlayState: "var(--anim)",
      }}
    >
      <span
        className="font-display font-extrabold text-white"
        style={{ fontSize: size * 0.3, textShadow: "0 1px 3px rgba(0,0,0,.4)" }}
      >
        {score}
      </span>
    </div>
  );
}
