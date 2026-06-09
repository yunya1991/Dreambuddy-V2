-- AlterTable
ALTER TABLE "credits_accounts" ADD COLUMN     "lastSigninAt" TIMESTAMP(3);

-- AlterTable
ALTER TABLE "strategy_tasks" ADD COLUMN     "taskOrderId" TEXT;

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

-- CreateIndex
CREATE INDEX "strategy_task_orders_ownerUserId_status_idx" ON "strategy_task_orders"("ownerUserId", "status");

-- CreateIndex
CREATE INDEX "strategy_task_orders_originStrategyId_idx" ON "strategy_task_orders"("originStrategyId");

-- CreateIndex
CREATE INDEX "strategy_execution_runs_strategyTaskOrderId_status_idx" ON "strategy_execution_runs"("strategyTaskOrderId", "status");

-- CreateIndex
CREATE INDEX "strategy_tasks_taskOrderId_idx" ON "strategy_tasks"("taskOrderId");

-- AddForeignKey
ALTER TABLE "strategy_tasks" ADD CONSTRAINT "strategy_tasks_taskOrderId_fkey" FOREIGN KEY ("taskOrderId") REFERENCES "strategy_task_orders"("strategyTaskOrderId") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_task_orders" ADD CONSTRAINT "strategy_task_orders_originStrategyId_fkey" FOREIGN KEY ("originStrategyId") REFERENCES "strategies"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_task_orders" ADD CONSTRAINT "strategy_task_orders_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "users"("uid") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_execution_runs" ADD CONSTRAINT "strategy_execution_runs_strategyTaskOrderId_fkey" FOREIGN KEY ("strategyTaskOrderId") REFERENCES "strategy_task_orders"("strategyTaskOrderId") ON DELETE CASCADE ON UPDATE CASCADE;
