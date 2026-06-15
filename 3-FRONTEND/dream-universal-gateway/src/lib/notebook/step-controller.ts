// ============================================================
// Notebook Step Controller — 服务端版本
// 版本: v1.0 | 日期: 2026-06-15
// 职责: 纯函数式步进控制器 — 启动任务/查看进度/完成步骤
//   对应 Python 版本 step_controller.py 的 TS 重写
// 注意: 服务端专用 (Node.js fs), 不导入到前端组件
// ============================================================

import fs from "fs";
import path from "path";
import {
  STEP_DEFINITIONS,
  type NotebookState,
  type NotebookTask,
  type NotebookStep,
  type TaskPhase,
  type StepId,
  type DZEChainState,
  type StepAction,
} from "./types";

// ---------- 路径配置 ----------

export const PROJECT_ROOT = process.cwd();
export const NOTEBOOK_DIR = path.join(PROJECT_ROOT, ".next", "notebook");
export const STATE_FILE = path.join(NOTEBOOK_DIR, "notebook-state.json");
export const TODO_DIR = path.join(NOTEBOOK_DIR, "0-TODO");
export const ACTIVE_DIR = path.join(NOTEBOOK_DIR, "1-ACTIVE");
export const DONE_DIR = path.join(NOTEBOOK_DIR, "2-DONE");
export const ARCHIVE_DIR = path.join(NOTEBOOK_DIR, "3-ARCHIVE");

// 内存 fallback（当文件系统不可用时使用）
let memoryState: NotebookState | null = null;
let fsAvailable = true;

function nowISO(): string {
  return new Date().toISOString();
}

// ---------- 目录初始化 ----------

export function ensureDirectories(): void {
  if (!fsAvailable) return;
  try {
    for (const dir of [NOTEBOOK_DIR, TODO_DIR, ACTIVE_DIR, DONE_DIR, ARCHIVE_DIR]) {
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    }
  } catch {
    fsAvailable = false;
  }
}

// ---------- 默认状态 ----------

function emptyState(): NotebookState {
  return {
    version: "1.0",
    currentTaskId: null,
    tasks: [],
    lastSyncAt: "",
    totalTasks: 0,
    completedCount: 0,
  };
}

// ---------- 状态读写 ----------

export function loadState(): NotebookState {
  ensureDirectories();
  if (!fsAvailable) {
    return memoryState || emptyState();
  }
  if (!fs.existsSync(STATE_FILE)) {
    return emptyState();
  }
  try {
    const raw = fs.readFileSync(STATE_FILE, "utf-8");
    const parsed = JSON.parse(raw);
    if (parsed.version !== "1.0") {
      return emptyState();
    }
    return parsed as NotebookState;
  } catch {
    return memoryState || emptyState();
  }
}

export function saveState(state: NotebookState): void {
  ensureDirectories();
  state.lastSyncAt = nowISO();
  state.totalTasks = state.tasks.length;
  state.completedCount = state.tasks.filter((t) => t.phase === "done").length;
  if (fsAvailable) {
    try {
      fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), "utf-8");
      memoryState = state;
      return;
    } catch {
      fsAvailable = false;
    }
  }
  memoryState = state;
}

// ---------- 任务构建 ----------

function buildSteps(): NotebookStep[] {
  return STEP_DEFINITIONS.map((def, idx) => ({
    id: def.id,
    number: def.number,
    name: def.name,
    icon: def.icon,
    status: idx === 0 ? ("active" as const) : ("pending" as const),
    output: "",
    artifacts: [],
    notes: "",
  }));
}

export function createTask(
  title: string,
  userInput: string,
  intent: string,
  sessionId: string,
  entities: Record<string, string> = {},
  routing: { chain: string[]; thinkingMode: "quick" | "deep" } | null = null
): NotebookTask {
  const steps = buildSteps();
  // Step 1 自动完成需求解析
  steps[0] = {
    ...steps[0],
    status: "done",
    output: `用户请求: **${title}**\n\n原始输入: ${userInput}\n\n意图识别: ${intent}\n实体: ${JSON.stringify(entities)}`,
    completedAt: nowISO(),
    startedAt: nowISO(),
  };
  // Step 2 激活
  steps[1] = {
    ...steps[1],
    status: "active",
    startedAt: nowISO(),
  };

  return {
    id: `task_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    sessionId,
    title,
    intent,
    userInput,
    phase: "active",
    startedAt: nowISO(),
    lastActiveAt: nowISO(),
    steps,
    dzeChain: null,
    routing,
    entities,
    credits: { estimated: 20, used: 0 },
  };
}

// ---------- 任务操作 ----------

export function startTask(params: {
  title: string;
  userInput: string;
  intent: string;
  sessionId: string;
  entities: Record<string, string>;
  routing: { chain: string[]; thinkingMode: "quick" | "deep" } | null;
}): { state: NotebookState; task: NotebookTask } {
  const state = loadState();
  const task = createTask(params.title, params.userInput, params.intent, params.sessionId, params.entities, params.routing);
  state.tasks = [task, ...state.tasks].slice(0, 100);
  state.currentTaskId = task.id;
  saveState(state);
  return { state, task };
}

export function getTaskById(taskId: string): NotebookTask | null {
  const state = loadState();
  return state.tasks.find((t) => t.id === taskId) || null;
}

export function getCurrentTask(): NotebookTask | null {
  const state = loadState();
  if (!state.currentTaskId) return null;
  return state.tasks.find((t) => t.id === state.currentTaskId) || null;
}

export function updateStep(taskId: string, stepId: StepId, updates: Partial<NotebookStep>): NotebookState {
  const state = loadState();
  state.tasks = state.tasks.map((t) => {
    if (t.id !== taskId) return t;
    const steps = t.steps.map((s) => (s.id === stepId ? { ...s, ...updates } : s));
    return { ...t, steps, lastActiveAt: nowISO() };
  });
  saveState(state);
  return state;
}

export function completeStep(taskId: string, stepId: StepId, output: string, artifacts: string[] = []): NotebookState {
  return updateStep(taskId, stepId, {
    output,
    artifacts,
    status: "done",
    completedAt: nowISO(),
  });
}

export function skipStep(taskId: string, stepId: StepId, reason: string = "跳过"): NotebookState {
  return updateStep(taskId, stepId, {
    status: "skipped",
    skippedReason: reason,
    completedAt: nowISO(),
  });
}

export function activateNextStep(taskId: string): { state: NotebookState; nextStepId: StepId | null } {
  const state = loadState();
  const task = state.tasks.find((t) => t.id === taskId);
  if (!task) return { state, nextStepId: null };

  const next = task.steps.find((s) => s.status === "pending");
  if (!next) return { state, nextStepId: null };

  state.tasks = state.tasks.map((t) => {
    if (t.id !== taskId) return t;
    return {
      ...t,
      lastActiveAt: nowISO(),
      steps: t.steps.map((s) => (s.id === next.id ? { ...s, status: "active" as const, startedAt: nowISO() } : s)),
    };
  });
  saveState(state);
  return { state, nextStepId: next.id };
}

export function applyAction(
  taskId: string,
  action: StepAction,
  targetStep?: number,
  reason?: string
): NotebookState {
  const state = loadState();
  const task = state.tasks.find((t) => t.id === taskId);
  if (!task) return state;

  const activeStep = task.steps.find((s) => s.status === "active");
  if (!activeStep && action !== "finalize") return state;

  let newSteps = [...task.steps];

  switch (action) {
    case "continue": {
      newSteps = newSteps.map((s) =>
        s.id === activeStep?.id
          ? { ...s, status: "done" as const, completedAt: nowISO(), output: s.output || "已完成" }
          : s
      );
      const nextIdx = newSteps.findIndex((s) => s.status === "pending");
      if (nextIdx >= 0) {
        newSteps[nextIdx] = { ...newSteps[nextIdx], status: "active" as const, startedAt: nowISO() };
      }
      break;
    }
    case "skip": {
      newSteps = newSteps.map((s) =>
        s.id === activeStep?.id
          ? { ...s, status: "skipped" as const, skippedReason: reason || "跳过", completedAt: nowISO() }
          : s
      );
      const nextIdx = newSteps.findIndex((s) => s.status === "pending");
      if (nextIdx >= 0) {
        newSteps[nextIdx] = { ...newSteps[nextIdx], status: "active" as const, startedAt: nowISO() };
      }
      break;
    }
    case "jump": {
      if (!targetStep) break;
      newSteps = newSteps.map((s) => {
        if (s.number === targetStep) {
          return { ...s, status: "active" as const, startedAt: nowISO() };
        }
        if (s.status === "pending" && s.number < targetStep) {
          return { ...s, status: "skipped" as const, skippedReason: "快速跳过", completedAt: nowISO() };
        }
        if (s.status === "active") {
          return { ...s, status: "skipped" as const, skippedReason: "跳步", completedAt: nowISO() };
        }
        return s;
      });
      break;
    }
    case "finalize": {
      newSteps = newSteps.map((s) =>
        s.status === "pending" || s.status === "active"
          ? { ...s, status: "done" as const, completedAt: nowISO(), output: s.output || "快速完成" }
          : s
      );
      break;
    }
    case "pause": {
      newSteps = newSteps.map((s) =>
        s.status === "active" ? { ...s, status: "pending" as const, notes: reason || "暂停中" } : s
      );
      break;
    }
  }

  const allCompleted = newSteps.every((s) => s.status !== "pending" && s.status !== "active");

  state.tasks = state.tasks.map((t) =>
    t.id === taskId
      ? {
          ...t,
          steps: newSteps,
          phase: allCompleted ? ("done" as TaskPhase) : ("active" as TaskPhase),
          lastActiveAt: nowISO(),
          completedAt: allCompleted ? nowISO() : t.completedAt,
        }
      : t
  );
  saveState(state);
  return state;
}

export function setTaskPhase(taskId: string, phase: TaskPhase): NotebookState {
  const state = loadState();
  state.tasks = state.tasks.map((t) =>
    t.id === taskId
      ? {
          ...t,
          phase,
          lastActiveAt: nowISO(),
          completedAt: phase === "done" ? nowISO() : t.completedAt,
        }
      : t
  );
  saveState(state);
  return state;
}

export function setCurrentTask(taskId: string | null): NotebookState {
  const state = loadState();
  state.currentTaskId = taskId;
  saveState(state);
  return state;
}

// ---------- D-Z-E 链 ----------

export function initDZEChain(taskId: string, scope: string): DZEChainState {
  const phaseNames: Record<string, string> = {
    d1: "D1 深度调研",
    d2: "D2 分析诊断",
    d3: "D3 推演验证",
    d4: "D4 规格合成",
    z1: "Z1 参数扫描",
    z2: "Z2 范围界定",
    z3: "Z3 路径设计",
    z4: "Z4 验收方案",
    e1: "E1 任务执行",
    e2: "E2 测试验证",
    e3: "E3 部署交付",
  };
  const methodologies: Record<string, string> = {
    d1: "四准则调研法",
    d2: "三问分析框架",
    d3: "情景推演矩阵",
    d4: "四段规格法",
    z1: "参数扫描与回测",
    z2: "拓扑切割+回滚点设计",
    z3: "完整实施路径",
    z4: "四层验收策略",
    e1: "任务驱动逐任务执行",
    e2: "测试验证",
    e3: "部署交付",
  };

  const phases = Object.keys(phaseNames).map((id) => ({
    id,
    name: phaseNames[id],
    status: id === "d1" ? ("active" as const) : ("pending" as const),
    output: "",
    methodology: methodologies[id],
    startedAt: id === "d1" ? nowISO() : undefined,
  }));

  const chain: DZEChainState = {
    scope,
    currentPhase: "d1",
    phases,
    relayHistory: [{ from: null, to: "d1", at: nowISO(), type: "transition" as const }],
    createdAt: nowISO(),
    modifiedAt: nowISO(),
  };

  const state = loadState();
  state.tasks = state.tasks.map((t) => (t.id === taskId ? { ...t, dzeChain: chain, lastActiveAt: nowISO() } : t));
  saveState(state);
  return chain;
}

// ---------- 统计 ----------

export function getStats(): {
  total: number;
  active: number;
  done: number;
  archived: number;
  today: number;
} {
  const state = loadState();
  const today = new Date().toISOString().slice(0, 10);
  return {
    total: state.tasks.length,
    active: state.tasks.filter((t) => t.phase === "active").length,
    done: state.tasks.filter((t) => t.phase === "done").length,
    archived: state.tasks.filter((t) => t.phase === "archive").length,
    today: state.tasks.filter((t) => t.startedAt.startsWith(today)).length,
  };
}
