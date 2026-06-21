"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { key: "overview", label: "总览", emoji: "📊", path: "/dashboard/fundamental/overview" },
];

const BASIC_MODULES = [
  { key: "news", label: "新闻", emoji: "📰", path: "/dashboard/fundamental/news" },
  { key: "flow", label: "资金", emoji: "💵", path: "/dashboard/fundamental/flow" },
  { key: "sentiment", label: "情绪", emoji: "📈", path: "/dashboard/fundamental/sentiment" },
  { key: "macro", label: "宏观", emoji: "🌐", path: "/dashboard/fundamental/macro" },
];

const EXTENDED_MODULES = [
  { key: "breadth", label: "广度", emoji: "📊", path: "/dashboard/fundamental/breadth" },
  { key: "intermarket", label: "跨市场", emoji: "🌐", path: "/dashboard/fundamental/intermarket" },
  { key: "valuation", label: "估值", emoji: "💹", path: "/dashboard/fundamental/valuation" },
  { key: "onchain", label: "链上", emoji: "⛓️", path: "/dashboard/fundamental/onchain" },
  { key: "calendar", label: "日历", emoji: "📅", path: "/dashboard/fundamental/calendar" },
  { key: "narrative", label: "叙事", emoji: "📚", path: "/dashboard/fundamental/narrative" },
];

const handleReturnToDashboard = () => {
  if (typeof window !== "undefined") {
    window.location.href = "/dashboard";
  }
};

export default function FundamentalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  const isActive = (path: string) => pathname === path;

  return (
    <div className="flex h-full" style={{ backgroundColor: "#0d0d0d" }}>
      <aside
        className="flex flex-col border-r transition-all duration-200"
        style={{
          width: collapsed ? 60 : 200,
          backgroundColor: "#1a1a1a",
          borderColor: "#2a2a2a",
        }}
      >
        <div
          className="flex items-center justify-between px-3 py-4 border-b"
          style={{ borderColor: "#2a2a2a" }}
        >
          {!collapsed && (
            <div className="flex items-center gap-2">
              <span className="text-lg">🧭</span>
              <span className="text-sm font-semibold text-white">基本面分析</span>
            </div>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1.5 rounded-md hover:bg-[#2a2a2a] transition"
            style={{ color: "#8a8a8a" }}
          >
            {collapsed ? "→" : "☰"}
          </button>
        </div>

        <div
          className="px-3 py-2 border-b"
          style={{ borderColor: "#2a2a2a" }}
        >
          <button
            onClick={handleReturnToDashboard}
            className="w-full px-2 py-1.5 rounded-md text-xs text-white transition hover:opacity-80"
            style={{ backgroundColor: "#374151" }}
            title="返回对话窗口主页面"
          >
            {collapsed ? "←" : "← 返回主界面"}
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto py-2">
          <div className="px-3 mb-2">
            {!collapsed && (
              <span className="text-xs text-[#6b7280] uppercase tracking-wider">
                基础模块
              </span>
            )}
          </div>
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.key}
              href={item.path}
              className="flex items-center gap-3 px-3 py-2 mx-2 rounded-md transition-all duration-150"
              style={{
                backgroundColor: isActive(item.path) ? "#1f2937" : "transparent",
                color: isActive(item.path) ? "#3b82f6" : "#e0e0e0",
                borderLeft: isActive(item.path) ? "3px solid #3b82f6" : "3px solid transparent",
              }}
            >
              <span className="text-base">{item.emoji}</span>
              {!collapsed && <span className="text-sm">{item.label}</span>}
            </Link>
          ))}

          <div className="px-3 mt-4 mb-2">
            {!collapsed && (
              <span className="text-xs text-[#6b7280] uppercase tracking-wider">
                基础
              </span>
            )}
          </div>
          {BASIC_MODULES.map((item) => (
            <Link
              key={item.key}
              href={item.path}
              className="flex items-center gap-3 px-3 py-2 mx-2 rounded-md transition-all duration-150"
              style={{
                backgroundColor: isActive(item.path) ? "#1f2937" : "transparent",
                color: isActive(item.path) ? "#3b82f6" : "#e0e0e0",
                borderLeft: isActive(item.path) ? "3px solid #3b82f6" : "3px solid transparent",
              }}
            >
              <span className="text-base">{item.emoji}</span>
              {!collapsed && <span className="text-sm">{item.label}</span>}
            </Link>
          ))}

          <div className="px-3 mt-4 mb-2">
            {!collapsed && (
              <span className="text-xs text-[#6b7280] uppercase tracking-wider">
                扩展
              </span>
            )}
          </div>
          {EXTENDED_MODULES.map((item) => (
            <Link
              key={item.key}
              href={item.path}
              className="flex items-center gap-3 px-3 py-2 mx-2 rounded-md transition-all duration-150"
              style={{
                backgroundColor: isActive(item.path) ? "#1f2937" : "transparent",
                color: isActive(item.path) ? "#3b82f6" : "#e0e0e0",
                borderLeft: isActive(item.path) ? "3px solid #3b82f6" : "3px solid transparent",
              }}
            >
              <span className="text-base">{item.emoji}</span>
              {!collapsed && <span className="text-sm">{item.label}</span>}
            </Link>
          ))}
        </nav>
      </aside>

      <main className="flex-1 overflow-y-auto" style={{ backgroundColor: "#0d0d0d" }}>
        {children}
      </main>
    </div>
  );
}
