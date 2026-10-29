import * as fs from "fs";
import * as path from "path";

/**
 * 40-周期神经网络系统 产出物只读数据层
 *
 * 红线约束（SPEC v0.8 路1 接入规格）：
 * - 只读访问 40 系统产出物，不做任何写入
 * - 前端呈现必须标注研究建议，与交易 UI 隔离
 * - 消费 effective_confidence 而非原始置信度
 */

export const CYCLE_SYSTEM_DIR = "/home/luke/dreambuddy/40-周期神经网络系统";

export const CYCLE_DISCLAIMER =
  "研究建议，非交易信号；仓位为建议区间，交易决策归 23 系统三步门禁";

/** 产出物文件清单（只读白名单） */
export const CYCLE_ARTIFACT_FILES = [
  "cycle_state.json",
  "asset_rotation.json",
  "strategy_mapping.json",
  "execution_state.json",
  "execution_trades.jsonl",
  "fund_flow.json",
  "meme_platform.json",
  "sector_transmission.json",
  "stagflation_correction_table.json",
  "stovall_breadth.json",
  "washout_verdicts.json",
  "x1_metrics_status.json",
] as const;

export type CycleArtifactFile = (typeof CYCLE_ARTIFACT_FILES)[number];

function resolveArtifactPath(fileName: string): string | null {
  // 安全校验：仅允许白名单内文件名，禁止路径穿越
  if (!CYCLE_ARTIFACT_FILES.includes(fileName as CycleArtifactFile)) {
    return null;
  }
  const resolved = path.resolve(CYCLE_SYSTEM_DIR, fileName);
  const root = path.resolve(CYCLE_SYSTEM_DIR);
  if (!resolved.startsWith(root + path.sep)) {
    return null;
  }
  return resolved;
}

export interface ArtifactReadResult {
  ok: boolean;
  data?: unknown;
  error?: string;
  file?: string;
  size_bytes?: number;
  modified_at?: string;
}

/** 只读读取单个产出物 JSON 文件 */
export function readCycleArtifact(fileName: string): ArtifactReadResult {
  const filePath = resolveArtifactPath(fileName);
  if (!filePath) {
    return { ok: false, error: "file not in cycle artifact whitelist", file: fileName };
  }
  try {
    if (!fs.existsSync(filePath)) {
      return { ok: false, error: "file not found", file: fileName };
    }
    const content = fs.readFileSync(filePath, "utf-8");
    const stat = fs.statSync(filePath);
    let data: unknown;
    if (fileName.endsWith(".jsonl")) {
      data = content
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
        .map((line) => {
          try {
            return JSON.parse(line);
          } catch {
            return { _parse_error: true, raw: line.slice(0, 200) };
          }
        });
    } else {
      data = JSON.parse(content);
    }
    return {
      ok: true,
      file: fileName,
      data,
      size_bytes: stat.size,
      modified_at: stat.mtime.toISOString(),
    };
  } catch (err) {
    return {
      ok: false,
      error: `failed to read ${fileName}: ${err instanceof Error ? err.message : String(err)}`,
      file: fileName,
    };
  }
}

/** 读取 execution_trades.jsonl 尾部 N 条（默认最近 50 条） */
export function readRecentTrades(limit = 50): ArtifactReadResult {
  const filePath = resolveArtifactPath("execution_trades.jsonl");
  if (!filePath) {
    return { ok: false, error: "trades file not allowed" };
  }
  try {
    if (!fs.existsSync(filePath)) {
      return { ok: false, error: "file not found", file: "execution_trades.jsonl" };
    }
    const content = fs.readFileSync(filePath, "utf-8");
    const stat = fs.statSync(filePath);
    const records = content
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return { _parse_error: true };
        }
      });
    return {
      ok: true,
      file: "execution_trades.jsonl",
      data: records.slice(-limit),
      size_bytes: stat.size,
      modified_at: stat.mtime.toISOString(),
    };
  } catch (err) {
    return {
      ok: false,
      error: `failed to read trades: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

/** 列出全部产出物文件清单（名称/大小/修改时间） */
export function listCycleArtifacts(): Array<{
  file: string;
  size_bytes: number;
  modified_at: string;
}> {
  const items: Array<{ file: string; size_bytes: number; modified_at: string }> = [];
  for (const fileName of CYCLE_ARTIFACT_FILES) {
    const filePath = resolveArtifactPath(fileName);
    if (!filePath) continue;
    try {
      if (!fs.existsSync(filePath)) continue;
      const stat = fs.statSync(filePath);
      items.push({
        file: fileName,
        size_bytes: stat.size,
        modified_at: stat.mtime.toISOString(),
      });
    } catch {
      // 单文件失败跳过，不影响清单整体
    }
  }
  return items;
}

/** 提取 effective_confidence（红线：前端消费 effective_confidence 而非原始置信度） */
export function extractEffectiveConfidence(strategyMapping: unknown): string | null {
  if (
    strategyMapping &&
    typeof strategyMapping === "object" &&
    "risk_guards" in (strategyMapping as Record<string, unknown>) &&
    (strategyMapping as Record<string, unknown>).risk_guards &&
    typeof (strategyMapping as Record<string, unknown>).risk_guards === "object"
  ) {
    const rg = (strategyMapping as Record<string, unknown>).risk_guards as Record<string, unknown>;
    if ("effective_confidence" in rg && typeof rg.effective_confidence === "string") {
      return rg.effective_confidence;
    }
  }
  if (
    strategyMapping &&
    typeof strategyMapping === "object" &&
    "inputs" in (strategyMapping as Record<string, unknown>)
  ) {
    const inputs = (strategyMapping as Record<string, unknown>).inputs as Record<string, unknown>;
    if (inputs && typeof inputs.effective_confidence === "string") {
      return inputs.effective_confidence;
    }
  }
  return null;
}
