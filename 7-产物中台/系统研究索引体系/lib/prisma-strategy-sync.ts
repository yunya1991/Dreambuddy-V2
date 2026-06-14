// ============================================================================
// 策略执行记录自动沉淀机制
//
// 目标：将 Prisma SQLite 中的业务数据（策略、任务、执行）转化为 artifacts
// 索引文件，写入到 ~/.workbuddy/artifacts/trading/ 目录，
// 使 ui-map 的内容索引系统能读取到业务执行记录。
//
// 闭环：
//   用户创建策略 → Prisma 写入 → 本模块读取并沉淀 → artifacts 目录更新
//   → ui-map 页面通过 content.server.ts 读取到策略执行记录
//
// 主要函数：
//   writeStrategyExecutionArtifacts()      - 主入口：将 Prisma 策略沉淀到 artifacts
//   syncBusinessDataToArtifacts()          - 综合：将 Prisma 所有业务数据沉淀到 artifacts
//   buildStrategyExecutionArtifact()       - 构建单个策略的 artifact
//   createTradingIndexFromPrisma()         - 构建 trading/index.json（合并原索引 + 新策略）
// ============================================================================

import { PrismaClient } from "@prisma/client";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const prisma = new PrismaClient();

// ----------------------------------------------------------------------------
// 辅助：解析 artifacts 根目录
// ----------------------------------------------------------------------------
function resolveArtifactsRoot(): string {
  // 优先使用环境变量
  if (process.env.WORKBUDDY_ARTIFACTS_ROOT) {
    return process.env.WORKBUDDY_ARTIFACTS_ROOT;
  }

  // 默认：~/.workbuddy/artifacts
  return path.join(os.homedir(), ".workbuddy", "artifacts");
}

// ----------------------------------------------------------------------------
// 辅助：确保目录存在
// ----------------------------------------------------------------------------
function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

// ----------------------------------------------------------------------------
// 辅助：格式化日期
// ----------------------------------------------------------------------------
function formatDate(date: Date | string | null | undefined): string {
  if (!date) return "未执行";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toISOString();
}

// ----------------------------------------------------------------------------
// 核心函数：将 Prisma 策略执行记录写入 artifacts 目录
//
// 流程：
//   1. 读取所有策略及其关联的任务和执行
//   2. 对每个策略创建一份 artifact 文件
//   3. 更新 trading/index.json 合并原索引与新策略
// ----------------------------------------------------------------------------
export interface StrategyExecutionArtifact {
  artifactId: string;
  category: string;
  generatedAt: string;
  type: "strategy_execution";
  strategy: {
    id: string;
    uid: string;
    name: string;
    description: string | null;
    type: string;
    direction: string;
    symbol: string;
    leverage: number;
    confidence: number | null;
    status: string;
    createdAt: string;
  };
  task: {
    total: number;
    active: number;
    nextExecutionAt: string | null;
    latestStatus: string | null;
  };
  execution: {
    totalRuns: number;
    completedRuns: number;
    successRate: number;
    latestRunAt: string | null;
    latestRunStatus: string | null;
  };
}

export interface TradingIndexEntry {
  artifact_id: string;
  title: string;
  file: string;
  filename: string;
  type: string;
  status: string;
  date: string;
  chain_phase: string;
  tags: string[];
  excerpt: string;
}

export interface TradingIndexData {
  last_updated: string;
  artifacts: TradingIndexEntry[];
}

export async function writeStrategyExecutionArtifacts(): Promise<{
  written: number;
  directory: string;
  artifacts: StrategyExecutionArtifact[];
}> {
  const artifactsRoot = resolveArtifactsRoot();
  const tradingDir = path.join(artifactsRoot, "trading");
  ensureDir(tradingDir);

  // 1. 读取策略数据 + 任务 + 执行记录
  const strategies = await prisma.strategy.findMany({
    orderBy: { createdAt: "desc" },
  });

  if (!strategies.length) {
    return { written: 0, directory: tradingDir, artifacts: [] };
  }

  const writtenArtifacts: StrategyExecutionArtifact[] = [];

  // 2. 对每个策略创建 artifact 文件
  for (const strategy of strategies) {
    // 读取任务统计
    const tasks = await prisma.strategyTask.findMany({
      where: { strategyId: strategy.id },
    });

    const activeTaskCount = tasks.filter((t) => t.status === "ACTIVE").length;
    const nextExecutionDates = tasks
      .map((t) => t.nextExecutionAt)
      .filter((d): d is Date => d instanceof Date)
      .sort((a, b) => a.getTime() - b.getTime());
    const nextExecutionAt = nextExecutionDates[0]
      ? nextExecutionDates[0].toISOString()
      : null;

    const latestTaskStatus = tasks.length > 0 ? tasks[0].status : null;

    // 读取执行统计（通过 taskOrder.originStrategyId 关联策略）
    const executions = await prisma.strategyExecutionRun.findMany({
      where: {
        taskOrder: { originStrategyId: strategy.id },
      },
      orderBy: { createdAt: "desc" },
      take: 10,
    });

    const totalRuns = await prisma.strategyExecutionRun.count({
      where: { taskOrder: { originStrategyId: strategy.id } },
    });

    const completedRuns = executions.filter(
      (e) => e.status === "completed" || e.status === "success",
    ).length;

    const successRate = totalRuns > 0
      ? Math.round((completedRuns / totalRuns) * 100) / 100
      : 0;

    const latestRun = executions[0];
    const latestRunAt = latestRun?.startedAt
      ? new Date(latestRun.startedAt).toISOString()
      : null;
    const latestRunStatus = latestRun?.status ?? null;

    // 构建 artifact 对象
    const artifactId = `trading/strategy_${strategy.id}`;
    const filename = `strategy_${strategy.id}.json`;
    const filePath = path.join(tradingDir, filename);

    const artifact: StrategyExecutionArtifact = {
      artifactId,
      category: "trading",
      generatedAt: new Date().toISOString(),
      type: "strategy_execution",
      strategy: {
        id: strategy.id,
        uid: strategy.uid,
        name: strategy.name,
        description: strategy.description ?? null,
        type: strategy.type ?? "UNKNOWN",
        direction: strategy.direction,
        symbol: strategy.symbol ?? "N/A",
        leverage: Number(strategy.leverage) ?? 1,
        confidence: strategy.confidence ? Number(strategy.confidence) : null,
        status: strategy.status ?? "UNKNOWN",
        createdAt: strategy.createdAt
          ? new Date(strategy.createdAt as unknown as Date | string).toISOString()
          : new Date().toISOString(),
      },
      task: {
        total: tasks.length,
        active: activeTaskCount,
        nextExecutionAt,
        latestStatus: latestTaskStatus ?? null,
      },
      execution: {
        totalRuns,
        completedRuns,
        successRate,
        latestRunAt,
        latestRunStatus,
      },
    };

    // 写入 JSON 文件
    fs.writeFileSync(filePath, JSON.stringify(artifact, null, 2), "utf-8");
    writtenArtifacts.push(artifact);
  }

  // 3. 更新 trading/index.json
  const indexPath = path.join(tradingDir, "index.json");
  const existingIndex = readTradingIndex(indexPath);

  // 构建新的 trading 索引条目
  const newEntries: TradingIndexEntry[] = writtenArtifacts.map((art) => ({
    artifact_id: art.artifactId,
    title: `策略执行：${art.strategy.name}`,
    file: `strategy_${art.strategy.id}.json`,
    filename: `strategy_${art.strategy.id}.json`,
    type: "strategy_execution",
    status: art.strategy.status === "APPLIED" ? "active" : "configured",
    date: art.generatedAt,
    chain_phase: "A9",
    tags: [
      "strategy",
      art.strategy.direction,
      art.strategy.symbol,
      art.strategy.type,
      art.strategy.status,
      `执行${art.execution.totalRuns}次`,
    ].filter(Boolean),
    excerpt: `${art.strategy.name} · ${art.strategy.direction} · ${art.strategy.symbol} · 已执行 ${art.execution.totalRuns} 次（成功 ${Math.round(art.execution.successRate * 100)}%）`,
  }));

  // 合并去重（按 artifact_id）
  const seen = new Set<string>();
  const merged: TradingIndexEntry[] = [];

  for (const entry of newEntries) {
    if (!seen.has(entry.artifact_id)) {
      seen.add(entry.artifact_id);
      merged.push(entry);
    }
  }

  for (const entry of existingIndex.artifacts) {
    if (!seen.has(entry.artifact_id) && !entry.artifact_id.startsWith("trading/strategy_")) {
      seen.add(entry.artifact_id);
      merged.push(entry);
    }
  }

  // 按日期排序（最新在前）
  merged.sort((a, b) => {
    const da = new Date(a.date).getTime();
    const db = new Date(b.date).getTime();
    return db - da;
  });

  const finalIndex: TradingIndexData = {
    last_updated: new Date().toISOString(),
    artifacts: merged,
  };

  fs.writeFileSync(indexPath, JSON.stringify(finalIndex, null, 2), "utf-8");

  return {
    written: writtenArtifacts.length,
    directory: tradingDir,
    artifacts: writtenArtifacts,
  };
}

// ----------------------------------------------------------------------------
// 辅助：读取现有的 trading/index.json
// ----------------------------------------------------------------------------
function readTradingIndex(indexPath: string): TradingIndexData {
  if (!fs.existsSync(indexPath)) {
    return { last_updated: new Date(0).toISOString(), artifacts: [] };
  }

  try {
    const raw = fs.readFileSync(indexPath, "utf-8");
    const parsed = JSON.parse(raw);

    // 兼容数组格式
    if (Array.isArray(parsed)) {
      return {
        last_updated: new Date().toISOString(),
        artifacts: parsed.map((item: Record<string, unknown>) => ({
          artifact_id: String(item?.id ?? item.artifact_id ?? ""),
          title: String(item?.title ?? ""),
          file: String(item?.file ?? item.filename ?? ""),
          filename: String(item?.filename ?? item.file ?? ""),
          type: String(item?.type ?? "trading"),
          status: String(item?.status ?? "unknown"),
          date: String(item?.date ?? new Date().toISOString()),
          chain_phase: String(item?.chain_phase ?? "A9"),
          tags: Array.isArray(item?.tags) ? (item.tags as string[]) : [],
          excerpt: String(item?.excerpt ?? item.description ?? ""),
        })),
      };
    }

    // 对象格式
    if (parsed && typeof parsed === "object") {
      const rawArtifacts = Array.isArray(parsed.artifacts) ? parsed.artifacts : [];
      return {
        last_updated: typeof parsed.last_updated === "string" ? parsed.last_updated : new Date().toISOString(),
        artifacts: rawArtifacts.map((item: Record<string, unknown>) => ({
          artifact_id: String(item.artifact_id ?? item.id ?? ""),
          title: String(item.title ?? ""),
          file: String(item.file ?? item.filename ?? ""),
          filename: String(item.filename ?? item.file ?? ""),
          type: String(item.type ?? "trading"),
          status: String(item.status ?? "unknown"),
          date: String(item.date ?? new Date().toISOString()),
          chain_phase: String(item.chain_phase ?? "A9"),
          tags: Array.isArray(item.tags) ? (item.tags as string[]) : [],
          excerpt: String(item.excerpt ?? ""),
        })),
      };
    }

    return { last_updated: new Date().toISOString(), artifacts: [] };
  } catch {
    return { last_updated: new Date().toISOString(), artifacts: [] };
  }
}

// ----------------------------------------------------------------------------
// 综合：将所有业务数据沉淀到 artifacts（包括用户、积分等）
// ----------------------------------------------------------------------------
export async function syncBusinessDataToArtifacts(): Promise<{
  strategies: number;
  summary: TradingIndexEntry | null;
  directory: string;
}> {
  const artifactsRoot = resolveArtifactsRoot();
  const tradingDir = path.join(artifactsRoot, "trading");
  ensureDir(tradingDir);

  // 1. 先写策略执行记录
  const strategyResult = await writeStrategyExecutionArtifacts();

  // 2. 读取用户与积分信息，生成综合 summary
  const [userCount, creditsAccounts, strategies, executions] = await Promise.all([
    prisma.user.count(),
    prisma.creditsAccount.findMany({
      select: { balance: true, uid: true },
      take: 100,
    }),
    prisma.strategy.count(),
    prisma.strategyExecutionRun.count(),
  ]);

  const totalCredits = creditsAccounts.reduce(
    (sum, acc) => sum + Number(acc.balance || 0),
    0,
  );
  const uniqueUsers = new Set(creditsAccounts.map((a) => a.uid)).size;

  // 生成综合 summary artifact
  const summaryArtifact = {
    artifactId: "trading/business_summary",
    category: "trading",
    generatedAt: new Date().toISOString(),
    type: "business_summary",
    summary: {
      users: {
        total: userCount,
        withStrategies: uniqueUsers,
      },
      strategies: {
        total: strategies,
      },
      executions: {
        total: executions,
      },
      credits: {
        total: totalCredits,
        accounts: creditsAccounts.length,
      },
    },
  };

  const summaryPath = path.join(tradingDir, "business_summary.json");
  fs.writeFileSync(summaryPath, JSON.stringify(summaryArtifact, null, 2), "utf-8");

  // 将综合 summary 合并到 trading/index.json
  const indexPath = path.join(tradingDir, "index.json");
  const existingIndex = readTradingIndex(indexPath);

  const summaryEntry: TradingIndexEntry = {
    artifact_id: "trading/business_summary",
    title: "业务数据沉淀总览",
    file: "business_summary.json",
    filename: "business_summary.json",
    type: "business_summary",
    status: "completed",
    date: summaryArtifact.generatedAt,
    chain_phase: "A8",
    tags: ["summary", "business", "data", "precipitation"],
    excerpt: `${userCount} 用户 · ${strategies} 策略 · ${executions} 次执行 · 积分余额 ${totalCredits.toFixed(0)}`,
  };

  const existingEntries = existingIndex.artifacts.filter(
    (e) => e.artifact_id !== "trading/business_summary",
  );

  const mergedIndex: TradingIndexData = {
    last_updated: new Date().toISOString(),
    artifacts: [summaryEntry, ...existingEntries].sort(
      (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
    ),
  };

  fs.writeFileSync(indexPath, JSON.stringify(mergedIndex, null, 2), "utf-8");

  return {
    strategies: strategyResult.written,
    summary: summaryEntry,
    directory: tradingDir,
  };
}

// ----------------------------------------------------------------------------
// CLI 入口：如果直接运行该脚本，则同步业务数据到 artifacts
// ----------------------------------------------------------------------------
async function main() {
  try {
    console.log("=" + "=".repeat(60));
    console.log(" 策略/任务执行记录自动沉淀到 artifacts 目录");
    console.log("=" + "=".repeat(60));
    console.log();

    const result = await syncBusinessDataToArtifacts();

    console.log(`📁 目录: ${result.directory}`);
    console.log(`📊 策略执行记录: ${result.strategies} 份`);
    console.log(`📋 综合摘要: ${result.summary ? "已生成" : "未生成"}`);
    console.log(`✅ 完成：业务数据沉淀 → artifacts 索引闭环`);
  } catch (error) {
    console.error("❌ 失败:", error instanceof Error ? error.message : String(error));
    process.exit(1);
  } finally {
    await prisma.$disconnect();
  }
}

// 支持直接运行：node --experimental-strip-types lib/prisma-strategy-sync.ts
// 在 ES module 模式下，通过 argv 检测
const __fileName =
  (globalThis.process && process.argv && process.argv[1]) || "";
if (__fileName.endsWith("prisma-strategy-sync.ts") || __fileName.endsWith("prisma-strategy-sync.js")) {
  main();
}
