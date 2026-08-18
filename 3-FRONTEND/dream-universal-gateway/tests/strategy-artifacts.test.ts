import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  buildStrategyTaskOrderArtifact,
  collectStrategyTaskOrderFeedItems,
  writeStrategyTaskOrderArtifact,
} from "../src/lib/strategy-artifacts";

function createStrategyTaskOrderFixture() {
  return {
    strategy: {
      id: "strat_custom_001",
      uid: "user_001",
      type: "CUSTOM" as const,
      name: "RSI 超卖反弹",
      description: "4H 超卖买入并自动跟踪止盈",
      direction: "BUY" as const,
      symbol: "BTC-USDT-SWAP",
      tradeType: "SWAP" as const,
      leverage: 2,
      positionSize: 0.3,
      stopLoss: 79200,
      takeProfit: 83500,
      confidence: 72,
      source: null,
      rawInput: "RSI低于30并且MACD金叉时做多",
      status: "APPLIED" as const,
    },
    taskOrder: {
      strategyTaskOrderId: "order_001",
      strategyType: "custom" as const,
      source: "user_created" as const,
      status: "applied" as const,
      title: "RSI 超卖反弹",
      summary: "4H 超卖买入并自动跟踪止盈",
      rawInput: "RSI低于30并且MACD金叉时做多",
      originStrategyId: "strat_custom_001",
      ownerUserId: "user_001",
      strategySnapshot: {
        direction: "BUY" as const,
        symbol: "BTC-USDT-SWAP",
        tradeType: "SWAP" as const,
        leverage: 2,
        positionSize: 0.3,
        stopLoss: 79200,
        takeProfit: 83500,
        frequency: "FOUR_H" as const,
        confidence: 72,
      },
      createdAt: "2026-05-22T09:00:00.000Z",
      updatedAt: "2026-05-22T09:00:00.000Z",
      appliedAt: "2026-05-22T09:00:00.000Z",
    },
    strategyTask: {
      id: "task_001",
      strategyId: "strat_custom_001",
      uid: "user_001",
      executionFrequency: "FOUR_H" as const,
      status: "ACTIVE" as const,
      nextExecutionAt: new Date("2026-05-22T13:00:00.000Z"),
      taskOrderId: "order_001",
    },
    executionRun: {
      strategyExecutionRunId: "run_001",
      strategyTaskOrderId: "order_001",
      triggerType: "manual" as const,
      status: "queued" as const,
      startedAt: null,
      endedAt: null,
      reason: null,
    },
    nextExecutionAt: "2026-05-22T13:00:00.000Z",
  };
}

test("buildStrategyTaskOrderArtifact returns Product Hub compatible metadata for a task order artifact", () => {
  const artifact = buildStrategyTaskOrderArtifact(createStrategyTaskOrderFixture());

  assert.equal(artifact.record.artifact_id, "trading/strategy-task-order-order_001");
  assert.equal(artifact.record.file, "strategy_task_order_order_001.json");
  assert.equal(artifact.record.type, "strategy_task_order");
  assert.equal(artifact.record.chain_phase, "A9");
  assert.equal(artifact.record.workflow_type, "trading_v2");
  assert.equal(artifact.record.trace_id, "order_001");
  assert.deepEqual(artifact.record.tags, [
    "strategy_task_order",
    "BUY",
    "BTC-USDT-SWAP",
    "FOUR_H",
    "custom",
  ]);
  assert.equal(artifact.document.strategyTaskOrderId, "order_001");
  assert.equal(artifact.document.strategySnapshot.frequency, "FOUR_H");
  assert.equal(artifact.feedItem.id, "trading/strategy-task-order-order_001");
  assert.equal(artifact.feedItem.category, "trading");
  assert.equal(artifact.feedItem.artifactId, "strategy-task-order-order_001");
  assert.equal(artifact.feedItem.departmentLabel, "交易部");
  assert.equal(artifact.feedItem.url, "/feed/trading/strategy-task-order-order_001");
});

test("writeStrategyTaskOrderArtifact persists the artifact and collectStrategyTaskOrderFeedItems exposes Product Hub fields", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "strategy-artifacts-"));

  try {
    const written = writeStrategyTaskOrderArtifact({
      artifactsDir: root,
      ...createStrategyTaskOrderFixture(),
    });

    const artifactPath = path.join(root, "trading", "strategy_task_order_order_001.json");
    const indexPath = path.join(root, "trading", "index.json");

    assert.equal(written.filePath, artifactPath);
    assert.ok(fs.existsSync(artifactPath));
    assert.ok(fs.existsSync(indexPath));

    const index = JSON.parse(fs.readFileSync(indexPath, "utf-8")) as {
      last_updated: string;
      artifacts: Array<Record<string, unknown>>;
    };

    assert.equal(index.artifacts.length, 1);
    assert.equal(index.artifacts[0].artifact_id, "trading/strategy-task-order-order_001");
    assert.equal(index.artifacts[0].file, "strategy_task_order_order_001.json");
    assert.equal(index.artifacts[0].type, "strategy_task_order");

    const feed = collectStrategyTaskOrderFeedItems({ artifactsDir: root });
    assert.equal(feed.length, 1);
    assert.equal(feed[0].file, "trading/strategy_task_order_order_001.json");
    assert.equal(feed[0].type, "strategy_task_order");
    assert.equal(feed[0].artifact_id, "trading/strategy-task-order-order_001");
    assert.equal(feed[0].category, "trading");
    assert.equal(feed[0].artifactId, "strategy-task-order-order_001");
    assert.equal(feed[0].department, "trading");
    assert.equal(feed[0].departmentLabel, "交易部");
    assert.equal(feed[0].chain_phase, "A9");
    assert.equal(feed[0].chainPhase, "A9");
    assert.equal(feed[0].url, "/feed/trading/strategy-task-order-order_001");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
