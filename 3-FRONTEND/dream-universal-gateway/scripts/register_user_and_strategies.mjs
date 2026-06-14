// 任务1：创建用户并生成策略
// 使用主前端的 Prisma Client + 策略 artifact 写入
// 运行: node --import tsx register_user_and_strategies.mjs

import { PrismaClient } from "@prisma/client";
import fs from "node:fs";
import path from "node:path";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

// 演示用户
const DEMO_UID = "Ur6GZTRLpum";
const DEMO_EMAIL = "demo.strategy.local@example.com";
const DEMO_PASSWORD = "demo-password-123";

// artifacts 目录解析
function resolveArtifactsDir() {
  // 方案1：尝试 ui-map 使用的路径
  const workbuddyPath = path.join(process.env.HOME || "/Users/zhangjiangtao", ".workbuddy/artifacts");

  // 方案2：尝试主前端 task-manager 解析的路径
  const repoRoot = path.resolve(process.cwd(), "..", "..");
  const primaryInRepo = path.join(repoRoot, "dreambuddy", "artifacts");
  const fallbackInRepo = path.join(repoRoot, "artifacts");

  // 选第一个存在的目录
  const candidates = [workbuddyPath, primaryInRepo, fallbackInRepo];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      console.log(`[artifacts] 找到现有目录: ${candidate}`);
      return candidate;
    }
  }

  // 都不存在则创建第一个
  fs.mkdirSync(workbuddyPath, { recursive: true });
  console.log(`[artifacts] 创建新目录: ${workbuddyPath}`);
  return workbuddyPath;
}

const ARTIFACTS_DIR = resolveArtifactsDir();
console.log(`[artifacts] 目录: ${ARTIFACTS_DIR}\n`);

// ========== 1. 创建演示用户 ==========
async function ensureDemoUser() {
  const existing = await prisma.user.findUnique({ where: { uid: DEMO_UID } });
  if (existing) {
    console.log(`[user] 用户已存在: ${DEMO_EMAIL} (${DEMO_UID})`);
    return existing;
  }

  const uid = DEMO_UID;
  const passwordHash = await bcrypt.hash(DEMO_PASSWORD, 10);

  await prisma.$transaction(async (tx) => {
    await tx.user.create({
      data: {
        uid,
        email: DEMO_EMAIL,
        passwordHash,
        displayName: "策略测试用户",
        role: "FREE",
        loginAttempts: 0,
      },
    });

    await tx.userProfile.create({
      data: {
        uid,
        availableCapital: 10000,
        capitalPercentage: 0.1,
        tradeType: "SWAP",
        tradeMode: "SWAP_MODE",
        positionMode: "NET",
        leverageMax: 3,
        dailyLossLimit: 500,
        dailyLossPercent: 0.05,
        accountLossLimit: 2000,
        accountLossPercent: 0.2,
        allowedSymbols: "BTC-USDT-SWAP",
        allowedTradeModes: "SPOT_MODE",
        isTradingEnabled: true,
        preferredFrequency: "FOUR_H",
        riskTolerance: "MODERATE",
      },
    });

    await tx.tradingParams.create({
      data: {
        uid,
        todayLoss: 0,
        todayTradeCount: 0,
        lastResetDate: new Date().toISOString().slice(0, 10),
        totalLoss: 0,
        totalTradeCount: 0,
        status: "ACTIVE",
      },
    });

    await tx.creditsAccount.create({
      data: {
        uid,
        balance: 100,
        totalEarned: 100,
        totalSpent: 0,
        pendingCredits: 0,
        signupBonus: true,
      },
    });
  });

  console.log(`[user] 新用户创建成功: ${DEMO_EMAIL} (${DEMO_UID})`);
  return { uid };
}

// ========== 2. 创建策略 ==========
async function createStrategy({
  name,
  description,
  direction,
  symbol,
  type = "CUSTOM",
  frequency = "FOUR_H",
  applied,
}) {
  const nowIso = new Date().toISOString();
  const strategy = await prisma.strategy.create({
    data: {
      uid: DEMO_UID,
      type,
      name,
      description,
      direction,
      symbol,
      tradeType: "SWAP",
      leverage: 1,
      positionSize: 100,
      confidence: 75,
      edgeScore: 65,
      regime: "range-bound",
      source: "manual_script",
      status: applied ? "APPLIED" : "APPROVED",
    },
  });

  console.log(`[strategy] 创建: ${name} (id=${strategy.id}, status=${strategy.status})`);

  // 如果 APPLIED，则创建 task order + task + execution run
  if (applied) {
    const taskOrderId = `sto_${strategy.id}_${Date.now()}`;
    const nextExec = new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString();

    await prisma.strategyTaskOrder.create({
      data: {
        strategyTaskOrderId: taskOrderId,
        strategyType: type === "RECOMMENDED" ? "system" : "custom",
        source: "user_created",
        status: "applied",
        title: name,
        summary: description ?? null,
        rawInput: `手动创建：${name} ${direction} ${symbol}`,
        originStrategyId: strategy.id,
        ownerUserId: DEMO_UID,
        strategySnapshot: {
          direction,
          symbol,
          tradeType: "SWAP",
          leverage: 1,
          positionSize: 100,
          stopLoss: null,
          takeProfit: null,
          frequency,
          confidence: 75,
        },
        createdAt: nowIso,
        updatedAt: nowIso,
        appliedAt: nowIso,
      },
    });

    const taskId = `task_${strategy.id}_${Date.now()}`;
    await prisma.strategyTask.create({
      data: {
        id: taskId,
        strategyId: strategy.id,
        uid: DEMO_UID,
        taskOrderId,
        exchangeConfigId: null,
        executionFrequency: frequency,
        status: "ACTIVE",
        nextExecutionAt: nextExec,
        executionCount: 0,
        skipCount: 0,
        tradeCount: 0,
      },
    });

    const runId = `run_${strategy.id}_${Date.now()}`;
    await prisma.strategyExecutionRun.create({
      data: {
        strategyExecutionRunId: runId,
        strategyTaskOrderId: taskOrderId,
        triggerType: "scheduled",
        status: "completed",
        startedAt: nowIso,
        endedAt: nowIso,
        reason: "演示脚本初始化：已成功执行一次",
      },
    });

    console.log(`[lifecycle] 已关联 task order + task + execution run`);

    // 写入 artifacts 目录
    writeStrategyArtifact({
      strategy,
      taskOrderId,
      taskId,
      runId,
      frequency,
      nextExecutionAt: nextExec,
      createdAt: nowIso,
    });
  }

  return strategy;
}

// ========== 3. 写入 artifacts 目录 ==========
function writeStrategyArtifact({
  strategy,
  taskOrderId,
  taskId,
  runId,
  frequency,
  nextExecutionAt,
  createdAt,
}) {
  const tradingDir = path.join(ARTIFACTS_DIR, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifactId = `strategy-task-order-${taskOrderId}`;
  const filename = `strategy_task_order_${taskOrderId}.json`;
  const filePath = path.join(tradingDir, filename);
  const indexPath = path.join(tradingDir, "index.json");

  const artifact = {
    artifactId: `trading/${artifactId}`,
    category: "trading",
    generatedAt: createdAt,
    strategyTaskOrderId: taskOrderId,
    nextExecutionAt,
    strategy: {
      id: strategy.id,
      uid: strategy.uid,
      type: strategy.type,
      name: strategy.name,
      description: strategy.description,
      direction: strategy.direction,
      symbol: strategy.symbol,
      tradeType: strategy.tradeType,
      leverage: strategy.leverage,
      positionSize: strategy.positionSize,
      stopLoss: strategy.stopLoss,
      takeProfit: strategy.takeProfit,
      confidence: strategy.confidence,
      source: strategy.source,
      rawInput: `手动脚本创建：${strategy.name}`,
      status: strategy.status,
    },
    taskOrder: {
      strategyTaskOrderId: taskOrderId,
      strategyType: strategy.type === "RECOMMENDED" ? "system" : "custom",
      source: "user_created",
      status: "applied",
      title: strategy.name,
      summary: strategy.description,
      rawInput: `手动脚本创建：${strategy.name}`,
      originStrategyId: strategy.id,
      ownerUserId: DEMO_UID,
      strategySnapshot: {
        direction: strategy.direction,
        symbol: strategy.symbol,
        tradeType: strategy.tradeType,
        leverage: strategy.leverage,
        positionSize: strategy.positionSize,
        stopLoss: strategy.stopLoss,
        takeProfit: strategy.takeProfit,
        frequency,
        confidence: strategy.confidence,
      },
      createdAt,
      updatedAt: createdAt,
      appliedAt: createdAt,
    },
    strategyTask: {
      id: taskId,
      strategyId: strategy.id,
      uid: strategy.uid,
      executionFrequency: frequency,
      status: "ACTIVE",
      nextExecutionAt,
      taskOrderId,
    },
    executionRun: {
      strategyExecutionRunId: runId,
      strategyTaskOrderId: taskOrderId,
      triggerType: "scheduled",
      status: "completed",
      startedAt: createdAt,
      endedAt: createdAt,
      reason: "演示脚本初始化执行",
    },
  };

  fs.writeFileSync(filePath, JSON.stringify(artifact, null, 2), "utf-8");
  console.log(`[artifact] 写入: ${filePath}`);

  // 更新 trading/index.json
  let indexData = { last_updated: createdAt, artifacts: [] };
  if (fs.existsSync(indexPath)) {
    try {
      indexData = JSON.parse(fs.readFileSync(indexPath, "utf-8"));
      if (!Array.isArray(indexData.artifacts)) indexData.artifacts = [];
    } catch {
      indexData = { last_updated: createdAt, artifacts: [] };
    }
  }

  const newRecord = {
    artifact_id: `trading/${artifactId}`,
    title: `Strategy Task Order: ${strategy.name}`,
    file: filename,
    filename,
    type: "strategy_task_order",
    status: "applied",
    date: createdAt,
    chain_phase: "A9",
    tags: ["strategy_task_order", strategy.direction, strategy.symbol, frequency, strategy.type === "RECOMMENDED" ? "system" : "custom"],
    workflow_id: strategy.id,
    workflow_type: "trading_v2",
    trace_id: taskOrderId,
    department: "trading",
    excerpt: `${strategy.symbol} | ${strategy.direction} | ${frequency} | ${strategy.description ?? "已创建"}`,
  };

  const existing = indexData.artifacts.filter((item) => item.artifact_id !== newRecord.artifact_id);
  indexData.artifacts = [newRecord, ...existing];
  indexData.last_updated = createdAt;

  fs.writeFileSync(indexPath, JSON.stringify(indexData, null, 2), "utf-8");
  console.log(`[artifact] 更新索引: ${indexPath} (共 ${indexData.artifacts.length} 条)`);
}

// ========== 主流程 ==========
async function main() {
  console.log("=" + "=".repeat(50));
  console.log(" 任务1：用户注册 + 策略创建 + 数据沉淀");
  console.log("=" + "=".repeat(50) + "\n");

  // 1. 用户
  const user = await ensureDemoUser();

  // 2. 创建3个策略（不同类型 / 状态）
  const strategies = [
    { name: "BTC趋势跟踪-4h", description: "基于4小时K线的中高风险趋势跟踪策略", direction: "BUY", symbol: "BTC-USDT-SWAP", type: "CUSTOM", frequency: "FOUR_H", applied: true },
    { name: "ETH低吸策略", description: "以太坊回调买入，基于波动率的低吸策略", direction: "BUY", symbol: "ETH-USDT-SWAP", type: "CUSTOM", frequency: "ONE_H", applied: true },
    { name: "A系统推荐策略-震荡市", description: "系统A系列识别的震荡区间策略推荐", direction: "SHORT", symbol: "BTC-USDT-SWAP", type: "RECOMMENDED", frequency: "ONE_D", applied: true },
  ];

  for (const def of strategies) {
    await createStrategy(def);
    await new Promise((resolve) => setTimeout(resolve, 500)); // 间隔，确保时间戳不同
  }

  // 3. 统计并输出
  const userCount = await prisma.user.count();
  const strategyCount = await prisma.strategy.count();
  const activeTasks = await prisma.strategyTask.count();
  const executionRuns = await prisma.strategyExecutionRun.count();

  console.log("\n" + "=" + "=".repeat(50));
  console.log(" 业务沉淀统计（Prisma SQLite）:");
  console.log(`  用户数: ${userCount}`);
  console.log(`  策略数: ${strategyCount}`);
  console.log(`  活跃任务数: ${activeTasks}`);
  console.log(`  执行记录: ${executionRuns}`);
  console.log("=" + "=".repeat(50));
  console.log("\n✅ 完成！现在刷新 ui-map 页面查看实时反映。");
}

main()
  .catch((e) => {
    console.error("错误:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
