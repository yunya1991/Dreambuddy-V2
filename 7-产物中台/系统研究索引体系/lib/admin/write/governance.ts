// ============================================================================
// GovernanceClient：L2 审批（27 策略治理审批系统）只读/提案客户端（SPEC-7 §6.4/§9）
// ----------------------------------------------------------------------------
// - health：/health 探活（执行前 FAIL-CLOSED，不可达即拒绝执行）
// - createApproval：POST /api/v1/approvals 提交 L2 提案
// - getApproval：GET /api/v1/approvals/<id> 取最新裁决（27 以追加同 id 记录表示裁决）
// 所有调用超时 ADMIN_GOVERNANCE_TIMEOUT_MS；失败不抛异常，返回 ok:false 由调用方决定语义。
// 提示：27 的待审批记录里 decision 为空/pending，通过为 approved，驳回为 rejected。
// ============================================================================

import {
  ADMIN_GOVERNANCE_TIMEOUT_MS,
  ENV_GOVERNANCE_ADMIN_TOKEN,
  GOVERNANCE_ADMIN_TOKEN_HEADER,
  GOVERNANCE_BASE_URL,
} from "../constants.ts";
import { AdminError } from "../errors.ts";

const APPROVED_DECISIONS = new Set(["approve", "approved", "ok", "pass", "yes"]);

export interface GovernanceCallOutcome {
  ok: boolean;
  status?: number;
  error?: string;
}

async function governanceFetch(
  pathname: string,
  init: RequestInit,
): Promise<{ ok: boolean; status?: number; body?: unknown; error?: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ADMIN_GOVERNANCE_TIMEOUT_MS);
  try {
    const res = await fetch(`${GOVERNANCE_BASE_URL}${pathname}`, {
      ...init,
      signal: controller.signal,
    });
    const body = (await res.json().catch(() => null)) as unknown;
    if (!res.ok) {
      const error =
        body && typeof body === "object" && "error" in body
          ? String((body as { error?: unknown }).error)
          : `27 返回 ${res.status}`;
      return { ok: false, status: res.status, body, error };
    }
    const okFlag =
      !body || typeof body !== "object" || (body as { ok?: unknown }).ok !== false;
    return { ok: okFlag, status: res.status, body, error: okFlag ? undefined : "27 返回 ok=false" };
  } catch (error) {
    const message =
      error instanceof Error && error.name === "AbortError"
        ? `27 请求超时（${ADMIN_GOVERNANCE_TIMEOUT_MS}ms）`
        : error instanceof Error
          ? error.message
          : String(error);
    return { ok: false, error: message };
  } finally {
    clearTimeout(timer);
  }
}

/** 执行前健康检查（G3：27 不可达必须拒绝执行，而不是降级放行） */
export async function checkGovernanceHealth(): Promise<GovernanceCallOutcome> {
  const result = await governanceFetch("/health", { method: "GET" });
  return { ok: result.ok, status: result.status, error: result.error };
}

/** 提交 L2 提案；返回 27 生成的 approvalId */
export async function createApproval(
  entry: Record<string, unknown>,
): Promise<GovernanceCallOutcome & { approvalId?: string }> {
  const token = process.env[ENV_GOVERNANCE_ADMIN_TOKEN];
  if (!token) {
    return { ok: false, error: `${ENV_GOVERNANCE_ADMIN_TOKEN} 未配置` };
  }
  const result = await governanceFetch("/api/v1/approvals", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [GOVERNANCE_ADMIN_TOKEN_HEADER]: token,
    },
    body: JSON.stringify(entry),
  });
  if (!result.ok) return { ok: false, status: result.status, error: result.error };
  const body = result.body as { approval_id?: string } | null;
  const approvalId = String(body?.approval_id || "").trim();
  if (!approvalId) return { ok: false, status: result.status, error: "27 未返回 approval_id" };
  return { ok: true, status: result.status, approvalId };
}

/** 读取审批最新状态（27 以「追加同 id 记录」表示裁决，lookup 返回最后一条） */
export async function getApproval(
  approvalId: string,
): Promise<GovernanceCallOutcome & { approval?: Record<string, unknown> }> {
  const result = await governanceFetch(
    `/api/v1/approvals/${encodeURIComponent(approvalId)}`,
    { method: "GET" },
  );
  if (!result.ok) return { ok: false, status: result.status, error: result.error };
  const body = result.body as { approval?: Record<string, unknown> } | null;
  if (!body?.approval) return { ok: false, status: result.status, error: "27 未返回 approval" };
  return { ok: true, status: result.status, approval: body.approval };
}

export function isApprovedDecision(decision: unknown): boolean {
  return APPROVED_DECISIONS.has(String(decision ?? "").trim().toLowerCase());
}

/**
 * L2 执行前的审批闸门（G3）：
 *   1) 审批目标必须与被执行文件一致（防止拿 A 的审批写 B）
 *   2) 裁决必须为 approved
 *   3) 审批人必须存在且 ≠ 发起人（双人原则）
 * 不满足一律抛 AdminError，由路由映射 403/422。
 */
export function assertApprovalUsableForExecution(
  approval: Record<string, unknown> | null | undefined,
  file: string,
): { requester: string; approver: string } {
  if (!approval) {
    throw new AdminError("FORBIDDEN_ROLE", "L2 执行必须有有效的审批记录");
  }
  const target = String(approval.target ?? "").trim();
  if (target !== file) {
    throw new AdminError("RULE_BLOCKED", `审批目标（${target || "空"}）与执行文件（${file}）不一致`);
  }
  if (!isApprovedDecision(approval.decision)) {
    throw new AdminError("RULE_BLOCKED", "审批尚未通过，禁止执行");
  }
  const requester = String(approval.requester ?? "").trim();
  const approver = String(approval.approver ?? "").trim();
  if (!requester || !approver) {
    throw new AdminError("FORBIDDEN_ROLE", "审批记录缺少发起人或审批人");
  }
  if (requester === approver) {
    throw new AdminError("FORBIDDEN_ROLE", "审批人与发起人不得为同一人");
  }
  return { requester, approver };
}
