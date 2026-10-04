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

-- AddForeignKey
ALTER TABLE "risk_rules" ADD CONSTRAINT "risk_rules_uid_fkey" FOREIGN KEY ("uid") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "risk_events" ADD CONSTRAINT "risk_events_ruleId_fkey" FOREIGN KEY ("ruleId") REFERENCES "risk_rules"("id") ON DELETE SET NULL ON UPDATE CASCADE;
