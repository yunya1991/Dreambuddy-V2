"use client";

// ============================================================
// ActiveDZEChain — D-Z-E 三链可视化
// 版本: v1.0 | 日期: 2026-06-15
// 显示 d1→d2→d3→d4 → z1→z2→z3→z4 → e1→e2→e3
// ============================================================

import type { DZEChainState } from "@/lib/notebook/types";

interface Props {
  chain: DZEChainState | null;
  compact?: boolean;
}

const CHAIN_COLORS: Record<string, string> = {
  d: "#0088aa",
  z: "#aa6600",
  e: "#008855",
};

const CHAIN_NAMES: Record<string, string> = {
  d: "调研链",
  z: "规划链",
  e: "执行链",
};

export default function ActiveDZEChain({ chain, compact }: Props) {
  if (!chain) {
    return (
      <div
        style={{
          padding: 12,
          backgroundColor: "#0d0d0d",
          border: "1px dashed #2a2a2a",
          borderRadius: 6,
          fontSize: 12,
          color: "#666",
          textAlign: "center",
        }}
      >
        D-Z-E 链未初始化 · 完成 Step1 后自动生成
      </div>
    );
  }

  const grouped = [
    { group: "d", items: chain.phases.filter((p) => p.id.startsWith("d")) },
    { group: "z", items: chain.phases.filter((p) => p.id.startsWith("z")) },
    { group: "e", items: chain.phases.filter((p) => p.id.startsWith("e")) },
  ];

  const totalDone = chain.phases.filter(
    (p) => p.status === "done" || p.status === "skipped"
  ).length;

  return (
    <div
      style={{
        padding: compact ? 8 : 12,
        backgroundColor: "#0d0d0d",
        border: "1px solid #1a1a1a",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
          fontSize: 12,
          color: "#888",
        }}
      >
        <span style={{ fontWeight: 600, color: "#ccc" }}>
          🔗 D-Z-E 思维链
        </span>
        <span>
          {totalDone}/{chain.phases.length} 阶段 · 范围: {chain.scope.slice(0, 20)}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {grouped.map((g) => {
          const groupDone = g.items.filter(
            (p) => p.status === "done" || p.status === "skipped"
          ).length;
          const groupColor = CHAIN_COLORS[g.group];
          return (
            <div
              key={g.group}
              style={{
                padding: 8,
                backgroundColor: "#141414",
                border: "1px solid #1a1a1a",
                borderRadius: 6,
              }}
            >
              <div
                style={{
                  display: "flex",
                  flexDirection: "row",
                  justifyContent: "center",
                  alignItems: "center",
                  fontSize: 11,
                  marginBottom: 8,
                  gap: 4,
                }}
              >
                <span
                  style={{
                    display: "block",
                    width: 8,
                    height: 8,
                    backgroundColor: groupColor,
                    borderRadius: 2,
                  }}
                />
                <span style={{ color: "#999", marginRight: 8 }}>
                  {CHAIN_NAMES[g.group]}
                </span>
                {groupDone === g.items.length ? (
                  <span style={{ fontSize: 10, color: groupColor, marginLeft: "auto" }}>
                    ({groupDone}/{g.items.length})
                  </span>
                ) : (
                  <span style={{ fontSize: 10, color: "#666", marginLeft: "auto" }}>
                    ({groupDone}/{g.items.length})
                  </span>
                )}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 4 }}>
                {g.items.map((phase) => {
                  const color = groupColor;
                  const isCurrent = chain.currentPhase === phase.id;
                  const isDone = phase.status === "done" || phase.status === "skipped";
                  return (
                    <div
                      key={phase.id}
                      style={{
                        flex: 1,
                        textAlign: "center",
                        padding: "6px 4px",
                        backgroundColor: isCurrent ? color + "22" : "#0d0d0d",
                        border: "1px solid " + (isCurrent ? color : "#222"),
                        borderRadius: 4,
                        fontSize: 11,
                        color: isDone ? color : isCurrent ? color : "#666",
                        fontWeight: isCurrent ? 700 : 400,
                        minWidth: 60,
                      }}
                    >
                      <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase" }}>
                        {phase.id}
                      </div>
                      <div style={{ fontSize: 9, opacity: 0.8, marginTop: 2 }}>
                        {phase.name.split(" ")[1] || phase.name}
                      </div>
                      {!compact && phase.output && (
                        <div style={{ fontSize: 9, color: "#555", marginTop: 4, lineHeight: 1.4 }}>
                          {phase.output.slice(0, 100)}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
