import { create } from "zustand";

// 4步配置队列（不含大模型配置）
const CONFIG_STEPS = [
  { key: "api", label: "API配置", icon: "⚙️", panel: "api" },
  { key: "trading", label: "交易设置", icon: "💰", panel: "trading" },
  { key: "strategy", label: "策略设置", icon: "🎯", panel: "strategy" },
  { key: "channels", label: "通信渠道", icon: "📡", panel: "communication" },
] as const;

export type StepKey = (typeof CONFIG_STEPS)[number]["key"];
export type AutoConfigPhase =
  | "idle"
  | "asking"
  | "inputting"
  | "exit_confirm"
  | "completed";

export interface AutoConfigResult {
  step: number;
  key: StepKey;
  status: "configured" | "skipped" | "error";
  data?: Record<string, unknown>;
  error?: string;
}

interface AutoConfigState {
  phase: AutoConfigPhase;
  currentStep: number;
  skipCount: number;
  results: AutoConfigResult[];
  isActive: boolean;

  start: () => void;
  handleYes: () => void;
  handleNo: () => void;
  handleSubmit: (data: Record<string, unknown>) => void;
  handleExitYes: () => void;
  handleExitNo: () => void;
  reset: () => void;
}

export const CONFIG_STEPS_LIST = CONFIG_STEPS;

export const useAutoConfigStore = create<AutoConfigState>((set, get) => ({
  phase: "idle",
  currentStep: 0,
  skipCount: 0,
  results: [],
  isActive: false,

  start: () =>
    set({
      phase: "asking",
      currentStep: 0,
      skipCount: 0,
      results: [],
      isActive: true,
    }),

  handleYes: () =>
    set({ phase: "inputting", skipCount: 0 }),

  handleNo: () => {
    const { currentStep, skipCount } = get();
    const newSkipCount = skipCount + 1;

    if (newSkipCount >= 2) {
      set({ phase: "exit_confirm", skipCount: newSkipCount });
    } else {
      // 标记当前步骤为 skipped，进入下一步
      const result: AutoConfigResult = {
        step: currentStep,
        key: CONFIG_STEPS[currentStep].key,
        status: "skipped",
      };
      const nextStep = currentStep + 1;

      if (nextStep >= CONFIG_STEPS.length) {
        set({
          phase: "completed",
          results: [...get().results, result],
          currentStep: nextStep,
        });
      } else {
        set({
          phase: "asking",
          currentStep: nextStep,
          skipCount: newSkipCount,
          results: [...get().results, result],
        });
      }
    }
  },

  handleSubmit: (data: Record<string, unknown>) => {
    const { currentStep } = get();
    const result: AutoConfigResult = {
      step: currentStep,
      key: CONFIG_STEPS[currentStep].key,
      status: "configured",
      data,
    };
    const nextStep = currentStep + 1;

    if (nextStep >= CONFIG_STEPS.length) {
      set({
        phase: "completed",
        results: [...get().results, result],
        currentStep: nextStep,
      });
    } else {
      set({
        phase: "asking",
        currentStep: nextStep,
        skipCount: 0,
        results: [...get().results, result],
      });
    }
  },

  handleExitYes: () => {
    // 未完成的步骤标记为 skipped
    const { currentStep, results } = get();
    const remainingResults: AutoConfigResult[] = [];
    for (let i = currentStep; i < CONFIG_STEPS.length; i++) {
      remainingResults.push({
        step: i,
        key: CONFIG_STEPS[i].key,
        status: "skipped",
      });
    }
    set({
      phase: "completed",
      results: [...results, ...remainingResults],
      isActive: false,
    });
  },

  handleExitNo: () => {
    const { currentStep, skipCount } = get();
    // 标记当前步骤为 skipped，重置计数器，继续下一步
    const result: AutoConfigResult = {
      step: currentStep,
      key: CONFIG_STEPS[currentStep].key,
      status: "skipped",
    };
    const nextStep = currentStep + 1;

    if (nextStep >= CONFIG_STEPS.length) {
      set({
        phase: "completed",
        results: [...get().results, result],
        currentStep: nextStep,
      });
    } else {
      set({
        phase: "asking",
        currentStep: nextStep,
        skipCount: 0,
        results: [...get().results, result],
      });
    }
  },

  reset: () =>
    set({
      phase: "idle",
      currentStep: 0,
      skipCount: 0,
      results: [],
      isActive: false,
    }),
}));
