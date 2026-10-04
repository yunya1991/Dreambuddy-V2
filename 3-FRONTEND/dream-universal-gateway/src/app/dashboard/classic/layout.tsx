"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 经典系统子 Tab 导航布局
 *
 * 路由驱动的子 tab 切换：每个子 tab 对应一个 URL 路径。
 * 顶部横向 Tab 栏，激活态根据当前路径判断。
 */

const SUB_TABS = [
  { id: "library", label: "策略库", icon: "📚" },
  { id: "strategies", label: "上线通道", icon: "🛠" },
  { id: "sandbox", label: "沙箱测试", icon: "🧪" },
  { id: "approvals", label: "审批", icon: "✅" },
  { id: "signals", label: "信号", icon: "🎯" },
  { id: "filter", label: "过滤", icon: "🔍" },
  { id: "execution", label: "执行", icon: "⚡" },
  { id: "exit", label: "离场", icon: "🏁" },
  { id: "arena", label: "Arena", icon: "🎲" },
  { id: "universe", label: "代币池", icon: "🌐" },
  { id: "macro", label: "宏观", icon: "📊" },
  { id: "evaluation", label: "评估", icon: "📈" },
] as const;

export default function ClassicLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // 路径形如 /dashboard/classic/[subtab]
  const activeSubTab = pathname?.split("/").pop() || "library";

  return (
    <div className="space-y-4">
      {/* 顶部子 Tab 导航 */}
      <div className="bg-[#1a1a1a] rounded-lg p-1 border border-[#1f1f1f] overflow-x-auto">
        <div className="flex gap-1 min-w-max">
          {SUB_TABS.map((tab) => {
            const isActive = activeSubTab === tab.id;
            return (
              <Link
                key={tab.id}
                href={`/dashboard/classic/${tab.id}`}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium whitespace-nowrap transition ${
                  isActive
                    ? "bg-[#8b5cf6] text-white"
                    : "text-[#8a8a8a] hover:text-white hover:bg-[#2a2a2a]"
                }`}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
              </Link>
            );
          })}
        </div>
      </div>

      {/* 子 Tab 内容 */}
      <div>{children}</div>
    </div>
  );
}
