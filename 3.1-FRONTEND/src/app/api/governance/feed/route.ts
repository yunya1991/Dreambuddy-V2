import { NextRequest, NextResponse } from "next/server";
import { listPendingGateTasks } from "@/lib/task-board/server-store";
import { GATE_RISK } from "@/lib/task-board/gate-priority";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * 治理待办统一收口（工作台左下抽屉）。
 *
 * 对接五个来源，任一来源失败都不影响其余来源（FAIL-OPEN）：
 * - gate     门禁待办（任务看板里的未确认门）
 * - monitor  Agent 工作监控的异常/拒绝事件
 * - memory   记忆管理的重要写入 / 清理
 * - approval 人工审批
 * - report   待查看/待确认报告
 *
 * 这里只做归一化，不在前端拼接多个接口，避免口径分裂。
 */
export type GovernanceSource =
  | "gate"
  | "monitor"
  | "memory"
  | "approval"
  | "report";

export interface GovernanceFeedItem {
  key: string;
  source: GovernanceSource;
  source_label: string;
  title: string;
  detail?: string;
  priority: "high" | "normal";
  href: string;
  created_at: number;
  /** 门禁类待办才有：点击后切换到该任务 */
  task_id?: string;
  gate_id?: string;
  gate_kind?: string;
  gate_title?: string;
  evidence_ref?: string;
}

const SOURCE_LABEL: Record<GovernanceSource, string> = {
  gate: "门禁待办",
  monitor: "工作监控",
  memory: "记忆管理",
  approval: "人工审批",
  report: "报告",
};

const SOURCE_HREF: Record<GovernanceSource, string> = {
  gate: "/dashboard/gates",
  monitor: "/dashboard/monitor",
  memory: "/dashboard/memory",
  approval: "/dashboard/board/approval",
  report: "/dashboard/reports",
};

/** 从各种响应壳里取出数组（不同模块的返回结构不统一） */
function pickArray(json: unknown): Record<string, unknown>[] {
  if (Array.isArray(json)) return json as Record<string, unknown>[];
  if (json && typeof json === "object") {
    const record = json as Record<string, unknown>;
    for (const key of ["items", "records", "data", "tasks", "list", "feed"]) {
      const value = record[key];
      if (Array.isArray(value)) return value as Record<string, unknown>[];
    }
  }
  return [];
}

async function fetchJson(url: string): Promise<unknown> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

async function gateItems(): Promise<GovernanceFeedItem[]> {
  const tasks = await listPendingGateTasks();
  return tasks.flatMap((task) =>
    task.pending_gates
      // 意图澄清属于对话内弹窗，不进治理待办；兼容历史数据
      .filter((gate) => gate.kind !== "intent")
      .map((gate) => {
      const risk = GATE_RISK[gate.kind];
      return {
        key: `gate:${task.task_id}:${gate.gate_id}:${gate.evidence_ref}`,
        source: "gate" as const,
        source_label: SOURCE_LABEL.gate,
        title: `${task.title} · ${gate.title}`,
        detail: `证据 ${gate.evidence_ref}`,
        priority: risk === "high" || risk === "critical" ? "high" : "normal",
        href: `/dashboard/task/${encodeURIComponent(task.task_id)}`,
        created_at: gate.requested_at ?? task.updated_at,
        task_id: task.task_id,
        gate_id: gate.gate_id,
        gate_kind: gate.kind,
        gate_title: gate.title,
        evidence_ref: gate.evidence_ref,
      } satisfies GovernanceFeedItem;
    }),
  );
}

function genericItems(
  source: Exclude<GovernanceSource, "gate">,
  json: unknown,
  options: {
    isActionable: (item: Record<string, unknown>) => boolean;
    titleOf: (item: Record<string, unknown>) => string;
    detailOf?: (item: Record<string, unknown>) => string | undefined;
    tsOf: (item: Record<string, unknown>) => number;
    hrefOf?: (item: Record<string, unknown>) => string;
  },
): GovernanceFeedItem[] {
  return pickArray(json)
    .filter(options.isActionable)
    .slice(0, 20)
    .map((item, index) => {
      const id = String(item.id ?? item.event_id ?? item.key ?? index);
      return {
        key: `${source}:${id}`,
        source,
        source_label: SOURCE_LABEL[source],
        title: options.titleOf(item),
        detail: options.detailOf?.(item),
        priority:
          item.priority === "high" || item.status === "error" || item.severity === "high"
            ? "high"
            : "normal",
        href: options.hrefOf?.(item) ?? SOURCE_HREF[source],
        created_at: options.tsOf(item),
      } satisfies GovernanceFeedItem;
    });
}

export async function GET(request: NextRequest) {
  const origin = request.nextUrl.origin;
  const [monitorJson, memoryJson, approvalJson, reportJson] = await Promise.all([
    fetchJson(`${origin}/api/monitor/events`),
    fetchJson(`${origin}/api/memory/records`),
    fetchJson(`${origin}/api/board/approval/pending`),
    fetchJson(`${origin}/api/reports`),
  ]);

  let gates: GovernanceFeedItem[] = [];
  try {
    gates = await gateItems();
  } catch {
    gates = [];
  }

  const monitor = genericItems("monitor", monitorJson, {
    isActionable: (item) =>
      item.status === "error" || item.status === "denied" || item.severity === "high",
    titleOf: (item) =>
      String(item.message_preview ?? item.message ?? item.title ?? "监控异常"),
    detailOf: (item) => String(item.phase ?? item.layer ?? ""),
    tsOf: (item) => Number(item.ts ?? item.timestamp ?? item.created_at ?? 0),
  });

  const memory = genericItems("memory", memoryJson, {
    isActionable: (item) =>
      item.status === "pending" ||
      item.needs_confirmation === true ||
      item.action === "delete" ||
      item.action === "cleanup",
    titleOf: (item) =>
      String(item.title ?? item.summary ?? item.content ?? "记忆变更待确认"),
    detailOf: (item) => String(item.action ?? item.kind ?? ""),
    tsOf: (item) => Number(item.updated_at ?? item.created_at ?? 0),
  });

  const approval = genericItems("approval", approvalJson, {
    isActionable: () => true,
    titleOf: (item) =>
      String(item.title ?? item.summary ?? item.name ?? "人工审批待处理"),
    detailOf: (item) => String(item.type ?? item.kind ?? ""),
    tsOf: (item) => Number(item.created_at ?? item.updated_at ?? 0),
  });

  const report = genericItems("report", reportJson, {
    isActionable: (item) =>
      item.status === "pending" ||
      item.status === "review" ||
      item.needs_review === true,
    titleOf: (item) => String(item.title ?? item.name ?? "报告待查看"),
    detailOf: (item) => String(item.type ?? ""),
    tsOf: (item) => Number(item.created_at ?? item.generated_at ?? 0),
  });

  const items = [...gates, ...monitor, ...memory, ...approval, ...report]
    .sort(
      (a, b) =>
        (a.priority === "high" ? 0 : 1) - (b.priority === "high" ? 0 : 1) ||
        b.created_at - a.created_at,
    )
    .slice(0, 50);

  const counts: Record<string, number> = {};
  for (const item of items) {
    counts[item.source] = (counts[item.source] ?? 0) + 1;
  }

  return NextResponse.json({
    success: true,
    count: items.length,
    high: items.filter((item) => item.priority === "high").length,
    counts,
    items,
  });
}
