"use client";

import React from "react";
import {
  getLevelColor,
  getLevelBgColor,
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
  { bg: string; color: string; border: string }
> = {
  critical: {
    bg: "rgba(239, 68, 68, 0.15)",
    color: "#f87171",
    border: "1px solid rgba(239, 68, 68, 0.3)",
  },
  low: {
    bg: "rgba(249, 115, 22, 0.15)",
    color: "#fb923c",
    border: "1px solid rgba(249, 115, 22, 0.3)",
  },
  medium: {
    bg: "rgba(234, 179, 8, 0.15)",
    color: "#facc15",
    border: "1px solid rgba(234, 179, 8, 0.3)",
  },
  healthy: {
    bg: "rgba(34, 197, 94, 0.15)",
    color: "#4ade80",
    border: "1px solid rgba(34, 197, 94, 0.3)",
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

  const paddingX = size === "sm" ? "px-2" : "px-3";
  const paddingY = size === "sm" ? "py-0.5" : "py-1.5";
  const fontSize = size === "sm" ? "text-xs" : "text-sm";

  return (
    <div
      className={`inline-flex items-center gap-2 ${paddingX} ${paddingY} rounded-lg ${fontSize} font-medium cursor-default ${
        onClick ? "cursor-pointer hover:opacity-80" : ""
      }`}
      style={{
        backgroundColor: style.bg,
        color: style.color,
        border: style.border,
        transition: "all 0.2s ease",
      }}
      onClick={onClick}
      title={
        isDowngraded
          ? "已自动降级到经典指标系统"
          : `Token 状态：${getLevelLabel(level)}`
      }
    >
      {/* 状态指示灯 */}
      <span
        className="w-2 h-2 rounded-full"
        style={{
          backgroundColor: style.color,
          boxShadow: isRunning ? `0 0 6px ${style.color}` : "none",
          animation: isRunning && level !== "healthy" ? "pulse 2s infinite" : "none",
        }}
      />

      {/* 降级标识 */}
      {isDowngraded && (
        <span
          className="px-1.5 py-0.5 rounded text-xs font-bold"
          style={{
            backgroundColor: "rgba(239, 68, 68, 0.2)",
            color: "#f87171",
          }}
        >
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
      <span className="opacity-80">
        {getLevelLabel(level)}
      </span>

      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}

export default TokenMonitorBadge;
