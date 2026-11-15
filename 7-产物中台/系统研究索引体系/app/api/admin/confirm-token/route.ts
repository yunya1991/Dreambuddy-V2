// ============================================================================
// POST /api/admin/confirm-token —— L1 一次性确认令牌签发（SPEC-7 §8.2）
// ----------------------------------------------------------------------------
// body: { action, targetId, payload }  → { token, nonce, exp, payloadHash }
//   · payload 为即将提交的业务载荷（不含 confirmToken），服务端计算指纹
//   · 兼容直接传 payloadHash（调用方自行按 canonicalStringify 计算）
// 有效期 60 秒；nonce 在写操作落库时占用（唯一索引冲突即重放，拒绝）。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk, assertSameOrigin, newRequestId } from "@/lib/admin/errors";
import { requireAdmin } from "@/lib/admin/auth";
import { assertWriteEnabled } from "@/lib/admin/gate";
import { assertWithinRateLimit } from "@/lib/admin/rate-limit";
import { createConfirmToken, hashPayload } from "@/lib/admin/confirm-token";
import { ADMIN_CONFIRM_TOKEN_TTL_SEC } from "@/lib/admin/constants";
import { readJsonBody } from "@/lib/admin/write/context";

export const dynamic = "force-dynamic";

const schema = z.object({
  action: z.string().min(1, "action 必填"),
  targetId: z.string().min(1, "targetId 必填"),
  payload: z.unknown().optional(),
  payloadHash: z.string().min(16).optional(),
});

export async function POST(request: Request) {
  const requestId = newRequestId();
  try {
    assertSameOrigin(request);
    const actor = await requireAdmin();
    assertWriteEnabled();
    assertWithinRateLimit(actor.uid);

    const body = await readJsonBody(request);
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new AdminError("VALIDATION_FAILED", "参数校验失败", {
        issues: parsed.error.issues.map((i) => ({
          path: i.path.join("."),
          message: i.message,
        })),
      });
    }

    const { action, targetId, payload, payloadHash } = parsed.data;
    const effectiveHash = payloadHash ?? (payload !== undefined ? hashPayload(payload) : null);
    if (!effectiveHash) {
      throw new AdminError("VALIDATION_FAILED", "payload 与 payloadHash 至少提供一个");
    }

    const { token, nonce, exp } = createConfirmToken({
      uid: actor.uid,
      action,
      targetId,
      payloadHash: effectiveHash,
    });

    return apiOk(
      { token, nonce, exp, payloadHash: effectiveHash, ttl: ADMIN_CONFIRM_TOKEN_TTL_SEC },
      { requestId, message: "ok" },
    );
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
