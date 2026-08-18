"use client";

import React from "react";
import { useAutoConfigStore, CONFIG_STEPS_LIST } from "@/stores/auto-config-store";
import type { AutoConfigResult } from "@/stores/auto-config-store";

// ============================================================
// UI Tokens
// ============================================================
const COLORS = {
  bg: "#2C2C2A",
  radius: "10px",
  padding: "16px",
  labelConfigured: "#1D9E75",
  labelSkipped: "#BA7517",
  labelError: "#A32D2D",
  progressBarDone: "#1D9E75",
  progressBarBg: "#444441",
  btnPrimary: "#378ADD",
  btnSecondary: "#444441",
} as const;

// ============================================================
// Helper: format result summary
// ============================================================
function getResultSummary(result: AutoConfigResult): string {
  if (result.status === "skipped") return "默认参数";
  if (result.status === "error") return result.error || "配置失败";
  if (!result.data) return "已配置";

  const d = result.data;
  switch (result.key) {
    case "api":
      return `账户: ${d.label || "未命名"} | ${d.provider || "OKX"} | ${d.environment === "live" ? "实盘" : "Demo"}`;
    case "trading": {
      const riskMap: Record<string, string> = {
        CONSERVATIVE: "保守",
        MODERATE: "稳健",
        AGGRESSIVE: "激进",
      };
      const typeMap: Record<string, string> = {
        SPOT: "现货",
        SWAP: "合约",
      };
      return `${typeMap[d.tradeType as string] || d.tradeType} | ${riskMap[d.riskTolerance as string] || d.riskTolerance} | ${d.leverageMax}x`;
    }
    case "strategy": {
      const riskMap: Record<string, string> = {
        CONSERVATIVE: "保守",
        MODERATE: "稳健",
        AGGRESSIVE: "激进",
      };
      const freqMap: Record<string, string> = {
        ONE_H: "1h",
        FOUR_H: "4h",
        ONE_D: "1d",
      };
      return `${riskMap[d.riskTolerance as string] || d.riskTolerance} | ${freqMap[d.executionFrequency as string] || d.executionFrequency} | ${(d.allowedSymbols as string[])?.length || 0}标的`;
    }
    case "channels": {
      const chMap: Record<string, string> = {
        TELEGRAM: "TG",
        WECHAT_SERVERCHAN: "微信",
        WECHAT_WORK: "企微",
        EMAIL_SMTP: "Email",
        DISCORD: "Discord",
      };
      const types = (d.pushTypes as string[]) || [];
      return `${chMap[d.channelType as string] || d.channelType} | ${types.length}类推送`;
    }
    default:
      return "已配置";
  }
}

function getStatusBadge(status: AutoConfigResult["status"]) {
  const map = {
    configured: { label: "已配置", bg: `${COLORS.labelConfigured}20`, color: COLORS.labelConfigured },
    skipped: { label: "已跳过", bg: `${COLORS.labelSkipped}20`, color: COLORS.labelSkipped },
    error: { label: "错误", bg: `${COLORS.labelError}20`, color: COLORS.labelError },
  };
  const s = map[status];
  return (
    <span
      className="text-[10px] font-medium px-1.5 py-0.5 rounded"
      style={{ backgroundColor: s.bg, color: s.color }}
    >
      {s.label}
    </span>
  );
}

// ============================================================
// Main Export: AutoConfigSummary
// ============================================================
export default function AutoConfigSummary() {
  const { results, reset, isActive } = useAutoConfigStore();

  if (!isActive && results.length === 0) return null;

  const configuredCount = results.filter((r) => r.status === "configured").length;
  const totalCount = CONFIG_STEPS_LIST.length;
  const pct = Math.round((configuredCount / totalCount) * 100);

  return (
    <div className="flex justify-start">
      <div
        className="max-w-[90%] w-full rounded-lg"
        style={{
          backgroundColor: COLORS.bg,
          borderRadius: COLORS.radius,
          padding: COLORS.padding,
        }}
      >
        {/* Title */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-[#06b6d4] text-xs">🤖 Dream Gateway</span>
          </div>
          <span className="text-xs text-white/60">配置完成摘要</span>
        </div>

        {/* 2x2 Grid */}
        <div className="grid grid-cols-2 gap-2 mb-4">
          {CONFIG_STEPS_LIST.map((step, idx) => {
            const result = results.find((r) => r.step === idx);
            const status = result?.status || "skipped";
            const summary = result ? getResultSummary(result) : "未配置";

            return (
              <div
                key={step.key}
                className="rounded-lg p-3"
                style={{
                  backgroundColor: "#1a1a1a",
                  border: `1px solid ${status === "configured" ? "#1D9E7530" : status === "error" ? "#A32D2D30" : "#44444130"}`,
                }}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-medium text-white">
                    {step.icon} {step.label}
                  </span>
                  {getStatusBadge(status)}
                </div>
                <div className="text-[11px] text-[#8a8a8a] truncate">{summary}</div>
              </div>
            );
          })}
        </div>

        {/* Progress Bar */}
        <div className="mb-4">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-white/60">完成度</span>
            <span className="text-white font-medium">{configuredCount}/{totalCount} ({pct}%)</span>
          </div>
          <div className="w-full h-1.5 rounded-full" style={{ backgroundColor: COLORS.progressBarBg }}>
            <div
              className="h-1.5 rounded-full transition-all duration-500"
              style={{
                backgroundColor: COLORS.progressBarDone,
                width: `${pct}%`,
              }}
            />
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2">
          <button
            onClick={reset}
            className="flex-1 px-4 py-2 rounded text-xs font-medium text-[#8a8a8a] transition hover:text-white"
            style={{ backgroundColor: COLORS.btnSecondary }}
          >
            稍后配置
          </button>
          <button
            onClick={reset}
            className="flex-1 px-4 py-2 rounded text-xs font-medium text-white transition hover:opacity-90"
            style={{ backgroundColor: COLORS.btnPrimary }}
          >
            进入 Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
