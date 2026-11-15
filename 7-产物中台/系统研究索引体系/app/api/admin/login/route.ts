// ============================================================================
// POST /api/admin/login —— 管理台登录（SPEC-7 §8.3）
// 仅签发独立 JWT 会话 cookie，不复用 3.1 的登录态
// ============================================================================

import { NextResponse } from "next/server";
import { z } from "zod";
import { assertSameOrigin, apiFail, AdminError, newRequestId } from "@/lib/admin/errors";
import {
  adminCookieOptions,
  issueAdminToken,
  verifyAdminCredentials,
} from "@/lib/admin/auth";
import { ADMIN_COOKIE_NAME } from "@/lib/admin/constants";
import { evaluateWriteGate } from "@/lib/admin/gate";

export const dynamic = "force-dynamic";

const loginSchema = z.object({
  email: z.string().email("邮箱格式不正确"),
  password: z.string().min(1, "密码不能为空"),
});

export async function POST(request: Request) {
  const requestId = newRequestId();
  try {
    assertSameOrigin(request);

    const body = await request.json().catch(() => null);
    const parsed = loginSchema.safeParse(body);
    if (!parsed.success) {
      throw new AdminError("VALIDATION_FAILED", "参数校验失败", {
        issues: parsed.error.issues.map((i) => ({
          path: i.path.join("."),
          message: i.message,
        })),
      });
    }

    const result = await verifyAdminCredentials(
      parsed.data.email,
      parsed.data.password,
    );
    if (!result.ok) {
      const message =
        result.reason === "LOCKED"
          ? "账号已被锁定，请稍后再试"
          : result.reason === "NOT_ADMIN"
            ? "该账号没有管理台权限"
            : "邮箱或密码错误";
      throw new AdminError("UNAUTHENTICATED", message);
    }

    const token = await issueAdminToken(result.user);
    const response = NextResponse.json(
      {
        success: true,
        data: {
          uid: result.user.uid,
          email: result.user.email,
          name: result.user.name,
          role: result.user.role,
          writeEnabled: evaluateWriteGate().enabled,
        },
        requestId,
        message: "ok",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
    response.cookies.set(ADMIN_COOKIE_NAME, token, adminCookieOptions());
    return response;
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
