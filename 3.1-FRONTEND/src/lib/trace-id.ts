/**
 * trace_id 生成器 — L1 可观测性试点
 *
 * 格式: {YYYYMMDD}-{HHMMSS}-{SYS}-{NANOID8}
 * 示例: 20260929-143022-FE-a3f9k2m1
 *
 * SPEC: 1-ARCHITECTURE/SPEC-20260929-L1-TRACE-PILOT.md §3.1
 */

export type SystemCode = 'FE' | 'DOS' | 'DSH' | 'HUB';

const NANOID_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789';

function nanoid8(): string {
  let s = '';
  for (let i = 0; i < 8; i++) {
    s += NANOID_CHARS[Math.floor(Math.random() * NANOID_CHARS.length)];
  }
  return s;
}

function pad(n: number, len: number): string {
  return String(n).padStart(len, '0');
}

/**
 * 生成 trace_id
 * @param sysCode 生成系统码 (FE=前端, DOS=DreamOS, DSH=DSH, HUB=中台)
 */
export function generateTraceId(sysCode: SystemCode = 'FE'): string {
  const now = new Date();
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1, 2)}${pad(now.getDate(), 2)}`;
  const time = `${pad(now.getHours(), 2)}${pad(now.getMinutes(), 2)}${pad(now.getSeconds(), 2)}`;
  return `${date}-${time}-${sysCode}-${nanoid8()}`;
}

/**
 * 验证 trace_id 格式
 */
export function isValidTraceId(id: string): boolean {
  return /^\d{8}-\d{6}-(FE|DOS|DSH|HUB)-[a-z0-9]{8}$/.test(id);
}

/**
 * 从 trace_id 提取日期 (YYYY-MM-DD)
 */
export function traceIdToDate(traceId: string): string | null {
  const m = traceId.match(/^(\d{4})(\d{2})(\d{2})-/);
  if (!m) return null;
  return `${m[1]}-${m[2]}-${m[3]}`;
}
