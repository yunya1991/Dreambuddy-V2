// ============================================================================
// POST /api/admin/jobs/audit-flush —— 内部补偿端点
// ----------------------------------------------------------------------------
// 调用方：systemd timer / launchd（每分钟），携带 X-Internal-Token。
// 不走管理员会话（middleware 对该前缀只做 token 校验放行）。
// 一次执行两类补偿：
//   1. 审计 outbox：把 27 审计推送失败的 opLog 重试至 APPLIED
//   2. Bridge outbox：把 APPLIED_WITH_WARNINGS 的非交易类下发补丁重试至 APPLIED
// 幂等：同一批重复调用安全（已成功的记录不再命中）。
// ============================================================================

import { apiFail, apiOk, AdminError, newRequestId } from "@/lib/admin/errors";
import { flushAuditOutbox } from "@/lib/admin/audit/outbox";
import { retryPendingBridgeSyncs } from "@/lib/admin/write/bridge-outbox";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const requestId = newRequestId();
  try {
    const expected = process.env.ADMIN_INTERNAL_TOKEN;
    const provided = request.headers.get("x-internal-token");
    if (!expected) {
      throw new AdminError("WRITE_DISABLED", "ADMIN_INTERNAL_TOKEN 未配置，内部端点不可用");
    }
    if (!provided || provided !== expected) {
      throw new AdminError("UNAUTHENTICATED", "内部令牌无效");
    }

    const audit = await flushAuditOutbox();
    const bridge = await retryPendingBridgeSyncs();
    return apiOk({ ...audit, bridge }, { requestId });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
