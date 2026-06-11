import type { UIMapScenario } from "./ui-map-scenarios.ts";

export interface UIMapSystemResearchOverride {
  description: string;
  bullets: string[];
}

export interface UIMapResearchChainOverride {
  description: string;
  bullets: string[];
}

export interface UIMapOperationsOverride {
  description: string;
  bullets: string[];
}

export interface UIMapStrategyOverride {
  convergenceLabel: string;
  chain: string;
  summaryNote?: string;
}

export interface UIMapUserContextOverride {
  description: string;
  buildLabel: string;
  runtimeLabel: string;
  summaryNote: string;
}

export interface UIMapShellOverrides {
  systemResearch?: UIMapSystemResearchOverride | null;
  researchChain?: UIMapResearchChainOverride | null;
  operations?: UIMapOperationsOverride | null;
  strategy?: UIMapStrategyOverride | null;
  userContext?: UIMapUserContextOverride | null;
}

export interface UIMapShellViewModel {
  hero: { title: string; subtitle: string; dataModeLabel: string };
  sourceLayer: Array<{ title: string; description: string; bullets: string[] }>;
  mainlineLayer: { title: string; convergenceLabel: string; chain: string; summaryNote?: string };
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
  perspectiveLayer: Array<{ title: string; description: string; bullets?: string[] }>;
}

export function buildUIMapShellViewModel(
  scenario: UIMapScenario,
  overrides: UIMapShellOverrides = {},
): UIMapShellViewModel {
  const systemResearch = overrides.systemResearch ?? {
    description: "平台基础能力底座，持续为系统策略和 AI 推理供能。",
    bullets: scenario.systemCapabilityBullets,
  };

  const researchChainCard = overrides.researchChain
    ? {
        title: "系统研究链路",
        description: overrides.researchChain.description,
        bullets: overrides.researchChain.bullets,
      }
    : {
        title: "系统研究链路",
        description: "展示固定研究流程、系统策略形成过程和研究产物关系。",
        bullets: [] as string[],
      };

  const operationsCard = overrides.operations
    ? {
        title: "系统运营链路",
        description: overrides.operations.description,
        bullets: overrides.operations.bullets,
      }
    : {
        title: "系统运营链路",
        description: "展示前端进入、策略收口、上下文调用、执行和索引更新。",
        bullets: [] as string[],
      };

  const realDataSources: string[] = [];
  if (overrides.systemResearch) realDataSources.push("系统研究索引");
  if (overrides.researchChain) realDataSources.push("研究链路");
  if (overrides.operations) realDataSources.push("运营链路");
  if (overrides.strategy) realDataSources.push("策略主线");
  if (overrides.userContext) realDataSources.push("用户上下文索引");

  const phaseLabel = realDataSources.length
    ? `Phase B · 已接入：${realDataSources.join("、")}`
    : "Phase A · 纯场景壳模式";

  return {
    hero: {
      title: "UI-Map 独立中台首页",
      subtitle: realDataSources.length
        ? `当前场景：${scenario.label}。${phaseLabel}，其余模块继续以壳模式展示。`
        : `当前场景：${scenario.label}。先稳定前端壳，再按模块逐块落地。`,
      dataModeLabel: phaseLabel,
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
    mainlineLayer: overrides.strategy
      ? {
          title: "策略主线",
          convergenceLabel: overrides.strategy.convergenceLabel,
          chain: overrides.strategy.chain,
          summaryNote: overrides.strategy.summaryNote,
        }
      : {
          title: "策略主线",
          convergenceLabel: "通过交易设置实现策略收口",
          chain: "策略设置成功 → 策略任务单 → 交易链条 → 交易执行 → 结果产物 → 索引",
        },
    indexFoundation: {
      userContext: overrides.userContext
        ? {
            title: "用户上下文索引系统",
            description: overrides.userContext.description,
            buildLabel: overrides.userContext.buildLabel,
            runtimeLabel: overrides.userContext.runtimeLabel,
            executionFrequencies: [
              scenario.executionFrequencies[0],
              scenario.executionFrequencies[1],
              scenario.executionFrequencies[2],
              overrides.userContext.summaryNote,
            ].filter(Boolean) as string[],
          }
        : {
            title: "用户上下文索引系统",
            description: "用户底座，既服务策略构建，也服务每次执行。",
            buildLabel: "支撑自定义策略生成",
            runtimeLabel: "支撑每次策略执行",
            executionFrequencies: scenario.executionFrequencies,
          },
      systemResearch: {
        title: "系统研究索引体系",
        description: systemResearch.description,
        bullets: systemResearch.bullets,
      },
    },
    perspectiveLayer: [
      {
        title: researchChainCard.title,
        description: researchChainCard.description,
        bullets: researchChainCard.bullets,
      },
      {
        title: operationsCard.title,
        description: operationsCard.description,
        bullets: operationsCard.bullets,
      },
    ],
  };
}
