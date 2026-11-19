import path from "path";
import { promises as fs } from "fs";

/**
 * GateFlow → D3D 事件导出器。
 *
 * 只导出 `node.rejected`（可扩展 `node.rewound`），由 Python
 * `gateflow_brainstorm_bridge.py` 消费并幂等立案。
 *
 * 硬约束：
 * - 只读 GateRun/门禁事实，不修改 GateFlow；
 * - 导出失败不阻断门禁响应（FAIL-OPEN），但调用方应记录 `gateflow_exported`；
 * - 目录可用 `GATEFLOW_EVENTS_DIR` 覆盖。
 */

export type GateFlowExportType = "node.rejected" | "node.rewound";

export interface GateFlowEventRecord {
  run_id: string;
  flow_id: string;
  task_id: string;
  trace_id: string;
  type: GateFlowExportType;
  node_id: string;
  at: number;
  detail: {
    reason: string;
    gate_kind: string;
    rewind_to: string;
    evidence_refs: string[];
    high_risk: boolean;
    risk_level: "critical" | "low";
    reversible: boolean;
    uncertainty_score: number;
  };
}

export interface GateRejectionExportInput {
  taskId: string;
  traceId?: string;
  runId?: string;
  flowId?: string;
  gateId: string;
  gateKind: string;
  comment?: string;
  rewindTo?: string;
  evidenceRef?: string;
  highRisk?: boolean;
  at?: number;
}

export interface AppendGateFlowOptions {
  dir?: string;
}

export function resolveGateFlowEventsDir(): string {
  return (
    process.env.GATEFLOW_EVENTS_DIR?.trim() ||
    path.join(process.cwd(), ".data", "gateflow")
  );
}

export function buildGateFlowRejectionRecord(
  input: GateRejectionExportInput,
): GateFlowEventRecord {
  const at = typeof input.at === "number" ? input.at : Date.now();
  const highRisk = input.highRisk === true;
  const rewindTo = input.rewindTo || "none";
  return {
    run_id: input.runId || `${input.taskId}:gate`,
    flow_id: input.flowId || "task-board",
    task_id: input.taskId,
    trace_id: input.traceId || input.taskId,
    type: "node.rejected",
    node_id: input.gateId,
    at,
    detail: {
      reason: input.comment || "gate rejected",
      gate_kind: input.gateKind,
      rewind_to: rewindTo,
      evidence_refs: input.evidenceRef ? [input.evidenceRef] : [],
      high_risk: highRisk,
      risk_level: highRisk ? "critical" : "low",
      reversible: !highRisk,
      uncertainty_score: rewindTo === "none" ? 0.7 : 0.5,
    },
  };
}

function safeFileName(value: string): string {
  return (value || "gateflow").replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 120);
}

/**
 * append-only JSONL；返回 false 表示写失败，调用方不得据此阻断门禁。
 */
export async function appendGateFlowEvent(
  record: GateFlowEventRecord,
  options: AppendGateFlowOptions = {},
): Promise<boolean> {
  try {
    if (!record?.run_id || !record?.type) return false;
    const dir = options.dir || resolveGateFlowEventsDir();
    await fs.mkdir(dir, { recursive: true });
    const file = path.join(dir, `${safeFileName(record.run_id)}.jsonl`);
    await fs.appendFile(file, `${JSON.stringify(record)}\n`, "utf8");
    return true;
  } catch {
    return false;
  }
}
