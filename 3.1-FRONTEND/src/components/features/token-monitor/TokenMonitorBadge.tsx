"use client";

import {
  getLevelLabel,
  formatTokenAmount,
} from "@/lib/token-monitor";
import type { TokenMonitorState, TokenLevel } from "@/lib/token-monitor";

interface TokenMonitorBadgeProps {
  state: TokenMonitorState;
  showBalance?: boolean;
  size?: "sm" | "md";
  onClick?: () => void;
}

const LEVEL_STYLES: Record<
  TokenLevel,
  { bg: string; color: string; dot: string }
> = {
  critical: {
    bg: "bg-red-500/15",
    color: "text-red-400",
    dot: "bg-red-400",
  },
  low: {
    bg: "bg-orange-500/15",
    color: "text-orange-400",
    dot: "bg-orange-400",
  },
  medium: {
    bg: "bg-yellow-500/15",
    color: "text-yellow-400",
    dot: "bg-yellow-400",
  },
  healthy: {
    bg: "bg-green-500/15",
    color: "text-green-400",
    dot: "bg-green-400",
  },
};

export function TokenMonitorBadge({
  state,
  showBalance = true,
  size = "md",
  onClick,
}: TokenMonitorBadgeProps) {
  const level = state.level;
  const style = LEVEL_STYLES[level];
  const isDowngraded = state.isDowngraded;
  const isRunning = state.status === "running";
  const pulsing = isRunning && level !== "healthy";

  const paddingX = size === "sm" ? "px-2" : "px-3";
  const paddingY = size === "sm" ? "py-0.5" : "py-1.5";
  const fontSize = size === "sm" ? "text-xs" : "text-sm";

  return (
    <div
      className={`inline-flex items-center gap-2 ${paddingX} ${paddingY} rounded-lg ${fontSize} font-medium ${style.bg} ${style.color} border border-current/30 transition-all ${
        onClick ? "cursor-pointer hover:opacity-80" : "cursor-default"
      }`}
      onClick={onClick}
      title={
        isDowngraded
          ? "已自动降级到经典指标系统"
          : `Token 状态：${getLevelLabel(level)}`
      }
    >
      {/* 状态指示灯 */}
      <span
        className={`w-2 h-2 rounded-full ${style.dot} ${pulsing ? "animate-pulse" : ""}`}
      />

      {/* 降级标识 */}
      {isDowngraded && (
        <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400">
          已降级
        </span>
      )}

      {/* 余额显示 */}
      {showBalance && (
        <span className="tabular-nums">
          {formatTokenAmount(state.balance)} tokens
        </span>
      )}

      {/* 等级标签 */}
      <span className="opacity-80">{getLevelLabel(level)}</span>
    </div>
  );
}

export default TokenMonitorBadge;
