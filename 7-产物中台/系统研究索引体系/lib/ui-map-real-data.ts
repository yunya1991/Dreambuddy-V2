import {
  getArtifactRelations,
  getArtifactsData,
  getChainPhaseArtifacts,
} from "./content.server.ts";
import type {
  UIMapResearchChainOverride,
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
