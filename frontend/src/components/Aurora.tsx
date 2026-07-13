// Very soft aurora backdrop: three heavily-blurred radial gradients drifting on
// long loops. Pauses under reduce-motion via the --anim token. Purely decorative.

import { useMotionAllowed } from "@/lib/prefs";

const BLOBS = [
  { color: "var(--aurora-1)", size: 620, top: "-8%", left: "-6%", anim: "sift-aurora-a", dur: "26s" },
  { color: "var(--aurora-2)", size: 560, top: "20%", left: "62%", anim: "sift-aurora-b", dur: "33s" },
  { color: "var(--aurora-3)", size: 520, top: "58%", left: "18%", anim: "sift-aurora-c", dur: "30s" },
];

export function Aurora() {
  const motion = useMotionAllowed();
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {BLOBS.map((b, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            top: b.top,
            left: b.left,
            width: b.size,
            height: b.size,
            borderRadius: "50%",
            background: `radial-gradient(circle at 50% 50%, ${b.color}, transparent 68%)`,
            filter: "blur(60px)",
            animation: motion ? `${b.anim} ${b.dur} ease-in-out infinite` : "none",
            animationPlayState: "var(--anim)",
          }}
        />
      ))}
    </div>
  );
}
