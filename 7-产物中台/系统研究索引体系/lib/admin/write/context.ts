// ============================================================================
// 写处理器统一入口（SPEC-7 §4.1 步骤 1-4）
// ----------------------------------------------------------------------------
// 固定顺序：同源 → 鉴权（查库 role）→ 实例门禁 → 限流 → 幂等键。
// 任何一步失败都在落库前抛出，符合「鉴权/校验失败零落库」硬要求。
// ============================================================================

import { AdminError, assertSameOrigin, newRequestId } from "../errors";
import { requireAdmin, type AdminActor } from "../auth";
import { assertWriteEnabled } from "../gate";
import { assertWithinRateLimit } from "../rate-limit";
import { requireIdempotencyKey } from "./idempotency";
import { hashPayload } from "../confirm-token";

export interface WriteContext {
  actor: AdminActor;
  requestId: string;
  idempotencyKey: string;
  dryRun: boolean;
  ip: string | null;
  userAgent: string | null;
}

export async function beginWrite(request: Request): Promise<WriteContext> {
  assertSameOrigin(request);
  const actor = await requireAdmin();
  assertWriteEnabled();
  assertWithinRateLimit(actor.uid);

  const url = new URL(request.url);
  const forwarded = request.headers.get("x-forwarded-for");
  return {
    actor,
    requestId: newRequestId(),
    idempotencyKey: requireIdempotencyKey(request),
    dryRun: url.searchParams.get("dryRun") === "1",
    ip: forwarded?.split(",")[0]?.trim() || request.headers.get("x-real-ip"),
    userAgent: request.headers.get("user-agent"),
  };
}

/** 写请求体必须是 JSON 对象；空 body / 数组一律拒绝 */
export async function readJsonBody(request: Request): Promise<Record<string, unknown>> {
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new AdminError("VALIDATION_FAILED", "请求体必须是 JSON 对象");
  }
  return body as Record<string, unknown>;
}

/** 去掉 confirmToken 后的载荷：确认令牌绑定的是「真实业务载荷」 */
export function payloadWithoutToken(body: Record<string, unknown>): Record<string, unknown> {
  const rest: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(body)) {
    if (key === "confirmToken") continue;
    rest[key] = value;
  }
  return rest;
}

/** 本次业务载荷指纹（签发与校验必须同源同函数） */
export function fingerprintBody(body: Record<string, unknown>): string {
  return hashPayload(payloadWithoutToken(body));
}
