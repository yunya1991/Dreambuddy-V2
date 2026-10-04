import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

const DEMO_UID = "Ur6GZTRLpum";
const DEMO_EMAIL = "demo.strategy.local@example.com";
const DEMO_DISPLAY_NAME = "测试用户";
const DEMO_PASSWORD_HASH =
  "$2b$10$/4/hVHTsQpHUqeZULFprpeeKwJbjr2Q5gLerfIzjigyF34nuF.Vf6";

async function main() {
  // upsert DEMO user
  const user = await prisma.user.upsert({
    where: { uid: DEMO_UID },
    update: { displayName: DEMO_DISPLAY_NAME },
    create: {
      uid: DEMO_UID,
      email: DEMO_EMAIL,
      passwordHash: DEMO_PASSWORD_HASH,
      displayName: DEMO_DISPLAY_NAME,
      role: "FREE",
      loginAttempts: 0,
    },
  });
  console.log(`[seed] user upserted: ${user.uid}`);

  // upsert UserProfile (默认交易配置)
  await prisma.userProfile.upsert({
    where: { uid: DEMO_UID },
    update: {},
    create: {
      uid: DEMO_UID,
      availableCapital: 10000,
      capitalPercentage: 0.1,
      tradeType: "SPOT",
      tradeMode: "SPOT_MODE",
      positionMode: "NET",
      leverageMax: 3,
      dailyLossLimit: 500,
      dailyLossPercent: 0.05,
      accountLossLimit: 2000,
      accountLossPercent: 0.2,
      allowedSymbols: '["BTC-USDT-SWAP"]',
      allowedTradeModes: '["SPOT_MODE"]',
      isTradingEnabled: false,
      riskTolerance: "MODERATE",
    },
  });
  console.log(`[seed] userProfile upserted`);

  // upsert TradingParams
  await prisma.tradingParams.upsert({
    where: { uid: DEMO_UID },
    update: {},
    create: {
      uid: DEMO_UID,
      todayLoss: 0,
      todayTradeCount: 0,
      lastResetDate: new Date().toISOString().slice(0, 10),
      totalLoss: 0,
      totalTradeCount: 0,
      status: "ACTIVE",
    },
  });
  console.log(`[seed] tradingParams upserted`);

  // upsert CreditsAccount
  const creditsAccount = await prisma.creditsAccount.upsert({
    where: { uid: DEMO_UID },
    update: {},
    create: {
      uid: DEMO_UID,
      balance: 1000,
      totalEarned: 1000,
      totalSpent: 0,
      pendingCredits: 0,
      signupBonus: true,
    },
  });
  console.log(`[seed] creditsAccount upserted`);

  // P1: upsert Customer (客户主表)
  const customer = await prisma.customer.upsert({
    where: { uid: DEMO_UID },
    update: {},
    create: {
      uid: DEMO_UID,
      realName: "测试用户",
      kycStatus: "UNVERIFIED",
      kycLevel: 0,
      riskLevel: "MODERATE",
      riskScore: 50,
      investorType: "RETAIL",
    },
  });
  console.log(`[seed] customer upserted: ${customer.uid}`);

  // P1: upsert FundsAccount (资金账户，关联积分账户)
  await prisma.fundsAccount.upsert({
    where: { customerUid: DEMO_UID },
    update: {},
    create: {
      customerUid: DEMO_UID,
      available: 10000,
      frozen: 0,
      pending: 0,
      total: 10000,
      currency: "USDT",
      creditsAccountId: creditsAccount.id,
    },
  });
  console.log(`[seed] fundsAccount upserted`);

  // P1: upsert TradingAccount (交易账户)
  await prisma.tradingAccount.upsert({
    where: { customerUid: DEMO_UID },
    update: {},
    create: {
      customerUid: DEMO_UID,
      marginBalance: 0,
      usedMargin: 0,
      availableMargin: 0,
      marginCallLevel: 0.3,
      liquidationLevel: 0.1,
      totalPositionValue: 0,
      unrealizedPnl: 0,
    },
  });
  console.log(`[seed] tradingAccount upserted`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
