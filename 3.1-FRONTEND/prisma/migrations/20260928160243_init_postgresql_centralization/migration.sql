-- CreateEnum
CREATE TYPE "UserRole" AS ENUM ('FREE', 'PRO', 'ADMIN');

-- CreateEnum
CREATE TYPE "TradeType" AS ENUM ('SPOT', 'SWAP');

-- CreateEnum
CREATE TYPE "TradeMode" AS ENUM ('SPOT_MODE', 'SWAP_MODE', 'FUTURES_MODE', 'OPTIONS_MODE', 'MARGIN_MODE');

-- CreateEnum
CREATE TYPE "MarginMode" AS ENUM ('CROSS', 'ISOLATED');

-- CreateEnum
CREATE TYPE "PositionMode" AS ENUM ('NET', 'HEDGE');

-- CreateEnum
CREATE TYPE "OptionsType" AS ENUM ('CALL', 'PUT');

-- CreateEnum
CREATE TYPE "Frequency" AS ENUM ('ONE_H', 'FOUR_H', 'ONE_D');

-- CreateEnum
CREATE TYPE "RiskTolerance" AS ENUM ('CONSERVATIVE', 'MODERATE', 'AGGRESSIVE');

-- CreateEnum
CREATE TYPE "ApiCategory" AS ENUM ('EXCHANGE', 'LLM', 'DATA_SOURCE');

-- CreateEnum
CREATE TYPE "TradingStatus" AS ENUM ('ACTIVE', 'PAUSED', 'FROZEN', 'LOCKED');

-- CreateEnum
CREATE TYPE "StrategyType" AS ENUM ('RECOMMENDED', 'CUSTOM');

-- CreateEnum
CREATE TYPE "Direction" AS ENUM ('BUY', 'SHORT', 'SKIP');

-- CreateEnum
CREATE TYPE "StrategyStatus" AS ENUM ('DRAFT', 'APPROVED', 'APPLIED', 'PAUSED', 'EXPIRED');

-- CreateEnum
CREATE TYPE "TaskStatus" AS ENUM ('ACTIVE', 'PAUSED', 'COMPLETED', 'FAILED');

-- CreateEnum
CREATE TYPE "ChannelType" AS ENUM ('TELEGRAM', 'WECHAT_SERVERCHAN', 'WECHAT_WORK', 'EMAIL_SMTP', 'DISCORD', 'SLACK');

-- CreateEnum
CREATE TYPE "PushFormat" AS ENUM ('CONCISE', 'DETAILED');

-- CreateEnum
CREATE TYPE "CreditsType" AS ENUM ('EARN', 'SPEND');

-- CreateEnum
CREATE TYPE "CreditsCategory" AS ENUM ('RECHARGE', 'SIGNIN', 'REFERRAL', 'BONUS', 'SIGNUP_BONUS', 'STRATEGY_EXECUTION', 'ANALYSIS_REPORT', 'INTEL_BRIEF');

-- CreateEnum
CREATE TYPE "PaymentMethod" AS ENUM ('WECHAT_PAY', 'ALIPAY', 'APPLE_PAY');

-- CreateEnum
CREATE TYPE "OrderStatus" AS ENUM ('PENDING', 'PAID', 'COMPLETED', 'CANCELLED', 'REFUNDED', 'FAILED');

-- CreateEnum
CREATE TYPE "CodeType" AS ENUM ('EMAIL_VERIFY', 'PASSWORD_RESET', 'LOGIN_2FA');

-- CreateTable
CREATE TABLE "users" (
    "uid" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "emailVerified" BOOLEAN NOT NULL DEFAULT false,
    "passwordHash" TEXT NOT NULL,
    "displayName" TEXT,
    "avatarUrl" TEXT,
    "role" "UserRole" NOT NULL DEFAULT 'FREE',
    "loginAttempts" INTEGER NOT NULL DEFAULT 0,
    "lockedUntil" TIMESTAMP(3),
    "lastLoginAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "users_pkey" PRIMARY KEY ("uid")
);

-- CreateTable
CREATE TABLE "user_profiles" (
    "uid" TEXT NOT NULL,
    "availableCapital" DECIMAL(18,8),
    "capitalPercentage" DECIMAL(5,4) NOT NULL DEFAULT 0.10,
    "tradeType" "TradeType" NOT NULL DEFAULT 'SPOT',
    "tradeMode" "TradeMode" NOT NULL DEFAULT 'SPOT_MODE',
    "marginMode" "MarginMode",
    "positionMode" "PositionMode" NOT NULL DEFAULT 'NET',
    "leverageMax" INTEGER NOT NULL DEFAULT 3,
    "dailyLossLimit" DECIMAL(18,8) NOT NULL DEFAULT 500,
    "dailyLossPercent" DECIMAL(5,4) NOT NULL DEFAULT 0.05,
    "accountLossLimit" DECIMAL(18,8) NOT NULL DEFAULT 2000,
    "accountLossPercent" DECIMAL(5,4) NOT NULL DEFAULT 0.20,
    "allowedSymbols" JSONB NOT NULL DEFAULT '["BTC-USDT-SWAP"]',
    "allowedTradeModes" JSONB NOT NULL DEFAULT '["SPOT_MODE"]',
    "isTradingEnabled" BOOLEAN NOT NULL DEFAULT false,
    "optionsType" "OptionsType",
    "expiryDate" TEXT,
    "preferredFrequency" "Frequency" DEFAULT 'FOUR_H',
    "riskTolerance" "RiskTolerance" NOT NULL DEFAULT 'MODERATE',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "user_profiles_pkey" PRIMARY KEY ("uid")
);

-- CreateTable
CREATE TABLE "api_configs" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "category" "ApiCategory" NOT NULL,
    "provider" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "encryptedData" TEXT NOT NULL,
    "iv" TEXT NOT NULL,
    "authTag" TEXT NOT NULL,
    "keyHint" TEXT,
    "environment" TEXT,
    "baseUrl" TEXT,
    "isVerified" BOOLEAN NOT NULL DEFAULT false,
    "lastVerifiedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "api_configs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trading_params" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "todayLoss" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "todayTradeCount" INTEGER NOT NULL DEFAULT 0,
    "lastResetDate" TEXT NOT NULL,
    "totalLoss" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "totalTradeCount" INTEGER NOT NULL DEFAULT 0,
    "status" "TradingStatus" NOT NULL DEFAULT 'ACTIVE',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "trading_params_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "strategies" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "type" "StrategyType" NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "direction" "Direction" NOT NULL,
    "symbol" TEXT NOT NULL DEFAULT 'BTC-USDT-SWAP',
    "tradeType" "TradeType" NOT NULL DEFAULT 'SPOT',
    "leverage" INTEGER NOT NULL DEFAULT 1,
    "positionSize" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "stopLoss" DECIMAL(18,8),
    "takeProfit" DECIMAL(18,8),
    "confidence" INTEGER,
    "edgeScore" INTEGER,
    "regime" TEXT,
    "source" TEXT,
    "isRead" BOOLEAN NOT NULL DEFAULT false,
    "rawInput" TEXT,
    "parsedIntent" JSONB,
    "backtestResult" JSONB,
    "status" "StrategyStatus" NOT NULL DEFAULT 'DRAFT',
    "backtestSharpe" DECIMAL(10,6),
    "backtestMaxDrawdown" DECIMAL(10,6),
    "backtestWinRate" DECIMAL(10,6),
    "backtestProfitFactor" DECIMAL(10,6),
    "backtestTotalReturn" DECIMAL(10,6),
    "backtestPeriod" TEXT,
    "backtestDate" TIMESTAMP(3),
    "baselineVersion" TEXT,
    "baselineSharpe" DECIMAL(10,6),
    "baselineMaxDrawdown" DECIMAL(10,6),
    "baselineTotalReturn" DECIMAL(10,6),
    "isBetterThanBaseline" BOOLEAN,
    "sourceEngine" TEXT,
    "sourceReportIds" TEXT,
    "generation" INTEGER,
    "parentStrategyId" TEXT,
    "isInLibrary" BOOLEAN,
    "libraryScore" DECIMAL(10,6),
    "libraryActive" BOOLEAN,
    "libraryArchivedAt" TIMESTAMP(3),
    "recommendedDays" INTEGER,
    "lastDailyBacktestDate" TIMESTAMP(3),
    "consecutiveBelowBaseline" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "strategies_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "strategy_tasks" (
    "id" TEXT NOT NULL,
    "strategyId" TEXT NOT NULL,
    "taskOrderId" TEXT,
    "uid" TEXT NOT NULL,
    "exchangeConfigId" TEXT,
    "executionFrequency" "Frequency" NOT NULL,
    "status" "TaskStatus" NOT NULL DEFAULT 'ACTIVE',
    "nextExecutionAt" TIMESTAMP(3),
    "lastExecutionAt" TIMESTAMP(3),
    "executionCount" INTEGER NOT NULL DEFAULT 0,
    "skipCount" INTEGER NOT NULL DEFAULT 0,
    "tradeCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "strategy_tasks_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "strategy_task_orders" (
    "strategyTaskOrderId" TEXT NOT NULL,
    "strategyType" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "summary" TEXT,
    "rawInput" TEXT,
    "originStrategyId" TEXT NOT NULL,
    "ownerUserId" TEXT NOT NULL,
    "strategySnapshot" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "appliedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "strategy_task_orders_pkey" PRIMARY KEY ("strategyTaskOrderId")
);

-- CreateTable
CREATE TABLE "strategy_execution_runs" (
    "strategyExecutionRunId" TEXT NOT NULL,
    "strategyTaskOrderId" TEXT NOT NULL,
    "triggerType" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "startedAt" TIMESTAMP(3),
    "endedAt" TIMESTAMP(3),
    "reason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "strategy_execution_runs_pkey" PRIMARY KEY ("strategyExecutionRunId")
);

-- CreateTable
CREATE TABLE "channel_configs" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "channelType" "ChannelType" NOT NULL,
    "label" TEXT NOT NULL,
    "encryptedData" TEXT NOT NULL,
    "iv" TEXT NOT NULL,
    "authTag" TEXT NOT NULL,
    "pushRules" JSONB NOT NULL,
    "silentStart" TEXT,
    "silentEnd" TEXT,
    "format" "PushFormat" NOT NULL DEFAULT 'CONCISE',
    "isOnline" BOOLEAN NOT NULL DEFAULT false,
    "lastTestAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "channel_configs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "credits_accounts" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "balance" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "totalEarned" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "totalSpent" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "pendingCredits" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "signupBonus" BOOLEAN NOT NULL DEFAULT false,
    "lastSigninAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "credits_accounts_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "credits_transactions" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "type" "CreditsType" NOT NULL,
    "category" "CreditsCategory" NOT NULL,
    "amount" DECIMAL(18,8) NOT NULL,
    "balanceAfter" DECIMAL(18,8) NOT NULL,
    "description" TEXT NOT NULL,
    "relatedId" TEXT,
    "expiresAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "credits_transactions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "orders" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "orderNo" TEXT NOT NULL,
    "packageId" TEXT NOT NULL,
    "amount" DECIMAL(18,8) NOT NULL,
    "credits" DECIMAL(18,8) NOT NULL,
    "bonusCredits" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "paymentMethod" "PaymentMethod" NOT NULL,
    "paymentNo" TEXT,
    "status" "OrderStatus" NOT NULL DEFAULT 'PENDING',
    "paidAt" TIMESTAMP(3),
    "completedAt" TIMESTAMP(3),
    "expiredAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "orders_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "verification_codes" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "type" "CodeType" NOT NULL,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "maxAttempts" INTEGER NOT NULL DEFAULT 5,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "usedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "verification_codes_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sessions" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "sessionToken" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "sessions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "strategy_backtest_records" (
    "id" TEXT NOT NULL,
    "strategyId" TEXT NOT NULL,
    "backtestDate" TIMESTAMP(3) NOT NULL,
    "backtestPeriod" TEXT NOT NULL,
    "baselineVersion" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "sharpeRatio" DECIMAL(10,6) NOT NULL,
    "maxDrawdown" DECIMAL(10,6) NOT NULL,
    "winRate" DECIMAL(10,6) NOT NULL,
    "profitFactor" DECIMAL(10,6) NOT NULL,
    "totalReturn" DECIMAL(10,6) NOT NULL,
    "tradeCount" INTEGER NOT NULL,
    "baselineSharpe" DECIMAL(10,6) NOT NULL,
    "baselineMaxDrawdown" DECIMAL(10,6) NOT NULL,
    "baselineTotalReturn" DECIMAL(10,6) NOT NULL,
    "isBetterThanBaseline" BOOLEAN NOT NULL DEFAULT false,
    "betterCount" INTEGER NOT NULL DEFAULT 0,
    "reportPath" TEXT,
    "rawMetrics" JSONB,
    "runId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "strategy_backtest_records_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "recommendation_engine_logs" (
    "runId" TEXT NOT NULL,
    "runDate" TIMESTAMP(3) NOT NULL,
    "triggerType" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "reportsUsed" INTEGER NOT NULL DEFAULT 0,
    "reportIds" JSONB NOT NULL,
    "candidatesGenerated" INTEGER NOT NULL DEFAULT 0,
    "strategiesBacktested" INTEGER NOT NULL DEFAULT 0,
    "strategiesPassed" INTEGER NOT NULL DEFAULT 0,
    "recommendedStrategyId" TEXT,
    "recommendedStrategyName" TEXT,
    "isForcedRefresh" BOOLEAN NOT NULL DEFAULT false,
    "decisionReason" TEXT,
    "errorMessage" TEXT,
    "durationMs" INTEGER,
    "startedAt" TIMESTAMP(3),
    "endedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "recommendation_engine_logs_pkey" PRIMARY KEY ("runId")
);

-- CreateTable
CREATE TABLE "trading_rankings" (
    "id" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "rank" INTEGER NOT NULL,
    "symbol" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "score" DECIMAL(10,6) NOT NULL,
    "signal" TEXT NOT NULL,
    "confidence" DECIMAL(10,6) NOT NULL,
    "decisionCard" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "trading_rankings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ranking_monitors" (
    "id" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "satisfaction" DECIMAL(10,6),
    "conversionRate" DECIMAL(10,6),
    "abandonRate" DECIMAL(10,6),
    "pushReachRate" DECIMAL(10,6),
    "unsubscribeRate" DECIMAL(10,6),
    "matu" INTEGER,
    "kFactor" DECIMAL(10,6),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ranking_monitors_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "audit_logs" (
    "id" TEXT NOT NULL,
    "uid" TEXT,
    "action" TEXT NOT NULL,
    "resource" TEXT NOT NULL,
    "resourceId" TEXT,
    "before" JSONB,
    "after" JSONB,
    "ip" TEXT,
    "userAgent" TEXT,
    "traceId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "audit_logs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ledger_transactions" (
    "id" TEXT NOT NULL,
    "txId" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "amount" DECIMAL(18,8) NOT NULL,
    "description" TEXT,
    "relatedType" TEXT,
    "relatedId" TEXT,
    "idempotencyKey" TEXT,
    "status" TEXT NOT NULL DEFAULT 'POSTED',
    "reversedBy" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "postedAt" TIMESTAMP(3),

    CONSTRAINT "ledger_transactions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ledger_postings" (
    "id" TEXT NOT NULL,
    "transactionId" TEXT NOT NULL,
    "accountCode" TEXT NOT NULL,
    "accountUid" TEXT,
    "direction" TEXT NOT NULL,
    "amount" DECIMAL(18,8) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ledger_postings_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE UNIQUE INDEX "api_configs_uid_category_provider_label_key" ON "api_configs"("uid", "category", "provider", "label");

-- CreateIndex
CREATE UNIQUE INDEX "trading_params_uid_key" ON "trading_params"("uid");

-- CreateIndex
CREATE INDEX "strategy_tasks_taskOrderId_idx" ON "strategy_tasks"("taskOrderId");

-- CreateIndex
CREATE INDEX "strategy_task_orders_ownerUserId_status_idx" ON "strategy_task_orders"("ownerUserId", "status");

-- CreateIndex
CREATE INDEX "strategy_task_orders_originStrategyId_idx" ON "strategy_task_orders"("originStrategyId");

-- CreateIndex
CREATE INDEX "strategy_execution_runs_strategyTaskOrderId_status_idx" ON "strategy_execution_runs"("strategyTaskOrderId", "status");

-- CreateIndex
CREATE UNIQUE INDEX "credits_accounts_uid_key" ON "credits_accounts"("uid");

-- CreateIndex
CREATE UNIQUE INDEX "orders_orderNo_key" ON "orders"("orderNo");

-- CreateIndex
CREATE UNIQUE INDEX "sessions_sessionToken_key" ON "sessions"("sessionToken");

-- CreateIndex
CREATE INDEX "strategy_backtest_records_strategyId_backtestDate_idx" ON "strategy_backtest_records"("strategyId", "backtestDate");

-- CreateIndex
CREATE INDEX "recommendation_engine_logs_runDate_status_idx" ON "recommendation_engine_logs"("runDate", "status");

-- CreateIndex
CREATE INDEX "trading_rankings_date_idx" ON "trading_rankings"("date");

-- CreateIndex
CREATE INDEX "trading_rankings_category_idx" ON "trading_rankings"("category");

-- CreateIndex
CREATE UNIQUE INDEX "ranking_monitors_date_key" ON "ranking_monitors"("date");

-- CreateIndex
CREATE INDEX "audit_logs_uid_createdAt_idx" ON "audit_logs"("uid", "createdAt");

-- CreateIndex
CREATE INDEX "audit_logs_resource_resourceId_idx" ON "audit_logs"("resource", "resourceId");

-- CreateIndex
CREATE UNIQUE INDEX "ledger_transactions_txId_key" ON "ledger_transactions"("txId");

-- CreateIndex
CREATE UNIQUE INDEX "ledger_transactions_idempotencyKey_key" ON "ledger_transactions"("idempotencyKey");

-- CreateIndex
CREATE INDEX "ledger_transactions_uid_createdAt_idx" ON "ledger_transactions"("uid", "createdAt");

-- CreateIndex
CREATE INDEX "ledger_transactions_relatedType_relatedId_idx" ON "ledger_transactions"("relatedType", "relatedId");

-- CreateIndex
CREATE INDEX "ledger_postings_transactionId_idx" ON "ledger_postings"("transactionId");

-- CreateIndex
CREATE INDEX "ledger_postings_accountCode_accountUid_idx" ON "ledger_postings"("accountCode", "accountUid");

-- AddForeignKey
ALTER TABLE "user_profiles" ADD CONSTRAINT "user_profiles_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "api_configs" ADD CONSTRAINT "api_configs_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trading_params" ADD CONSTRAINT "trading_params_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategies" ADD CONSTRAINT "strategies_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_tasks" ADD CONSTRAINT "strategy_tasks_strategyId_fkey" FOREIGN KEY ("strategyId") REFERENCES "strategies"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_tasks" ADD CONSTRAINT "strategy_tasks_taskOrderId_fkey" FOREIGN KEY ("taskOrderId") REFERENCES "strategy_task_orders"("strategyTaskOrderId") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_task_orders" ADD CONSTRAINT "strategy_task_orders_originStrategyId_fkey" FOREIGN KEY ("originStrategyId") REFERENCES "strategies"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_task_orders" ADD CONSTRAINT "strategy_task_orders_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_execution_runs" ADD CONSTRAINT "strategy_execution_runs_strategyTaskOrderId_fkey" FOREIGN KEY ("strategyTaskOrderId") REFERENCES "strategy_task_orders"("strategyTaskOrderId") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "channel_configs" ADD CONSTRAINT "channel_configs_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "credits_accounts" ADD CONSTRAINT "credits_accounts_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "credits_transactions" ADD CONSTRAINT "credits_transactions_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "orders" ADD CONSTRAINT "orders_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_backtest_records" ADD CONSTRAINT "strategy_backtest_records_strategyId_fkey" FOREIGN KEY ("strategyId") REFERENCES "strategies"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ledger_postings" ADD CONSTRAINT "ledger_postings_transactionId_fkey" FOREIGN KEY ("transactionId") REFERENCES "ledger_transactions"("id") ON DELETE CASCADE ON UPDATE CASCADE;
