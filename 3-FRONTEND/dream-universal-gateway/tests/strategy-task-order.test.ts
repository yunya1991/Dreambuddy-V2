import test from "node:test";
import assert from "node:assert/strict";

import {
  buildQueuedExecutionRun,
  buildTaskOrderFromStrategy,
} from "../src/lib/strategy-task-order";
import { persistStrategyTaskOrder } from "../src/lib/strategy-task-order-service";

test("buildTaskOrderFromStrategy creates a system strategy task order snapshot", () => {
  const order = buildTaskOrderFromStrategy({
    strategy: {
      id: "strat_rec_001",
      type: "RECOMMENDED",
      name: "区间震荡防守策略",
      description: "A4 推荐",
      direction: "SKIP",
      symbol: "BTC-USDT-SWAP",
      tradeType: "SPOT",
      leverage: 1,
      positionSize: 0,
      stopLoss: null,
      takeProfit: null,
      confidence: 65,
      source: "A4",
      rawInput: null,
    },
    uid: "user_001",
    frequency: "ONE_D",
    nowIso: "2026-05-21T12:00:00.000Z",
  });

  assert.equal(order.strategyType, "system");
  assert.equal(order.source, "a4_push");
  assert.equal(order.originStrategyId, "strat_rec_001");
  assert.equal(order.status, "applied");
  assert.equal(order.strategySnapshot.frequency, "ONE_D");
});

test("buildTaskOrderFromStrategy creates the same task-order shape for custom strategies", () => {
  const order = buildTaskOrderFromStrategy({
    strategy: {
      id: "strat_custom_001",
      type: "CUSTOM",
      name: "RSI 超卖反弹",
      description: "自定义策略",
      direction: "BUY",
      symbol: "BTC-USDT-SWAP",
      tradeType: "SWAP",
      leverage: 2,
      positionSize: 0.3,
      stopLoss: 79200,
      takeProfit: 83500,
      confidence: 72,
      source: null,
      rawInput: "RSI低于30并且MACD金叉时做多",
    },
    uid: "user_001",
    frequency: "FOUR_H",
    nowIso: "2026-05-21T12:00:00.000Z",
  });

  assert.equal(order.strategyType, "custom");
  assert.equal(order.source, "user_created");
  assert.equal(order.strategySnapshot.tradeType, "SWAP");
  assert.equal(order.strategySnapshot.frequency, "FOUR_H");
  assert.equal(order.rawInput, "RSI低于30并且MACD金叉时做多");
});

test("buildQueuedExecutionRun creates a queued run bound to the task order", () => {
  const run = buildQueuedExecutionRun({
    strategyTaskOrderId: "order_001",
    triggerType: "scheduled",
    nowIso: "2026-05-21T12:05:00.000Z",
  });

  assert.equal(run.strategyTaskOrderId, "order_001");
  assert.equal(run.triggerType, "scheduled");
  assert.equal(run.status, "queued");
  assert.equal(run.startedAt, null);
  assert.equal(run.endedAt, null);
});

test("persistStrategyTaskOrder stores the task order, queues an execution run, and links the strategy task", async () => {
  const calls: {
    orderCreate?: { data: unknown };
    runCreate?: { data: unknown };
    taskUpdate?: { where: { id: string }; data: { taskOrderId: string } };
  } = {};

  const tx = {
    strategyTaskOrder: {
      async create(args: { data: unknown }) {
        calls.orderCreate = args;
        return args.data;
      },
    },
    strategyExecutionRun: {
      async create(args: { data: unknown }) {
        calls.runCreate = args;
        return args.data;
      },
    },
    strategyTask: {
      async update(args: {
        where: { id: string };
        data: { taskOrderId: string };
      }) {
        calls.taskUpdate = args;
        return args;
      },
    },
  };

  const prisma = {
    async $transaction<T>(callback: (client: typeof tx) => Promise<T>) {
      return callback(tx);
    },
  };

  const result = await persistStrategyTaskOrder({
    prisma,
    strategyTaskId: "task_001",
    triggerType: "scheduled",
    uid: "user_001",
    frequency: "FOUR_H",
    nowIso: "2026-05-21T12:10:00.000Z",
    strategy: {
      id: "strat_custom_001",
      type: "CUSTOM",
      name: "RSI 超卖反弹",
      description: "自定义策略",
      direction: "BUY",
      symbol: "BTC-USDT-SWAP",
      tradeType: "SWAP",
      leverage: 2,
      positionSize: 0.3,
      stopLoss: 79200,
      takeProfit: 83500,
      confidence: 72,
      source: null,
      rawInput: "RSI低于30并且MACD金叉时做多",
    },
  });

  assert.ok(calls.orderCreate);
  assert.ok(calls.runCreate);
  assert.deepEqual(calls.taskUpdate, {
    where: { id: "task_001" },
    data: { taskOrderId: result.taskOrder.strategyTaskOrderId },
  });

  assert.equal(
    (calls.orderCreate?.data as { originStrategyId: string }).originStrategyId,
    "strat_custom_001",
  );
  assert.equal(
    (calls.runCreate?.data as { strategyTaskOrderId: string }).strategyTaskOrderId,
    result.taskOrder.strategyTaskOrderId,
  );
  assert.equal(result.executionRun.status, "queued");
  assert.equal(result.taskOrder.strategySnapshot.frequency, "FOUR_H");
});
