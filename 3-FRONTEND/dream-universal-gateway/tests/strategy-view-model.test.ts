import test from "node:test";
import assert from "node:assert/strict";

import { buildStrategyPanelViewModel } from "../src/app/dashboard/strategy-view-model";

test("buildStrategyPanelViewModel derives applied and active strategies from lowercase task order status", () => {
  const viewModel = buildStrategyPanelViewModel({
    strategies: [
      {
        id: "recommended_001",
        type: "RECOMMENDED",
        name: "A4 顺势策略",
        direction: "BUY",
        leverage: 2,
        positionSize: 0.2,
        confidence: 76,
        edgeScore: 63,
        regime: "TREND",
        source: "A4",
        isRead: false,
      },
      {
        id: "custom_draft_001",
        type: "CUSTOM",
        status: "DRAFT",
        name: "草稿策略",
        direction: "SHORT",
        leverage: 3,
        positionSize: 0.15,
        tradeType: "SWAP",
        rawInput: "跌破支撑后做空",
        createdAt: "2026-05-22T08:00:00.000Z",
        updatedAt: "2026-05-22T08:30:00.000Z",
      },
      {
        id: "custom_applied_001",
        type: "CUSTOM",
        status: "PAUSED",
        name: "旧策略名称",
        description: "旧策略描述",
        direction: "BUY",
        leverage: 2,
        positionSize: 0.3,
        tradeType: "SWAP",
        createdAt: "2026-05-22T09:00:00.000Z",
        updatedAt: "2026-05-22T10:00:00.000Z",
        taskOrders: [
          {
            strategyTaskOrderId: "order_applied_001",
            status: "applied",
            title: "RSI 超卖反弹",
            summary: "以 task order 为准的摘要",
            originStrategyId: "custom_applied_001",
            appliedAt: "2026-05-22T10:00:00.000Z",
            strategySnapshot: {
              direction: "BUY",
              symbol: "BTC-USDT-SWAP",
              tradeType: "SWAP",
              leverage: 2,
              positionSize: 0.3,
              stopLoss: 79200,
              takeProfit: 83500,
              frequency: "FOUR_H",
              confidence: 72,
            },
            strategyTasks: [
              {
                id: "task_001",
                status: "ACTIVE",
                executionFrequency: "ONE_H",
                nextExecutionAt: "2026-05-22T12:00:00.000Z",
                executionCount: 3,
                tradeCount: 1,
                skipCount: 2,
              },
            ],
            executionRuns: [
              {
                strategyExecutionRunId: "run_001",
                status: "running",
                createdAt: "2026-05-22T10:05:00.000Z",
              },
            ],
          },
          {
            strategyTaskOrderId: "order_paused_001",
            status: "paused",
            title: "已暂停任务单",
            originStrategyId: "custom_applied_001",
            appliedAt: "2026-05-22T09:00:00.000Z",
            strategySnapshot: {
              direction: "BUY",
              symbol: "BTC-USDT-SWAP",
              tradeType: "SWAP",
              leverage: 1,
              positionSize: 0.1,
              stopLoss: null,
              takeProfit: null,
              frequency: "ONE_D",
              confidence: 60,
            },
            strategyTasks: [],
            executionRuns: [],
          },
        ],
      },
    ],
  });

  assert.equal(viewModel.recommended.length, 1);
  assert.equal(viewModel.drafts.length, 1);
  assert.equal(viewModel.custom.length, 2);

  assert.equal(viewModel.applied.length, 1);
  assert.equal(viewModel.applied[0]?.strategyId, "custom_applied_001");
  assert.equal(viewModel.applied[0]?.taskOrderId, "order_applied_001");
  assert.equal(viewModel.applied[0]?.title, "RSI 超卖反弹");
  assert.equal(viewModel.applied[0]?.summary, "以 task order 为准的摘要");
  assert.equal(viewModel.applied[0]?.status, "applied");
  assert.equal(viewModel.applied[0]?.frequency, "FOUR_H");
  assert.equal(viewModel.applied[0]?.frequencyLabel, "4小时");

  assert.equal(viewModel.active.length, 1);
  assert.equal(viewModel.active[0]?.taskOrderId, "order_applied_001");
  assert.equal(viewModel.active[0]?.runStatus, "running");
  assert.equal(viewModel.active[0]?.taskStatus, "ACTIVE");
  assert.equal(viewModel.active[0]?.nextExecutionAt, "2026-05-22T12:00:00.000Z");
  assert.equal(viewModel.active[0]?.executionCount, 3);
  assert.equal(viewModel.active[0]?.tradeCount, 1);
  assert.equal(viewModel.active[0]?.skipCount, 2);
});

test("buildStrategyPanelViewModel falls back to empty collections for malformed payload", () => {
  const viewModel = buildStrategyPanelViewModel(null);

  assert.deepEqual(viewModel, {
    recommended: [],
    custom: [],
    drafts: [],
    applied: [],
    active: [],
  });
});
