"use client";

import { useState, useMemo } from "react";
import type { ChainTrace } from "@/types";

// ============================================================
// 对话内嵌思考卡
// 展示在 AI 回复顶部，可折叠展开
// ============================================================

interface StreamProgress {
  isStreaming: boolean;
  currentStep: string | null;
  currentSkill: string | null;
  planSteps: Array<{
    stepId: string;
    stage: string;
    chain: string;
    label?: string;
    status: 'pending' | 'active' | 'done' | 'skipped';
  }>;
  skillStatuses: Record<string, {
    status: 'pending' | 'active' | 'done';
    confidence?: number;
    latencyMs?: number;
  }>;
  contentAccumulated: string;
}

interface Props {
  trace: ChainTrace | null | undefined;
  executionTimeMs?: number;
  isLoading?: boolean;
  streamProgress?: StreamProgress | null;
}

// S 链节点图标（降级路径）
const STEP_ICONS: Record<string, string> = {
  S1_RESEARCH: "🔍",
  S2_ANALYSIS: "🧠",
  S3_DESIGN: "📐",
  S4_VALIDATE: "✅",
  S5_EXECUTE: "⚡",
  S0_DIRECT_ANSWER: "💬",
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

// 解析节点图标：优先用 stage → S 链 → 技能 ID → 默认
function resolveNodeIcon(node: { icon?: string; id: string; stage?: string; is_skill?: boolean }): string {
  if (node.icon) return node.icon;
  if (node.stage && STAGE_ICONS[node.stage]) return STAGE_ICONS[node.stage];
  if (STEP_ICONS[node.id]) return STEP_ICONS[node.id];
  if (node.is_skill) return getSkillIcon(node.id);
  return "⚙️";
}

export default function ThinkingCard({ trace, executionTimeMs, isLoading, streamProgress }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!trace && !isLoading && !streamProgress) return null;

  // 流式模式下，从 streamProgress 构建动态节点
  const streamANodes = useMemo(() => {
    if (!streamProgress) return [];
    const nodes: Array<{
      id: string;
      name: string;
      icon: string;
      layer: string;
      stage: string;
      chain: string;
      is_skill: boolean;
      status: string;
      confidence?: number;
      latency_ms?: number;
    }> = [];

    for (const step of streamProgress.planSteps) {
      const stageIcon = STAGE_ICONS[step.stage] || '⚙️';
      const stageLabel = STAGE_LABELS[step.stage] || step.label || step.stepId;
      
      // 思维阶段节点
      nodes.push({
        id: step.stepId,
        name: stageLabel,
        icon: stageIcon,
        layer: 'A',
        stage: step.stage,
        chain: step.chain,
        is_skill: false,
        status: step.status === 'done' ? 'done' : step.status === 'active' ? 'active' : step.status === 'skipped' ? 'skipped' : 'pending',
      });

      // 技能节点（从 skillStatuses 中查找）
      const skillKeyPrefix = `${step.stepId}_`;
      const skills = Object.entries(streamProgress.skillStatuses)
        .filter(([key]) => key.startsWith(skillKeyPrefix))
        .map(([key, val]) => ({
          skillId: key.slice(skillKeyPrefix.length),
          ...val,
        }));

      for (const skill of skills) {
        nodes.push({
          id: skill.skillId,
          name: skill.skillId,
          icon: getSkillIcon(skill.skillId),
          layer: 'A',
          stage: step.stage,
          chain: step.chain,
          is_skill: true,
          status: skill.status === 'done' ? 'done' : skill.status === 'active' ? 'active' : 'pending',
          confidence: skill.confidence ? skill.confidence / 100 : undefined,
          latency_ms: skill.latencyMs,
        });
      }
    }

    return nodes;
  }, [streamProgress]);

  const aNodes = trace?.nodes?.filter((n) => n.layer === "A") || streamANodes || [];
  const totalSteps = aNodes.length || (streamProgress?.planSteps.length || 5);
  const doneSteps = aNodes.filter((n) => n.status === "done").length;
  const progress = isLoading || streamProgress?.isStreaming
    ? totalSteps > 0 ? (doneSteps / totalSteps) * 100 : 30
    : 100;

  const timeText = executionTimeMs
    ? executionTimeMs >= 1000
      ? `${(executionTimeMs / 1000).toFixed(1)}s`
      : `${executionTimeMs}ms`
    : "";

  const isStreamingActive = streamProgress?.isStreaming;

  return (
    <div
      style={{
        marginBottom: 8,
        borderRadius: 10,
        backgroundColor: "#0d0d0d",
        border: "1px solid #1a1a1a",
        overflow: "hidden",
      }}
    >
      {/* ── 头部（折叠态也可见） ── */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: "10px 12px",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          userSelect: "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ fontSize: 14 }}>🧠</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>
            {isLoading || isStreamingActive ? "思考中..." : "思考过程"}
          </span>
          {isStreamingActive && streamProgress?.currentStep && (
            <span style={{ fontSize: 11, color: "#3b82f6", marginLeft: 4 }}>
              · {STAGE_LABELS[streamProgress.currentStep.split('_')[0]?.toLowerCase()] || streamProgress.currentStep}
            </span>
          )}
          {timeText && !isLoading && !isStreamingActive && (
            <span style={{ fontSize: 11, color: "#666" }}>· {timeText}</span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* 节点 icon 流 */}
          <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
            {aNodes.length > 0 ? (
              aNodes.slice(0, 8).map((node, idx) => (
                <span
                  key={`${idx}-${node.id}`}
                  style={{
                    fontSize: node.is_skill ? 10 : 12,
                    opacity: node.status === "done" ? 1 : node.status === "active" ? 1 : 0.3,
                    transition: "opacity 0.3s",
                  }}
                  title={node.name}
                >
                  {resolveNodeIcon(node)}
                </span>
              ))
            ) : isLoading || isStreamingActive ? (
              <span style={{ fontSize: 12, animation: "pulse 1.5s infinite" }}>🔄</span>
            ) : null}
          </div>

          <span style={{ fontSize: 11, color: "#666", transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}>
            ▼
          </span>
        </div>
      </div>

      {/* 进度条 */}
      <div style={{ height: 2, backgroundColor: "#1a1a1a" }}>
        <div
          style={{
            height: "100%",
            width: `${progress}%`,
            backgroundColor: isLoading || isStreamingActive ? "#3b82f6" : "#00c853",
            transition: "width 0.4s ease, background-color 0.3s",
          }}
        />
      </div>

      {/* ── 展开详情 ── */}
      {expanded && trace && (
        <div style={{ padding: "12px", borderTop: "1px solid #1a1a1a", fontSize: 11 }}>
          {/* 意图 & 链路 */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 10 }}>
            <div>
              <span style={{ color: "#666" }}>意图: </span>
              <span style={{ color: "#3b82f6", fontWeight: 600 }}>{trace.intent.type}</span>
            </div>
            <div>
              <span style={{ color: "#666" }}>置信度: </span>
              <span style={{ color: "#00c853", fontWeight: 600 }}>
                {(trace.intent.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div>
              <span style={{ color: "#666" }}>模式: </span>
              <span style={{ color: "#ccc" }}>{trace.plan.complexity}</span>
            </div>
            <div>
              <span style={{ color: "#666" }}>品质: </span>
              <span style={{ color: trace.final.grade === 'excellent' ? '#00c853' : trace.final.grade === 'good' ? '#10b981' : '#f59e0b', fontWeight: 600 }}>
                {trace.final.grade}
              </span>
            </div>
          </div>

          {/* A层节点详情 */}
          {aNodes.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: "#888", marginBottom: 6, fontWeight: 600 }}>执行节点</div>
              <ANodeList nodes={aNodes as any} />
            </div>
          )}

          {/* 自省结果 */}
          <div
            style={{
              padding: "8px 10px",
              borderRadius: 6,
              backgroundColor: "#0a0a0a",
              border: "1px solid #1a1a1a",
            }}
          >
            <div style={{ color: "#888", marginBottom: 4, fontWeight: 600 }}>🧠 自省结果</div>
            <div style={{ display: "flex", gap: 12 }}>
              <div>
                <span style={{ color: "#666" }}>质量: </span>
                <span style={{ color: "#00c853", fontWeight: 600 }}>
                  {(trace.final.quality_score * 100).toFixed(0)}%
                </span>
              </div>
              <div>
                <span style={{ color: "#666" }}>风险: </span>
                <span
                  style={{
                    color: trace.final.risk_score > 0.5 ? "#ff3b30" : "#f59e0b",
                    fontWeight: 600,
                  }}
                >
                  {(trace.final.risk_score * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {expanded && !trace && (isLoading || isStreamingActive) && (
        <div style={{ padding: "12px", borderTop: "1px solid #1a1a1a", fontSize: 11 }}>
          {streamProgress && streamProgress.planSteps.length > 0 ? (
            <div>
              <div style={{ color: "#888", marginBottom: 8, fontWeight: 600 }}>执行进度</div>
              <ANodeList nodes={streamANodes as any} />
              {streamProgress.currentSkill && (
                <div style={{ marginTop: 8, padding: "6px 8px", backgroundColor: "#0d1525", borderRadius: 6, color: "#3b82f6", fontSize: 11 }}>
                  ⚙️ 正在执行: {streamProgress.currentSkill}
                </div>
              )}
            </div>
          ) : (
            <div style={{ color: "#666", textAlign: "center" }}>
              正在初始化思考链...
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── A 层节点列表（动态编排：按思维阶段分组；降级：平铺） ──

function ANodeList({ nodes }: { nodes: import("@/types").OrchestrationNode[] }) {
  // 是否为动态编排模式（节点带 stage 字段）
  const hasStages = nodes.some((n) => n.stage);

  if (!hasStages) {
    // S 链降级路径：保持原有平铺展示
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {nodes.map((node) => (
          <NodeRowItem key={node.id} node={node} />
        ))}
      </div>
    );
  }

  // 动态编排模式：按思维阶段分组
  const stageOrder = ["research", "analysis", "design", "validate", "execute"];
  const grouped = new Map<string, typeof nodes>();
  for (const node of nodes) {
    const key = node.stage || "other";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(node);
  }

  // 按阶段顺序排列，未知阶段放最后
  const orderedStages = [
    ...stageOrder.filter((s) => grouped.has(s)),
    ...[...grouped.keys()].filter((s) => !stageOrder.includes(s)),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {orderedStages.map((stage) => {
        const stageNodes = grouped.get(stage) || [];
        const stageNode = stageNodes.find((n) => !n.is_skill);
        const skillNodes = stageNodes.filter((n) => n.is_skill);
        const stageIcon = stageNode?.icon || STAGE_ICONS[stage] || "⚙️";
        const stageLabel = stageNode?.name || STAGE_LABELS[stage] || stage;
        const stageStatus = stageNode?.status || "done";

        return (
          <div key={stage}>
            {/* 阶段头 */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 8px",
                borderRadius: 6,
                backgroundColor: stageStatus === "done" ? "#0d1f15" : stageStatus === "active" ? "#0d1525" : "transparent",
              }}
            >
              <span style={{ fontSize: 13 }}>
                {stageStatus === "done" ? "✓" : stageStatus === "active" ? "▶" : "○"}
              </span>
              <span style={{ fontSize: 12 }}>{stageIcon}</span>
              <span style={{ fontSize: 12, color: "#ccc", fontWeight: 600, flex: 1 }}>{stageLabel}</span>
              {stageNode?.confidence !== undefined && (
                <span style={{ fontSize: 10, color: "#00c853" }}>
                  {(stageNode.confidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
            {/* 技能子节点 */}
            {skillNodes.length > 0 && (
              <div style={{ marginLeft: 24, marginTop: 2, display: "flex", flexDirection: "column", gap: 2 }}>
                {skillNodes.map((node) => (
                  <NodeRowItem key={node.id} node={node} compact />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── 单个节点行（可紧凑模式） ──

function NodeRowItem({
  node,
  compact = false,
}: {
  node: import("@/types").OrchestrationNode;
  compact?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: compact ? "2px 8px" : "4px 8px",
        borderRadius: 6,
        backgroundColor: node.status === "done" ? "#0d1f15" : node.status === "active" ? "#0d1525" : "transparent",
      }}
    >
      <span style={{ fontSize: compact ? 11 : 13 }}>
        {node.status === "done" ? "✓" : node.status === "active" ? "▶" : "○"}
      </span>
      <span style={{ fontSize: compact ? 11 : 12 }}>{resolveNodeIcon(node)}</span>
      <span style={{ fontSize: compact ? 11 : 12, color: "#aaa", flex: 1 }}>{node.name}</span>
      {node.confidence !== undefined && (
        <span style={{ fontSize: 10, color: "#00c853" }}>
          {(node.confidence * 100).toFixed(0)}%
        </span>
      )}
      {node.tokens_used !== undefined && node.tokens_used > 0 && (
        <span style={{ fontSize: 9, color: "#666" }}>{node.tokens_used.toLocaleString()}t</span>
      )}
    </div>
  );
}
