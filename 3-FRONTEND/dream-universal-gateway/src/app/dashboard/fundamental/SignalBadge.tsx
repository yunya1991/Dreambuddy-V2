"use client";

import React from "react";

export interface TradingSignal {
  type: "strong_buy" | "buy" | "hold" | "sell" | "strong_sell" | "reduce" | string;
  strength: number;
  reason: string;
  horizon: string;
}

interface Props {
  signal?: TradingSignal;
  signals?: TradingSignal[];
  size?: "sm" | "md" | "lg";
}

function toNum(v: any, def = 0): number {
  if (typeof v === "number" && isFinite(v)) return v;
  if (typeof v === "string" && v.trim()) {
    const n = parseFloat(v);
    return isFinite(n) ? n : def;
  }
  return def;
}

function signalBadgeColor(type: string): string {
  const colors: Record<string, string> = {
    strong_buy: "#22c55e",
    buy: "#3b82f6",
    hold: "#eab308",
    sell: "#f97316",
    strong_sell: "#ef4444",
    reduce: "#ef4444",
  };
  return colors[type] || "#8a8a8a";
}

function signalLabel(type: string): string {
  const labels: Record<string, string> = {
    strong_buy: "强买入",
    buy: "买入",
    hold: "持有",
    sell: "卖出",
    strong_sell: "强卖出",
    reduce: "减仓",
  };
  return labels[type] || type;
}

function signalIcon(type: string): string {
  const icons: Record<string, string> = {
    strong_buy: "⚡",
    buy: "📈",
    hold: "⏸️",
    sell: "📉",
    strong_sell: "⚠️",
    reduce: "🔻",
  };
  return icons[type] || "➖";
}

function SignalItem({
  signal,
  compact = false,
}: {
  signal: TradingSignal;
  compact?: boolean;
}) {
  const color = signalBadgeColor(signal.type);
  const strength = toNum(signal.strength);
  const strengthPct = strength <= 1 ? strength * 100 : strength;

  if (compact) {
    return (
      <div
        className="rounded-lg"
        style={{ backgroundColor: "#1a1a1a", padding: 10, border: `1px solid ${color}30` }}
      >
        <div className="flex items-center justify-between mb-1">
          <span
            className="text-xs font-bold"
            style={{ color }}
          >
            {signalIcon(signal.type)} {signalLabel(signal.type)}
          </span>
          <span className="text-[11px] font-mono text-[#9ca3af]">
            {strengthPct.toFixed(0)}%
          </span>
        </div>
        {signal.reason && (
          <div className="text-[11px] text-[#9ca3af] leading-snug">
            {signal.reason}
          </div>
        )}
        {signal.horizon && (
          <div className="text-[10px] text-[#6b7280] mt-1">
            {signal.horizon.replace(/_/g, " ")}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="rounded-lg text-center"
      style={{
        backgroundColor: `${color}18`,
        padding: 14,
        border: `1px solid ${color}40`,
      }}
    >
      <div
        className="font-bold mb-1"
        style={{ color, fontSize: 20 }}
      >
        {signalIcon(signal.type)} {signalLabel(signal.type)}
      </div>
      <div className="text-xs text-[#9ca3af] mb-1">
        强度 <span className="font-mono font-bold" style={{ color }}>{strengthPct.toFixed(0)}%</span>
      </div>
      {signal.reason && (
        <div className="text-xs text-[#c0c0c0] leading-snug mt-2">
          {signal.reason}
        </div>
      )}
      {signal.horizon && (
        <div className="text-[11px] text-[#6b7280] mt-2">
          周期：{signal.horizon.replace(/_/g, " ")}
        </div>
      )}
    </div>
  );
}

export default function SignalBadge({ signal, signals, size = "md" }: Props) {
  const main = signal || (signals && signals[0]);
  const rest = signals ? signals.slice(1) : [];

  if (!main) {
    return (
      <div
        className="rounded-lg text-sm text-center"
        style={{ backgroundColor: "#121212", padding: 16, color: "#6b7280" }}
      >
        暂无信号
      </div>
    );
  }

  const color = signalBadgeColor(main.type);
  const strength = toNum(main.strength);
  const strengthPct = strength <= 1 ? strength * 100 : strength;

  const titleSize =
    size === "lg" ? "text-3xl" : size === "sm" ? "text-lg" : "text-2xl";

  return (
    <div style={{ backgroundColor: "#121212", padding: 16, borderRadius: 8 }}>
      <div
        className="text-center rounded-lg mb-3"
        style={{
          backgroundColor: `${color}15`,
          border: `1px solid ${color}40`,
          padding: 14,
        }}
      >
        <div
          className={`${titleSize} font-bold mb-1 leading-tight`}
          style={{ color, opacity: 0.95 }}
        >
          {signalIcon(main.type)} {signalLabel(main.type)}
        </div>
        <div className="text-xs text-[#9ca3af]">
          强度 <span className="font-mono font-bold" style={{ color }}>{strengthPct.toFixed(0)}%</span>
        </div>
        {main.reason && (
          <div className="text-xs text-[#c0c0c0] leading-snug mt-2">
            {main.reason}
          </div>
        )}
        {main.horizon && (
          <div className="text-[11px] text-[#6b7280] mt-2">
            {main.horizon.replace(/_/g, " ")}
          </div>
        )}
      </div>

      {rest.length > 0 && (
        <div className="space-y-2">
          {rest.slice(0, 2).map((s, i) => (
            <SignalItem key={i} signal={s} compact />
          ))}
        </div>
      )}
    </div>
  );
}
