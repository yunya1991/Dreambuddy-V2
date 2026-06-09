export interface DashboardMainPanelItemViewModel {
  label: string;
  value: string;
  tone: "neutral" | "success" | "info";
  href?: string;
}

export interface DashboardMainPanelTrackViewModel {
  title: string;
  items: DashboardMainPanelItemViewModel[];
}

export interface DashboardMainPanelViewModel {
  hero: {
    entryLabel: string;
    title: string;
    summary: string;
  };
  strategyTrack: DashboardMainPanelTrackViewModel;
  intentTrack: DashboardMainPanelTrackViewModel;
  systemTrack: DashboardMainPanelTrackViewModel;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function buildDashboardMainPanelViewModel(input: unknown): DashboardMainPanelViewModel {
  const source = asRecord(input) ?? {};
  const strategy = asRecord(source.strategy) ?? {};
  const memory = asRecord(source.memory) ?? {};
  const llm = asRecord(source.llm) ?? {};

  const drafts = Array.isArray(strategy.drafts) ? strategy.drafts.length : 0;
  const applied = Array.isArray(strategy.applied) ? strategy.applied.length : 0;
  const active = Array.isArray(strategy.active) ? strategy.active.length : 0;
  const totalRecords = asFiniteNumber(memory.totalRecords) ?? 0;
  const llmOnline = llm.status === "online";
  const model = typeof llm.model === "string" ? llm.model : "待接入";
  const intentMethod = llm.intentMethod === "llm" ? "LLM 意图识别" : "规则识别";

  return {
    hero: {
      entryLabel: "Dashboard 主入口",
      title: "前端主需求总面板",
      summary: "先用 Web UI 看清策略主线、意图闭环、系统策略入口，再决定后端承接方式。",
    },
    strategyTrack: {
      title: "策略主线",
      items: [
        {
          label: "策略设置",
          value: drafts > 0 ? `${drafts} 个草稿` : "待配置",
          tone: drafts > 0 ? "info" : "neutral",
        },
        {
          label: "策略任务单",
          value: applied > 0 ? `${applied} 个任务单` : "待生成",
          tone: applied > 0 ? "success" : "neutral",
        },
        {
          label: "执行状态",
          value: active > 0 ? `${active} 条进行中` : "等待执行",
          tone: active > 0 ? "success" : "neutral",
        },
      ],
    },
    intentTrack: {
      title: "意图闭环",
      items: [
        {
          label: "意图识别",
          value: intentMethod,
          tone: llmOnline ? "success" : "neutral",
        },
        {
          label: "智能路由",
          value: model,
          tone: llmOnline ? "info" : "neutral",
        },
        {
          label: "中台能力链",
          value: "SKILL / 策略库 / 回测 / 贝叶斯优化",
          tone: "info",
        },
        {
          label: "意图记忆库",
          value: totalRecords > 0 ? `${totalRecords} 条经验` : "待接入",
          tone: totalRecords > 0 ? "success" : "neutral",
        },
      ],
    },
    systemTrack: {
      title: "系统策略入口",
      items: [
        {
          label: "系统策略 Feed",
          value: "进入系统策略与系统产物入口",
          tone: "info",
          href: "http://127.0.0.1:3456/feed",
        },
        {
          label: "统一承接",
          value: "等待承接",
          tone: "neutral",
        },
      ],
    },
  };
}
