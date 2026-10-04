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

-- CreateEnum
CREATE TYPE "RiskRuleType" AS ENUM ('PRE_TRADE', 'IN_TRADE', 'POST_TRADE');

-- CreateEnum
CREATE TYPE "RiskAction" AS ENUM ('BLOCK', 'WARN', 'APPROVE');

-- CreateEnum
CREATE TYPE "RiskSeverity" AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');

-- CreateEnum
CREATE TYPE "RiskEventStatus" AS ENUM ('OPEN', 'RESOLVED', 'IGNORED');

-- CreateEnum
CREATE TYPE "ReconciliationStatus" AS ENUM ('PENDING', 'MATCHED', 'MISMATCHED', 'ADJUSTED');

-- CreateEnum
CREATE TYPE "IdempotencyStatus" AS ENUM ('PROCESSING', 'SUCCESS', 'FAILED');

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
    "orderId" TEXT,
    "exchangeOrderId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "trade_orders_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "risk_rules" (
    "id" TEXT NOT NULL,
    "uid" TEXT,
    "name" TEXT NOT NULL,
    "ruleType" "RiskRuleType" NOT NULL,
    "ruleCode" TEXT NOT NULL,
    "description" TEXT,
    "threshold" DECIMAL(18,8),
    "thresholdPct" DECIMAL(5,4),
    "config" JSONB,
    "action" "RiskAction" NOT NULL DEFAULT 'BLOCK',
    "severity" "RiskSeverity" NOT NULL DEFAULT 'MEDIUM',
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "risk_rules_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "risk_events" (
    "id" TEXT NOT NULL,
    "uid" TEXT,
    "ruleId" TEXT,
    "eventType" TEXT NOT NULL,
    "severity" "RiskSeverity" NOT NULL DEFAULT 'MEDIUM',
    "status" "RiskEventStatus" NOT NULL DEFAULT 'OPEN',
    "resourceType" TEXT,
    "resourceId" TEXT,
    "detail" JSONB,
    "actionTaken" TEXT,
    "resolvedAt" TIMESTAMP(3),
    "resolvedBy" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "risk_events_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "reconciliation_records" (
    "id" TEXT NOT NULL,
    "reconDate" TIMESTAMP(3) NOT NULL,
    "reconType" TEXT NOT NULL,
    "status" "ReconciliationStatus" NOT NULL DEFAULT 'PENDING',
    "expectedAmount" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "actualAmount" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "difference" DECIMAL(18,8) NOT NULL DEFAULT 0,
    "detail" JSONB,
    "remark" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "reconciledAt" TIMESTAMP(3),

    CONSTRAINT "reconciliation_records_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "idempotency_keys" (
    "id" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "uid" TEXT,
    "resourceType" TEXT NOT NULL,
    "resourceId" TEXT,
    "status" "IdempotencyStatus" NOT NULL DEFAULT 'PROCESSING',
    "requestHash" TEXT,
    "response" JSONB,
    "expiresAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),

    CONSTRAINT "idempotency_keys_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "dreamos_sessions" (
    "id" BIGSERIAL NOT NULL,
    "trace_id" TEXT NOT NULL,
    "session_id" TEXT NOT NULL,
    "graph_name" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "start_ts" TIMESTAMP(3) NOT NULL,
    "end_ts" TIMESTAMP(3),
    "duration_ms" INTEGER,
    "total_nodes" INTEGER,
    "executed_nodes" INTEGER,
    "budget_tokens" INTEGER,
    "used_tokens" INTEGER,
    "termination_reason" TEXT,
    "extra" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "dreamos_sessions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "dreamos_spans" (
    "id" BIGSERIAL NOT NULL,
    "trace_id" TEXT NOT NULL,
    "span_id" TEXT NOT NULL,
    "parent_span_id" TEXT,
    "node_id" TEXT NOT NULL,
    "node_type" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "start_ts" TIMESTAMP(3) NOT NULL,
    "end_ts" TIMESTAMP(3),
    "duration_ms" INTEGER,
    "allocated_tokens" INTEGER,
    "used_tokens" INTEGER,
    "confidence" DECIMAL(5,4),
    "error_message" TEXT,
    "meta" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "dreamos_spans_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "dsh_subagent_calls" (
    "id" BIGSERIAL NOT NULL,
    "trace_id" TEXT NOT NULL,
    "subagent_type" TEXT NOT NULL,
    "request_payload" JSONB,
    "response_payload" JSONB,
    "status" TEXT NOT NULL,
    "duration_ms" INTEGER,
    "error_message" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "dsh_subagent_calls_pkey" PRIMARY KEY ("id")
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

-- CreateIndex
CREATE UNIQUE INDEX "risk_rules_ruleCode_key" ON "risk_rules"("ruleCode");

-- CreateIndex
CREATE INDEX "risk_rules_uid_isActive_idx" ON "risk_rules"("uid", "isActive");

-- CreateIndex
CREATE INDEX "risk_events_uid_createdAt_idx" ON "risk_events"("uid", "createdAt");

-- CreateIndex
CREATE INDEX "risk_events_ruleId_idx" ON "risk_events"("ruleId");

-- CreateIndex
CREATE INDEX "risk_events_status_idx" ON "risk_events"("status");

-- CreateIndex
CREATE UNIQUE INDEX "reconciliation_records_reconDate_key" ON "reconciliation_records"("reconDate");

-- CreateIndex
CREATE INDEX "reconciliation_records_reconDate_status_idx" ON "reconciliation_records"("reconDate", "status");

-- CreateIndex
CREATE UNIQUE INDEX "idempotency_keys_key_key" ON "idempotency_keys"("key");

-- CreateIndex
CREATE INDEX "idempotency_keys_uid_createdAt_idx" ON "idempotency_keys"("uid", "createdAt");

-- CreateIndex
CREATE INDEX "idempotency_keys_key_idx" ON "idempotency_keys"("key");

-- CreateIndex
CREATE UNIQUE INDEX "dreamos_sessions_trace_id_key" ON "dreamos_sessions"("trace_id");

-- CreateIndex
CREATE INDEX "dreamos_sessions_trace_id_idx" ON "dreamos_sessions"("trace_id");

-- CreateIndex
CREATE INDEX "dreamos_sessions_status_start_ts_idx" ON "dreamos_sessions"("status", "start_ts");

-- CreateIndex
CREATE INDEX "dreamos_spans_trace_id_idx" ON "dreamos_spans"("trace_id");

-- CreateIndex
CREATE INDEX "dreamos_spans_node_id_status_idx" ON "dreamos_spans"("node_id", "status");

-- CreateIndex
CREATE INDEX "dsh_subagent_calls_trace_id_idx" ON "dsh_subagent_calls"("trace_id");

-- CreateIndex
CREATE INDEX "dsh_subagent_calls_subagent_type_status_idx" ON "dsh_subagent_calls"("subagent_type", "status");

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

-- AddForeignKey
ALTER TABLE "trade_orders" ADD CONSTRAINT "trade_orders_orderId_fkey" FOREIGN KEY ("orderId") REFERENCES "orders"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "risk_rules" ADD CONSTRAINT "risk_rules_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "risk_events" ADD CONSTRAINT "risk_events_ruleId_fkey" FOREIGN KEY ("ruleId") REFERENCES "risk_rules"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "dreamos_spans" ADD CONSTRAINT "dreamos_spans_trace_id_fkey" FOREIGN KEY ("trace_id") REFERENCES "dreamos_sessions"("trace_id") ON DELETE SET NULL ON UPDATE CASCADE;
