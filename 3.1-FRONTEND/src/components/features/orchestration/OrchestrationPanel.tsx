"use client";

import { useState } from "react";
import type { ChainTrace, ChainTraceNode } from "@/stores/chain-store";

// ============================================================
// 三层架构可视化面板
// B层(Blueprint) → A层(Arrange) → C层(Chronicle)
// ============================================================

const LAYER_COLORS = {
  B: "#6366f1",
  A: "#f59e0b",
  C: "#0ea5e9",
};

interface StatusStyle {
  bg: string;
  border: string;
  text: string;
  icon: string;
}

const STATUS_STYLES: Record<string, StatusStyle> = {
  pending:  { bg: "bg-slate-900",   border: "border-slate-700", text: "text-slate-500", icon: "⬜" },
  active:   { bg: "bg-blue-500/15", border: "border-blue-500",  text: "text-white",     icon: "▶" },
  done:     { bg: "bg-green-500/15",border: "border-green-600", text: "text-green-400", icon: "✓" },
  skipped:  { bg: "bg-slate-700/20",border: "border-slate-600", text: "text-slate-400", icon: "⏭" },
  failed:   { bg: "bg-red-500/15",  border: "border-red-500",   text: "text-red-400",   icon: "✗" },
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

interface PlannedStep {
  stage: string;
  chain: string;
  selected_skills: string[];
}

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
      <div className="p-5 text-center">
        <div className="w-16 h-16 mx-auto mb-3 rounded-2xl bg-slate-900 flex items-center justify-center text-3xl">
          🔀
        </div>
        <div className="text-sm font-semibold text-slate-300 mb-1">
          编排追踪面板
        </div>
        <div className="text-xs text-slate-600 mb-3">
          发送一条消息开始追踪
        </div>
        <div className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg text-[10px] text-slate-600 text-left leading-relaxed">
          <div className="text-indigo-400 font-semibold mb-1">🔵 B层 · 意图蓝图</div>
          <div className="text-amber-400 font-semibold mb-1">🟠 A层 · 编排计划</div>
          <div className="text-sky-400 font-semibold">🔵 C层 · 执行记录</div>
        </div>
        <div className="text-[10px] text-slate-700 mt-2.5">
          试试输入「分析BTC」
        </div>
      </div>
    );
  }

  const bNodes = trace.nodes.filter((n) => n.layer === "B");
  const aNodes = trace.nodes.filter((n) => n.layer === "A");
  const cNodes = trace.nodes.filter((n) => n.layer === "C");
  const totalTokens = trace.cost_report?.total_tokens ?? 0;
  const budgetTokens = trace.plan?.total_budget || trace.cost_report?.budget_tokens || 0;
  const tokenPct = budgetTokens > 0 ? Math.min(100, (totalTokens / budgetTokens) * 100) : 0;

  // 是否为动态编排模式（A 层节点带 stage 字段）
  const isDynamicOrchestration = aNodes.some((n) => n.stage);

  const plannedSteps = trace.plan?.planned_steps as PlannedStep[] | undefined;

  return (
    <div className="flex flex-col gap-3">
      {/* ── 任务概览 ── */}
      <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg">
        <div className="text-xs font-bold text-slate-300 mb-2">
          🎯 任务概览
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <InfoItem label="意图" value={trace.intent?.type ?? "-"} valueColor="text-blue-400" />
          <InfoItem label="置信度" value={`${((trace.intent?.confidence ?? 0) * 100).toFixed(0)}%`} valueColor="text-green-400" />
          <InfoItem label="识别方法" value={trace.intent?.method ?? "-"} />
          <InfoItem label="链路" value={trace.plan?.chain_name || trace.plan?.chain_id || "-"} />
          <InfoItem label="复杂度" value={trace.plan?.complexity ?? "-"} />
          <InfoItem label="编排理由" value={trace.plan?.rationale ?? "-"} span={2} />
        </div>
      </div>

      {/* ── Token 预算条 ── */}
      {budgetTokens > 0 && (
        <div className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg">
          <div className="flex justify-between text-[11px] mb-1.5">
            <span className="text-slate-500">💰 Token 预算</span>
            <span className={tokenPct > 80 ? "text-red-400" : "text-green-400"}>
              {totalTokens.toLocaleString()} / {budgetTokens.toLocaleString()}
            </span>
          </div>
          <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${tokenPct > 80 ? "bg-red-500" : "bg-blue-500"}`}
              style={{ width: `${tokenPct}%` }}
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
              plannedSteps={plannedSteps}
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
      {trace.final?.execution_chain && (
        <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg">
          <div className="text-xs font-bold text-slate-300 mb-2">
            🧠 自省结果
          </div>
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <InfoItem label="执行链路" value={trace.final.execution_chain} />
            <InfoItem label="品质评级" value={trace.final.grade} valueColor="text-green-400" />
            <InfoItem
              label="质量评分"
              value={(trace.final.quality_score * 100).toFixed(0) + "%"}
              valueColor="text-green-400"
            />
            <InfoItem
              label="风险评分"
              value={(trace.final.risk_score * 100).toFixed(0) + "%"}
              valueColor={trace.final.risk_score > 0.5 ? "text-red-400" : "text-amber-400"}
            />
          </div>
        </div>
      )}

      {/* ── CostKeeper 报告 ── */}
      {trace.cost_report && (
        <div className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg text-[11px]">
          <div className="font-semibold text-slate-300 mb-1.5">📊 CostKeeper</div>
          <div className="text-slate-500">
            Prompt: {(trace.cost_report.prompt_tokens ?? 0).toLocaleString()} ·
            Completion: {(trace.cost_report.completion_tokens ?? 0).toLocaleString()}
          </div>
          {(trace.cost_report.skipped_steps?.length ?? 0) > 0 && (
            <div className="text-amber-400 mt-1">
              ⏭ 跳过: {(trace.cost_report.skipped_steps ?? []).join(", ")}
            </div>
          )}
        </div>
      )}

      {/* ── 压缩报告 ── */}
      {trace.compression && (
        <div className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg text-[11px]">
          <div className="font-semibold text-slate-300 mb-1.5">🗜️ 上下文压缩</div>
          <div className="text-slate-500">
            {(trace.compression.original_tokens ?? 0).toLocaleString()} →{" "}
            {(trace.compression.compressed_tokens ?? 0).toLocaleString()} tokens
          </div>
          <div className="text-green-400 mt-0.5">
            压缩率: {((trace.compression.ratio ?? 0) * 100).toFixed(0)}%
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
      className="p-3 bg-slate-950 rounded-lg"
      style={{ border: `1px solid ${color}33` }}
    >
      <div className="mb-1.5">
        <div className="text-xs font-bold" style={{ color }}>
          <span className="mr-1.5">●</span>
          {title}
        </div>
        <div className="text-[10px] text-slate-600 mt-0.5">{desc}</div>
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
  nodes: ChainTraceNode[];
  expandedNode: string | null;
  onToggle: (id: string | null) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {/* 节点横向流 */}
      <div className="flex items-center gap-0.5 flex-wrap">
        {nodes.map((node, idx) => {
          const style = STATUS_STYLES[node.status] || STATUS_STYLES.pending;
          const isExpanded = expandedNode === node.id;
          return (
            <div key={`${idx}-${node.id}`} className="flex items-center">
              <div
                onClick={() => onToggle(isExpanded ? null : node.id)}
                className={`w-14 h-14 rounded-lg ${style.bg} border-2 ${style.border} ${style.text} flex flex-col items-center justify-center cursor-pointer transition-all shrink-0`}
                title={node.name}
              >
                <span className="text-base">{node.icon || style.icon}</span>
                <span className="text-[9px] mt-0.5 text-center leading-tight">
                  {node.id.split("_")[0]}
                </span>
              </div>
              {idx < nodes.length - 1 && (
                <div
                  className={`w-3 h-0.5 transition-colors ${
                    nodes[idx + 1].status !== "pending" ? "bg-blue-500" : "bg-slate-800"
                  }`}
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
            className={`mt-1 p-2.5 bg-slate-900 rounded-md text-[11px]`}
            style={{ border: `1px solid ${style.border.replace("border-", "")}44` }}
          >
            <div className="flex justify-between mb-1.5">
              <span className="font-semibold text-slate-300">
                {node.icon} {node.name}
              </span>
              <span className={`font-semibold ${style.text}`}>
                {style.icon} {node.status}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-1 text-slate-500">
              {node.confidence !== undefined && (
                <div>置信度: <span className="text-green-400">{(node.confidence * 100).toFixed(0)}%</span></div>
              )}
              {node.risk !== undefined && (
                <div>风险: <span className={(node.risk?.score ?? 0) > 0.5 ? "text-red-400" : "text-amber-400"}>{((node.risk?.score ?? 0) * 100).toFixed(0)}%</span></div>
              )}
              {node.latency_ms !== undefined && node.latency_ms > 0 && (
                <div>延迟: <span className="text-slate-400">{node.latency_ms.toFixed(0)}ms</span></div>
              )}
              {node.tokens_used !== undefined && node.tokens_used > 0 && (
                <div>Token: <span className="text-slate-400">{node.tokens_used.toLocaleString()}</span></div>
              )}
              {node.tokens_budget !== undefined && (node.tokens_budget?.total ?? 0) > 0 && (
                <div>预算: <span className="text-slate-400">{node.tokens_budget.toLocaleString()}</span></div>
              )}
              {node.reflect_action && (
                <div>反射: <span className="text-blue-400">{node.reflect_action}</span></div>
              )}
              {node.skip_reason && (
                <div className="col-span-2 text-amber-400">
                  跳过原因: {node.skip_reason}
                </div>
              )}
              {node.artifact && (
                <div className="col-span-2 text-blue-400">
                  📎 {node.artifact.title}
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
  nodes: ChainTraceNode[];
  plannedSteps?: PlannedStep[];
  expandedNode: string | null;
  onToggle: (id: string | null) => void;
}) {
  const stageOrder = ["research", "analysis", "design", "validate", "execute"];
  const grouped = new Map<string, ChainTraceNode[]>();
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
    <div className="flex flex-col gap-2">
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
              className={`flex items-center gap-1.5 px-2 py-1.5 rounded-md ${stageStyle.bg}`}
              style={{ border: `1px solid ${stageStyle.border.replace("border-", "")}55` }}
            >
              <span className="text-base">{stageIcon}</span>
              <div className="flex-1 min-w-0">
                <div className={`text-[11px] font-bold ${stageStyle.text}`}>
                  {stageLabel}
                </div>
                {plannedStep && (
                  <div className="text-[9px] text-slate-600 mt-0.5">
                    {plannedStep.chain}链 · {plannedStep.selected_skills.length}个技能
                  </div>
                )}
              </div>
              {stageNode?.confidence !== undefined && (
                <span className="text-[10px] text-green-400 font-semibold">
                  {(stageNode.confidence * 100).toFixed(0)}%
                </span>
              )}
              {stageNode?.tokens_used !== undefined && stageNode.tokens_used > 0 && (
                <span className="text-[9px] text-slate-500">
                  {stageNode.tokens_used.toLocaleString()}t
                </span>
              )}
            </div>

            {/* 技能横向流 */}
            {skillNodes.length > 0 && (
              <div className="flex items-center gap-0.5 flex-wrap mt-1 ml-3">
                {skillNodes.map((node, idx) => {
                  const style = STATUS_STYLES[node.status] || STATUS_STYLES.pending;
                  const isExpanded = expandedNode === node.id;
                  const skillIcon = node.icon || getSkillIcon(node.id);
                  return (
                    <div key={`${idx}-${node.id}`} className="flex items-center">
                      <div
                        onClick={() => onToggle(isExpanded ? null : node.id)}
                        className={`w-11 h-11 rounded-md ${style.bg} border ${style.border} ${style.text} flex flex-col items-center justify-center cursor-pointer transition-all shrink-0`}
                        title={node.name}
                      >
                        <span className="text-[13px]">{skillIcon}</span>
                        <span className="text-[8px] mt-px text-center leading-tight max-w-10 overflow-hidden text-ellipsis whitespace-nowrap">
                          {node.name.slice(0, 6)}
                        </span>
                      </div>
                      {idx < skillNodes.length - 1 && (
                        <div
                          className={`w-2 h-0.5 ${
                            skillNodes[idx + 1].status !== "pending" ? "bg-blue-500" : "bg-slate-800"
                          }`}
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
                  className={`mt-1 ml-3 p-2 bg-slate-900 rounded-md text-[10px]`}
                  style={{ border: `1px solid ${style.border.replace("border-", "")}44` }}
                >
                  <div className="flex justify-between mb-1">
                    <span className="font-semibold text-slate-300">
                      {getSkillIcon(node.id)} {node.name}
                    </span>
                    <span className={`font-semibold ${style.text}`}>
                      {style.icon} {node.status}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-1 text-slate-500">
                    {node.confidence !== undefined && (
                      <div>置信度: <span className="text-green-400">{(node.confidence * 100).toFixed(0)}%</span></div>
                    )}
                    {node.latency_ms !== undefined && node.latency_ms > 0 && (
                      <div>延迟: <span className="text-slate-400">{node.latency_ms.toFixed(0)}ms</span></div>
                    )}
                    {node.tokens_used !== undefined && node.tokens_used > 0 && (
                      <div>Token: <span className="text-slate-400">{node.tokens_used.toLocaleString()}</span></div>
                    )}
                    {node.chain && (
                      <div>链路: <span className="text-amber-400">{node.chain}</span></div>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* 阶段间连接线 */}
            {stageIdx < orderedStages.length - 1 && (
              <div className="flex justify-center my-0.5">
                <div className="w-0.5 h-2 bg-blue-500/30" />
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
    <div className={span === 2 ? "col-span-2" : undefined}>
      <span className="text-slate-600">{label}: </span>
      <span className={`font-semibold ${valueColor || "text-slate-300"}`}>{value}</span>
    </div>
  );
}
