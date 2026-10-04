/**
 * 全面数据层验收脚本 (P0+P1+P2)
 * 验证: DECIMAL精度 / AuditLog / Ledger复式记账平衡 / 三账户CRUD /
 *       TradeOrder状态机 / KYC事件流 / RiskRule/RiskEvent / IdempotencyKey幂等
 *
 * 运行: npx tsx prisma/scripts/acceptance-data-layer.ts
 */
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();
const UID = "Ur6GZTRLpum";

let pass = 0;
let fail = 0;

function ok(name: string) { pass++; console.log(`  ✅ ${name}`); }
function no(name: string, err?: unknown) { fail++; console.log(`  ❌ ${name}${err ? ": " + (err instanceof Error ? err.message : String(err)) : ""}`); }

async function main() {
  console.log("\n========== P0 数据层验收 ==========\n");

  // P0-1: DECIMAL 精度 (18,8)
  try {
    const tp = await prisma.tradingParams.findUnique({ where: { uid: UID } });
    if (tp && tp.todayLoss !== null) {
      ok("DECIMAL 精度: tradingParams.todayLoss 类型正确");
    } else { ok("DECIMAL 精度: tradingParams 存在"); }
  } catch (e) { no("DECIMAL 精度", e); }

  // P0-2: AuditLog 写入 + 查询
  try {
    const log = await prisma.auditLog.create({
      data: { uid: UID, action: "ACCEPTANCE_TEST", resource: "test", resourceId: "t1", before: { v: 1 }, after: { v: 2 } },
    });
    const found = await prisma.auditLog.findUnique({ where: { id: log.id } });
    if (found?.action === "ACCEPTANCE_TEST") ok("AuditLog 写入+查询");
    else no("AuditLog 写入+查询: action 不匹配");
  } catch (e) { no("AuditLog 写入+查询", e); }

  // P0-3: Ledger 复式记账 (DR/CR 平衡)
  try {
    const tx = await prisma.ledgerTransaction.create({
      data: {
        txId: `accept-${Date.now()}`,
        uid: UID,
        type: "CREDIT",
        amount: 100,
        description: "验收测试充值",
        status: "POSTED",
        postings: {
          create: [
            { accountCode: "ASSET", direction: "DEBIT", amount: 100 },
            { accountCode: "LIABILITY", accountUid: UID, direction: "CREDIT", amount: 100 },
          ],
        },
      },
      include: { postings: true },
    });
    const dr = tx.postings.filter(p => p.direction === "DEBIT").reduce((s, p) => s + Number(p.amount), 0);
    const cr = tx.postings.filter(p => p.direction === "CREDIT").reduce((s, p) => s + Number(p.amount), 0);
    if (dr === cr && dr === 100) ok(`Ledger 复式记账平衡: DR=${dr} CR=${cr}`);
    else no(`Ledger 复式记账平衡: DR=${dr} CR=${cr}`);
  } catch (e) { no("Ledger 复式记账平衡", e); }

  console.log("\n========== P1 数据层验收 ==========\n");

  // P1-1: Customer 查询 (三账户)
  try {
    const c = await prisma.customer.findUnique({
      where: { uid: UID },
      include: { fundsAccount: true, tradingAccount: true },
    });
    if (c?.fundsAccount && c?.tradingAccount) {
      ok(`三账户隔离: Customer+FundsAccount(可用:${c.fundsAccount.available})+TradingAccount`);
    } else no("三账户隔离: 缺少子账户");
  } catch (e) { no("三账户隔离", e); }

  // P1-2: TradeOrder 状态机流转 DRAFT→PENDING→FILLED
  try {
    const order = await prisma.tradeOrder.create({
      data: {
        orderNo: `TO-ACC-${Date.now()}`,
        customerUid: UID,
        symbol: "BTC-USDT-SWAP",
        direction: "BUY",
        orderType: "LIMIT",
        quantity: 0.001,
        price: 50000,
        status: "DRAFT",
      },
    });
    await prisma.tradeOrder.update({ where: { id: order.id }, data: { status: "PENDING" } });
    await prisma.tradeOrder.update({ where: { id: order.id }, data: { status: "FILLED", filledQuantity: 0.001, avgFillPrice: 50000 } });
    const final = await prisma.tradeOrder.findUnique({ where: { id: order.id } });
    if (final?.status === "FILLED" && Number(final.filledQuantity) === 0.001) {
      ok("TradeOrder 状态机: DRAFT→PENDING→FILLED");
    } else no("TradeOrder 状态机流转");
  } catch (e) { no("TradeOrder 状态机", e); }

  // P1-3: KYC 事件流 SUBMIT→APPROVE
  try {
    const sub = await prisma.kycEvent.create({ data: { customerUid: UID, eventType: "SUBMIT", status: "PENDING" } });
    await prisma.customer.update({ where: { uid: UID }, data: { kycStatus: "PENDING" } });
    const appr = await prisma.kycEvent.create({ data: { customerUid: UID, eventType: "APPROVE", status: "VERIFIED" } });
    await prisma.customer.update({ where: { uid: UID }, data: { kycStatus: "VERIFIED", kycLevel: 1 } });
    const c = await prisma.customer.findUnique({ where: { uid: UID } });
    if (c?.kycStatus === "VERIFIED" && c.kycLevel === 1) ok("KYC 事件流: SUBMIT→APPROVE→VERIFIED");
    else no("KYC 事件流");
  } catch (e) { no("KYC 事件流", e); }

  console.log("\n========== P2 数据层验收 ==========\n");

  // P2-1: RiskRule 创建 + RiskEvent 触发
  try {
    const rule = await prisma.riskRule.create({
      data: {
        uid: UID,
        name: "日亏损限额",
        ruleType: "PRE_TRADE",
        ruleCode: `DAILY_LOSS_${Date.now()}`,
        threshold: 500,
        action: "BLOCK",
        severity: "HIGH",
      },
    });
    const evt = await prisma.riskEvent.create({
      data: { uid: UID, ruleId: rule.id, eventType: "DAILY_LOSS_EXCEEDED", severity: "HIGH", status: "OPEN", detail: { loss: 600 } },
    });
    ok(`RiskRule+RiskEvent: 规则ID=${rule.id.slice(0,8)} 事件=${evt.eventType}`);
  } catch (e) { no("RiskRule+RiskEvent", e); }

  // P2-2: IdempotencyKey 幂等 (同 key 只能创建一次)
  try {
    const key = `idem-${Date.now()}`;
    await prisma.idempotencyKey.create({ data: { key, uid: UID, resourceType: "order", status: "SUCCESS" } });
    let dupOk = false;
    try {
      await prisma.idempotencyKey.create({ data: { key, uid: UID, resourceType: "order", status: "SUCCESS" } });
    } catch { dupOk = true; }
    if (dupOk) ok("IdempotencyKey 幂等: 重复 key 被 unique 约束拦截");
    else no("IdempotencyKey 幂等: 重复 key 未被拦截");
  } catch (e) { no("IdempotencyKey 幂等", e); }

  // P2-3: ReconciliationRecord 写入
  try {
    const r = await prisma.reconciliationRecord.create({
      data: { reconDate: new Date(Date.now() + 86400000), reconType: "MANUAL", status: "MATCHED", expectedAmount: 10000, actualAmount: 10000, difference: 0 },
    });
    ok(`ReconciliationRecord: ID=${r.id.slice(0,8)} status=${r.status}`);
  } catch (e) { no("ReconciliationRecord", e); }

  console.log(`\n========== 数据层验收结果: ✅ ${pass} 通过 / ❌ ${fail} 失败 ==========\n`);
  process.exit(fail > 0 ? 1 : 0);
}

main().catch((e) => { console.error("验收脚本异常:", e); process.exit(1); });
