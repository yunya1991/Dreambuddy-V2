import { promises as fs } from "fs";
import * as path from "path";
import { NextResponse } from "next/server";
import {
  buildForgettingPlan,
} from "@/lib/cognition/residual-forgetting";
import {
  ingestPendingCandidates,
  listMemoryRecords,
  refreshAnchors,
} from "@/lib/cognition/memory-records";
import { sweepGateSla } from "@/lib/task-board/server-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DATA_DIR = path.join(process.cwd(), ".data");
const PLAN_FILE =
  process.env.FORGETTING_PLAN_FILE?.trim() ||
  path.join(DATA_DIR, "governance", "forgetting-plan.json");

/**
 * POST /api/governance/cycle
 * 治理周期：门禁 SLA 巡检 + 锚点复核 + 残差遗忘调度（只出计划，不物理删除）。
 * 供 launchd/systemd 定时调用。
 */
export async function POST() {
  const now = Date.now();
  // settle 暂存候选先过准入，再进入治理计划
  const ingested = await ingestPendingCandidates({ now });
  const [sla, records] = await Promise.all([
    sweepGateSla(now),
    listMemoryRecords(),
  ]);
  // 事件驱动复核：锚点存在性变化即时反映到治理计划
  const refreshed = await refreshAnchors(records, { now });

  const plan = buildForgettingPlan(refreshed.records, {
    now,
    deletion_test_passed: process.env.DELETION_TEST_PASSED === "true",
  });

  const report = {
    generated_at: now,
    records: refreshed.records.length,
    anchors_changed: refreshed.changed.length,
    ingested,
    records_file: process.env.MEMORY_RECORDS_FILE?.trim() || path.join(DATA_DIR, "memory", "records.jsonl"),
    sla,
    forgetting: plan,
  };

  try {
    await fs.mkdir(path.dirname(PLAN_FILE), { recursive: true });
    await fs.writeFile(PLAN_FILE, JSON.stringify(report, null, 2), "utf-8");
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: error instanceof Error ? error.message : String(error),
        report,
      },
      { status: 500 },
    );
  }

  return NextResponse.json({ success: true, plan_file: PLAN_FILE, report });
}

/** GET /api/governance/cycle：读取最近一次治理计划 */
export async function GET() {
  try {
    const raw = await fs.readFile(PLAN_FILE, "utf-8");
    return NextResponse.json({ success: true, plan: JSON.parse(raw) });
  } catch {
    return NextResponse.json(
      { success: false, error: "plan_not_found" },
      { status: 404 },
    );
  }
}
