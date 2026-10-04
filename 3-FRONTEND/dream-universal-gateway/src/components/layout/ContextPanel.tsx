"use client";

// ============================================================
// ContextPanel — 上下文侧边面板（Phase 3）
// 版本: v2.0 | Phase 3
// 右侧面板容器。Phase 3 增强为 ai 推荐标签展示 + contextView 驱动。
// ============================================================

import { ReactNode } from "react";
import { useUIStore } from "@/stores/ui-store";

interface Props {
  /** 当前面板内容类型 */
  content: string;
  /** 是否折叠 */
  collapsed: boolean;
  /** 折叠回调 */
  onToggleCollapse: () => void;
  /** 面板标题 */
  title?: string;
  /** 面板内容（透传现有 renderRightPanel 结果） */
  children: ReactNode;
}

// 视图类型 → 中文标签
const VIEW_LABELS: Record<string, string> = {
  analysis: "分析",
  market: "市场行情",
  signal: "信号",
  position: "持仓",
  api: "API 配置",
  trading: "交易配置",
  strategy: "策略",
  communication: "通知",
  llm: "LLM",
  report: "研报",
  monitor: "监控",
  memory: "记忆",
  notebook: "笔记",
  "graph-compression": "图压缩",
  orchestration: "编排",
};

export default function ContextPanel({
  content,
  collapsed,
  onToggleCollapse,
  title,
  children,
}: Props) {
  // Phase 3: 从 ui-store 读取 AI 推荐的 contextView
  const contextView = useUIStore((s) => s.contextView);
  const isAiSuggested = contextView === content;

  return (
    <div
      className={`${collapsed ? "w-0" : "w-80"} flex-shrink-0 flex flex-col bg-[#1a1a1a] border-l border-[#1a1a1a] transition-all duration-300 overflow-hidden`}
    >
      {/* 标题栏 */}
      <div className="p-4 border-b border-[#1a1a1a] flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="text-sm font-semibold text-[#3b82f6] truncate">
            {title || "面板"}
          </h2>
          {/* Phase 3: AI 推荐标签 */}
          {isAiSuggested && (
            <span className="flex-shrink-0 px-1.5 py-0.5 bg-[#0f3460] text-[#06b6d4] rounded text-[9px] font-medium flex items-center gap-1">
              <span>🤖</span>
              AI 推荐
            </span>
          )}
        </div>
        <button
          onClick={onToggleCollapse}
          className="p-1 hover:bg-[#1f1f1f] rounded transition text-[#8a8a8a]"
          title="关闭面板"
        >
          ✕
        </button>
      </div>

      {/* Phase 3: AI 推荐上下文提示条 */}
      {isAiSuggested && contextView && (
        <div className="px-4 py-1.5 bg-[#0d1525] border-b border-[#1a2a3a] text-[10px] text-[#06b6d4] flex items-center gap-1">
          <span>💡</span>
          <span>根据对话意图自动切换至「{VIEW_LABELS[contextView] || contextView}」面板</span>
        </div>
      )}

      {/* 内容区 — 透传 children */}
      <div className="flex-1 overflow-y-auto p-4">
        {children}
      </div>
    </div>
  );
}
