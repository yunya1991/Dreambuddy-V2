import type { UIMapScenario } from "./ui-map-scenarios.ts";

export interface UIMapShellViewModel {
  hero: { title: string; subtitle: string };
  sourceLayer: Array<{ title: string; description: string; bullets: string[] }>;
  mainlineLayer: { title: string; convergenceLabel: string; chain: string };
  indexFoundation: {
    userContext: {
      title: string;
      description: string;
      buildLabel: string;
      runtimeLabel: string;
      executionFrequencies: string[];
    };
    systemResearch: {
      title: string;
      description: string;
      bullets: string[];
    };
  };
  perspectiveLayer: Array<{ title: string; description: string }>;
}

export function buildUIMapShellViewModel(scenario: UIMapScenario): UIMapShellViewModel {
  return {
    hero: {
      title: "UI-Map 独立中台首页",
      subtitle: `当前场景：${scenario.label}。先稳定前端壳，再按模块逐块落地。`,
    },
    sourceLayer: [
      {
        title: "自定义策略",
        description: "业务来源层：自定义策略由意图闭环、AI 推理与推荐、个人经验和传统联网金融经验共同形成。",
        bullets: scenario.customStrategyBullets,
      },
      {
        title: "系统策略",
        description: "业务来源层：系统策略承接系统研究产物、固定研究链路和 feed 入口。",
        bullets: scenario.systemStrategyBullets,
      },
    ],
    mainlineLayer: {
      title: "策略主线",
      convergenceLabel: "通过交易设置实现策略收口",
      chain: "策略设置成功 → 策略任务单 → 交易链条 → 交易执行 → 结果产物 → 索引",
    },
    indexFoundation: {
      userContext: {
        title: "用户上下文索引系统",
        description: "用户底座，既服务策略构建，也服务每次执行。",
        buildLabel: "支撑自定义策略生成",
        runtimeLabel: "支撑每次策略执行",
        executionFrequencies: scenario.executionFrequencies,
      },
      systemResearch: {
        title: "系统研究索引体系",
        description: "平台基础能力底座，持续为系统策略和 AI 推理供能。",
        bullets: scenario.systemCapabilityBullets,
      },
    },
    perspectiveLayer: [
      { title: "系统研究链路", description: "展示固定研究流程、系统策略形成过程和研究产物关系。" },
      { title: "系统运营链路", description: "展示前端进入、策略收口、上下文调用、执行和索引更新。" },
    ],
  };
}
