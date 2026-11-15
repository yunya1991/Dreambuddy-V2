// ============================================================================
// 写操作门禁（SPEC-7 §12.1 / ADR-9）
// ----------------------------------------------------------------------------
// 三重门禁：INSTANCE_ROLE 必须是 cloud/local；ADMIN_WRITE_ENABLED 必须为真；
// DATABASE_URL 的 host 必须在 ADMIN_ALLOWED_DB_HOSTS 白名单内。
// 任一不满足 → 写服务整体拒绝（UI 退化为只读），防止本地误写生产库。
// ============================================================================

import { AdminError } from "./errors";
import {
  ENV_ADMIN_ALLOWED_DB_HOSTS,
  ENV_ADMIN_WRITE_ENABLED,
  ENV_INSTANCE_ROLE,
} from "./constants";

export interface WriteGateStatus {
  enabled: boolean;
  reasons: string[];
  instanceRole: string;
  dbHost: string;
}

function parseDbHost(raw: string | undefined): string {
  if (!raw) return "";
  try {
    // postgresql://user@host:port/db?schema=public
    const withoutScheme = raw.replace(/^[a-zA-Z0-9+.-]+:\/\//, "");
    const afterCreds = withoutScheme.includes("@")
      ? withoutScheme.slice(withoutScheme.lastIndexOf("@") + 1)
      : withoutScheme;
    const hostPort = afterCreds.split("/")[0];
    return hostPort.split(":")[0].toLowerCase();
  } catch {
    return "";
  }
}

export function evaluateWriteGate(): WriteGateStatus {
  const reasons: string[] = [];
  const instanceRole = (process.env[ENV_INSTANCE_ROLE] || "").toLowerCase();
  const writeEnabled = (process.env[ENV_ADMIN_WRITE_ENABLED] || "").toLowerCase();
  const dbHost = parseDbHost(process.env.DATABASE_URL);

  if (instanceRole !== "cloud" && instanceRole !== "local") {
    reasons.push(`${ENV_INSTANCE_ROLE} 必须是 cloud 或 local（当前：${instanceRole || "空"}）`);
  }
  if (writeEnabled !== "1" && writeEnabled !== "true") {
    reasons.push(`${ENV_ADMIN_WRITE_ENABLED} 未开启（当前：${writeEnabled || "空"}）`);
  }
  const allowed = (process.env[ENV_ADMIN_ALLOWED_DB_HOSTS] || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  if (!dbHost) {
    reasons.push("无法从 DATABASE_URL 解析数据库 host");
  } else if (!allowed.includes(dbHost)) {
    reasons.push(
      `数据库 host ${dbHost} 不在 ${ENV_ADMIN_ALLOWED_DB_HOSTS} 白名单（${allowed.join(",") || "空"}）`,
    );
  }

  return { enabled: reasons.length === 0, reasons, instanceRole, dbHost };
}

export function isAdminWriteEnabled(): boolean {
  return evaluateWriteGate().enabled;
}

/** 写处理器入口调用：门禁不通过直接 503 WRITE_DISABLED */
export function assertWriteEnabled(): void {
  const gate = evaluateWriteGate();
  if (!gate.enabled) {
    throw new AdminError("WRITE_DISABLED", "当前实例为只读模式", {
      reasons: gate.reasons,
    });
  }
}
