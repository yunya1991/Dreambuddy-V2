/**
 * 服务端会话角色读取（配额豁免用）。
 *
 * 规则：只有 ADMIN 免配额限制（不限 CU / 不因余额为 0 锁定）。
 * FAIL-CLOSED：鉴权不可用、无会话、角色缺失时一律按非管理员处理。
 */
import { auth } from "@/lib/auth";

export async function getSessionRole(): Promise<string | null> {
  try {
    const session = await auth();
    const role = (session?.user as { role?: unknown } | undefined)?.role;
    return typeof role === "string" ? role : null;
  } catch {
    return null;
  }
}

export async function isAdminSession(): Promise<boolean> {
  return (await getSessionRole()) === "ADMIN";
}
