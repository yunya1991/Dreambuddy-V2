"use client";

import React from "react";

interface WhaleTransaction {
  wallet_address?: string;
  wallet_label?: string;
  amount: number;
  direction: "in" | "out";
  timestamp?: string;
  exchange?: string;
  usd_value?: number;
}

interface WhaleTrackerProps {
  transactions: WhaleTransaction[];
  title?: string;
  maxItems?: number;
}

function formatBTC(v: number): string {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}K BTC`;
  return `${v.toFixed(2)} BTC`;
}

function formatUSD(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toFixed(0)}`;
}

function shortenAddress(addr: string): string {
  if (!addr || addr.length < 12) return addr || "未知钱包";
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

export default function WhaleTracker({
  transactions,
  title = "鲸鱼钱包追踪",
  maxItems = 8,
}: WhaleTrackerProps) {
  if (!transactions || transactions.length === 0) {
    return (
      <div
        style={{
          backgroundColor: "#1a1a1a",
          border: "1px solid #2a2a2a",
          borderRadius: 12,
          padding: 20,
          color: "#8a8a8a",
        }}
      >
        {title}：暂无数据
      </div>
    );
  }

  const items = transactions.slice(0, maxItems);

  const totalIn = items
    .filter((t) => t.direction === "in")
    .reduce((sum, t) => sum + (t.amount || 0), 0);
  const totalOut = items
    .filter((t) => t.direction === "out")
    .reduce((sum, t) => sum + (t.amount || 0), 0);

  return (
    <div
      style={{
        backgroundColor: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderRadius: 12,
        padding: 20,
      }}
    >
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "#e0e0e0",
          marginBottom: 12,
        }}
      >
        {title}
      </div>

      <div
        style={{
          display: "flex",
          gap: 16,
          marginBottom: 16,
          fontSize: 12,
        }}
      >
        <div style={{ color: "#22c55e" }}>
          累计转入: {formatBTC(totalIn)}
        </div>
        <div style={{ color: "#ef4444" }}>
          累计转出: {formatBTC(totalOut)}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((tx, i) => {
          const isIn = tx.direction === "in";
          const color = isIn ? "#22c55e" : "#ef4444";
          const icon = isIn ? "📥" : "📤";
          const wallet = tx.wallet_label || shortenAddress(tx.wallet_address || "");
          const usdVal = tx.usd_value || tx.amount * 65000;

          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "8px 12px",
                backgroundColor: "#0d0d0d",
                borderRadius: 8,
                border: `1px solid ${isIn ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"}`,
              }}
            >
              <span style={{ fontSize: 16 }}>{icon}</span>
              <div style={{ flex: 1, fontSize: 12, color: "#e0e0e0" }}>
                <div style={{ fontWeight: 500 }}>{wallet}</div>
                <div style={{ fontSize: 11, color: "#8a8a8a" }}>
                  {tx.exchange || "未知交易所"} · {tx.timestamp || "近期"}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 13, fontWeight: 600, color }}>
                  {formatBTC(tx.amount)}
                </div>
                <div style={{ fontSize: 11, color: "#8a8a8a" }}>
                  {formatUSD(usdVal)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}