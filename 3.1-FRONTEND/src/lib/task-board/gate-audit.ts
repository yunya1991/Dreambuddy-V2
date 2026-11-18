/**
 * 门禁预审审计（append-only）。
 *
 * 只记录判定要素，不记录证据原文与密钥：
 * who(model) / family / verdict / confidence / latency / evidence_ref。
 */

import { promises as fs } from "fs";
import * as path from "path";

const DATA_DIR =
  process.env.GATE_AUDIT_DIR?.trim() ||
  path.join(process.cwd(), ".data", "gate-audit");

export interface GateAuditRecord {
  ts: number;
  task_id: string;
  gate_id: string;
  evidence_ref: string;
  verdict: string;
  votes: Array<{
    model_id: string;
    family: string;
    verdict: string;
    confidence: number | null;
    latency_ms: number;
    degraded: boolean;
  }>;
  reasons: string[];
}

let chain: Promise<unknown> = Promise.resolve();

export function appendGateAudit(record: GateAuditRecord): Promise<void> {
  const run = async () => {
    await fs.mkdir(DATA_DIR, { recursive: true });
    await fs.appendFile(
      path.join(DATA_DIR, "precheck.jsonl"),
      `${JSON.stringify(record)}\n`,
      "utf-8",
    );
  };
  chain = chain.then(run, run);
  return (chain as Promise<unknown>).then(
    () => undefined,
    () => undefined,
  );
}
