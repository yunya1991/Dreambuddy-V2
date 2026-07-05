"use client";

import { useState } from "react";
import type { ChainTrace, OrchestrationNode, PlannedStep } from "@/types";

// ============================================================
// 三层架构可视化面板
// B层(Blueprint) → A层(Arrange) → C层(Chronicle)
// ============================================================

const LAYER_COLORS = {
  B: "#6366f1",
  A: "#f59e0b",
  C: "#0ea5e9",
};

const STATUS_STYLES: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  pending:  { bg: "#1a1a1a", border: "#2a2a2a", text: "#666", icon: "⬜" },
  active:   { bg: "#0066ff22", border: "#0066ff", text: "#fff", icon: "▶" },
  done:     { bg: "#006b3f22", border: "#006b3f", text: "#00c853", icon: "✓" },
  skipped:  { bg: "#4a4a4a22", border: "#4a4a4a", text: "#999", icon: "⏭" },
  failed:   { bg: "#ff3b3022", border: "#ff3b30", text: "#ff3b30", icon: "✗" },
};

// 思维阶段图标（动态编排模式）
const STAGE_ICONS: Record<string, string> = {
  research: "🔍",
  analysis: "🧠",
  design: "📐",
  validate: "✅",
  execute: "⚡",
};

const STAGE_LABELS: Record<string, string> = {
  research: "调研",
  analysis: "分析",
  design: "设计",
  validate: "验证",
  execute: "执行",
};

// 根据技能 ID 推断图标
function getSkillIcon(skillId: string): string {
  if (skillId.startsWith("dream-")) return "🤖";
  if (skillId.startsWith("Regime") || skillId.startsWith("Classic")) return "📊";
  if (skillId.includes("fundamental") || skillId.includes("news")) return "📰";
  if (skillId.includes("risk")) return "🛡️";
  if (skillId.includes("execute") || skillId.includes("order")) return "🎯";
  return "⚙️";
}

interface Props {
  trace: ChainTrace | null;
}

export default function OrchestrationPanel({ trace }: Props) {
  const [expandedNode, setExpandedNode] = useState<string | null>(null);

  if (!trace) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <div style={{
          width: 64,
          height: 64,
          margin: "0 auto 12px",
          borderRadius: 16,
          backgroundColor: "#1a1a1a",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 28,
        }}>
          🔀
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#ccc", marginBottom: 4 }}>
          编排追踪面板
        </div>
        <div style={{ fontSize: 11, color: "#666", marginBottom: 12 }}>
          发送一条消息开始追踪
        </div>
        <div style={{
          padding: 10,
          backgroundColor: "#0d0d0d",
          border: "1px solid #1a1a1a",
          borderRadius: 8,
          fontSize: 10,
          color: "#888",
          textAlign: "left",
          lineHeight: 1.6,
        }}>
          <div style={{ color: "#6366f1", fontWeight: 600, marginBottom: 4 }}>🔵 B层 · 意图蓝图</div>
          <div style={{ color: "#f59e0b", fontWeight: 600, marginBottom: 4 }}>🟠 A层 · 编排计划</div>
          <div style={{ color: "#0ea5e9", fontWeight: 600 }}>🔵 C层 · 执行记录</div>
        </div>
        <div style={{ fontSize: 10, color: "#444", marginTop: 10 }}>
          试试输入「分析BTC」
        </div>
      </div>
    );
  }

  const bNodes = trace.nodes.filter((n) => n.layer === "B");
  const aNodes = trace.nodes.filter((n) => n.layer === "A");
  const cNodes = trace.nodes.filter((n) => n.layer === "C");
  const totalTokens = trace.cost_report?.total_tokens ?? 0;
  const budgetTokens = trace.plan.total_budget || trace.cost_report?.budget_tokens || 0;
  const tokenPct = budgetTokens > 0 ? Math.min(100, (totalTokens / budgetTokens) * 100) : 0;

  // 是否为动态编排模式（A 层节点带 stage 字段）
  const isDynamicOrchestration = aNodes.some((n) => n.stage);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* ── 任务概览 ── */}
      <div
        style={{
          padding: 12,
          backgroundColor: "#0d0d0d",
          border: "1px solid #1a1a1a",
          borderRadius: 8,
        }}
      >
        <div style={{ fontSize: 12, fontWeight: 700, color: "#ccc", marginBottom: 8 }}>
          🎯 任务概览
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 11 }}>
          <InfoItem label="意图" value={trace.intent.type} valueColor="#0066ff" />
          <InfoItem label="置信度" value={`${(trace.intent.confidence * 100).toFixed(0)}%`} valueColor="#00c853" />
          <InfoItem label="识别方法" value={trace.intent.method} />
          <InfoItem label="链路" value={trace.plan.chain_name || trace.plan.chain_id} />
          <InfoItem label="复杂度" value={trace.plan.complexity} />
          <InfoItem label="编排理由" value={trace.plan.rationale} span={2} />
        </div>
      </div>

      {/* ── Token 预算条 ── */}
      {budgetTokens > 0 && (
        <div
          style={{
            padding: 10,
            backgroundColor: "#0d0d0d",
            border: "1px solid #1a1a1a",
            borderRadius: 8,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 6 }}>
            <span style={{ color: "#888" }}>💰 Token 预算</span>
            <span style={{ color: tokenPct > 80 ? "#ff3b30" : "#00c853" }}>
              {totalTokens.toLocaleString()} / {budgetTokens.toLocaleString()}
            </span>
          </div>
          <div style={{ height: 6, backgroundColor: "#1a1a1a", borderRadius: 3, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${tokenPct}%`,
                backgroundColor: tokenPct > 80 ? "#ff3b30" : "#0066ff",
                transition: "width 0.3s ease",
              }}
            />
          </div>
        </div>
      )}

      {/* ── B层 · Blueprint 意图蓝图 ── */}
      {bNodes.length > 0 && (
        <LayerSection
          title="B层 · Blueprint 意图蓝图"
          color={LAYER_COLORS.B}
          desc="意图识别 → 链路选择 → 复杂度评估"
        >
          <NodeRow
            nodes={bNodes}
            expandedNode={expandedNode}
            onToggle={setExpandedNode}
          />
        </LayerSection>
      )}

      {/* ── A层 · Architecture 编排计划 ── */}
      {aNodes.length > 0 && (
        <LayerSection
          title="A层 · Architecture 编排计划"
          color={LAYER_COLORS.A}
          desc={
            isDynamicOrchestration
              ? "动态编排 → 技能选择 → 执行图构建"
              : "节点选择 → 预算分配 → 执行图构建"
          }
        >
          {isDynamicOrchestration ? (
            <ANodeGrouped
              nodes={aNodes}
              plannedSteps={trace.plan.planned_steps}
              expandedNode={expandedNode}
              onToggle={setExpandedNode}
            />
          ) : (
            <NodeRow
              nodes={aNodes}
              expandedNode={expandedNode}
              onToggle={setExpandedNode}
            />
          )}
        </LayerSection>
      )}

      {/* ── C层 · Chronicle 执行记录 ── */}
      {cNodes.length > 0 && (
        <LayerSection
          title="C层 · Chronicle 执行记录"
          color={LAYER_COLORS.C}
          desc="节点执行 → 反射决策 → 结果聚合"
        >
          <NodeRow
            nodes={cNodes}
            expandedNode={expandedNode}
            onToggle={setExpandedNode}
          />
        </LayerSection>
      )}

      {/* ── 自省结果 ── */}
      {trace.final.execution_chain && (
        <div
          style={{
            padding: 12,
            backgroundColor: "#0d0d0d",
            border: "1px solid #1a1a1a",
            borderRadius: 8,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, color: "#ccc", marginBottom: 8 }}>
            🧠 自省结果
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 11 }}>
            <InfoItem label="执行链路" value={trace.final.execution_chain} />
            <InfoItem label="品质评级" value={trace.final.grade} valueColor="#00c853" />
            <InfoItem
              label="质量评分"
              value={(trace.final.quality_score * 100).toFixed(0) + "%"}
              valueColor="#00c853"
            />
            <InfoItem
              label="风险评分"
              value={(trace.final.risk_score * 100).toFixed(0) + "%"}
              valueColor={trace.final.risk_score > 0.5 ? "#ff3b30" : "#f59e0b"}
            />
          </div>
        </div>
      )}

      {/* ── CostKeeper 报告 ── */}
      {trace.cost_report && (
        <div
          style={{
            padding: 10,
            backgroundColor: "#0d0d0d",
            border: "1px solid #1a1a1a",
            borderRadius: 8,
            fontSize: 11,
          }}
        >
          <div style={{ fontWeight: 600, color: "#ccc", marginBottom: 6 }}>📊 CostKeeper</div>
          <div style={{ color: "#888" }}>
            Prompt: {trace.cost_report.prompt_tokens.toLocaleString()} ·
            Completion: {trace.cost_report.completion_tokens.toLocaleString()}
          </div>
          {trace.cost_report.skipped_steps.length > 0 && (
            <div style={{ color: "#f59e0b", marginTop: 4 }}>
              ⏭ 跳过: {trace.cost_report.skipped_steps.join(", ")}
            </div>
          )}
        </div>
      )}

      {/* ── 压缩报告 ── */}
      {trace.compression && (
        <div
          style={{
            padding: 10,
            backgroundColor: "#0d0d0d",
            border: "1px solid #1a1a1a",
            borderRadius: 8,
            fontSize: 11,
          }}
        >
          <div style={{ fontWeight: 600, color: "#ccc", marginBottom: 6 }}>🗜️ 上下文压缩</div>
          <div style={{ color: "#888" }}>
            {trace.compression.original_tokens.toLocaleString()} →{" "}
            {trace.compression.compressed_tokens.toLocaleString()} tokens
          </div>
          <div style={{ color: "#00c853", marginTop: 2 }}>
            压缩率: {(trace.compression.ratio * 100).toFixed(0)}%
          </div>
        </div>
      )}
    </div>
  );
}

// ── 层级容器 ─────────────────────────────────────────

function LayerSection({
  title,
  color,
  desc,
  children,
}: {
  title: string;
  color: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        padding: 12,
        backgroundColor: "#0d0d0d",
        border: `1px solid ${color}33`,
        borderRadius: 8,
      }}
    >
      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color }}>
          <span style={{ marginRight: 6 }}>●</span>
          {title}
        </div>
        <div style={{ fontSize: 10, color: "#666", marginTop: 2 }}>{desc}</div>
      </div>
      {children}
    </div>
  );
}

// ── 节点行 ───────────────────────────────────────────

function NodeRow({
  nodes,
  expandedNode,
  onToggle,
}: {
  nodes: OrchestrationNode[];
  expandedNode: string | null;
  onToggle: (id: string | null) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {/* 节点横向流 */}
      <div style={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
        {nodes.map((node, idx) => {
          const style = STATUS_STYLES[node.status] || STATUS_STYLES.pending;
          const isExpanded = expandedNode === node.id;
          return (
            <div key={`${idx}-${node.id}`} style={{ display: "flex", alignItems: "center" }}>
              <div
                onClick={() => onToggle(isExpanded ? null : node.id)}
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 8,
                  backgroundColor: style.bg,
                  border: `2px solid ${style.border}`,
                  color: style.text,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                  transition: "all 0.2s",
                  flexShrink: 0,
                }}
                title={node.name}
              >
                <span style={{ fontSize: 16 }}>{node.icon || style.icon}</span>
                <span style={{ fontSize: 9, marginTop: 2, textAlign: "center", lineHeight: 1.1 }}>
                  {node.id.split("_")[0]}
                </span>
              </div>
              {idx < nodes.length - 1 && (
                <div
                  style={{
                    width: 12,
                    height: 2,
                    backgroundColor: nodes[idx + 1].status !== "pending" ? "#3b82f6" : "#2a2a2a",
                    transition: "background-color 0.2s",
                  }}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* 展开的节点详情 */}
      {expandedNode && (() => {
        const node = nodes.find((n) => n.id === expandedNode);
        if (!node) return null;
        const style = STATUS_STYLES[node.status] || STATUS_STYLES.pending;
        return (
          <div
            style={{
              marginTop: 4,
              padding: 10,
              backgroundColor: "#141414",
              border: `1px solid ${style.border}44`,
              borderRadius: 6,
              fontSize: 11,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontWeight: 600, color: "#ccc" }}>
                {node.icon} {node.name}
              </span>
              <span style={{ color: style.text, fontWeight: 600 }}>
                {style.icon} {node.status}
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, color: "#888" }}>
              {node.confidence !== undefined && (
                <div>置信度: <span style={{ color: "#00c853" }}>{(node.confidence * 100).toFixed(0)}%</span></div>
              )}
              {node.risk !== undefined && (
                <div>风险: <span style={{ color: node.risk > 0.5 ? "#ff3b30" : "#f59e0b" }}>{(node.risk * 100).toFixed(0)}%</span></div>
              )}
              {node.latency_ms !== undefined && node.latency_ms > 0 && (
                <div>延迟: <span style={{ color: "#aaa" }}>{node.latency_ms.toFixed(0)}ms</span></div>
              )}
              {node.tokens_used !== undefined && node.tokens_used > 0 && (
                <div>Token: <span style={{ color: "#aaa" }}>{node.tokens_used.toLocaleString()}</span></div>
              )}
              {node.tokens_budget !== undefined && node.tokens_budget > 0 && (
                <div>预算: <span style={{ color: "#aaa" }}>{node.tokens_budget.toLocaleString()}</span></div>
              )}
              {node.reflect_action && (
                <div>反射: <span style={{ color: "#0066ff" }}>{node.reflect_action}</span></div>
              )}
              {node.skip_reason && (
                <div style={{ gridColumn: "span 2", color: "#f59e0b" }}>
                  跳过原因: {node.skip_reason}
                </div>
              )}
              {node.artifact && (
                <div style={{ gridColumn: "span 2", color: "#3b82f6" }}>
                  📎 {node.artifact}
                </div>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ── A 层动态编排分组（按思维阶段） ─────────────────

function ANodeGrouped({
  nodes,
  plannedSteps,
  expandedNode,
  onToggle,
}: {
  nodes: OrchestrationNode[];
  plannedSteps?: PlannedStep[];
  expandedNode: string | null;
  onToggle: (id: string | null) => void;
}) {
  const stageOrder = ["research", "analysis", "design", "validate", "execute"];
  const grouped = new Map<string, OrchestrationNode[]>();
  for (const node of nodes) {
    const key = node.stage || "other";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(node);
  }

  const orderedStages = [
    ...stageOrder.filter((s) => grouped.has(s)),
    ...[...grouped.keys()].filter((s) => !stageOrder.includes(s)),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {orderedStages.map((stage, stageIdx) => {
        const stageNodes = grouped.get(stage) || [];
        const stageNode = stageNodes.find((n) => !n.is_skill);
        const skillNodes = stageNodes.filter((n) => n.is_skill);
        const stageStyle = STATUS_STYLES[stageNode?.status || "done"] || STATUS_STYLES.done;
        const stageIcon = stageNode?.icon || STAGE_ICONS[stage] || "⚙️";
        const stageLabel = stageNode?.name || STAGE_LABELS[stage] || stage;
        const plannedStep = plannedSteps?.find((p) => p.stage === stage);

        return (
          <div key={stage}>
            {/* 阶段头 */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 8px",
                borderRadius: 6,
                backgroundColor: stageStyle.bg,
                border: `1px solid ${stageStyle.border}55`,
              }}
            >
              <span style={{ fontSize: 16 }}>{stageIcon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: stageStyle.text }}>
                  {stageLabel}
                </div>
                {plannedStep && (
                  <div style={{ fontSize: 9, color: "#666", marginTop: 1 }}>
                    {plannedStep.chain}链 · {plannedStep.selected_skills.length}个技能
                  </div>
                )}
              </div>
              {stageNode?.confidence !== undefined && (
                <span style={{ fontSize: 10, color: "#00c853", fontWeight: 600 }}>
                  {(stageNode.confidence * 100).toFixed(0)}%
                </span>
              )}
              {stageNode?.tokens_used !== undefined && stageNode.tokens_used > 0 && (
                <span style={{ fontSize: 9, color: "#888" }}>
                  {stageNode.tokens_used.toLocaleString()}t
                </span>
              )}
            </div>

            {/* 技能横向流 */}
            {skillNodes.length > 0 && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 2,
                  flexWrap: "wrap",
                  marginTop: 4,
                  marginLeft: 12,
                }}
              >
                {skillNodes.map((node, idx) => {
                  const style = STATUS_STYLES[node.status] || STATUS_STYLES.pending;
                  const isExpanded = expandedNode === node.id;
                  const skillIcon = node.icon || getSkillIcon(node.id);
                  return (
                    <div key={`${idx}-${node.id}`} style={{ display: "flex", alignItems: "center" }}>
                      <div
                        onClick={() => onToggle(isExpanded ? null : node.id)}
                        style={{
                          width: 44,
                          height: 44,
                          borderRadius: 6,
                          backgroundColor: style.bg,
                          border: `1.5px solid ${style.border}`,
                          color: style.text,
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          justifyContent: "center",
                          cursor: "pointer",
                          transition: "all 0.2s",
                          flexShrink: 0,
                        }}
                        title={node.name}
                      >
                        <span style={{ fontSize: 13 }}>{skillIcon}</span>
                        <span style={{ fontSize: 8, marginTop: 1, textAlign: "center", lineHeight: 1.1, maxWidth: 40, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {node.name.slice(0, 6)}
                        </span>
                      </div>
                      {idx < skillNodes.length - 1 && (
                        <div
                          style={{
                            width: 8,
                            height: 1.5,
                            backgroundColor: skillNodes[idx + 1].status !== "pending" ? "#3b82f6" : "#2a2a2a",
                          }}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* 展开的技能节点详情 */}
            {expandedNode && skillNodes.some((n) => n.id === expandedNode) && (() => {
              const node = skillNodes.find((n) => n.id === expandedNode);
              if (!node) return null;
              const style = STATUS_STYLES[node.status] || STATUS_STYLES.pending;
              return (
                <div
                  style={{
                    marginTop: 4,
                    marginLeft: 12,
                    padding: 8,
                    backgroundColor: "#141414",
                    border: `1px solid ${style.border}44`,
                    borderRadius: 6,
                    fontSize: 10,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, color: "#ccc" }}>
                      {getSkillIcon(node.id)} {node.name}
                    </span>
                    <span style={{ color: style.text, fontWeight: 600 }}>
                      {style.icon} {node.status}
                    </span>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, color: "#888" }}>
                    {node.confidence !== undefined && (
                      <div>置信度: <span style={{ color: "#00c853" }}>{(node.confidence * 100).toFixed(0)}%</span></div>
                    )}
                    {node.latency_ms !== undefined && node.latency_ms > 0 && (
                      <div>延迟: <span style={{ color: "#aaa" }}>{node.latency_ms.toFixed(0)}ms</span></div>
                    )}
                    {node.tokens_used !== undefined && node.tokens_used > 0 && (
                      <div>Token: <span style={{ color: "#aaa" }}>{node.tokens_used.toLocaleString()}</span></div>
                    )}
                    {node.chain && (
                      <div>链路: <span style={{ color: "#f59e0b" }}>{node.chain}</span></div>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* 阶段间连接线 */}
            {stageIdx < orderedStages.length - 1 && (
              <div style={{ display: "flex", justifyContent: "center", margin: "2px 0" }}>
                <div style={{ width: 1.5, height: 8, backgroundColor: "#3b82f655" }} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── 信息项 ───────────────────────────────────────────

function InfoItem({
  label,
  value,
  valueColor,
  span,
}: {
  label: string;
  value: string;
  valueColor?: string;
  span?: number;
}) {
  return (
    <div style={{ gridColumn: span === 2 ? "span 2" : undefined }}>
      <span style={{ color: "#666" }}>{label}: </span>
      <span style={{ color: valueColor || "#ccc", fontWeight: 600 }}>{value}</span>
    </div>
  );
}
