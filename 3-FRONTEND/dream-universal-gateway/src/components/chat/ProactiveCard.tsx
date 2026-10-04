"use client";

// ============================================================
// ProactiveCard — 后台主动推送通知卡片
// Phase 4: 将 monitor 事件转为 chat 系统消息的渲染组件
// 版本: v1.0 | 日期: 2026-09-23
// ============================================================

import { useState } from "react";

interface ProactiveData {
  /** 事件类型 */
  event_type: "trade_alert" | "task_completed" | "artifact_synced" | "intel_ready" | "risk_alert" | "system_notice";
  /** 事件标题 */
  title: string;
  /** 详细描述 */
  description: string;
  /** 关联的任务 ID */
  task_id?: string;
  /** 关联的产物文件 */
  artifact_file?: string;
  /** 时间戳 */
  timestamp?: string;
  /** 置信度 */
  confidence?: number;
  /** 建议动作 */
  suggested_action?: {
    label: string;
    view?: string; // 右侧面板视图
  };
}

interface Props {
  data: ProactiveData;
  /** 是否为离线期间的历史事件 */
  isHistorical?: boolean;
  /** 点击建议动作回调 */
  onAction?: (view?: string) => void;
}

// 事件类型 → 图标 + 颜色
const TYPE_CONFIG: Record<ProactiveData["event_type"], { icon: string; color: string; bg: string; border: string }> = {
  trade_alert: { icon: "🎯", color: "#f59e0b", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.4)" },
  task_completed: { icon: "✅", color: "#22c55e", bg: "rgba(34,197,94,0.08)", border: "rgba(34,197,94,0.4)" },
  artifact_synced: { icon: "📎", color: "#06b6d4", bg: "rgba(6,182,212,0.08)", border: "rgba(6,182,212,0.4)" },
  intel_ready: { icon: "📡", color: "#8b5cf6", bg: "rgba(139,92,246,0.08)", border: "rgba(139,92,246,0.4)" },
  risk_alert: { icon: "⚠️", color: "#ef4444", bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.4)" },
  system_notice: { icon: "🔔", color: "#71717a", bg: "rgba(113,113,122,0.08)", border: "rgba(113,113,122,0.3)" },
};

export default function ProactiveCard({ data, isHistorical, onAction }: Props) {
  const [expanded, setExpanded] = useState(false);
  const config = TYPE_CONFIG[data.event_type] || TYPE_CONFIG.system_notice;

  const timeStr = data.timestamp
    ? new Date(data.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "";

  return (
    <div
      className="my-1.5 rounded-lg border overflow-hidden transition-all"
      style={{ borderColor: config.border, background: config.bg }}
    >
      {/* 头部 */}
      <div
        className="px-3 py-2 flex items-center gap-2 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-base flex-shrink-0">{config.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold truncate" style={{ color: config.color }}>
              {data.title}
            </span>
            {isHistorical && (
              <span className="px-1 py-0.5 bg-[#1a1a1a] text-[9px] text-[#8a8a8a] rounded flex-shrink-0">
                离线期间
              </span>
            )}
          </div>
          <div className="text-[10px] text-[#8a8a8a] truncate">
            {timeStr && <span>{timeStr} · </span>}
            {data.description}
          </div>
        </div>
        <button className="text-[#71717a] hover:text-[#fff] flex-shrink-0 text-xs">
          {expanded ? "▾" : "▸"}
        </button>
      </div>

      {/* 展开内容 */}
      {expanded && (
        <div className="px-3 pb-2 pt-1 border-t border-[#1a1a1a] space-y-1.5">
          {data.task_id && (
            <div className="text-[10px] text-[#71717a]">
              任务 ID: <span className="text-[#06b6d4]">{data.task_id}</span>
            </div>
          )}
          {data.artifact_file && (
            <div className="text-[10px] text-[#71717a]">
              产物: <span className="text-[#06b6d4]">{data.artifact_file}</span>
            </div>
          )}
          {data.confidence !== undefined && (
            <div className="text-[10px] text-[#71717a]">
              置信度: <span className={data.confidence >= 0.7 ? "text-green-400" : "text-yellow-400"}>
                {(data.confidence * 100).toFixed(0)}%
              </span>
            </div>
          )}
          {data.description && (
            <div className="text-[11px] text-[#a0a0a0] leading-relaxed">
              {data.description}
            </div>
          )}
          {data.suggested_action && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onAction?.(data.suggested_action?.view);
              }}
              className="px-2 py-1 bg-[#0f3460] hover:bg-[#1a4a7a] text-[#06b6d4] text-[10px] rounded transition"
            >
              {data.suggested_action.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export type { ProactiveData };
