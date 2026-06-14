// ============================================================================
// 推荐策略引擎: 研报读取适配器
// ============================================================================
// 从 ~/.workbuddy/artifacts/trading/index.json 读取 A1-A3 研报数据
// ============================================================================

import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import type { ResearchReport } from "./types";

// ----------------------------------------------------------------------------
// 研报目录解析
// ----------------------------------------------------------------------------

function resolveArtifactsRoot(): string {
  if (process.env.WORKBUDDY_ARTIFACTS_ROOT) {
    return process.env.WORKBUDDY_ARTIFACTS_ROOT;
  }
  return path.join(os.homedir(), ".workbuddy", "artifacts");
}

function getTradingIndexPath(): string {
  return path.join(resolveArtifactsRoot(), "trading", "index.json");
}

// ----------------------------------------------------------------------------
// 研报读取
// ----------------------------------------------------------------------------

export interface ReportReadOptions {
  /** 过滤的链阶段，默认 A1, A2, A3 */
  phases?: string[];
  /** 只读取最近 N 天的研报，默认 7 天 */
  days?: number;
  /** 最多返回数量，默认 20 */
  limit?: number;
  /** 只读取当日的研报 */
  todayOnly?: boolean;
}

export interface ReportReadResult {
  reports: ResearchReport[];
  total: number;
  readAt: string;
  sourcePath: string;
}

/**
 * 读取 A1-A3 最新研报
 */
export async function readLatestReports(
  options: ReportReadOptions = {}
): Promise<ReportReadResult> {
  const {
    phases = ["A1", "A2", "A3"],
    days = 7,
    limit = 20,
    todayOnly = false,
  } = options;

  const indexPath = getTradingIndexPath();

  let artifacts: ResearchReport[] = [];

  // 读取 index.json
  if (fs.existsSync(indexPath)) {
    try {
      const content = fs.readFileSync(indexPath, "utf-8");
      const parsed = JSON.parse(content);

      if (Array.isArray(parsed)) {
        artifacts = parsed;
      } else if (parsed.artifacts && Array.isArray(parsed.artifacts)) {
        artifacts = parsed.artifacts;
      }
    } catch (error) {
      console.error("[report-reader] Failed to parse index.json:", error);
    }
  }

  // 按链阶段过滤
  const upperPhases = phases.map((p) => p.toUpperCase());
  artifacts = artifacts.filter((a) =>
    upperPhases.includes((a.chain_phase || "").toUpperCase())
  );

  // 按日期过滤（最近 N 天）
  if (days > 0) {
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - days);
    artifacts = artifacts.filter((a) => {
      if (!a.date) return false;
      return new Date(a.date) >= cutoffDate;
    });
  }

  // 今日过滤
  if (todayOnly) {
    const todayStr = new Date().toISOString().slice(0, 10);
    artifacts = artifacts.filter((a) => {
      const artifactDate = a.date
        ? new Date(a.date).toISOString().slice(0, 10)
        : "";
      return artifactDate === todayStr;
    });
  }

  // 按日期降序
  artifacts.sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
  );

  // 限制数量
  const reports = artifacts.slice(0, limit);

  return {
    reports,
    total: artifacts.length,
    readAt: new Date().toISOString(),
    sourcePath: indexPath,
  };
}

/**
 * 读取单个研报内容
 */
export async function readReportContent(
  filename: string
): Promise<{ content: string; metadata: ResearchReport | null } | null> {
  const indexPath = getTradingIndexPath();
  const safeName = filename.replace(/[^a-zA-Z0-9_\-\.]/g, "");
  const filePath = path.join(resolveArtifactsRoot(), "trading", safeName);

  if (!fs.existsSync(filePath)) {
    return null;
  }

  let metadata: ResearchReport | null = null;

  // 从 index.json 获取元数据
  if (fs.existsSync(indexPath)) {
    try {
      const content = fs.readFileSync(indexPath, "utf-8");
      const parsed = JSON.parse(content);
      const artifacts = Array.isArray(parsed)
        ? parsed
        : parsed.artifacts || [];
      metadata =
        (artifacts as ResearchReport[]).find(
          (a) => a.file === safeName
        ) || null;
    } catch {}
  }

  const content = fs.readFileSync(filePath, "utf-8");
  return { content, metadata };
}

/**
 * 获取研报统计信息
 */
export async function getReportStats(): Promise<{
  total: number;
  byPhase: Record<string, number>;
  recentDays: number[];
  lastReportDate: string | null;
}> {
  const indexPath = getTradingIndexPath();

  let artifacts: ResearchReport[] = [];

  if (fs.existsSync(indexPath)) {
    try {
      const content = fs.readFileSync(indexPath, "utf-8");
      const parsed = JSON.parse(content);
      artifacts = Array.isArray(parsed)
        ? parsed
        : parsed.artifacts || [];
    } catch {}
  }

  const byPhase: Record<string, number> = {};
  const recentDaysSet = new Set<number>();

  for (const a of artifacts) {
    const phase = (a.chain_phase || "UNKNOWN").toUpperCase();
    byPhase[phase] = (byPhase[phase] || 0) + 1;

    if (a.date) {
      const d = new Date(a.date);
      recentDaysSet.add(d.getTime());
    }
  }

  const recentDays = Array.from(recentDaysSet)
    .sort((a, b) => b - a)
    .slice(0, 30)
    .map((t) => new Date(t).getTime());

  const sorted = artifacts
    .filter((a) => a.date)
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  return {
    total: artifacts.length,
    byPhase,
    recentDays,
    lastReportDate: sorted[0]?.date || null,
  };
}
