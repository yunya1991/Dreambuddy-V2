/**
 * 日终对账脚本 (P2-8)
 * 验证: 各用户 funds_accounts.available == SUM(ledger_postings 净额)
 *
 * 运行: npx tsx prisma/scripts/reconcile-daily.ts
 */
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const reconDate = new Date();
  reconDate.setHours(0, 0, 0, 0);

  console.log(`\n=== 日终对账 ${reconDate.toISOString().slice(0, 10)} ===\n`);

  // 1. 取所有资金账户
  const fundsAccounts = await prisma.fundsAccount.findMany();
  console.log(`资金账户数: ${fundsAccounts.length}\n`);

  let matched = 0;
  let mismatched = 0;
  const details: Array<Record<string, unknown>> = [];

  for (const acc of fundsAccounts) {
    // 2. 汇总该用户 ledger_postings 净额
    // 复式记账: CREDIT(+负债) - DEBIT(-负债) = 账户余额
    const postings = await prisma.ledgerPosting.aggregate({
      where: {
        accountUid: acc.customerUid,
        accountCode: "LIABILITY",
      },
      _sum: { amount: true },
      // 方向由 direction 字段区分，需要分别计算
    });

    // 分别汇总 DEBIT 和 CREDIT
    const debitSum = await prisma.ledgerPosting.aggregate({
      where: { accountUid: acc.customerUid, accountCode: "LIABILITY", direction: "DEBIT" },
      _sum: { amount: true },
    });
    const creditSum = await prisma.ledgerPosting.aggregate({
      where: { accountUid: acc.customerUid, accountCode: "LIABILITY", direction: "CREDIT" },
      _sum: { amount: true },
    });

    const expected = Number(creditSum._sum.amount ?? 0) - Number(debitSum._sum.amount ?? 0);
    const actual = Number(acc.available);
    const diff = actual - expected;

    const isMatched = Math.abs(diff) < 0.0001;

    details.push({
      uid: acc.customerUid,
      expected: expected.toFixed(8),
      actual: actual.toFixed(8),
      diff: diff.toFixed(8),
      matched: isMatched,
    });

    if (isMatched) matched++;
    else mismatched++;

    console.log(
      `[${isMatched ? "✓" : "✗"}] ${acc.customerUid}: 预期=${expected.toFixed(2)} 实际=${actual.toFixed(2)} 差异=${diff.toFixed(8)}`,
    );
  }

  // 3. 写入对账记录
  const totalExpected = details.reduce((s, d) => s + Number(d.expected), 0);
  const totalActual = details.reduce((s, d) => s + Number(d.actual), 0);
  const totalDiff = totalActual - totalExpected;
  const status = mismatched === 0 ? "MATCHED" : "MISMATCHED";

  const record = await prisma.reconciliationRecord.upsert({
    where: { reconDate },
    create: {
      reconDate,
      reconType: "DAILY",
      status,
      expectedAmount: totalExpected,
      actualAmount: totalActual,
      difference: totalDiff,
      detail: details as never,
      remark: `一致:${matched} 不一致:${mismatched}`,
      reconciledAt: new Date(),
    },
    update: {
      reconType: "DAILY",
      status,
      expectedAmount: totalExpected,
      actualAmount: totalActual,
      difference: totalDiff,
      detail: details as never,
      remark: `一致:${matched} 不一致:${mismatched}`,
      reconciledAt: new Date(),
    },
  });

  console.log(`\n=== 对账结果 ===`);
  console.log(`总预期: ${totalExpected.toFixed(2)}`);
  console.log(`总实际: ${totalActual.toFixed(2)}`);
  console.log(`总差异: ${totalDiff.toFixed(8)}`);
  console.log(`状态: ${status} (一致:${matched} 不一致:${mismatched})`);
  console.log(`对账记录 ID: ${record.id}\n`);

  process.exit(0);
}

main().catch((err) => {
  console.error("对账失败:", err);
  process.exit(1);
});
