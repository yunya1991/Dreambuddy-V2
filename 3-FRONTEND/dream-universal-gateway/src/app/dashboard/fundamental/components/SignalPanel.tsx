"use client";

import React from "react";

interface TradingSignal {
  id: string;
  type: "strong_buy" | "buy" | "hold" | "sell" | "strong_sell" | "reduce";
  strength: number;
  confidence: number;
  reason: string;
  horizon: "short" | "medium" | "long";
  factors: string[];
  created_at: string;
}

interface SignalPanelProps {
  signals: TradingSignal[];
  title?: string;
}

const SIGNAL_CONFIG: Record<
  TradingSignal["type"],
  { label: string; emoji: string; color: string; bgColor: string }
> = {
  strong_buy: { label: "强买入", emoji: "🚀", color: "#22c55e", bgColor: "rgba(34, 197, 94, 0.15)" },
  buy: { label: "买入", emoji: "📈", color: "#22c55e", bgColor: "rgba(34, 197, 94, 0.1)" },
  hold: { label: "持有", emoji: "➡️", color: "#eab308", bgColor: "rgba(234, 179, 8, 0.1)" },
  sell: { label: "卖出", emoji: "📉", color: "#ef4444", bgColor: "rgba(239, 68, 68, 0.1)" },
  strong_sell: { label: "强卖出", emoji: "💥", color: "#ef4444", bgColor: "rgba(239, 68, 68, 0.15)" },
  reduce: { label: "减仓", emoji: "🔻", color: "#f97316", bgColor: "rgba(249, 115, 22, 0.1)" },
};

const FALLBACK_CONFIG = { label: "观察", emoji: "👁️", color: "#8a8a8a", bgColor: "rgba(138, 138, 138, 0.1)" };

const HORIZON_LABEL: Record<TradingSignal["horizon"], string> = {
  short: "短期",
  medium: "中期",
  long: "长期",
};

export default function SignalPanel({ signals, title }: SignalPanelProps) {
  if (!signals || signals.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full rounded-lg"
        style={{ backgroundColor: "#1a1a1a", minHeight: 150 }}
      >
        <p className="text-[#6b7280] text-sm">暂无信号</p>
      </div>
    );
  }

  const mainSignal = signals[0];
  const mainConfig = SIGNAL_CONFIG[mainSignal.type] ?? FALLBACK_CONFIG;

  return (
    <div
      className="rounded-lg p-4"
      style={{ backgroundColor: "#1a1a1a", border: "1px solid #2a2a2a" }}
    >
      {title && (
        <h3 className="text-sm font-semibold text-white mb-4">{title}</h3>
      )}

      <div
        className="rounded-lg p-4 mb-4"
        style={{ backgroundColor: mainConfig.bgColor, border: `1px solid ${mainConfig.color}30` }}
      >
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{mainConfig.emoji}</span>
            <span className="text-lg font-bold" style={{ color: mainConfig.color }}>
              {mainConfig.label}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-[#8a8a8a]">
              强度: <span className="font-mono text-white">{(mainSignal.strength * 100).toFixed(0)}%</span>
            </span>
            <span className="text-xs text-[#8a8a8a]">
              置信: <span className="font-mono text-white">{(mainSignal.confidence * 100).toFixed(0)}%</span>
            </span>
          </div>
        </div>
        <p className="text-sm text-[#e0e0e0] mb-2">{mainSignal.reason}</p>
        <div className="flex items-center gap-2">
          <span
            className="px-2 py-0.5 rounded text-xs"
            style={{ backgroundColor: "#2a2a2a", color: "#8a8a8a" }}
          >
            {HORIZON_LABEL[mainSignal.horizon]}
          </span>
          <span className="text-xs text-[#6b7280]">
            {new Date(mainSignal.created_at).toLocaleString("zh-CN")}
          </span>
        </div>
      </div>

      {signals.length > 1 && (
        <div className="space-y-2">
          <div className="text-xs text-[#6b7280] uppercase tracking-wider">其他信号</div>
          {signals.slice(1, 4).map((signal) => {
            const config = SIGNAL_CONFIG[signal.type] ?? FALLBACK_CONFIG;
            return (
              <div
                key={signal.id}
                className="flex items-center justify-between p-2 rounded"
                style={{ backgroundColor: "#121212" }}
              >
                <div className="flex items-center gap-2">
                  <span style={{ color: config.color }}>{config.emoji}</span>
                  <span className="text-sm text-[#e0e0e0]">{config.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[#6b7280]">
                    {(signal.strength * 100).toFixed(0)}%
                  </span>
                  <span
                    className="px-1.5 py-0.5 rounded text-xs"
                    style={{ backgroundColor: "#2a2a2a", color: "#8a8a8a" }}
                  >
                    {HORIZON_LABEL[signal.horizon]}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
