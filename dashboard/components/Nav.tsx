"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "GRADUATION", shortLabel: "GRAD" },
  { href: "/ops", label: "COMMAND CENTER", shortLabel: "OPS" },
  { href: "/intel", label: "INTELLIGENCE", shortLabel: "INTEL" },
  { href: "/chat", label: "CHAT HUB", shortLabel: "CHAT" },
] as const;

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav
      className="flex items-center justify-between px-4 shrink-0 select-none"
      style={{
        height: 48,
        background: "var(--terminal-bg-elevated)",
        borderBottom: "1px solid rgba(0, 255, 65, 0.12)",
      }}
    >
      {/* Left: Brand */}
      <div className="flex items-center gap-2">
        <span
          className="text-base font-bold tracking-wider terminal-glow-bright"
          style={{ color: "var(--terminal-green-bright)" }}
        >
          DAE
        </span>
        <span
          className="text-[10px] tracking-wide"
          style={{ color: "var(--terminal-green-dim)", opacity: 0.7 }}
        >
          v3.0
        </span>
      </div>

      {/* Center: Nav Links */}
      <div className="flex items-center gap-1.5 sm:gap-2">
        {NAV_ITEMS.map(({ href, label, shortLabel }) => {
          const isActive =
            href === "/"
              ? pathname === "/"
              : pathname.startsWith(href);

          return (
            <Link
              key={href}
              href={href}
              className="px-3 py-1 text-xs tracking-wider transition-all duration-200"
              style={{
                color: isActive
                  ? "var(--terminal-green-bright)"
                  : "var(--terminal-green-dim)",
                textShadow: isActive
                  ? "0 0 4px rgba(0, 255, 65, 1), 0 0 10px rgba(0, 255, 65, 0.6)"
                  : "none",
                background: isActive
                  ? "rgba(0, 255, 65, 0.08)"
                  : "transparent",
                border: isActive
                  ? "1px solid rgba(0, 255, 65, 0.25)"
                  : "1px solid transparent",
                borderRadius: 2,
              }}
            >
              <span className="hidden sm:inline">[ {label} ]</span>
              <span className="sm:hidden">[ {shortLabel} ]</span>
            </Link>
          );
        })}
      </div>

      {/* Right: Heartbeat + Mode Badge */}
      <div className="flex items-center gap-3">
        {/* Heartbeat Pulse */}
        <div className="flex items-center gap-1.5">
          <span
            className="inline-block w-2 h-2 rounded-full animate-live-pulse"
            style={{
              background: "var(--terminal-green)",
              boxShadow:
                "0 0 4px var(--terminal-green), 0 0 8px var(--terminal-green), 0 0 12px rgba(0, 255, 65, 0.4)",
            }}
          />
          <span
            className="text-[10px] tracking-wide hidden sm:inline"
            style={{ color: "var(--terminal-green-dim)" }}
          >
            LIVE
          </span>
        </div>

        {/* Mode Badge */}
        <span className="badge-green text-[10px] font-semibold tracking-widest">
          PAPER
        </span>
      </div>
    </nav>
  );
}
