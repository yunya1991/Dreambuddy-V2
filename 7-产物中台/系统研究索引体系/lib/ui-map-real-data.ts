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
        const timestamp = new Date(latest.timestamp).toISOString().replace("T", " ").slice(0, 16);
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

export function buildStrategyUIMapOverride(): UIMapStrategyOverride | null {
  try {
    const artifactsData = getArtifactsData();
    const byType = artifactsData.statistics.by_type ?? {};
    const strategyCount = Number(byType["strategy"] ?? 0);
    const total = artifactsData.total;

    if (!total || !strategyCount) {
      return null;
    }

    const byStatus = artifactsData.statistics.by_status ?? {};
    const completedCount = Number(byStatus["completed"] ?? 0);
    const activeCount = total - completedCount;
    const lastUpdated = artifactsData.generated_at
      ? new Date(artifactsData.generated_at).toISOString().replace("T", " ").slice(0, 16)
      : "";

    const convergenceLabel =
      `summary-only：${strategyCount} 份策略产物沉淀（strategy_setting_result 契约待落地）`;
    const chain =
      `${strategyCount} 策略设置 → ${total} 产物链条 → ${activeCount} 活跃 → 结果产物 → 索引${lastUpdated ? `（${lastUpdated}）` : ""}`;

    return {
      convergenceLabel,
      chain,
      summaryNote: "当前为摘要级接入：基于 artifacts 索引的 type=strategy 统计，敏感配置与执行状态尚未透出。",
    };
  } catch {
    return null;
  }
}
