// ============================================================================
// 管理台写请求客户端（浏览器端共用，SPEC-7 §8.1/§8.2）
// ----------------------------------------------------------------------------
// 统一注入 Idempotency-Key、解析 {success,data,error,message} 契约，
// 并提供 L1 二次确认令牌获取。禁止在此模块引入服务端依赖。
// ============================================================================

export interface WriteApiResult<T = Record<string, unknown>> {
  ok: boolean;
  data: T | null;
  error?: string;
  message?: string;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `key-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export async function postWrite<T = Record<string, unknown>>(
  url: string,
  body: unknown,
): Promise<WriteApiResult<T>> {
  return sendWrite<T>("POST", url, body);
}

export async function patchWrite<T = Record<string, unknown>>(
  url: string,
  body: unknown,
): Promise<WriteApiResult<T>> {
  return sendWrite<T>("PATCH", url, body);
}

export async function sendWrite<T = Record<string, unknown>>(
  method: "POST" | "PATCH",
  url: string,
  body: unknown,
): Promise<WriteApiResult<T>> {
  try {
    const res = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": newIdempotencyKey(),
      },
      body: JSON.stringify(body),
    });
    const json = (await res.json().catch(() => null)) as
      | { success?: boolean; data?: T; error?: string; message?: string }
      | null;
    if (!res.ok || !json?.success) {
      return {
        ok: false,
        data: null,
        error: json?.error || `HTTP_${res.status}`,
        message: json?.message || "请求失败",
      };
    }
    return { ok: true, data: json.data ?? null, message: json.message };
  } catch (error) {
    return {
      ok: false,
      data: null,
      error: "NETWORK_ERROR",
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

/** L1 二次确认：返回一次性 confirmToken */
export async function fetchConfirmToken(
  action: string,
  targetId: string,
  payload: unknown,
): Promise<{ ok: boolean; token?: string; message?: string }> {
  const result = await postWrite<{ token: string; exp: number }>("/api/admin/confirm-token", {
    action,
    targetId,
    payload,
  });
  if (!result.ok || !result.data?.token) {
    return { ok: false, message: result.message || "确认令牌获取失败" };
  }
  return { ok: true, token: result.data.token };
}

/** warnings 统一转可读文本 */
export function describeWarnings(warnings: unknown): string {
  if (!Array.isArray(warnings) || warnings.length === 0) return "";
  return warnings
    .map((item) => {
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        return `${String(record.kind || "warning")}: ${String(record.error || "")}`;
      }
      return String(item);
    })
    .join("；");
}
