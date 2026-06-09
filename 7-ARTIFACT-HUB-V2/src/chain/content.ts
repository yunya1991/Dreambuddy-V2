import fs from "node:fs";
import path from "node:path";
import { ArtifactStore } from "../artifact-store.js";
import { normalizeWorkflowType } from "../chain-workflow-guard.js";
import type { ChainAnomaly, ChainOverviewViewModel, ChainWorkflowItem } from "./types.js";

function toTaskIdCandidates(artifactId: string): string[] {
  const shortId = artifactId.split("/").pop() ?? artifactId;
  return [artifactId, shortId];
}

export class ChainContentStore {
  constructor(private readonly artifactsRoot: string) {}

  getOverview(): ChainOverviewViewModel {
    const store = new ArtifactStore(this.artifactsRoot);
    const items: ChainWorkflowItem[] = store.getArtifactsIndex().map((item) => ({
      artifactId: item.id,
      title: item.title,
      category: item.id.split("/")[0] ?? "",
      department: item.department,
      workflowType: normalizeWorkflowType(item.workflow_type),
      chainPhase: item.chain_phase,
      status: item.status,
      feedUrl: item.url
    }));

    const anomalies = items.flatMap((item) => this.detectAnomalies(item));

    return {
      workflowGroups: {
        legacy_chain: items.filter((item) => item.workflowType === "legacy_chain"),
        trading_v2: items.filter((item) => item.workflowType === "trading_v2")
      },
      anomalies
    };
  }

  private detectAnomalies(item: ChainWorkflowItem): ChainAnomaly[] {
    if (item.status === "completed") {
      return [];
    }

    const anomalies: ChainAnomaly[] = [];
    const candidates = toTaskIdCandidates(item.artifactId);

    const hasTask = candidates.some((taskId) =>
      fs.existsSync(path.join(this.artifactsRoot, "tasks", `task_${taskId}.json`))
    );
    const hasResult = candidates.some((taskId) =>
      fs.existsSync(path.join(this.artifactsRoot, "results", `result_${taskId}.json`))
    );

    if (!hasTask) {
      anomalies.push({
        kind: "missing_task",
        artifactId: item.artifactId,
        workflowType: item.workflowType
      });
    }

    if (!hasResult) {
      anomalies.push({
        kind: "missing_result",
        artifactId: item.artifactId,
        workflowType: item.workflowType
      });
    }

    return anomalies;
  }
}
