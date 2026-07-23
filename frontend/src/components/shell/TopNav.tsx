// Floating top-nav bar (no left sidebar). Active pill = quiet accent-soft fill;
// Junk carries a numeric count badge.

import { NavLink } from "react-router-dom";

import { useStatus } from "@/lib/hooks";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/library", label: "Library" },
  { to: "/missing", label: "Missing" },
  { to: "/junk", label: "Junk" },
  { to: "/ask", label: "Ask" },
  { to: "/profile", label: "Taste Profile" },
  { to: "/activity", label: "Activity" },
  { to: "/settings", label: "Settings" },
];

function Badge({ n }: { n: number }) {
  if (!n) return null;
  return (
    <span className="ml-1.5 rounded-pill bg-accent-soft px-1.5 text-[10px] font-bold text-accent">
      {n}
    </span>
  );
}

export function TopNav() {
  const { data: status } = useStatus();
  const junkCount = status?.counts.actions_pending ?? 0;

  const pill =
    "flex items-center rounded-pill px-3.5 py-1.5 text-[13px] font-semibold transition-colors";

  return (
    <nav
      aria-label="Primary"
      className="glass flex flex-wrap items-center gap-1 rounded-xl px-2 py-1.5"
    >
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `${pill} ${
              isActive
                ? "bg-accent-soft text-accent"
                : "text-fg2 hover:bg-bg2 hover:text-fg"
            }`
          }
        >
          {item.label}
          {item.label === "Junk" && <Badge n={junkCount} />}
        </NavLink>
      ))}
    </nav>
  );
}
