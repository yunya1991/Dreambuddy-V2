export type UIMapScenarioId = "balanced" | "custom-heavy" | "system-heavy" | "execution-heavy";

export interface UIMapScenario {
  id: UIMapScenarioId;
  label: string;
  customStrategyBullets: string[];
  systemStrategyBullets: string[];
  executionFrequencies: string[];
  systemCapabilityBullets: string[];
}

const SCENARIOS: Record<UIMapScenarioId, UIMapScenario> = {
  balanced: {
    id: "balanced",
    label: "平衡场景",
    customStrategyBullets: ["意图闭环", "AI 推理与推荐", "个人经验", "传统联网金融经验"],
    systemStrategyBullets: ["feed 系统策略入口", "系统研究产物", "固定研究链路结果"],
    executionFrequencies: ["1h", "4h", "1d"],
    systemCapabilityBullets: ["系统研究结果沉淀", "系统策略支撑", "平台公共能力", "AI 推理优先参考路径"],
  },
  "custom-heavy": {
    id: "custom-heavy",
    label: "自定义策略主导",
    customStrategyBullets: ["意图闭环", "AI 推理与推荐", "个人经验加强", "联网金融经验增强"],
    systemStrategyBullets: ["系统策略补充入口", "系统研究辅助"],
    executionFrequencies: ["1h", "4h"],
    systemCapabilityBullets: ["研究能力调用", "最优路径参考"],
  },
  "system-heavy": {
    id: "system-heavy",
    label: "系统策略主导",
    customStrategyBullets: ["意图闭环辅助", "AI 推荐辅助", "个人经验补充"],
    systemStrategyBullets: ["feed 主入口", "固定研究链路", "系统研究主导"],
    executionFrequencies: ["4h", "1d"],
    systemCapabilityBullets: ["系统研究结果沉淀", "系统策略支撑", "平台公共能力"],
  },
  "execution-heavy": {
    id: "execution-heavy",
    label: "执行频次主导",
    customStrategyBullets: ["意图闭环", "AI 推理与推荐", "个人经验", "联网金融经验"],
    systemStrategyBullets: ["系统策略入口", "系统研究产物"],
    executionFrequencies: ["1h", "4h", "1d"],
    systemCapabilityBullets: ["系统研究结果沉淀", "AI 推理路径", "系统策略支撑"],
  },
};

export function getUIMapScenario(id: string | undefined): UIMapScenario {
  if (!id || !(id in SCENARIOS)) {
    return SCENARIOS.balanced;
  }

  return SCENARIOS[id as UIMapScenarioId];
}
