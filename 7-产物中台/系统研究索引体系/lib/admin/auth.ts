// ============================================================================
// 管理台鉴权（SPEC-7 §5.1 / ADR-7）
// ----------------------------------------------------------------------------
// 设计要点：
//   1. 与 3.1-FRONTEND 完全隔离：独立 cookie 名 + 独立 ADMIN_AUTH_SECRET
//   2. 只签发 JWT（不做 database session）：业务库 sessions 表形状不兼容
//      Auth.js adapter（字段为 id/uid/sessionToken/expiresAt）
//   3. JWT 内不携带 role —— 每个请求都回查 users.role，
//      保证降权/禁用立即生效（middleware 只判 cookie 是否存在）
//   4. 使用 next-auth v5 的 JWT 编解码原语（A256CBC-HS512），与 3.1 同版本
// ============================================================================

import { cookies } from "next/headers";
import { decode, encode } from "next-auth/jwt";
import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { AdminError } from "./errors";
import {
  ADMIN_COOKIE_NAME,
  ADMIN_LOGIN_LOCK_MINUTES,
  ADMIN_LOGIN_MAX_ATTEMPTS,
  ADMIN_SESSION_MAX_AGE_SEC,
  ENV_ADMIN_AUTH_SECRET,
} from "./constants";

export interface AdminActor {
  uid: string;
  email: string;
  name: string;
  role: "ADMIN";
}

export type LoginResult =
  | { ok: true; user: AdminActor }
  | { ok: false; reason: "INVALID_CREDENTIALS" | "LOCKED" | "NOT_ADMIN" };

/** 密钥必须显式配置，缺失即拒绝（FAIL-CLOSED），不复用 3.1 的 AUTH_SECRET */
export function getAdminAuthSecret(): string {
  const secret = process.env[ENV_ADMIN_AUTH_SECRET];
  if (!secret || secret.length < 32) {
    throw new AdminError(
      "UNAUTHENTICATED",
      `${ENV_ADMIN_AUTH_SECRET} 未配置或长度不足 32 位，管理台会话不可用`,
    );
  }
  return secret;
}

/** 校验账号密码；复用 3.1 的 loginAttempts / lockedUntil 语义 */
export async function verifyAdminCredentials(
  email: string,
  password: string,
): Promise<LoginResult> {
  const user = await prisma.user.findUnique({
    where: { email },
    select: {
      uid: true,
      email: true,
      displayName: true,
      role: true,
      passwordHash: true,
      loginAttempts: true,
      lockedUntil: true,
    },
  });

  if (!user) {
    // 不区分「用户不存在」与「密码错误」，避免账号枚举
    return { ok: false, reason: "INVALID_CREDENTIALS" };
  }

  if (user.lockedUntil && new Date() < user.lockedUntil) {
    return { ok: false, reason: "LOCKED" };
  }

  const valid = await bcrypt.compare(password, user.passwordHash);
  if (!valid) {
    const attempts = user.loginAttempts + 1;
    const lock = attempts >= ADMIN_LOGIN_MAX_ATTEMPTS;
    await prisma.user.update({
      where: { uid: user.uid },
      data: {
        loginAttempts: attempts,
        lockedUntil: lock
          ? new Date(Date.now() + ADMIN_LOGIN_LOCK_MINUTES * 60 * 1000)
          : null,
      },
    });
    return { ok: false, reason: lock ? "LOCKED" : "INVALID_CREDENTIALS" };
  }

  // 非管理员不签发会话（降权用户在后续请求也会被 requireAdmin 拦截）
  if (user.role !== "ADMIN") {
    return { ok: false, reason: "NOT_ADMIN" };
  }

  await prisma.user.update({
    where: { uid: user.uid },
    data: { loginAttempts: 0, lockedUntil: null, lastLoginAt: new Date() },
  });

  return {
    ok: true,
    user: {
      uid: user.uid,
      email: user.email,
      name: user.displayName || user.uid,
      role: "ADMIN",
    },
  };
}

/** 签发会话 JWT（salt 绑定 cookie 名，与 Auth.js 规范一致） */
export async function issueAdminToken(actor: AdminActor): Promise<string> {
  return encode({
    token: {
      uid: actor.uid,
      sub: actor.uid,
      email: actor.email,
      name: actor.name,
    },
    secret: getAdminAuthSecret(),
    salt: ADMIN_COOKIE_NAME,
    maxAge: ADMIN_SESSION_MAX_AGE_SEC,
  });
}

/** 读取当前请求的会话（仅解码，不查库） */
export async function getAdminSession(): Promise<{ uid: string; email: string } | null> {
  const raw = cookies().get(ADMIN_COOKIE_NAME)?.value;
  if (!raw) return null;
  try {
    const payload = await decode({
      token: raw,
      secret: getAdminAuthSecret(),
      salt: ADMIN_COOKIE_NAME,
    });
    if (!payload || typeof payload.uid !== "string") return null;
    if (typeof payload.exp === "number" && payload.exp * 1000 <= Date.now()) {
      return null;
    }
    return {
      uid: payload.uid,
      email: typeof payload.email === "string" ? payload.email : "",
    };
  } catch {
    // 签名错误 / 会话过期 / 跨应用 cookie 一律视为未登录
    return null;
  }
}

/**
 * 授权的唯一入口：会话 → 回查数据库 role。
 * 所有 /api/admin/** 写处理器必须先调用本函数，actorUid 只允许来自会话。
 */
export async function requireAdmin(): Promise<AdminActor> {
  const session = await getAdminSession();
  if (!session) {
    throw new AdminError("UNAUTHENTICATED", "未登录或会话已过期");
  }
  const user = await prisma.user.findUnique({
    where: { uid: session.uid },
    select: { uid: true, email: true, displayName: true, role: true },
  });
  if (!user) {
    throw new AdminError("UNAUTHENTICATED", "会话对应的账号不存在");
  }
  if (user.role !== "ADMIN") {
    throw new AdminError("FORBIDDEN_ROLE", "需要管理员权限");
  }
  return {
    uid: user.uid,
    email: user.email,
    name: user.displayName || user.uid,
    role: "ADMIN",
  };
}

/** 会话 cookie 选项（path=/ 才能同时覆盖 /admin 与 /api/admin） */
export function adminCookieOptions() {
  const secureEnv = process.env.ADMIN_COOKIE_SECURE;
  const secure = secureEnv ? secureEnv === "true" : process.env.NODE_ENV === "production";
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure,
    path: "/",
    maxAge: ADMIN_SESSION_MAX_AGE_SEC,
  };
}
