// ============================================================================
// 推荐策略引擎: 模块布局
// ============================================================================

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "推荐策略引擎 | Dream 管理系统",
  description: "自动化策略推荐引擎 - 基于研报、D-Z-E思维链、回测优化的智能策略生成系统",
};

const navItems = [
  { href: "/recommendation-engine", label: "总览", icon: "📊", exact: true },
  { href: "/recommendation-engine/reports", label: "研报源", icon: "📄" },
  { href: "/recommendation-engine/backtests", label: "回测历史", icon: "📈" },
  { href: "/recommendation-engine/library", label: "策略库", icon: "📚" },
  { href: "/recommendation-engine/logs", label: "运行日志", icon: "📋" },
];

export default function RecommendationEngineLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-gray-900">
                🧠 推荐策略引擎
              </h1>
              <p className="text-xs text-gray-500 mt-0.5">
                基于研报 · D-Z-E思维链 · 回测优化
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span
                className="px-2 py-1 rounded-full bg-green-100 text-green-700 font-medium"
                style={{ fontSize: 11 }}
              >
                ● 基线: v9
              </span>
              <span
                className="px-2 py-1 rounded-full bg-blue-100 text-blue-700"
                style={{ fontSize: 11 }}
              >
                回测周期: 7D
              </span>
              <span
                className="px-2 py-1 rounded-full bg-purple-100 text-purple-700"
                style={{ fontSize: 11 }}
              >
                BTC-USDT-SWAP
              </span>
            </div>
          </div>

          {/* 子导航 */}
          <nav className="flex items-center gap-1 mt-4 -mb-px overflow-x-auto">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`
                  flex items-center gap-1.5 px-4 py-2 text-sm rounded-t-lg border-b-2 transition-colors
                  whitespace-nowrap
                  ${item.exact
                    ? "border-blue-500 text-blue-700 bg-blue-50"
                    : "border-transparent text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                  }
                `}
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            ))}
          </nav>
        </div>
      </header>

      {/* 内容 */}
      <main className="p-6">{children}</main>
    </div>
  );
}
