import {
  getArtifactRelations,
  getArtifactsData,
  getChainPhaseArtifacts,
} from "./content.server.ts";
import type { UIMapSystemResearchOverride } from "../app/ui-map/ui-map-shell-view-model.ts";

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
