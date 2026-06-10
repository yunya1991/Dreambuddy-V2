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
        const timestamp = formatSummaryTimestamp(latest.timestamp as string | undefined | null);
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

export function buildStrategyUIMapOverride(): UIMapStrategyOverride | null {
  try {
    const artifactsData = getArtifactsData();
    const byType = artifactsData.statistics.by_type ?? {};
    const strategyCount = Number(byType["strategy"] ?? 0);
    const total = artifactsData.total;

    if (!total || !strategyCount) {
      return null;
    }

    const byPhase = artifactsData.statistics.by_a_phase ?? {};
    const activePhases = A_PHASE_ORDER.filter((phase) => (byPhase[phase] ?? 0) > 0);
    const phaseDistribution = activePhases.length
      ? activePhases.map((phase) => `${phase}×${byPhase[phase]}`).join(" / ")
      : "无 A-phase 标注";

    const byStatus = artifactsData.statistics.by_status ?? {};
    const completedCount = Number(byStatus[ARTIFACT_STATUS_COMPLETED] ?? 0);
    const activeCount = total - completedCount;
    const lastUpdated = formatSummaryTimestamp(artifactsData.generated_at);

    const convergenceLabel =
      `summary-only：${strategyCount} 份策略产物沉淀（${phaseDistribution}，strategy_setting_result 契约待落地）`;
    const chain =
      `${strategyCount} 策略设置 → ${total} 产物链条（${activeCount} 活跃 / ${completedCount} 已沉淀）→ 结果产物 → 索引${lastUpdated ? `（${lastUpdated}）` : ""}`;

    return {
      convergenceLabel,
      chain,
      summaryNote: "当前为摘要级接入：基于 artifacts 索引的 type=strategy 与 A-phase 分布统计，敏感配置与执行状态尚未透出。",
    };
  } catch {
    return null;
  }
}

export function buildUserContextUIMapOverride(): UIMapUserContextOverride | null {
  try {
    const artifactsData = getArtifactsData();
    const total = artifactsData.total;
    const departmentCount = Object.keys(artifactsData.statistics.by_department ?? {}).length;
    const byStatus = artifactsData.statistics.by_status ?? {};
    const completedCount = Number(byStatus["completed"] ?? 0);
    const activeCount = total - completedCount;

    if (!total) {
      return null;
    }

    const lastUpdated = formatSummaryTimestamp(artifactsData.generated_at);

    return {
      description: `已接入 summary-only 用户上下文摘要：基于 ${total} 个产物沉淀，覆盖 ${departmentCount} 个部门的执行上下文可见范围。`,
      buildLabel: `支撑自定义策略生成（${completedCount} 个已沉淀产物可被索引回溯）`,
      runtimeLabel: `支撑每次策略执行（${activeCount} 个活跃产物可供上下文注入）`,
      summaryNote: `summary-only：未透出任何用户配置或敏感信息（${lastUpdated}）`,
    };
  } catch {
    return null;
  }
}
