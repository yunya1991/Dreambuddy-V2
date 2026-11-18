/**
 * 调度轨迹（Run Trace）——服务端打点与前端时间线共用的类型。
 *
 * O0 目标：把一次对话的 S→C→A→G 调度过程变成可观测事件，
 * 与 reasoning 一样通过 UIMessage 的 data-trace part 透传。
 */

export type TraceStage =
  | "S1" // 意图识别
  | "S2" // 上下文/工具准备
  | "C1" // 能力发现/规划
  | "C2" // 能力/子代理调用
  | "C3" // 聚合裁决
  | "A1" // 验收/门禁
  | "G1" // 汇总输出
  | "L1" // L1 确定性直答
  | "L2"; // L2 模型推理

export type TraceStatus = "running" | "done" | "failed" | "degraded" | "skipped";

export interface TraceSpan {
  span_id: string;
  trace_id: string;
  stage: TraceStage;
  label: string;
  role?: string;
  capability_id?: string;
  status: TraceStatus;
  /** epoch ms */
  started_at: number;
  duration_ms?: number;
  summary?: string;
  degraded?: boolean;
  seq: number;
}

export const TRACE_STAGE_LABEL: Record<TraceStage, string> = {
  S1: "意图识别",
  S2: "上下文准备",
  C1: "能力发现",
  C2: "能力调用",
  C3: "聚合裁决",
  A1: "验收门禁",
  G1: "汇总输出",
  L1: "L1 直答",
  L2: "L2 推理",
};

export const TRACE_STAGE_ORDER: TraceStage[] = [
  "S1",
  "S2",
  "C1",
  "C2",
  "C3",
  "A1",
  "G1",
  "L1",
  "L2",
];
