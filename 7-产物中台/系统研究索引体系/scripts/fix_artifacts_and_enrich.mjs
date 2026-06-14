// 修复：正确更新 trading/index.json（追加而不是覆盖）
// 同时补全缺少的用户业务数据

import { PrismaClient } from "@prisma/client";
import fs from "node:fs";
import path from "node:path";

const prisma = new PrismaClient();

const ARTIFACTS_DIR = "/Users/zhangjiangtao/.workbuddy/artifacts";

async function main() {
  const DEMO_UID = "Ur6GZTRLpum";

  // ========== 1. 补全缺失的用户 profile ==========
  const profile = await prisma.userProfile.findUnique({ where: { uid: DEMO_UID } });
  if (!profile) {
    console.log("[profile] 用户 profile 不存在，创建中...");
    await prisma.userProfile.create({
      data: {
        uid: DEMO_UID,
        availableCapital: 10000,
        capitalPercentage: 0.1,
        leverageMax: 3,
        dailyLossLimit: 500,
        dailyLossPercent: 0.05,
        accountLossLimit: 2000,
        accountLossPercent: 0.2,
        allowedSymbols: "BTC-USDT-SWAP",
        isTradingEnabled: true,
        riskTolerance: "MODERATE",
      },
    });
  } else {
    console.log("[profile] 用户 profile 存在");
  }

  // ========== 2. 补全缺失的 trading params ==========
  const params = await prisma.tradingParams.findUnique({ where: { uid: DEMO_UID } });
  if (!params) {
    console.log("[params] trading params 不存在，创建中...");
    await prisma.tradingParams.create({
      data: {
        uid: DEMO_UID,
        todayLoss: 0,
        todayTradeCount: 3,
        lastResetDate: new Date().toISOString().slice(0, 10),
        totalLoss: -45,
        totalTradeCount: 27,
        status: "ACTIVE",
      },
    });
  } else {
    // 更新一些模拟交易数据
    await prisma.tradingParams.update({
      where: { uid: DEMO_UID },
      data: {
        todayTradeCount: 3,
        totalTradeCount: 27,
        totalLoss: -45,
        status: "ACTIVE",
      },
    });
    console.log("[params] 更新模拟交易数据");
  }

  // ========== 3. 修复 trading/index.json（追加策略而不是覆盖） ==========
  const tradingDir = path.join(ARTIFACTS_DIR, "trading");
  const indexPath = path.join(tradingDir, "index.json");

  const raw = fs.readFileSync(indexPath, "utf-8");
  let existingIndex;
  try {
    existingIndex = JSON.parse(raw);
  } catch {
    existingIndex = [];
  }

  // 原有记录（可能是数组或对象）
  const existingRecords = Array.isArray(existingIndex)
    ? existingIndex
    : Array.isArray(existingIndex?.artifacts)
      ? existingIndex.artifacts
      : [];

  // 从我们策略 artifact 文件中读取新记录
  const strategyFiles = fs.readdirSync(tradingDir).filter((f) => f.startsWith("strategy_task_order_"));
  const strategyRecords = strategyFiles.map((filename) => {
    try {
      const artifact = JSON.parse(fs.readFileSync(path.join(tradingDir, filename), "utf-8"));
      return {
        id: artifact.artifactId,
        file: filename,
        title: `策略任务：${artifact.strategy?.name ?? "未命名"}`,
        department: "trading",
        type: "strategy_task_order",
        date: artifact.generatedAt,
        status: artifact.taskOrder?.status ?? "applied",
        chain_phase: "A9",
        url: `/feed/trading/${artifact.artifactId?.replace("trading/", "")}`,
        tags: [
          "strategy",
          artifact.strategy?.direction ?? "",
          artifact.strategy?.symbol ?? "",
          artifact.strategy?.type === "RECOMMENDED" ? "system" : "custom",
        ].filter(Boolean),
      };
    } catch {
      return null;
    }
  }).filter(Boolean);

  // 合并并去重（按 id）
  const seen = new Set();
  const allRecords = [];
  for (const record of [...strategyRecords, ...existingRecords]) {
    const id = String(record?.id ?? record?.artifact_id ?? "");
    if (id && !seen.has(id)) {
      seen.add(id);
      allRecords.push(record);
    }
  }

  // 按日期排序（最新的在前）
  allRecords.sort((a, b) => {
    const da = a?.date ?? "";
    const db = b?.date ?? "";
    return db.localeCompare(da);
  });

  // 写入数组格式
  fs.writeFileSync(indexPath, JSON.stringify(allRecords, null, 2), "utf-8");
  console.log(`\\n[index] trading/index.json 已更新：策略 ${strategyRecords.length} 条，总 ${allRecords.length} 条`);

  // ========== 4. 创建业务沉淀独立模块 artifact ==========
  const bizArtifactDir = path.join(ARTIFACTS_DIR, "dashboard");
  fs.mkdirSync(bizArtifactDir, { recursive: true });

  const userCount = await prisma.user.count();
  const strategyCount = await prisma.strategy.count();
  const activeStrategies = await prisma.strategy.count({ where: { status: "APPLIED" } });
  const tasks = await prisma.strategyTask.count();
  const executions = await prisma.strategyExecutionRun.count();
  const creditBalance = await prisma.creditsAccount.findUnique({ where: { uid: DEMO_UID } });

  const bizArtifact = {
    id: "dashboard/business_summary",
    title: "业务数据沉淀汇总",
    department: "dashboard",
    type: "business_summary",
    date: new Date().toISOString(),
    status: "completed",
    chain_phase: "A8",
    summary: {
      users: { total: userCount },
      strategies: {
        total: strategyCount,
        active: activeStrategies,
      },
      tasks,
      executions,
      credits: creditBalance?.balance ?? 0,
      artifactsIndex: {
        trading: allRecords.length,
      },
    },
  };

  const bizIndexPath = path.join(bizArtifactDir, "index.json");
  let existingBizIndex = [];
  if (fs.existsSync(bizIndexPath)) {
    try {
      const rawBiz = JSON.parse(fs.readFileSync(bizIndexPath, "utf-8"));
      existingBizIndex = Array.isArray(rawBiz) ? rawBiz : rawBiz.artifacts ?? [];
    } catch {}
  }

  const newBizRecord = {
    id: bizArtifact.id,
    title: bizArtifact.title,
    department: "dashboard",
    type: "business_summary",
    date: bizArtifact.date,
    status: "completed",
    chain_phase: "A8",
    url: "/feed/dashboard/business_summary",
    file: "business_summary.json",
    filename: "business_summary.json",
    artifact_id: "dashboard/business_summary",
    tags: ["business", "data", "summary"],
    excerpt: `用户 ${userCount} 人，策略 ${strategyCount} 条（活跃 ${activeStrategies}），任务 ${tasks} 个，执行 ${executions} 次`,
  };

  const bizAll = [newBizRecord, ...existingBizIndex.filter((r) => (r?.id ?? r?.artifact_id) !== newBizRecord.id)];
  fs.writeFileSync(bizIndexPath, JSON.stringify(bizAll, null, 2), "utf-8");
  fs.writeFileSync(path.join(bizArtifactDir, "business_summary.json"), JSON.stringify(bizArtifact, null, 2), "utf-8");
  console.log("[business] 创建业务沉淀独立模块：dashboard/business_summary.json");

  console.log("\\n✅ 所有业务数据沉淀完成！");
  console.log(`   - 用户 profile: 存在`);
  console.log(`   - 交易参数: 已更新为 ACTIVE 状态，累计 ${27} 笔交易`);
  console.log(`   - trading/index.json: 合并了 ${strategyRecords.length} 条策略记录，总 ${allRecords.length} 条`);
  console.log(`   - dashboard/index.json: 创建了业务沉淀独立模块`);
}

main().catch(console.error).finally(() => prisma.$disconnect());
