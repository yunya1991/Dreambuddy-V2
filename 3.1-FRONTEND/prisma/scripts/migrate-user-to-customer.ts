/**
 * P1-9 数据迁移脚本：从 User 拆分 Customer 初值
 *
 * 逻辑：遍历所有 User，若不存在对应 Customer，则创建 Customer + FundsAccount + TradingAccount
 * 用于存量用户迁移到三账户隔离体系
 *
 * 运行: npx tsx prisma/scripts/migrate-user-to-customer.ts
 */
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const users = await prisma.user.findMany({
    select: { uid: true, email: true, role: true, createdAt: true },
  });

  console.log(`\n=== 迁移 User → Customer (共 ${users.length} 个用户) ===\n`);

  let created = 0;
  let skipped = 0;

  for (const user of users) {
    // 检查是否已有 Customer
    const existing = await prisma.customer.findUnique({ where: { uid: user.uid } });
    if (existing) {
      skipped++;
      continue;
    }

    // 创建 Customer + FundsAccount + TradingAccount (事务)
    await prisma.$transaction(async (tx) => {
      await tx.customer.create({
        data: {
          uid: user.uid,
          realName: null,
          kycStatus: "UNVERIFIED",
          kycLevel: 0,
          riskLevel: "MODERATE",
          riskScore: 50,
          investorType: user.role === "PRO" ? "PROFESSIONAL" : "RETAIL",
          fundsAccount: {
            create: {
              available: 0,
              frozen: 0,
              pending: 0,
              total: 0,
            },
          },
          tradingAccount: {
            create: {
              marginBalance: 0,
              usedMargin: 0,
              availableMargin: 0,
              totalPositionValue: 0,
              unrealizedPnl: 0,
              marginCallThreshold: 0.3,
              liquidationThreshold: 0.1,
            },
          },
        },
      });
    });

    created++;
    console.log(`  ✓ 创建 Customer: ${user.uid} (${user.email ?? "no-email"})`);
  }

  console.log(`\n=== 迁移完成 ===`);
  console.log(`新建: ${created}`);
  console.log(`跳过(已存在): ${skipped}`);
  console.log(`总计: ${users.length}\n`);

  process.exit(0);
}

main().catch((err) => {
  console.error("迁移失败:", err);
  process.exit(1);
});
