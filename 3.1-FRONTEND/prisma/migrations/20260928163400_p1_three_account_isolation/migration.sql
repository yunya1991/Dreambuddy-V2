-- CreateEnum
CREATE TYPE "IdCardType" AS ENUM ('ID_CARD', 'PASSPORT', 'DRIVER_LICENSE', 'OTHER');

-- CreateEnum
CREATE TYPE "KycStatus" AS ENUM ('UNVERIFIED', 'PENDING', 'VERIFIED', 'REJECTED', 'EXPIRED');

-- CreateEnum
CREATE TYPE "RiskLevel" AS ENUM ('CONSERVATIVE', 'STABLE', 'MODERATE', 'AGGRESSIVE', 'PROFESSIONAL');

-- CreateEnum
CREATE TYPE "InvestorType" AS ENUM ('RETAIL', 'PROFESSIONAL', 'QUALIFIED');

-- CreateEnum
CREATE TYPE "KycEventType" AS ENUM ('SUBMIT', 'REVIEW', 'APPROVE', 'REJECT', 'EXPIRE', 'UPDATE');

-- CreateEnum
CREATE TYPE "PositionDirection" AS ENUM ('LONG', 'SHORT');

-- CreateEnum
CREATE TYPE "PositionStatus" AS ENUM ('OPEN', 'PARTIAL_CLOSED', 'CLOSED', 'LIQUIDATED');

-- CreateEnum
CREATE TYPE "OrderType" AS ENUM ('MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT');

-- CreateEnum
CREATE TYPE "TradeOrderStatus" AS ENUM ('DRAFT', 'PENDING', 'PARTIAL_FILLED', 'FILLED', 'SETTLED', 'CANCELLED', 'REJECTED', 'REVERSED');

-- CreateTable
CREATE TABLE "customers" (
    "uid" TEXT NOT NULL,
    "realName" TEXT,
    "idCardType" "IdCardType",
    "idCardNumber" TEXT,
    "idCardEncrypted" TEXT,
    "idCardIv" TEXT,
    "idCardAuthTag" TEXT,
    "kycStatus" "KycStatus" NOT NULL DEFAULT 'UNVERIFIED',
    "kycLevel" INTEGER NOT NULL DEFAULT 0,
    "riskLevel" "RiskLevel" NOT NULL DEFAULT 'MODERATE',
    "riskScore" INTEGER NOT NULL DEFAULT 50,
    "investorType" "InvestorType",
    "netWorth" DECIMAL(18,2),
    "annualIncome" DECIMAL(18,2),
    "investmentExperience" INTEGER DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "customers_pkey" PRIMARY KEY ("uid")
);

-- CreateTable
CREATE TABLE "kyc_events" (
    "id" TEXT NOT NULL,
    "customerUid" TEXT NOT NULL,
    "eventType" "KycEventType" NOT NULL,
    "status" "KycStatus" NOT NULL,
    "reviewerUid" TEXT,
    "reason" TEXT,
    "evidence" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "kyc_events_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "funds_accounts" (
    "id" TEXT NOT NULL,
    "customerUid" TEXT NOT NULL,
    "available" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "frozen" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "pending" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "total" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "currency" TEXT NOT NULL DEFAULT 'USDT',
    "creditsAccountId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "funds_accounts_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trading_accounts" (
    "id" TEXT NOT NULL,
    "customerUid" TEXT NOT NULL,
    "marginBalance" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "usedMargin" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "availableMargin" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "marginCallLevel" DECIMAL(5,4) NOT NULL DEFAULT 0.3,
    "liquidationLevel" DECIMAL(5,4) NOT NULL DEFAULT 0.1,
    "totalPositionValue" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "unrealizedPnl" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "trading_accounts_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "positions" (
    "id" TEXT NOT NULL,
    "tradingAccountId" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "direction" "PositionDirection" NOT NULL,
    "quantity" DECIMAL(18,8) NOT NULL,
    "avgPrice" DECIMAL(18,8) NOT NULL,
    "currentPrice" DECIMAL(18,8),
    "leverage" INTEGER NOT NULL DEFAULT 1,
    "marginMode" "MarginMode" NOT NULL DEFAULT 'CROSS',
    "unrealizedPnl" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "realizedPnl" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "status" "PositionStatus" NOT NULL DEFAULT 'OPEN',
    "openedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "closedAt" TIMESTAMP(3),

    CONSTRAINT "positions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trade_orders" (
    "id" TEXT NOT NULL,
    "orderNo" TEXT NOT NULL,
    "customerUid" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "direction" "Direction" NOT NULL,
    "orderType" "OrderType" NOT NULL,
    "quantity" DECIMAL(18,8) NOT NULL,
    "price" DECIMAL(18,8),
    "stopPrice" DECIMAL(18,8),
    "leverage" INTEGER NOT NULL DEFAULT 1,
    "filledQuantity" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "avgFillPrice" DECIMAL(18,8),
    "status" "TradeOrderStatus" NOT NULL DEFAULT 'DRAFT',
    "strategyId" TEXT,
    "exchangeOrderId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "trade_orders_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "kyc_events_customerUid_createdAt_idx" ON "kyc_events"("customerUid", "createdAt");

-- CreateIndex
CREATE UNIQUE INDEX "funds_accounts_customerUid_key" ON "funds_accounts"("customerUid");

-- CreateIndex
CREATE UNIQUE INDEX "funds_accounts_creditsAccountId_key" ON "funds_accounts"("creditsAccountId");

-- CreateIndex
CREATE UNIQUE INDEX "trading_accounts_customerUid_key" ON "trading_accounts"("customerUid");

-- CreateIndex
CREATE INDEX "positions_tradingAccountId_symbol_idx" ON "positions"("tradingAccountId", "symbol");

-- CreateIndex
CREATE UNIQUE INDEX "trade_orders_orderNo_key" ON "trade_orders"("orderNo");

-- CreateIndex
CREATE INDEX "trade_orders_customerUid_status_idx" ON "trade_orders"("customerUid", "status");

-- CreateIndex
CREATE INDEX "trade_orders_strategyId_idx" ON "trade_orders"("strategyId");

-- AddForeignKey
ALTER TABLE "customers" ADD CONSTRAINT "customers_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "kyc_events" ADD CONSTRAINT "kyc_events_customerUid_fkey" FOREIGN KEY ("customerUid") REFERENCES "customers"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "funds_accounts" ADD CONSTRAINT "funds_accounts_customerUid_fkey" FOREIGN KEY ("customerUid") REFERENCES "customers"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "funds_accounts" ADD CONSTRAINT "funds_accounts_creditsAccountId_fkey" FOREIGN KEY ("creditsAccountId") REFERENCES "credits_accounts"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trading_accounts" ADD CONSTRAINT "trading_accounts_customerUid_fkey" FOREIGN KEY ("customerUid") REFERENCES "customers"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "positions" ADD CONSTRAINT "positions_tradingAccountId_fkey" FOREIGN KEY ("tradingAccountId") REFERENCES "trading_accounts"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trade_orders" ADD CONSTRAINT "trade_orders_customerUid_fkey" FOREIGN KEY ("customerUid") REFERENCES "customers"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trade_orders" ADD CONSTRAINT "trade_orders_strategyId_fkey" FOREIGN KEY ("strategyId") REFERENCES "strategies"("id") ON DELETE SET NULL ON UPDATE CASCADE;
