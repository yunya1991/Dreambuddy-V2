"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// 图标 SVG 路径数据 — 每个图标都是简单线条图标
const NAV_ITEMS = [
  {
    id: "dashboard",
    label: "Dashboard",
    href: "/v3/dashboard",
    group: "main",
    icon: `<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>`,
  },
  {
    id: "trade",
    label: "AI Skill",
    href: "/v3/dashboard/trade",
    group: "main",
    sacgLayer: "S",
    icon: `<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>`,
  },
  {
    id: "classic",
    label: "Classic",
    href: "/v3/dashboard/classic",
    group: "main",
    icon: `<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>`,
  },
  {
    id: "three-screens",
    label: "Three Screens",
    href: "/v3/dashboard/three-screens",
    group: "main",
    isAppLayer: true,
    icon: `<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>`,
  },
  {
    id: "fundamental",
    label: "Fundamental",
    href: "/v3/dashboard/fundamental",
    group: "main",
    icon: `<path d="M3 3v18h18"/><path d="M7 16l4-8 4 4 4-6"/>`,
  },
  {
    id: "monitor",
    label: "Monitor",
    href: "/v3/dashboard/monitor",
    group: "system",
    icon: `<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>`,
  },
  {
    id: "memory",
    label: "Memory",
    href: "/v3/dashboard/memory",
    group: "system",
    icon: `<path d="M4 7h16"/><path d="M5 7l-1 5h14l-1-5"/><path d="M7 12v7h10v-7"/><path d="M9 17h6"/>`,
  },
  {
    id: "settings",
    label: "Settings",
    href: "/v3/dashboard/settings",
    group: "system",
    icon: `<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>`,
  },
  {
    id: "reports",
    label: "Reports",
    href: "/v3/dashboard/reports",
    group: "system",
    icon: `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>`,
  },
  {
    id: "governance",
    label: "Governance",
    href: "/v3/dashboard/governance",
    group: "system",
    icon: `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>`,
  },
];

interface V3SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function V3Sidebar({ collapsed, onToggle }: V3SidebarProps) {
  const pathname = usePathname();

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  const mainItems = NAV_ITEMS.filter((i) => i.group === "main");
  const systemItems = NAV_ITEMS.filter((i) => i.group === "system");

  return (
    <aside
      className={`flex flex-col border-r v3-transition ${
        collapsed ? "w-16" : "w-60"
      }`}
      style={{
        background: "var(--v3-bg-secondary)",
        borderColor: "var(--v3-border)",
      }}
    >
      {/* Logo */}
      <div
        className={`flex items-center h-14 px-3 border-b v3-transition ${
          collapsed ? "justify-center" : ""
        }`}
        style={{ borderColor: "var(--v3-border)" }}
      >
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div
              className="w-7 h-7 rounded-md flex items-center justify-center text-xs font-bold"
              style={{ background: "var(--v3-accent-blue)", color: "#fff" }}
            >
              DB
            </div>
            <span className="text-sm font-semibold" style={{ color: "var(--v3-text-primary)" }}>
              DreamBuddy v3
            </span>
          </div>
        )}
        {collapsed && (
          <div
            className="w-7 h-7 rounded-md flex items-center justify-center text-xs font-bold"
            style={{ background: "var(--v3-accent-blue)", color: "#fff" }}
          >
            DB
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 v3-scrollbar-thin">
        {/* Main group */}
        <div className="mb-4">
          {!collapsed && (
            <div
              className="px-3 mb-1 text-[10px] font-medium uppercase tracking-wider"
              style={{ color: "var(--v3-text-muted)" }}
            >
              Trading
            </div>
          )}
          {mainItems.map((item) => (
            <NavLink key={item.id} item={item} active={isActive(item.href)} collapsed={collapsed} />
          ))}
        </div>

        {/* System group */}
        <div>
          {!collapsed && (
            <div
              className="px-3 mb-1 text-[10px] font-medium uppercase tracking-wider"
              style={{ color: "var(--v3-text-muted)" }}
            >
              System
            </div>
          )}
          {systemItems.map((item) => (
            <NavLink key={item.id} item={item} active={isActive(item.href)} collapsed={collapsed} />
          ))}
        </div>
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        className="flex items-center justify-center h-10 border-t v3-transition cursor-pointer"
        style={{ borderColor: "var(--v3-border)", color: "var(--v3-text-muted)" }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ transform: collapsed ? "rotate(180deg)" : "none" }}
          className="v3-transition"
        >
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>
    </aside>
  );
}

function NavLink({
  item,
  active,
  collapsed,
}: {
  item: (typeof NAV_ITEMS)[number];
  active: boolean;
  collapsed: boolean;
}) {
  // SACG 层色
  const layerColors: Record<string, string> = {
    S: "var(--v3-sacg-sense)",
    A: "var(--v3-sacg-arrange)",
    C: "var(--v3-sacg-compute)",
    G: "var(--v3-sacg-graph)",
  };
  const layerColor = item.sacgLayer ? layerColors[item.sacgLayer] : undefined;

  // 应用层特殊色
  const appLayerColor = item.isAppLayer ? "var(--v3-accent-yellow)" : undefined;

  const indicatorColor = appLayerColor || layerColor;

  return (
    <Link
      href={item.href}
      className={`flex items-center gap-3 h-9 px-3 mx-1 rounded-md v3-transition ${
        collapsed ? "justify-center px-0 mx-1" : ""
      }`}
      style={{
        background: active ? "var(--v3-bg-hover)" : "transparent",
        color: active ? "var(--v3-text-primary)" : "var(--v3-text-secondary)",
      }}
      title={collapsed ? item.label : undefined}
    >
      {/* SACG 层色条 */}
      <div className="flex-shrink-0 relative w-5 h-5 flex items-center justify-center">
        {indicatorColor && (
          <div
            className="absolute left-[-9px] top-1 bottom-1 w-[3px] rounded-full"
            style={{ background: indicatorColor }}
          />
        )}
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          dangerouslySetInnerHTML={{ __html: item.icon }}
        />
      </div>
      {!collapsed && (
        <span className="text-[13px] font-medium truncate">{item.label}</span>
      )}
    </Link>
  );
}
