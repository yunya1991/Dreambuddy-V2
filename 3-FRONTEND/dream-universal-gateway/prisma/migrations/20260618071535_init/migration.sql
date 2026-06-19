-- CreateTable
CREATE TABLE "users" (
    "uid" TEXT NOT NULL PRIMARY KEY,
    "email" TEXT NOT NULL,
    "emailVerified" BOOLEAN NOT NULL DEFAULT false,
    "passwordHash" TEXT NOT NULL,
    "displayName" TEXT,
    "avatarUrl" TEXT,
    "role" TEXT NOT NULL DEFAULT 'FREE',
    "loginAttempts" INTEGER NOT NULL DEFAULT 0,
    "lockedUntil" DATETIME,
    "lastLoginAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "user_profiles" (
    "uid" TEXT NOT NULL PRIMARY KEY,
    "availableCapital" REAL,
    "capitalPercentage" REAL NOT NULL DEFAULT 0.10,
    "tradeType" TEXT NOT NULL DEFAULT 'SPOT',
    "tradeMode" TEXT NOT NULL DEFAULT 'SPOT_MODE',
    "marginMode" TEXT,
    "positionMode" TEXT NOT NULL DEFAULT 'NET',
    "leverageMax" INTEGER NOT NULL DEFAULT 3,
    "dailyLossLimit" REAL NOT NULL DEFAULT 500,
    "dailyLossPercent" REAL NOT NULL DEFAULT 0.05,
    "accountLossLimit" REAL NOT NULL DEFAULT 2000,
    "accountLossPercent" REAL NOT NULL DEFAULT 0.20,
    "allowedSymbols" TEXT NOT NULL DEFAULT '["BTC-USDT-SWAP"]',
    "allowedTradeModes" TEXT NOT NULL DEFAULT '["SPOT_MODE"]',
    "isTradingEnabled" BOOLEAN NOT NULL DEFAULT false,
    "optionsType" TEXT,
    "expiryDate" TEXT,
    "preferredFrequency" TEXT DEFAULT 'FOUR_H',
    "riskTolerance" TEXT NOT NULL DEFAULT 'MODERATE',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "user_profiles_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "api_configs" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "provider" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "encryptedData" TEXT NOT NULL,
    "iv" TEXT NOT NULL,
    "authTag" TEXT NOT NULL,
    "keyHint" TEXT,
    "environment" TEXT,
    "baseUrl" TEXT,
    "isVerified" BOOLEAN NOT NULL DEFAULT false,
    "lastVerifiedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "api_configs_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "trading_params" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "todayLoss" REAL NOT NULL DEFAULT 0,
    "todayTradeCount" INTEGER NOT NULL DEFAULT 0,
    "lastResetDate" TEXT NOT NULL,
    "totalLoss" REAL NOT NULL DEFAULT 0,
    "totalTradeCount" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'ACTIVE',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "trading_params_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "strategies" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "direction" TEXT NOT NULL,
    "symbol" TEXT NOT NULL DEFAULT 'BTC-USDT-SWAP',
    "tradeType" TEXT NOT NULL DEFAULT 'SPOT',
    "leverage" INTEGER NOT NULL DEFAULT 1,
    "positionSize" REAL NOT NULL DEFAULT 0,
    "stopLoss" REAL,
    "takeProfit" REAL,
    "confidence" INTEGER,
    "edgeScore" INTEGER,
    "regime" TEXT,
    "source" TEXT,
    "isRead" BOOLEAN NOT NULL DEFAULT false,
    "rawInput" TEXT,
    "parsedIntent" JSONB,
    "backtestResult" JSONB,
    "status" TEXT NOT NULL DEFAULT 'DRAFT',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "strategies_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "strategy_tasks" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "strategyId" TEXT NOT NULL,
    "taskOrderId" TEXT,
    "uid" TEXT NOT NULL,
    "exchangeConfigId" TEXT,
    "executionFrequency" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'ACTIVE',
    "nextExecutionAt" DATETIME,
    "lastExecutionAt" DATETIME,
    "executionCount" INTEGER NOT NULL DEFAULT 0,
    "skipCount" INTEGER NOT NULL DEFAULT 0,
    "tradeCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "strategy_tasks_strategyId_fkey" FOREIGN KEY ("strategyId") REFERENCES "strategies" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "strategy_tasks_taskOrderId_fkey" FOREIGN KEY ("taskOrderId") REFERENCES "strategy_task_orders" ("strategyTaskOrderId") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "strategy_task_orders" (
    "strategyTaskOrderId" TEXT NOT NULL PRIMARY KEY,
    "strategyType" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "summary" TEXT,
    "rawInput" TEXT,
    "originStrategyId" TEXT NOT NULL,
    "ownerUserId" TEXT NOT NULL,
    "strategySnapshot" JSONB NOT NULL,
    "createdAt" DATETIME NOT NULL,
    "updatedAt" DATETIME NOT NULL,
    "appliedAt" DATETIME NOT NULL,
    CONSTRAINT "strategy_task_orders_originStrategyId_fkey" FOREIGN KEY ("originStrategyId") REFERENCES "strategies" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "strategy_task_orders_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "strategy_execution_runs" (
    "strategyExecutionRunId" TEXT NOT NULL PRIMARY KEY,
    "strategyTaskOrderId" TEXT NOT NULL,
    "triggerType" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "startedAt" DATETIME,
    "endedAt" DATETIME,
    "reason" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "strategy_execution_runs_strategyTaskOrderId_fkey" FOREIGN KEY ("strategyTaskOrderId") REFERENCES "strategy_task_orders" ("strategyTaskOrderId") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "channel_configs" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "channelType" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "encryptedData" TEXT NOT NULL,
    "iv" TEXT NOT NULL,
    "authTag" TEXT NOT NULL,
    "pushRules" JSONB NOT NULL,
    "silentStart" TEXT,
    "silentEnd" TEXT,
    "format" TEXT NOT NULL DEFAULT 'CONCISE',
    "isOnline" BOOLEAN NOT NULL DEFAULT false,
    "lastTestAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "channel_configs_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "credits_accounts" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "balance" REAL NOT NULL DEFAULT 0,
    "totalEarned" REAL NOT NULL DEFAULT 0,
    "totalSpent" REAL NOT NULL DEFAULT 0,
    "pendingCredits" REAL NOT NULL DEFAULT 0,
    "signupBonus" BOOLEAN NOT NULL DEFAULT false,
    "lastSigninAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "credits_accounts_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "credits_transactions" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "amount" REAL NOT NULL,
    "balanceAfter" REAL NOT NULL,
    "description" TEXT NOT NULL,
    "relatedId" TEXT,
    "expiresAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "credits_transactions_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "orders" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "orderNo" TEXT NOT NULL,
    "packageId" TEXT NOT NULL,
    "amount" REAL NOT NULL,
    "credits" REAL NOT NULL,
    "bonusCredits" REAL NOT NULL DEFAULT 0,
    "paymentMethod" TEXT NOT NULL,
    "paymentNo" TEXT,
    "status" TEXT NOT NULL DEFAULT 'PENDING',
    "paidAt" DATETIME,
    "completedAt" DATETIME,
    "expiredAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "orders_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "verification_codes" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "email" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "maxAttempts" INTEGER NOT NULL DEFAULT 5,
    "expiresAt" DATETIME NOT NULL,
    "usedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "sessions" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "uid" TEXT NOT NULL,
    "sessionToken" TEXT NOT NULL,
    "expiresAt" DATETIME NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "sessions_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users" ("uid") ON DELETE CASCADE ON UPDATE CASCADE
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
