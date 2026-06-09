-- CreateEnum
CREATE TYPE "UserRole" AS ENUM ('FREE', 'PRO', 'ADMIN');

-- CreateEnum
CREATE TYPE "TradeType" AS ENUM ('SPOT', 'SWAP');

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
    "availableCapital" DOUBLE PRECISION,
    "capitalPercentage" DOUBLE PRECISION NOT NULL DEFAULT 0.10,
    "tradeType" "TradeType" NOT NULL DEFAULT 'SPOT',
    "leverageMax" INTEGER NOT NULL DEFAULT 3,
    "dailyLossLimit" DOUBLE PRECISION NOT NULL DEFAULT 500,
    "dailyLossPercent" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "accountLossLimit" DOUBLE PRECISION NOT NULL DEFAULT 2000,
    "accountLossPercent" DOUBLE PRECISION NOT NULL DEFAULT 0.20,
    "allowedSymbols" TEXT[] DEFAULT ARRAY['BTC-USDT-SWAP']::TEXT[],
    "isTradingEnabled" BOOLEAN NOT NULL DEFAULT false,
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
    "todayLoss" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "todayTradeCount" INTEGER NOT NULL DEFAULT 0,
    "lastResetDate" TEXT NOT NULL,
    "totalLoss" DOUBLE PRECISION NOT NULL DEFAULT 0,
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
    "positionSize" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "stopLoss" DOUBLE PRECISION,
    "takeProfit" DOUBLE PRECISION,
    "confidence" INTEGER,
    "edgeScore" INTEGER,
    "regime" TEXT,
    "source" TEXT,
    "isRead" BOOLEAN NOT NULL DEFAULT false,
    "rawInput" TEXT,
    "parsedIntent" JSONB,
    "backtestResult" JSONB,
    "status" "StrategyStatus" NOT NULL DEFAULT 'DRAFT',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "strategies_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "strategy_tasks" (
    "id" TEXT NOT NULL,
    "strategyId" TEXT NOT NULL,
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
CREATE TABLE "channel_configs" (
    "id" TEXT NOT NULL,
    "uid" TEXT NOT NULL,
    "channelType" "ChannelType" NOT NULL,
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
    "balance" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "totalEarned" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "totalSpent" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "pendingCredits" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "signupBonus" BOOLEAN NOT NULL DEFAULT false,
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
    "amount" DOUBLE PRECISION NOT NULL,
    "balanceAfter" DOUBLE PRECISION NOT NULL,
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
    "amount" DOUBLE PRECISION NOT NULL,
    "credits" DOUBLE PRECISION NOT NULL,
    "bonusCredits" DOUBLE PRECISION NOT NULL DEFAULT 0,
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

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE UNIQUE INDEX "api_configs_uid_category_provider_label_key" ON "api_configs"("uid", "category", "provider", "label");

-- CreateIndex
CREATE UNIQUE INDEX "trading_params_uid_key" ON "trading_params"("uid");

-- CreateIndex
CREATE UNIQUE INDEX "credits_accounts_uid_key" ON "credits_accounts"("uid");

-- CreateIndex
CREATE UNIQUE INDEX "orders_orderNo_key" ON "orders"("orderNo");

-- CreateIndex
CREATE UNIQUE INDEX "sessions_sessionToken_key" ON "sessions"("sessionToken");

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
ALTER TABLE "channel_configs" ADD CONSTRAINT "channel_configs_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "credits_accounts" ADD CONSTRAINT "credits_accounts_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "credits_transactions" ADD CONSTRAINT "credits_transactions_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "orders" ADD CONSTRAINT "orders_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;
