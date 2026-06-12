import {
  getArtifactRelations,
  getArtifactsData,
  getChainPhaseArtifacts,
} from "./content.server.ts";
import { getRealtimeHub } from "./realtime-hub.ts";
import type { RealtimeChannel } from "./types.ts";
import type {
  UIMapOperationsOverride,
  UIMapResearchChainOverride,
  UIMapStrategyOverride,
  UIMapSystemResearchOverride,
  UIMapUserContextOverride,
} from "../app/ui-map/ui-map-shell-view-model.ts";
import {
  buildStrategyFullView,
  type StrategyFullView,
  type StrategySettingResult,
} from "./strategy-standard-objects.ts";
import {
  buildUserContextSummary,
  type UserContextFullView,
} from "./user-context-standard-objects.ts";
import {
  getBusinessDataView,
  type BusinessDataPrecipitationView,
} from "./prisma-data-hub.ts";

export function buildSystemResearchUIMapOverride(): UIMapSystemResearchOverride | null {
  try {
    const artifactsData = getArtifactsData();

    if (!artifactsData.total) {
      return null;
    }

    const relations = getArtifactRelations();
    const groupedByPhase = getChainPhaseArtifacts();
    const departmentCount = Object.keys(artifactsData.statistics.by_department).length;
    const phaseCount = Object.keys(groupedByPhase).length;

    return {
      description: `已接入真实系统研究数据：${artifactsData.total} 个产物，覆盖 ${departmentCount} 个部门、${phaseCount} 个阶段。`,
      bullets: [
        `系统研究结果沉淀：${artifactsData.total} 个真实产物`,
        `关系链路覆盖：${relations.length} 条关系，${phaseCount} 个阶段`,
        `平台能力覆盖：${departmentCount} 个部门`,
      ],
    };
  } catch {
    return null;
  }
}

export function buildResearchChainUIMapOverride(): UIMapResearchChainOverride | null {
  try {
    const relations = getArtifactRelations();
    if (!relations.length) {
      return null;
    }

    const groupedByPhase = getChainPhaseArtifacts(3);
    const phases = Object.keys(groupedByPhase).sort();
    const totalArtifacts = relations.length;

    const topPhaseLines: string[] = phases.slice(0, 3).map((phase) => {
      const artifacts = groupedByPhase[phase] ?? [];
      return `${phase}：${artifacts.length} 个产物`;
    });

    return {
      description: `已接入真实研究链路数据：${totalArtifacts} 条关系，覆盖 ${phases.length} 个阶段。`,
      bullets: [
        `阶段覆盖：${phases.slice(0, 3).join(" → ")}${phases.length > 3 ? `（共 ${phases.length} 阶段）` : ""}`,
        ...topPhaseLines,
      ],
    };
  } catch {
    return null;
  }
}

const OPERATIONS_CHANNELS: RealtimeChannel[] = ["dream-agent", "meeting", "system"];

/**
 * Canonical status labels used by the artifact index. The repository writes
 * `status` verbatim from the index JSON, so this constant documents the
 * specific values that the summary-only adapter relies on.
 */
const ARTIFACT_STATUS_COMPLETED = "completed";

/** Format an ISO-ish string timestamp or numeric ms timestamp as "YYYY-MM-DD HH:mm" for summary banners. */
function formatSummaryTimestamp(ts: string | number | undefined | null): string {
  if (ts === undefined || ts === null || ts === "") return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().replace("T", " ").slice(0, 16);
}

export function buildOperationsUIMapOverride(): UIMapOperationsOverride | null {
  try {
    const hub = getRealtimeHub();
    const channelSummaries = OPERATIONS_CHANNELS.map((channel) => ({
      channel,
      events: hub.getRecentEvents(channel),
    }));

    const totalEvents = channelSummaries.reduce((sum, item) => sum + item.events.length, 0);

    if (!totalEvents) {
      return null;
    }

    const channelLines = channelSummaries
      .filter((item) => item.events.length > 0)
      .map((item) => {
        const latest = item.events[item.events.length - 1];
        const timestamp = formatSummaryTimestamp(latest.timestamp);
        return `${item.channel}：${item.events.length} 条最近（${timestamp}）`;
      });

    return {
      description: `已接入真实运营事件：共 ${totalEvents} 条最近事件，覆盖 ${channelLines.length} 个通道。`,
      bullets: channelLines.slice(0, 3),
    };
  } catch {
    return null;
  }
}

const A_PHASE_ORDER = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"];

function phaseLabelFor(value: string): string {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return trimmed;
  const m = trimmed.match(/^A([0-9])$/i);
  return m ? `A${m[1]}` : "";
}

export function buildStrategyUIMapOverride(
  businessData?: BusinessDataPrecipitationView | null,
): UIMapStrategyOverride | null {
  try {
    // === 数据源 1: 策略知识沉淀 (来自 artifacts 文件系统) ===
    const artifactsData = getArtifactsData();
    const byType = artifactsData.statistics.by_type ?? {};
    const strategyKnowledgeCount = Number(byType["strategy"] ?? 0);
    const total = artifactsData.total;

    const strategyArtifacts = artifactsData.artifacts.filter((item) => item.type === "strategy");

    const strategyPhaseCount: Record<string, number> = {};
    strategyArtifacts.forEach((item) => {
      const normalized = phaseLabelFor(item.chain_phase);
      if (normalized) strategyPhaseCount[normalized] = (strategyPhaseCount[normalized] ?? 0) + 1;
    });
    const activePhases = A_PHASE_ORDER.filter((phase) => (strategyPhaseCount[phase] ?? 0) > 0);
    const phaseDistribution = activePhases.length
      ? activePhases.map((phase) => `${phase}×${strategyPhaseCount[phase]}`).join(" / ")
      : "无 A-phase 标注";

    const strategyStatusCount: Record<string, number> = {};
    strategyArtifacts.forEach((item) => {
      const s = (item.status ?? "").toLowerCase();
      strategyStatusCount[s] = (strategyStatusCount[s] ?? 0) + 1;
    });
    const strategyCompleted = Number(strategyStatusCount[ARTIFACT_STATUS_COMPLETED] ?? 0);
    const strategyActive = strategyKnowledgeCount - strategyCompleted;

    const lastUpdated = formatSummaryTimestamp(artifactsData.generated_at);

    const strategyFullViews: StrategyFullView[] = strategyArtifacts
      .map((artifact) => buildStrategyFullView(artifact as unknown as Record<string, unknown>))
      .filter((view): view is StrategyFullView => view !== null);

    const activeSettings = strategyFullViews.filter(
      (view) => view.setting.status === "active",
    );
    const completedSettings = strategyFullViews.filter(
      (view) => view.setting.status === "completed",
    );
    const draftSettings = strategyFullViews.filter(
      (view) => view.setting.status === "draft",
    );

    const runningExecutions = strategyFullViews.filter(
      (view) => view.executionStatus.status === "running",
    );
    const totalTasks = strategyFullViews.reduce(
      (sum, view) => sum + view.executionStatus.metrics.totalTasks,
      0,
    );
    const completedTasks = strategyFullViews.reduce(
      (sum, view) => sum + view.executionStatus.metrics.completedTasks,
      0,
    );

    // === 数据源 2: 业务执行沉淀 (来自 Prisma SQLite) ===
    const biz = businessData?.strategies;
    const hasBusinessData = biz !== null && biz !== undefined && biz.totalStrategies > 0;

    let convergenceLabel = "";
    let chain = "";
    let summaryNote = "";

    if (hasBusinessData && biz) {
      // 双源数据合并视图
      const totalBusiness = biz.totalStrategies;
      const activeBiz = biz.byStatus["APPLIED"] ?? biz.byStatus["APPROVED"] ?? 0;
      const totalBizTasks = biz.activeTasks;
      const totalBizExecutions = biz.totalExecutions;
      const completedBizExecutions = biz.completedExecutions;
      const lastExecAt = biz.lastExecutionAt
        ? formatSummaryTimestamp(biz.lastExecutionAt)
        : null;

      const recommendedStrategies = biz.byType["RECOMMENDED"] ?? 0;
      const customStrategies = biz.byType["CUSTOM"] ?? 0;

      convergenceLabel =
        `策略主线完整接入（双源数据沉淀）：${strategyKnowledgeCount} 份策略知识沉淀（${phaseDistribution}）+ ${totalBusiness} 个用户策略配置（${customStrategies} 自定义 / ${recommendedStrategies} 推荐）`;

      chain =
        `${strategyKnowledgeCount} 策略知识 → ${totalBusiness} 用户策略 → ${totalBizTasks} 活跃任务 → ${completedBizExecutions}/${totalBizExecutions} 次执行 → 结果产物入索引${lastExecAt ? `（最近执行 ${lastExecAt}）` : ""}`;

      const businessLabel = `业务执行：${completedBizExecutions}/${totalBizExecutions} 次成功执行${lastExecAt ? `，最近 ${lastExecAt}` : "，等待首次执行"}`;
      summaryNote = businessLabel;
    } else if (strategyKnowledgeCount > 0) {
      // 只有知识沉淀的视图
      convergenceLabel =
        `策略主线完整接入：${strategyKnowledgeCount} 份策略产物沉淀（${phaseDistribution}），${activeSettings.length} 活跃 / ${completedSettings.length} 已完成 / ${draftSettings.length} 草稿`;

      chain =
        `${strategyKnowledgeCount} 策略设置 → ${runningExecutions.length} 正在执行 → ${completedTasks}/${totalTasks} 任务完成 → 结果产物入索引${lastUpdated ? `（${lastUpdated}）` : ""}`;

      const activeStrategyNames = activeSettings
        .slice(0, 3)
        .map((view) => view.setting.strategyName)
        .join("、");
      summaryNote = activeStrategyNames
        ? `活跃策略：${activeStrategyNames}${activeSettings.length > 3 ? ` 等共 ${activeSettings.length} 个` : ""}（业务数据沉淀待接入）`
        : "暂无活跃策略（业务数据沉淀待接入）";
    } else {
      return null;
    }

    return {
      convergenceLabel,
      chain,
      summaryNote,
    };
  } catch {
    return null;
  }
}

export function buildUserContextUIMapOverride(
  businessData?: BusinessDataPrecipitationView | null,
): UIMapUserContextOverride | null {
  try {
    // === 数据源 1: 内容沉淀 (来自 artifacts 文件系统) ===
    const artifactsData = getArtifactsData();
    const total = artifactsData.total;

    if (!total) {
      return null;
    }

    const departmentCount = Object.keys(artifactsData.statistics.by_department ?? {}).length;
    const byStatus = artifactsData.statistics.by_status ?? {};
    const completedCount = Number(byStatus["completed"] ?? 0);
    const activeCount = total - completedCount;

    // 使用标准对象契约构建用户上下文视图（字段映射：id -> artifact_id）
    const contextView = buildUserContextSummary({
      total: artifactsData.total,
      statistics: artifactsData.statistics,
      artifacts: artifactsData.artifacts.map((a) => ({
        artifact_id: a.id,
        title: a.title,
        type: a.type,
        department: String(a.department),
        status: String(a.status),
        date: a.date,
      })),
    }, 'build-time');

    const lastUpdated = formatSummaryTimestamp(artifactsData.generated_at);
    const coveragePercent = Math.round(contextView.summary.coverageRate * 100);

    // === 数据源 2: 业务执行沉淀 (来自 Prisma SQLite) ===
    const biz = businessData?.userContext;
    const tradingBiz = businessData?.trading;
    const hasBusinessData =
      biz !== null && biz !== undefined && (biz.totalUsers > 0 || biz.usersWithStrategies > 0);

    if (hasBusinessData && biz) {
      // 双源数据合并视图
      const totalUsers = biz.totalUsers;
      const verifiedUsers = biz.verifiedUsers;
      const usersWithStrategies = biz.usersWithStrategies;
      const verifiedApiConfigs = biz.verifiedApiConfigs;
      const totalApiConfigs = biz.totalApiConfigs;
      const activeTrading = tradingBiz ? tradingBiz.activeTradingParams : 0;
      const creditsBalance = biz.creditsTotalBalance;
      const totalOrders = biz.totalOrders;

      const businessLine1 = `用户沉淀：${totalUsers} 注册用户（${verifiedUsers} 已验证），${usersWithStrategies} 人已创建策略`;
      const businessLine2 = `连通性沉淀：${verifiedApiConfigs}/${totalApiConfigs} API 配置已验证 · ${biz.totalChannelConfigs} 通道 · ${activeTrading} 活跃交易账户`;
      const businessLine3 = creditsBalance > 0 || totalOrders > 0
        ? `经济沉淀：积分总余额 ${creditsBalance.toFixed(0)}，订单 ${totalOrders} 笔`
        : "";

      return {
        description: `用户上下文索引完整接入（双源数据沉淀）：内容沉淀 ${total} 个产物（覆盖 ${departmentCount} 部门）+ 业务沉淀 ${totalUsers} 用户（覆盖率 ${coveragePercent}%）`,
        buildLabel: businessLine1,
        runtimeLabel: businessLine2,
        summaryNote: businessLine3
          ? `${businessLine3}（${lastUpdated}，脱敏聚合展示）`
          : `基于 artifacts 索引 + Prisma 业务数据双重沉淀；未透出任何用户敏感信息（${lastUpdated}）`,
      };
    }

    // 回退：只有内容沉淀的视图
    return {
      description: `用户上下文索引完整接入：基于 ${total} 个产物沉淀，覆盖 ${departmentCount} 个部门的执行上下文可见范围（覆盖率 ${coveragePercent}%）`,
      buildLabel: `支撑自定义策略生成（${completedCount} 个已沉淀产物可被索引回溯，${contextView.buildTimeArtifactCount} 个可用于构建时上下文）`,
      runtimeLabel: `支撑每次策略执行（${activeCount} 个活跃产物可供上下文注入，${contextView.runtimeArtifactCount} 个可用于运行时上下文）`,
      summaryNote: `基于 artifacts 索引构建用户上下文摘要；业务数据沉淀待接入（${lastUpdated}）`,
    };
  } catch {
    return null;
  }
}

// 业务数据沉淀枢纽：从 Prisma 读取用户策略/任务/执行/积分等业务层数据
export { getBusinessDataView };

// ============================================================================
// 业务数据沉淀独立模块 — 类似系统研究索引的独立 section
// ============================================================================
import type { UIMapBusinessPrecipitationOverride } from "../app/ui-map/ui-map-shell-view-model.ts";

export function buildBusinessPrecipitationOverride(
  businessData?: BusinessDataPrecipitationView | null,
): UIMapBusinessPrecipitationOverride | null {
  try {
    if (!businessData) return null;

    const biz = businessData.strategies;
    const user = businessData.userContext;
    const trading = businessData.trading;

    if (!biz && !user && !trading) return null;

    // 顶层统计卡片
    const statsCards = [];
    if (biz?.totalStrategies) {
      statsCards.push({
        label: "策略总数",
        value: String(biz.totalStrategies),
        detail: `${biz.byStatus["APPLIED"] ?? 0} 个活跃 · ${biz.byStatus["APPROVED"] ?? 0} 个待执行`,
      });
    }
    if (biz?.totalExecutions) {
      statsCards.push({
        label: "执行总次数",
        value: String(biz.totalExecutions),
        detail: `${biz.completedExecutions} 次已完成 · ${biz.lastExecutionAt ? "最近 " + biz.lastExecutionAt.slice(0, 10) : "等待首次执行"}`,
      });
    }
    if (biz?.activeTasks) {
      statsCards.push({
        label: "活跃任务",
        value: String(biz.activeTasks),
        detail: `自动按策略频率触发`,
      });
    }
    if (user?.totalUsers) {
      statsCards.push({
        label: "注册用户",
        value: String(user.totalUsers),
        detail: `${user.usersWithStrategies ?? 0} 人已创建策略`,
      });
    }
    if (user?.creditsTotalBalance !== undefined && user.creditsTotalBalance !== 0) {
      statsCards.push({
        label: "积分余额",
        value: String(user.creditsTotalBalance.toFixed(0)),
        detail: `${user.totalOrders ?? 0} 笔历史订单`,
      });
    }
    if (trading?.totalTradeCount) {
      statsCards.push({
        label: "交易总笔数",
        value: String(trading.totalTradeCount),
        detail: `${trading.activeTradingParams ?? 0} 个活跃交易账户`,
      });
    }

    // 3 个细分卡片
    const strategyCard = biz
      ? {
          label: "策略层沉淀",
          detail: `${biz.totalStrategies} 条策略（${biz.byType?.CUSTOM ?? 0} 自定义 / ${biz.byType?.RECOMMENDED ?? 0} 系统推荐）· ${biz.totalExecutions} 次执行 · ${biz.activeTasks} 个任务`,
        }
      : { label: "策略层沉淀", detail: "暂无策略数据" };

    const userCard = user
      ? {
          label: "用户层沉淀",
          detail: `${user.totalUsers} 用户 · ${user.usersWithStrategies ?? 0} 人创建策略 · API 配置 ${user.totalApiConfigs ?? 0} 个 · 积分余额 ${user.creditsTotalBalance !== undefined ? user.creditsTotalBalance.toFixed(0) : "0"}`,
        }
      : { label: "用户层沉淀", detail: "暂无用户数据" };

    const tradingCard = trading
      ? {
          label: "交易层沉淀",
          detail: `${trading.activeTradingParams ?? 0} 活跃账户 · 今日 ${trading.todayTradeCount} 笔 · 累计 ${trading.totalTradeCount} 笔 · 盈亏 ${trading.totalLoss ?? 0}`,
        }
      : { label: "交易层沉淀", detail: "暂无交易数据" };

    return {
      description: "业务数据沉淀独立模块：读取 Prisma SQLite 业务数据库，聚合策略、任务、执行、用户、积分等实时指标。",
      statsCards,
      strategyCard,
      userCard,
      tradingCard,
      aggregatedAt: businessData.aggregatedAt
        ? `聚合于 ${new Date(businessData.aggregatedAt).toLocaleString("zh-CN")}`
        : "",
    };
  } catch {
    return null;
  }
}

