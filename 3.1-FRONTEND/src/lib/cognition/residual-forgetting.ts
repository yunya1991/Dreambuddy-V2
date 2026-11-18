/**
 * 残差遗忘调度（SPEC-ResidualMemory-Admission v1.5 §3.7′，P2.5 生产化）。
 *
 * 判据不是"时间到点就删"，而是事件驱动：
 *   subclass + source_anchor 复核结果 + 可重建性。
 *
 * 红线：
 * - D-policy（policy）与未分型存量永不自动降级/删除；
 * - 物理删除需先通过删除测试集，未建立前只降级（demote）；
 * - 遗忘 = 移出检索索引，痕迹必须归入痕迹池，不得无归属堆放。
 */

export type ResidualSubclass =
  | "code_fact"
  | "runtime"
  | "policy"
  | "relationship"
  | "tech_decision"
  | "artifact";

export type VerifyState = "verified" | "stale" | "degraded";
export type ForgettingAction = "keep" | "demote" | "archive_trace";

export interface MemoryRecord {
  id: string;
  /** trace 贯穿：来源 run / task（T5.1） */
  trace_id?: string;
  /** 缺失或 null 视为未分型存量，按 D-policy 冻结 */
  subclass?: ResidualSubclass | null;
  /** 事实源锚点（文件:行 / 章节 / 接口），用于事件驱动复核 */
  source_anchor?: string;
  /** 锚点复核结果：false 表示锚点已不存在 */
  anchor_exists?: boolean;
  verify_state?: VerifyState;
  created_at?: number;
  last_verified_at?: number;
  last_used_at?: number;
  access_count?: number;
  /** 人工 pin，永不自动降级 */
  pinned?: boolean;
  form?: "M1" | "M2" | "M3";
  /** 痕迹池摘要（200 字以内） */
  summary?: string;
}

export interface ForgettingOptions {
  now?: number;
  /** runtime 类宽限期（天），默认 7 */
  grace_days?: number;
  /** 删除测试集是否已通过；未通过只降级不删除 */
  deletion_test_passed?: boolean;
  /** M1 硬上限，默认 150 */
  m1_limit?: number;
}

export interface ForgettingTrace {
  id: string;
  subclass?: string;
  tags: string[];
  summary?: string;
  last_used_at?: number;
}

export interface ForgettingDecision {
  id: string;
  action: ForgettingAction;
  reason_code: string;
  reason: string;
  /** archive_trace 时必须携带，表示痕迹归属 */
  trace?: ForgettingTrace;
}

export interface M1Overflow {
  id: string;
  reason: string;
  access_count: number;
  last_used_at?: number;
}

export interface ForgettingPlan {
  decisions: ForgettingDecision[];
  counts: Record<ForgettingAction, number>;
  m1_overflow: M1Overflow[];
  /** 下一步动作提示，例如 recheck_anchor / consolidate_m1 */
  next: string[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

function daysSince(now: number, record: MemoryRecord): number {
  const base =
    record.last_used_at ?? record.last_verified_at ?? record.created_at ?? now;
  return Math.max(0, (now - base) / DAY_MS);
}

function buildTrace(record: MemoryRecord): ForgettingTrace {
  return {
    id: record.id,
    subclass: record.subclass ?? undefined,
    tags: [
      record.subclass ?? "untyped",
      record.form ?? "unknown",
      ...(record.source_anchor ? ["anchored"] : []),
    ],
    summary: record.summary,
    last_used_at: record.last_used_at,
  };
}

/** 单条记录判定（纯函数，不读写存储）。 */
export function decideForgetting(
  record: MemoryRecord,
  options: ForgettingOptions = {},
): ForgettingDecision {
  const now = options.now ?? Date.now();
  const graceDays = options.grace_days ?? 7;
  const deletionTestPassed = options.deletion_test_passed ?? false;

  if (!record.subclass) {
    return {
      id: record.id,
      action: "keep",
      reason_code: "policy_frozen",
      reason: "未分型存量按 D-policy 冻结，不自动降级/删除",
    };
  }
  if (record.subclass === "policy") {
    return {
      id: record.id,
      action: "keep",
      reason_code: "policy_frozen",
      reason: "D-policy 永不自动降级/删除",
    };
  }
  if (record.pinned) {
    return {
      id: record.id,
      action: "keep",
      reason_code: "pinned",
      reason: "人工 pin，跳过自动治理",
    };
  }

  const effectiveState: VerifyState =
    record.anchor_exists === false ? "degraded" : record.verify_state ?? "verified";
  const ageDays = daysSince(now, record);
  const isRuntime = record.subclass === "runtime";
  const beyondGrace = ageDays > graceDays;

  if (effectiveState === "verified") {
    return {
      id: record.id,
      action: "keep",
      reason_code: "verified",
      reason: "事实源复核通过，时间不参与降级",
    };
  }

  if (effectiveState === "degraded") {
    if (isRuntime && beyondGrace && deletionTestPassed) {
      return {
        id: record.id,
        action: "archive_trace",
        reason_code: "degraded_runtime_grace_expired",
        reason: "运行期记忆已失效且超宽限期，降为痕迹池",
        trace: buildTrace(record),
      };
    }
    return {
      id: record.id,
      action: "demote",
      reason_code: isRuntime ? "degraded_runtime" : "degraded",
      reason: "已被推翻或锚点失效，先移出检索索引（可逆）",
    };
  }

  // stale：可召回但带 verify_state=stale，只有运行期短期经验会继续降级
  if (isRuntime && beyondGrace) {
    if (deletionTestPassed) {
      return {
        id: record.id,
        action: "archive_trace",
        reason_code: "stale_runtime_grace_expired",
        reason: "运行期记忆超宽限期，降为痕迹池",
        trace: buildTrace(record),
      };
    }
    return {
      id: record.id,
      action: "demote",
      reason_code: "stale_runtime_grace_expired",
      reason: "运行期记忆超宽限期，删除测试集未通过，只降级",
    };
  }

  return {
    id: record.id,
    action: "keep",
    reason_code: isRuntime ? "stale_within_grace" : "stale_kept",
    reason: "仍可召回，结果需标注 verify_state=stale",
  };
}

/** 全量调度：逐条判定 + M1 容量门。 */
export function buildForgettingPlan(
  records: MemoryRecord[],
  options: ForgettingOptions = {},
): ForgettingPlan {
  const m1Limit = options.m1_limit ?? 150;
  const decisions = records.map((record) => decideForgetting(record, options));
  const counts: Record<ForgettingAction, number> = {
    keep: 0,
    demote: 0,
    archive_trace: 0,
  };
  for (const decision of decisions) counts[decision.action] += 1;

  const activeM1 = records
    .filter(
      (record, index) =>
        record.form === "M1" && decisions[index].action === "keep",
    )
    .sort((left, right) => {
      const byAccess = (left.access_count ?? 0) - (right.access_count ?? 0);
      if (byAccess !== 0) return byAccess;
      return (left.last_used_at ?? 0) - (right.last_used_at ?? 0);
    });

  const overflow = Math.max(0, activeM1.length - m1Limit);
  const m1Overflow: M1Overflow[] = activeM1.slice(0, overflow).map((record) => ({
    id: record.id,
    reason: "m1_cap_exceeded",
    access_count: record.access_count ?? 0,
    last_used_at: record.last_used_at,
  }));

  const next: string[] = [];
  if (
    decisions.some(
      (decision) =>
        decision.reason_code.startsWith("degraded") ||
        decision.reason_code.startsWith("stale"),
    )
  ) {
    next.push("recheck_anchor");
  }
  if (m1Overflow.length > 0) next.push("consolidate_m1");

  return { decisions, counts, m1_overflow: m1Overflow, next };
}
