// ============================================================
// Notebook Store — zustand + localStorage 持久化
// 版本: v1.0 | 日期: 2026-06-15
// 职责: 管理笔记本系统的内存状态 + 跨 session 持久化
// ============================================================

import { create } from "zustand";
import {
  STEP_DEFINITIONS,
  type NotebookState,
  type NotebookTask,
  type NotebookStep,
  type TaskPhase,
  type StepId,
  type DZEChainState,
  type StepAction,
} from "@/lib/notebook/types";

const STORAGE_KEY = "dream_ug_notebook_state_v1";
const EMPTY_STATE: NotebookState = {
  version: "1.0",
  currentTaskId: null,
  tasks: [],
  lastSyncAt: "",
  totalTasks: 0,
  completedCount: 0,
};

// ---------- 工具函数 ----------

function nowISO(): string {
  return new Date().toISOString();
}

function createTask(title: string, userInput: string, intent: string, sessionId: string, entities: Record<string, string>, routing: { chain: string[]; thinkingMode: "quick" | "deep" } | null): NotebookTask {
  const steps: NotebookStep[] = STEP_DEFINITIONS.map((def, idx) => ({
    id: def.id,
    number: def.number,
    name: def.name,
    icon: def.icon,
    status: idx === 0 ? ("active" as const) : ("pending" as const),
    output: "",
    artifacts: [],
    notes: "",
  }));

  // Step 1 自动完成基础需求解析
  steps[0].status = "done";
  steps[0].output = `用户请求: **${title}**\n\n原始输入: ${userInput}\n\n意图识别: ${intent}\n实体: ${JSON.stringify(entities)}`;
  steps[0].completedAt = nowISO();
  steps[0].startedAt = nowISO();

  // Step 2 激活
  steps[1].status = "active";
  steps[1].startedAt = nowISO();

  return {
    id: `task_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    sessionId,
    title,
    intent,
    userInput,
    phase: "active" as TaskPhase,
    startedAt: nowISO(),
    lastActiveAt: nowISO(),
    steps,
    dzeChain: null,
    routing,
    entities,
    credits: { estimated: 20, used: 0 },
  };
}

function loadFromStorage(): NotebookState {
  if (typeof window === "undefined") return EMPTY_STATE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_STATE;
    const parsed = JSON.parse(raw) as NotebookState;
    // 版本兼容检查
    if (parsed.version !== "1.0") return EMPTY_STATE;
    return parsed;
  } catch {
    return EMPTY_STATE;
  }
}

function saveToStorage(state: NotebookState): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // 存储空间满或禁用, 忽略
  }
}

// ---------- Store 定义 ----------

interface NotebookStoreState extends NotebookState {
  // 操作
  init: () => void;
  startTask: (input: {
    title: string;
    userInput: string;
    intent: string;
    sessionId: string;
    entities: Record<string, string>;
    routing: { chain: string[]; thinkingMode: "quick" | "deep" } | null;
  }) => NotebookTask;

  getCurrentTask: () => NotebookTask | null;
  getTaskById: (id: string) => NotebookTask | null;

  updateStep: (taskId: string, stepId: StepId, updates: Partial<NotebookStep>) => void;
  setStepOutput: (taskId: string, stepId: StepId, output: string) => void;
  completeStep: (taskId: string, stepId: StepId, output: string, artifacts?: string[]) => void;
  activateNextStep: (taskId: string) => StepId | null;

  updateDZEChain: (taskId: string, chain: DZEChainState) => void;

  applyStepAction: (taskId: string, action: StepAction, targetStep?: number, reason?: string) => void;

  setTaskPhase: (taskId: string, phase: TaskPhase) => void;
  completeTask: (taskId: string) => void;

  syncFromServer: (serverState: NotebookState) => void;
  clear: () => void;
}

export const useNotebookStore = create<NotebookStoreState>((set, get) => ({
  // 默认值 (会被 init 覆盖)
  ...EMPTY_STATE,

  init: () => {
    const loaded = loadFromStorage();
    set({
      ...loaded,
      totalTasks: loaded.tasks.length,
      completedCount: loaded.tasks.filter((t) => t.phase === "done").length,
      lastSyncAt: loaded.lastSyncAt || get().lastSyncAt,
    });
  },

  startTask: ({ title, userInput, intent, sessionId, entities, routing }) => {
    const task = createTask(title, userInput, intent, sessionId, entities, routing);
    const state = get();
    const newTasks = [task, ...state.tasks].slice(0, 50); // 保留最近 50 个任务
    const newState: NotebookState = {
      ...state,
      currentTaskId: task.id,
      tasks: newTasks,
      totalTasks: newTasks.length,
      lastSyncAt: nowISO(),
    };
    saveToStorage(newState);
    set(newState);
    return task;
  },

  getCurrentTask: () => {
    const { currentTaskId, tasks } = get();
    if (!currentTaskId) return null;
    return tasks.find((t) => t.id === currentTaskId) || null;
  },

  getTaskById: (id) => {
    return get().tasks.find((t) => t.id === id) || null;
  },

  updateStep: (taskId, stepId, updates) => {
    const state = get();
    const tasks = state.tasks.map((t) => {
      if (t.id !== taskId) return t;
      const steps = t.steps.map((s) =>
        s.id === stepId ? { ...s, ...updates } : s
      );
      return { ...t, steps, lastActiveAt: nowISO() };
    });
    const newState = { ...state, tasks, lastSyncAt: nowISO() };
    saveToStorage(newState);
    set(newState);
  },

  setStepOutput: (taskId, stepId, output) => {
    get().updateStep(taskId, stepId, { output });
  },

  completeStep: (taskId, stepId, output, artifacts) => {
    get().updateStep(taskId, stepId, {
      output,
      artifacts: artifacts ?? [],
      status: "done",
      completedAt: nowISO(),
    });
  },

  activateNextStep: (taskId) => {
    const state = get();
    const task = state.tasks.find((t) => t.id === taskId);
    if (!task) return null;

    // 找到第一个 pending 步骤
    const nextPending = task.steps.find((s) => s.status === "pending");
    if (!nextPending) return null;

    // 标记为 active, 并设置 startedAt
    const newSteps = task.steps.map((s) => {
      if (s.id === nextPending.id) {
        return { ...s, status: "active" as const, startedAt: nowISO() };
      }
      return s;
    });

    const tasks = state.tasks.map((t) =>
      t.id === taskId ? { ...t, steps: newSteps, lastActiveAt: nowISO() } : t
    );
    const newState = { ...state, tasks, lastSyncAt: nowISO() };
    saveToStorage(newState);
    set(newState);
    return nextPending.id;
  },

  updateDZEChain: (taskId, chain) => {
    const state = get();
    const tasks = state.tasks.map((t) =>
      t.id === taskId ? { ...t, dzeChain: chain, lastActiveAt: nowISO() } : t
    );
    const newState = { ...state, tasks, lastSyncAt: nowISO() };
    saveToStorage(newState);
    set(newState);
  },

  applyStepAction: (taskId, action, targetStep, reason) => {
    const state = get();
    const task = state.tasks.find((t) => t.id === taskId);
    if (!task) return;

    const activeStep = task.steps.find((s) => s.status === "active");
    if (!activeStep && action !== "finalize") return;

    let newSteps = [...task.steps];

    switch (action) {
      case "continue": {
        // 完成当前步 + 激活下一个
        newSteps = newSteps.map((s) => {
          if (s.id === activeStep?.id) {
            return { ...s, status: "done" as const, completedAt: nowISO(), output: s.output || "已完成" };
          }
          return s;
        });
        // 找第一个 pending
        const nextIdx = newSteps.findIndex((s) => s.status === "pending");
        if (nextIdx >= 0) {
          newSteps[nextIdx] = { ...newSteps[nextIdx], status: "active" as const, startedAt: nowISO() };
        }
        break;
      }
      case "skip": {
        // 标记 skipped, 激活下一个
        newSteps = newSteps.map((s) => {
          if (s.id === activeStep?.id) {
            return { ...s, status: "skipped" as const, skippedReason: reason || "跳过", completedAt: nowISO() };
          }
          return s;
        });
        const nextIdx = newSteps.findIndex((s) => s.status === "pending");
        if (nextIdx >= 0) {
          newSteps[nextIdx] = { ...newSteps[nextIdx], status: "active" as const, startedAt: nowISO() };
        }
        break;
      }
      case "jump": {
        if (!targetStep) break;
        // 标记当前 active 为 skipped, 中间步骤都 skipped, 目标步骤 active
        const targetNum = targetStep;
        newSteps = newSteps.map((s) => {
          if (s.number === targetNum) {
            return { ...s, status: "active" as const, startedAt: nowISO() };
          }
          if (s.status === "pending" && s.number < targetNum) {
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
        // 所有 pending 标记 done (简化版), 当前任务结束
        newSteps = newSteps.map((s) =>
          s.status === "pending" || s.status === "active"
            ? { ...s, status: "done" as const, completedAt: nowISO(), output: s.output || "快速完成" }
            : s
        );
        break;
      }
      case "pause": {
        // 当前 activestep 保持 pending, 以便下次恢复
        newSteps = newSteps.map((s) =>
          s.status === "active" ? { ...s, status: "pending" as const, notes: reason || "暂停中" } : s
        );
        break;
      }
    }

    const tasks = state.tasks.map((t) =>
      t.id === taskId
        ? {
            ...t,
            steps: newSteps,
            phase: newSteps.every((s) => s.status !== "pending" && s.status !== "active")
              ? ("done" as TaskPhase)
              : ("active" as TaskPhase),
            lastActiveAt: nowISO(),
            completedAt: newSteps.every((s) => s.status !== "pending" && s.status !== "active") ? nowISO() : undefined,
          }
        : t
    );

    const newState: NotebookState = {
      ...state,
      tasks,
      lastSyncAt: nowISO(),
      completedCount: tasks.filter((t) => t.phase === "done").length,
    };
    saveToStorage(newState);
    set(newState);
  },

  setTaskPhase: (taskId, phase) => {
    const state = get();
    const tasks = state.tasks.map((t) =>
      t.id === taskId ? { ...t, phase, lastActiveAt: nowISO(), completedAt: phase === "done" ? nowISO() : t.completedAt } : t
    );
    const newState: NotebookState = {
      ...state,
      tasks,
      lastSyncAt: nowISO(),
      completedCount: tasks.filter((t) => t.phase === "done").length,
    };
    saveToStorage(newState);
    set(newState);
  },

  completeTask: (taskId) => {
    get().setTaskPhase(taskId, "done");
  },

  syncFromServer: (serverState) => {
    // 从 API 同步到本地 — 优先采用服务器状态
    saveToStorage(serverState);
    set({
      ...serverState,
      totalTasks: serverState.tasks.length,
      completedCount: serverState.tasks.filter((t) => t.phase === "done").length,
    });
  },

  clear: () => {
    saveToStorage(EMPTY_STATE);
    set({ ...EMPTY_STATE });
  },
}));

// 初始化 — 模块加载时读取本地存储
if (typeof window !== "undefined") {
  useNotebookStore.getState().init();
}
