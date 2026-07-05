"use client";

import { usePathname } from "next/navigation";

interface V3TopBarProps {
  onToggleSidebar: () => void;
}

const PAGE_TITLES: Record<string, string> = {
  "/v3/dashboard": "Dashboard",
  "/v3/dashboard/trade": "AI Skill Trading",
  "/v3/dashboard/classic": "Classic Trading",
  "/v3/dashboard/three-screens": "Three-Screen System",
  "/v3/dashboard/fundamental": "Fundamental Analysis",
  "/v3/dashboard/monitor": "SACG Monitor",
  "/v3/dashboard/memory": "Memory & Evolution",
  "/v3/dashboard/settings": "Settings",
  "/v3/dashboard/reports": "Reports & Artifacts",
  "/v3/dashboard/governance": "Governance",
};

export function V3TopBar({ onToggleSidebar }: V3TopBarProps) {
  const pathname = usePathname();
  const title = PAGE_TITLES[pathname] || "DreamBuddy v3";

  return (
    <header
      className="flex items-center justify-between h-14 px-4 lg:px-6 border-b"
      style={{
        background: "var(--v3-bg-secondary)",
        borderColor: "var(--v3-border)",
      }}
    >
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="p-1.5 rounded-md cursor-pointer v3-transition"
          style={{ color: "var(--v3-text-muted)" }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
        <h1 className="text-sm font-semibold" style={{ color: "var(--v3-text-primary)" }}>
          {title}
        </h1>
      </div>
      <div className="flex items-center gap-3">
        {/* LLM 状态指示 */}
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ background: "var(--v3-accent-green)" }} />
          <span className="text-xs" style={{ color: "var(--v3-text-muted)" }}>Online</span>
        </div>
      </div>
    </header>
  );
}
