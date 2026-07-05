"use client";

import Link from "next/link";

const QUICK_LINKS = [
  { label: "AI Skill Trading", href: "/v3/dashboard/trade", desc: "S系列思维链对话交易" },
  { label: "Classic Trading", href: "/v3/dashboard/classic", desc: "C系列经典量化交易" },
  { label: "Three-Screen System", href: "/v3/dashboard/three-screens", desc: "Elder三屏交易系统（应用层）", highlight: true },
  { label: "Fundamental", href: "/v3/dashboard/fundamental", desc: "基本面分析" },
  { label: "SACG Monitor", href: "/v3/dashboard/monitor", desc: "四层架构监控" },
];

const SACG_STATUS = [
  { layer: "S", name: "Sense", color: "var(--v3-sacg-sense)", status: "Active" },
  { layer: "A", name: "Arrange", color: "var(--v3-sacg-arrange)", status: "Active" },
  { layer: "C", name: "Compute", color: "var(--v3-sacg-compute)", status: "Active" },
  { layer: "G", name: "Graph", color: "var(--v3-sacg-graph)", status: "Active" },
];

export default function DashboardPage() {
  return (
    <div className="space-y-6 max-w-6xl">
      {/* SACG 四层状态 */}
      <div>
        <h2 className="text-lg font-semibold mb-3">SACG Architecture Status</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {SACG_STATUS.map((item) => (
            <div key={item.layer} className="v3-card" style={{ borderLeft: `3px solid ${item.color}` }}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium" style={{ color: item.color }}>{item.layer} — {item.name}</span>
                <span className="w-2 h-2 rounded-full" style={{ background: "var(--v3-accent-green)" }} />
              </div>
              <div className="mt-2 text-xs v3-text-muted">{item.status}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 快速入口 */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Quick Access</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {QUICK_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="v3-card flex items-center justify-between v3-transition hover:border-[var(--v3-accent-blue)]"
              style={link.highlight ? { borderLeft: `3px solid var(--v3-accent-yellow)` } : {}}
            >
              <div>
                <div className="text-sm font-medium">{link.label}</div>
                <div className="text-xs v3-text-muted mt-0.5">{link.desc}</div>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--v3-text-muted)" }}>
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
