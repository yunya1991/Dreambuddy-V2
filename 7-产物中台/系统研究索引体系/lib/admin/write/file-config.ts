// ============================================================================
// FileConfigWriter：白名单 JSON 文件配置写入（SPEC-7 §10 / ADR-5）
// ----------------------------------------------------------------------------
// 安全链路：fileKey 枚举 → 常量路径 → 可写规格表（FILE_WRITE_SPECS）
//           → 白名单 key + 类型校验 → 快照 → 临时文件 → rename 原子替换 → 回读比对。
// 任何一步失败都不留下半写文件。
// 在线生效：monitor 每轮重建 UnifiedMonitor() 并重读本文件，requiresRestart=false；
//           trailing_stop 由执行侧启动时加载，requiresRestart=true。
// ============================================================================

import fs from "node:fs/promises";
import path from "node:path";
import {
  ADMIN_BACKUP_DIR,
  ADMIN_FILE_KEYS,
  MONITOR_MAX_IDLE_MINUTES_MAX,
  MONITOR_MAX_IDLE_MINUTES_MIN,
  MONITOR_WRITABLE_LEAVES,
  TRAILING_STOP_OUTPUT_DIR_MAX_LEN,
  TRAILING_STOP_SECONDS_MAX,
  TRAILING_STOP_SECONDS_MIN,
  type AdminFileKey,
} from "../constants.ts";
import { AdminError } from "../errors.ts";

export function repoRoot(): string {
  return process.env.DREAMBUDDY_ROOT || path.resolve(process.cwd(), "../..");
}

/**
 * 进程内串行化文件写（PM2 instances=1；跨进程由 expectedMtimeMs + rename 兜底）。
 * 写入与回滚共用同一条链，避免两个请求交叉 rename。
 */
let fileWriteChain: Promise<unknown> = Promise.resolve();
export function serializeFileWrite<T>(task: () => Promise<T>): Promise<T> {
  const next = fileWriteChain.then(task, task);
  fileWriteChain = next.catch(() => undefined);
  return next;
}

/** fileKey → 绝对路径；并做一次越界断言（常量映射仍防御） */
export function resolveConfigPath(key: AdminFileKey): string {
  const root = repoRoot();
  const abs = path.resolve(root, ADMIN_FILE_KEYS[key]);
  if (!abs.startsWith(`${root}${path.sep}`)) {
    throw new AdminError("VALIDATION_FAILED", "配置路径越界");
  }
  return abs;
}

export function isAdminFileKey(value: string): value is AdminFileKey {
  return Object.prototype.hasOwnProperty.call(ADMIN_FILE_KEYS, value);
}

export interface FileSnapshot {
  filePath: string;
  mtimeMs: number;
  data: Record<string, unknown>;
}

export async function readConfigFile(key: AdminFileKey): Promise<FileSnapshot> {
  const filePath = resolveConfigPath(key);
  let raw: string;
  let stat;
  try {
    stat = await fs.stat(filePath);
    raw = await fs.readFile(filePath, "utf8");
  } catch {
    throw new AdminError("NOT_FOUND", "配置文件不存在");
  }
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new AdminError("VALIDATION_FAILED", "配置文件不是合法 JSON");
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new AdminError("VALIDATION_FAILED", "配置文件顶层必须是对象");
  }
  return { filePath, mtimeMs: stat.mtimeMs, data: data as Record<string, unknown> };
}

function readPath(source: Record<string, unknown>, dotted: string): unknown {
  return dotted.split(".").reduce<unknown>((acc, key) => {
    if (acc && typeof acc === "object" && !Array.isArray(acc)) {
      return (acc as Record<string, unknown>)[key];
    }
    return undefined;
  }, source);
}

function writePath(target: Record<string, unknown>, dotted: string, value: unknown): void {
  const keys = dotted.split(".");
  let cursor: Record<string, unknown> = target;
  for (let i = 0; i < keys.length - 1; i += 1) {
    const next = cursor[keys[i]];
    if (!next || typeof next !== "object" || Array.isArray(next)) {
      throw new AdminError("VALIDATION_FAILED", `配置路径不存在：${keys.slice(0, i + 1).join(".")}`);
    }
    cursor = next as Record<string, unknown>;
  }
  cursor[keys[keys.length - 1]] = value;
}

export interface FilePatchPlan {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  next: Record<string, unknown>;
}

function assertBoolean(dotted: string, value: unknown): boolean {
  if (typeof value !== "boolean") {
    throw new AdminError("VALIDATION_FAILED", `${dotted} 必须是布尔值`);
  }
  return value;
}

function assertInteger(dotted: string, value: unknown, min: number, max: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    throw new AdminError("VALIDATION_FAILED", `${dotted} 必须是 ${min}~${max} 的整数`);
  }
  return value;
}

/** 报告输出目录：只接受仓库内相对路径（拒绝绝对路径、盘符与 ..） */
function assertRelativeDir(dotted: string, value: unknown, maxLength: number): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new AdminError("VALIDATION_FAILED", `${dotted} 必须是非空字符串`);
  }
  const trimmed = value.trim();
  if (trimmed.length > maxLength) {
    throw new AdminError("VALIDATION_FAILED", `${dotted} 长度不得超过 ${maxLength}`);
  }
  if (path.isAbsolute(trimmed) || /^[A-Za-z]:[\\/]/.test(trimmed)) {
    throw new AdminError("VALIDATION_FAILED", `${dotted} 必须是相对路径`);
  }
  if (trimmed.split(/[\\/]+/).some((segment) => segment === "..")) {
    throw new AdminError("VALIDATION_FAILED", `${dotted} 不允许包含 ..`);
  }
  return trimmed;
}

/** 统一执行「白名单 + 类型校验 → before/after/next」，resolve 返回规范化后的值 */
function applyPatch(
  current: Record<string, unknown>,
  patch: Record<string, unknown>,
  resolve: (dotted: string, value: unknown) => unknown,
): FilePatchPlan {
  const entries = Object.entries(patch);
  if (entries.length === 0) {
    throw new AdminError("VALIDATION_FAILED", "patch 不能为空");
  }
  const next = JSON.parse(JSON.stringify(current)) as Record<string, unknown>;
  const before: Record<string, unknown> = {};
  const after: Record<string, unknown> = {};

  for (const [dotted, value] of entries) {
    const normalized = resolve(dotted, value);
    before[dotted] = readPath(current, dotted) ?? null;
    after[dotted] = normalized;
    writePath(next, dotted, normalized);
  }

  return { before, after, next };
}

/**
 * monitor_config 白名单：
 *   systems.<systemName>.enabled            boolean
 *   systems.<systemName>.max_idle_minutes   integer ∈ [1,1440]
 * systemName 必须已存在于当前配置（不允许凭空新增系统）。
 */
export function planMonitorPatch(
  current: Record<string, unknown>,
  patch: Record<string, unknown>,
): FilePatchPlan {
  const systems = current.systems;
  if (!systems || typeof systems !== "object" || Array.isArray(systems)) {
    throw new AdminError("VALIDATION_FAILED", "monitor 配置缺少 systems 节点");
  }
  const systemNames = Object.keys(systems as Record<string, unknown>);

  return applyPatch(current, patch, (dotted, value) => {
    const parts = dotted.split(".");
    if (parts.length !== 3 || parts[0] !== "systems") {
      throw new AdminError("VALIDATION_FAILED", `不允许写入的配置项：${dotted}`);
    }
    const [, systemName, leaf] = parts;
    if (!systemNames.includes(systemName)) {
      throw new AdminError("RULE_BLOCKED", `未知系统：${systemName}`);
    }
    if (!(MONITOR_WRITABLE_LEAVES as readonly string[]).includes(leaf)) {
      throw new AdminError("VALIDATION_FAILED", `不允许写入的配置项：${dotted}`);
    }
    return leaf === "enabled"
      ? assertBoolean(dotted, value)
      : assertInteger(
          dotted,
          value,
          MONITOR_MAX_IDLE_MINUTES_MIN,
          MONITOR_MAX_IDLE_MINUTES_MAX,
        );
  });
}

/**
 * trailing_stop_config 白名单（SPEC-7 §10）：
 *   trigger_cooldown_sec   integer ∈ [0,86400]
 *   auto_close_after_sec   integer ∈ [0,86400]
 *   report.enabled         boolean
 *   report.output_dir      仓库内相对路径
 * 写入后下游执行侧需重启才生效。
 */
export function planTrailingStopPatch(
  current: Record<string, unknown>,
  patch: Record<string, unknown>,
): FilePatchPlan {
  const report = current.report;
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    throw new AdminError("VALIDATION_FAILED", "trailing_stop 配置缺少 report 节点");
  }

  return applyPatch(current, patch, (dotted, value) => {
    if (dotted === "trigger_cooldown_sec" || dotted === "auto_close_after_sec") {
      return assertInteger(
        dotted,
        value,
        TRAILING_STOP_SECONDS_MIN,
        TRAILING_STOP_SECONDS_MAX,
      );
    }
    if (dotted === "report.enabled") {
      return assertBoolean(dotted, value);
    }
    if (dotted === "report.output_dir") {
      return assertRelativeDir(dotted, value, TRAILING_STOP_OUTPUT_DIR_MAX_LEN);
    }
    throw new AdminError("VALIDATION_FAILED", `不允许写入的配置项：${dotted}`);
  });
}

export interface FileWriteSpec {
  /** 写入后是否需要重启下游服务 */
  requiresRestart: boolean;
  /** UI / 响应文案用短名 */
  label: string;
  plan: (current: Record<string, unknown>, patch: Record<string, unknown>) => FilePatchPlan;
}

/**
 * 可写文件配置注册表（ADR-5）。
 * 只有登记在册的 fileKey 允许 PATCH；capital_control / capital_allocator 仅 L2 提案。
 */
export const FILE_WRITE_SPECS = {
  monitor: { requiresRestart: false, label: "监控开关", plan: planMonitorPatch },
  trailing_stop: { requiresRestart: true, label: "移动止损", plan: planTrailingStopPatch },
} satisfies Record<string, FileWriteSpec>;

export type WritableFileKey = keyof typeof FILE_WRITE_SPECS;

export function isWritableFileKey(value: string): value is WritableFileKey {
  return Object.prototype.hasOwnProperty.call(FILE_WRITE_SPECS, value);
}

export function planFilePatch(
  key: WritableFileKey,
  current: Record<string, unknown>,
  patch: Record<string, unknown>,
): FilePatchPlan {
  return FILE_WRITE_SPECS[key].plan(current, patch);
}

export function fileWriteSpec(key: WritableFileKey): FileWriteSpec {
  return FILE_WRITE_SPECS[key];
}

/** 快照 + 原子写 + 回读校验；返回快照文件相对仓库根的路径 */
export async function writeConfigAtomic(
  key: AdminFileKey,
  snapshot: FileSnapshot,
  next: Record<string, unknown>,
  expected: Record<string, unknown>,
): Promise<string> {
  const root = repoRoot();
  const backupDir = path.resolve(root, ADMIN_BACKUP_DIR);
  await fs.mkdir(backupDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const backupPath = path.join(backupDir, `${key}-${stamp}.json`);
  await fs.writeFile(backupPath, `${JSON.stringify(snapshot.data, null, 2)}\n`, "utf8");

  const tmpPath = `${snapshot.filePath}.tmp-${process.pid}-${Date.now()}`;
  try {
    await fs.writeFile(tmpPath, `${JSON.stringify(next, null, 2)}\n`, "utf8");
    await fs.rename(tmpPath, snapshot.filePath);
  } catch (error) {
    await fs.rm(tmpPath, { force: true }).catch(() => undefined);
    throw new AdminError(
      "INTERNAL_ERROR",
      `配置写入失败：${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const reread = await readConfigFile(key);
  for (const [dotted, value] of Object.entries(expected)) {
    if (JSON.stringify(readPath(reread.data, dotted)) !== JSON.stringify(value)) {
      throw new AdminError("INTERNAL_ERROR", `回读校验失败：${dotted} 未生效`);
    }
  }

  return path.relative(root, backupPath);
}
