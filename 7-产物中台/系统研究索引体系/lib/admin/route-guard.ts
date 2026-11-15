// ============================================================================
// 路由鉴权包装（SPEC-7 §5.1）
// ----------------------------------------------------------------------------
// 所有 /api/admin/** 处理器（含存量只读接口）第一行必须调用本函数：
//   const denied = await requireAdminOrResponse();
//   if (denied) return denied;
// middleware 只判 cookie 是否存在，真正的角色校验在这里完成。
// ============================================================================

import { requireAdmin } from "./auth";
import { apiFail, newRequestId } from "./errors";

export async function requireAdminOrResponse(): Promise<Response | null> {
  try {
    await requireAdmin();
    return null;
  } catch (error) {
    return apiFail(
      error instanceof Error ? error : new Error(String(error)),
      newRequestId(),
    );
  }
}
