import test from "node:test";
import assert from "node:assert/strict";

import {
  applyStrategyWithTaskOrder,
  createStrategyWithLifecycle,
  pauseStrategyWithTaskOrder,
} from "../src/lib/strategy-lifecycle-service";

function createApplyPrismaMock() {
  const calls: Record<string, unknown> = {};
  let createdTaskFrequency: "ONE_H" | "FOUR_H" | "ONE_D" = "ONE_H";

  const tx = {
    strategy: {
      async update(args: { where: { id: string }; data: { status: string } }) {
        calls.strategyUpdate = args;
        return {
          id: args.where.id,
          uid: "user_001",
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
          status: args.data.status,
        };
      },
      async create(args: { data: Record<string, unknown> }) {
        calls.strategyCreate = args;
        return {
          id: "strat_new_001",
          uid: args.data.uid,
          type: args.data.type,
          name: args.data.name,
          description: args.data.description,
          direction: args.data.direction,
          symbol: args.data.symbol,
          tradeType: args.data.tradeType,
          leverage: args.data.leverage,
          positionSize: args.data.positionSize,
          stopLoss: args.data.stopLoss,
          takeProfit: args.data.takeProfit,
          confidence: args.data.confidence,
          source: args.data.source,
          rawInput: args.data.rawInput,
          status: args.data.status,
        };
      },
    },
    strategyTask: {
      async create(args: { data: Record<string, unknown> }) {
        calls.strategyTaskCreate = args;
        createdTaskFrequency = args.data.executionFrequency as
          | "ONE_H"
          | "FOUR_H"
          | "ONE_D";
        return {
          id: "task_001",
          ...args.data,
        };
      },
      async update(args: {
        where: { id: string };
        data: { taskOrderId: string };
      }) {
        calls.strategyTaskUpdate = args;
        return {
          id: args.where.id,
          taskOrderId: args.data.taskOrderId,
          strategyId: "strat_custom_001",
          uid: "user_001",
          executionFrequency: createdTaskFrequency,
          status: "ACTIVE",
          nextExecutionAt: new Date("2026-05-22T10:00:00.000Z"),
        };
      },
      async updateMany(args: {
        where: { strategyId: string };
        data: { status: string };
      }) {
        calls.strategyTaskUpdateMany = args;
        return { count: 2 };
      },
    },
    strategyTaskOrder: {
      async create(args: { data: Record<string, unknown> }) {
        calls.strategyTaskOrderCreate = args;
        return args.data;
      },
      async updateMany(args: {
        where: { originStrategyId: string };
        data: { status: string; updatedAt: string };
      }) {
        calls.strategyTaskOrderUpdateMany = args;
        return { count: 1 };
      },
    },
    strategyExecutionRun: {
      async create(args: { data: Record<string, unknown> }) {
        calls.strategyExecutionRunCreate = args;
        return args.data;
      },
    },
  };

  const prisma = {
    async $transaction<T>(callback: (client: typeof tx) => Promise<T>) {
      return callback(tx);
    },
  };

  return { prisma, calls };
}

test("applyStrategyWithTaskOrder returns task order as the primary object and creates scheduler task", async () => {
  const { prisma, calls } = createApplyPrismaMock();

  const result = await applyStrategyWithTaskOrder({
    prisma,
    uid: "user_001",
    frequency: "ONE_H",
    triggerType: "manual",
    nowIso: "2026-05-22T09:00:00.000Z",
    strategy: {
      id: "strat_custom_001",
      uid: "user_001",
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
      status: "DRAFT",
    },
  });

  assert.equal(result.taskOrder.originStrategyId, "strat_custom_001");
  assert.equal(result.taskOrder.status, "applied");
  assert.equal(result.strategy.status, "APPLIED");
  assert.equal(result.strategyTask.executionFrequency, "ONE_H");
  assert.equal(result.executionRun.strategyTaskOrderId, result.taskOrder.strategyTaskOrderId);
  assert.equal(result.nextExecutionAt, "2026-05-22T10:00:00.000Z");

  assert.deepEqual(calls.strategyUpdate, {
    where: { id: "strat_custom_001" },
    data: { status: "APPLIED" },
  });
  assert.deepEqual(calls.strategyTaskCreate, {
    data: {
      strategyId: "strat_custom_001",
      uid: "user_001",
      executionFrequency: "ONE_H",
      status: "ACTIVE",
      nextExecutionAt: new Date("2026-05-22T10:00:00.000Z"),
    },
  });
});

test("applyStrategyWithTaskOrder writes a StrategyTaskOrder artifact when an artifact writer is provided", async () => {
  const { prisma } = createApplyPrismaMock();
  const artifactCalls: Array<Record<string, unknown>> = [];

  const result = await applyStrategyWithTaskOrder({
    prisma,
    uid: "user_001",
    frequency: "FOUR_H",
    triggerType: "manual",
    nowIso: "2026-05-22T09:00:00.000Z",
    artifactWriter: {
      writeStrategyTaskOrderArtifact(input) {
        artifactCalls.push(input as Record<string, unknown>);
        return {
          record: {
            artifact_id: "trading/strategy-task-order-order_001",
          },
        };
      },
    },
    strategy: {
      id: "strat_custom_001",
      uid: "user_001",
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
      status: "DRAFT",
    },
  });

  assert.equal(artifactCalls.length, 1);
  assert.equal(artifactCalls[0].nextExecutionAt, "2026-05-22T13:00:00.000Z");
  assert.equal(
    (artifactCalls[0].taskOrder as { strategyTaskOrderId: string }).strategyTaskOrderId,
    result.taskOrder.strategyTaskOrderId,
  );
  assert.deepEqual(result.artifact, {
    record: {
      artifact_id: "trading/strategy-task-order-order_001",
    },
  });
});

test("pauseStrategyWithTaskOrder pauses strategy, task orders, and scheduler tasks together", async () => {
  const { prisma, calls } = createApplyPrismaMock();

  const result = await pauseStrategyWithTaskOrder({
    prisma,
    strategyId: "strat_custom_001",
    nowIso: "2026-05-22T09:30:00.000Z",
  });

  assert.equal(result.strategy.status, "PAUSED");
  assert.equal(result.pausedTaskOrdersCount, 1);
  assert.equal(result.pausedStrategyTasksCount, 2);

  assert.deepEqual(calls.strategyTaskOrderUpdateMany, {
    where: { originStrategyId: "strat_custom_001" },
    data: { status: "paused", updatedAt: "2026-05-22T09:30:00.000Z" },
  });
  assert.deepEqual(calls.strategyTaskUpdateMany, {
    where: { strategyId: "strat_custom_001" },
    data: { status: "PAUSED" },
  });
});

test("createStrategyWithLifecycle can create and immediately apply a strategy with task order output", async () => {
  const { prisma, calls } = createApplyPrismaMock();

  const result = await createStrategyWithLifecycle({
    prisma,
    uid: "user_001",
    apply: true,
    preferredFrequency: "FOUR_H",
    requestedFrequency: "ONE_D",
    nowIso: "2026-05-22T09:00:00.000Z",
    strategy: {
      type: "CUSTOM",
      name: "突破回踩买入",
      description: "自动创建并应用",
      direction: "BUY",
      symbol: "BTC-USDT-SWAP",
      tradeType: "SWAP",
      leverage: 3,
      positionSize: 0.4,
      stopLoss: 78000,
      takeProfit: 86000,
      confidence: 81,
      edgeScore: 77,
      regime: null,
      source: null,
      rawInput: "突破后回踩 5 日均线买入",
    },
  });

  assert.equal(result.strategy.id, "strat_new_001");
  assert.ok(result.taskOrder);
  assert.equal(result.taskOrder?.originStrategyId, "strat_new_001");
  assert.equal(result.strategyTask?.executionFrequency, "ONE_D");
  assert.equal(result.executionRun?.status, "queued");

  assert.deepEqual(calls.strategyCreate, {
    data: {
      uid: "user_001",
      type: "CUSTOM",
      name: "突破回踩买入",
      description: "自动创建并应用",
      direction: "BUY",
      symbol: "BTC-USDT-SWAP",
      tradeType: "SWAP",
      leverage: 3,
      positionSize: 0.4,
      stopLoss: 78000,
      takeProfit: 86000,
      confidence: 81,
      edgeScore: 77,
      regime: null,
      source: null,
      rawInput: "突破后回踩 5 日均线买入",
      status: "DRAFT",
    },
  });
});
