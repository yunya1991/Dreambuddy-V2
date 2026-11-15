// ============================================================================
// param_center 覆盖文件（SPEC-7 §6.4 / §16-3 / G3 硬下限）
// ----------------------------------------------------------------------------
// 路径：16-调控系统/config/param_center_override.json（只由中台 L2 审批后写入）
// 允许键：sl_floor / tp_floor / rr_ratio_target / atr_mult_range
// 硬下限：SL≥4%、TP≥12%、RR≥2、ATR∈[2,6]——任何提案/执行都不得突破。
// 文件不存在时按空对象处理（首次写入自动创建）。
// ============================================================================

import { PARAM_CENTER_FLOORS } from "../constants.ts";
import { AdminError } from "../errors.ts";
import {
  readConfigFile,
  resolveConfigPath,
  type FilePatchPlan,
  type FileSnapshot,
} from "./file-config.ts";

export const PARAM_CENTER_OVERRIDE_KEYS = [
  "sl_floor",
  "tp_floor",
  "rr_ratio_target",
  "atr_mult_range",
] as const;

/** SL floor 上限（防止把止损放宽到不可交易区间） */
const SL_FLOOR_MAX = 0.5;
const TP_FLOOR_MAX = 1;
const RR_RATIO_MAX = 10;

function assertNumber(dotted: string, value: unknown, min: number, max: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) {
    throw new AdminError("VALIDATION_FAILED", `${dotted} 必须是 ${min}~${max} 之间的数值`);
  }
  return value;
}

/**
 * 校验并生成覆盖文件 patch。
 * before/after 只含本次改动键；next 为合并后的完整对象。
 */
export function planParamCenterPatch(
  current: Record<string, unknown>,
  patch: Record<string, unknown>,
): FilePatchPlan {
  const entries = Object.entries(patch);
  if (entries.length === 0) {
    throw new AdminError("VALIDATION_FAILED", "patch 不能为空");
  }
  const next = JSON.parse(JSON.stringify(current)) as Record<string, unknown>;
  const before: Record<string, unknown> = {};
  const after: Record<string, unknown> = {};

  for (const [dotted, value] of entries) {
    if (!(PARAM_CENTER_OVERRIDE_KEYS as readonly string[]).includes(dotted)) {
      throw new AdminError("VALIDATION_FAILED", `不允许写入的配置项：${dotted}`);
    }
    let normalized: unknown;
    if (dotted === "sl_floor") {
      normalized = assertNumber(
        dotted,
        value,
        PARAM_CENTER_FLOORS.slFloorMin,
        SL_FLOOR_MAX,
      );
    } else if (dotted === "tp_floor") {
      normalized = assertNumber(
        dotted,
        value,
        PARAM_CENTER_FLOORS.tpFloorMin,
        TP_FLOOR_MAX,
      );
    } else if (dotted === "rr_ratio_target") {
      normalized = assertNumber(
        dotted,
        value,
        PARAM_CENTER_FLOORS.rrRatioMin,
        RR_RATIO_MAX,
      );
    } else {
      if (!Array.isArray(value) || value.length !== 2) {
        throw new AdminError("VALIDATION_FAILED", `${dotted} 必须是 [min,max] 两个数值`);
      }
      const low = assertNumber(
        `${dotted}[0]`,
        value[0],
        PARAM_CENTER_FLOORS.atrMultMin,
        PARAM_CENTER_FLOORS.atrMultMax,
      );
      const high = assertNumber(
        `${dotted}[1]`,
        value[1],
        PARAM_CENTER_FLOORS.atrMultMin,
        PARAM_CENTER_FLOORS.atrMultMax,
      );
      if (low > high) {
        throw new AdminError("VALIDATION_FAILED", `${dotted} 需满足 min ≤ max`);
      }
      normalized = [low, high];
    }
    before[dotted] = current[dotted] ?? null;
    after[dotted] = normalized;
    next[dotted] = normalized;
  }

  return { before, after, next };
}

/** 读取覆盖文件；不存在视为空对象（首次 L2 写入自动创建） */
export async function readParamCenterOverride(): Promise<FileSnapshot> {
  try {
    return await readConfigFile("param_center");
  } catch (error) {
    if (error instanceof AdminError && error.code === "NOT_FOUND") {
      return { filePath: resolveConfigPath("param_center"), mtimeMs: 0, data: {} };
    }
    throw error;
  }
}
