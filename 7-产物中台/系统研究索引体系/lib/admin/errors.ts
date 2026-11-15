// ============================================================================
// 管理台统一错误码与响应封装（SPEC-7 §8.1）
// ============================================================================

export type AdminErrorCode =
  | "VALIDATION_FAILED"
  | "UNAUTHENTICATED"
  | "FORBIDDEN_ROLE"
  | "NOT_FOUND"
  | "CONFLICT_STALE"
  | "RULE_BLOCKED"
  | "RATE_LIMITED"
  | "BRIDGE_SYNC_FAILED"
  | "GOVERNANCE_UNAVAILABLE"
  | "WRITE_DISABLED"
  | "INTERNAL_ERROR";

const STATUS_MAP: Record<AdminErrorCode, number> = {
  VALIDATION_FAILED: 400,
  UNAUTHENTICATED: 401,
  FORBIDDEN_ROLE: 403,
  NOT_FOUND: 404,
  CONFLICT_STALE: 409,
  RULE_BLOCKED: 422,
  RATE_LIMITED: 429,
  BRIDGE_SYNC_FAILED: 502,
  GOVERNANCE_UNAVAILABLE: 503,
  WRITE_DISABLED: 503,
  INTERNAL_ERROR: 500,
};

export class AdminError extends Error {
  readonly code: AdminErrorCode;
  readonly status: number;
  readonly details?: unknown;

  constructor(code: AdminErrorCode, message?: string, details?: unknown) {
    super(message || code);
    this.name = "AdminError";
    this.code = code;
    this.status = STATUS_MAP[code];
    this.details = details;
  }
}

/** 生成请求追踪 ID（写入响应与 opLog，便于串联） */
export function newRequestId(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `req_${Date.now().toString(36)}${rand}`;
}

export function apiOk<T>(
  data: T,
  opts: { message?: string; requestId?: string; status?: number } = {},
) {
  const body = {
    success: true as const,
    data,
    requestId: opts.requestId || newRequestId(),
    message: opts.message || "ok",
  };
  return Response.json(body, {
    status: opts.status || 200,
    headers: { "Cache-Control": "no-store" },
  });
}

export function apiFail(
  error: AdminError | Error,
  requestId?: string,
): Response {
  const isAdminError = error instanceof AdminError;
  const code: AdminErrorCode = isAdminError ? error.code : "INTERNAL_ERROR";
  const status = isAdminError ? error.status : 500;
  const body = {
    success: false as const,
    data: null,
    error: code,
    message: isAdminError ? error.message : "服务内部错误",
    details: isAdminError ? error.details ?? null : null,
    requestId: requestId || newRequestId(),
  };
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

/**
 * 同源校验（CSRF 缓解）：写接口必须满足 Origin 与 Host 一致。
 * 无 Origin（服务端调用/curl）放行，由 cookie + SameSite=Lax 兜底。
 */
export function assertSameOrigin(request: Request): void {
  const origin = request.headers.get("origin");
  if (!origin) return;
  const host = request.headers.get("host");
  try {
    if (new URL(origin).host !== host) {
      throw new AdminError("FORBIDDEN_ROLE", "跨站请求被拒绝");
    }
  } catch (e) {
    if (e instanceof AdminError) throw e;
    throw new AdminError("FORBIDDEN_ROLE", "非法 Origin");
  }
}
