// ============================================================
// Notebook System — 核心类型定义
// 版本: v1.0 | 日期: 2026-06-15
// 职责: 笔记本系统的步进状态机 + 任务生命周期管理
// ============================================================

import type { IntentType } from "@/types";

/** 单个步骤的状态 */
export type StepStatus = "pending" | "active" | "done" | "skipped";

/** 7步定义 — 对应笔记本架构 Step1-Step7 */
export const STEP_DEFINITIONS = [
  { number: 1 as const, id: "S1_REQUIREMENT", name: "需求解析", icon: "🎯", system: "笔记本" },
  { number: 2 as const, id: "S2_CHAIN", name: "思维链调研", icon: "🔗", system: "思维链+chain_guard" },
  { number: 3 as const, id: "S3_KNOWLEDGE", name: "知识库检索", icon: "📚", system: "知识库" },
  { number: 4 as const, id: "S4_METHODOLOGY", name: "方法论借鉴", icon: "🧠", system: "A系列skill" },
  { number: 5 as const, id: "S5_INDEX", name: "索引更新", icon: "🔍", system: "索引" },
  { number: 6 as const, id: "S6_COLLAB", name: "协作归档", icon: "✈️", system: "飞书" },
  { number: 7 as const, id: "S7_DISTILL", name: "记忆蒸馏", icon: "🧪", system: "记忆系统" },
] as const;

export type StepId = typeof STEP_DEFINITIONS[number]["id"];

/** 单步详细记录 */
export interface NotebookStep {
  id: StepId;
  number: 1 | 2 | 3 | 4 | 5 | 6 | 7;
  name: string;
  icon: string;
  status: StepStatus;
  output: string;           // 每步产出的内容 (Markdown)
  artifacts: string[];      // 产物路径列表
  notes: string;            // 用户备注 / 修改说明
  startedAt?: string;
  completedAt?: string;
  skippedReason?: string;   // 跳过原因 (需要用户授权)
}

/** D-Z-E 链状态 — 从 chain_guard.py 的数据模型对齐 */
export interface DZEPhase {
  id: string;               // d1 / d2 / d3 / d4 / z1 / z2 / z3 / z4 / e1 / e2 / e3
  name: string;
  status: "pending" | "active" | "done" | "skipped";
  output: string;
  methodology: string;      // 四准则调研法 / 三问分析框架 ...
  startedAt?: string;
  completedAt?: string;
}

export interface DZEChainState {
  scope: string;            // 任务范围描述
  currentPhase: string | null;  // 当前激活阶段
  phases: DZEPhase[];       // 所有阶段记录
  relayHistory: Array<{     // 阶段切换历史
    from: string | null;
    to: string;
    at: string;
    type: "transition" | "override" | "approve";
    reason?: string;
  }>;
  createdAt: string;
  modifiedAt: string;
}

/** 任务阶段 */
export type TaskPhase = "todo" | "active" | "done" | "archive";

/** 单个笔记本任务 */
export interface NotebookTask {
  id: string;
  sessionId: string;
  title: string;            // 用户输入的任务标题
  intent: IntentType | string;  // 关联的意图识别结果
  userInput: string;        // 用户原始请求
  phase: TaskPhase;
  startedAt: string;
  lastActiveAt: string;
  completedAt?: string;
  steps: NotebookStep[];    // 7步
  dzeChain: DZEChainState | null;  // Step2 的链状态
  routing: {                // 智能路由快照
    chain: string[];
    thinkingMode: "quick" | "deep";
  } | null;
  entities: Record<string, string>;  // BTC / ETH / XAU 等
  credits: {
    estimated: number;
    used: number;
  };
}

/** 笔记本全局状态 */
export interface NotebookState {
  version: "1.0";
  currentTaskId: string | null;
  tasks: NotebookTask[];
  lastSyncAt: string;
  totalTasks: number;
  completedCount: number;
}

/** 动作类型 (Step 决策菜单) */
export type StepAction =
  | "continue"    // 继续 Step N+1
  | "skip"        // 跳过当前步
  | "jump"        // 跳到指定步 (带 targetStep 参数)
  | "finalize"    // 直接执行全部未完成
  | "pause";      // 暂停 / 修改

export interface StepActionRequest {
  action: StepAction;
  taskId: string;
  stepId?: StepId;
  targetStep?: number;   // 用于 jump
  reason?: string;
}
