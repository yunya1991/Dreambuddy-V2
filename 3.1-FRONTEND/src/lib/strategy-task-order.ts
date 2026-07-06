import { randomUUID } from "node:crypto";

export type TaskOrderFrequency = "ONE_H" | "FOUR_H" | "ONE_D";
export type TaskOrderSource = "a4_push" | "system_generated" | "user_created";
export type TaskOrderKind = "system" | "custom";
export type TaskOrderStatus =
  | "configured"
  | "applied"
  | "paused"
  | "completed"
  | "failed";
export type StrategyRunTriggerType = "manual" | "scheduled" | "signal";
export type StrategyExecutionStatus =
  | "queued"
  | "running"
  | "skipped"
  | "completed"
  | "failed";

interface StrategyLike {
  id: string;
  type: "RECOMMENDED" | "CUSTOM";
  name: string;
  description: string | null;
  direction: "BUY" | "SHORT" | "SKIP";
  symbol: string;
  tradeType: "SPOT" | "SWAP";
  leverage: number;
  positionSize: number;
  stopLoss: number | null;
  takeProfit: number | null;
  confidence: number | null;
  source: string | null;
  rawInput: string | null;
}

export interface StrategyTaskOrderDraft {
  strategyTaskOrderId: string;
  strategyType: TaskOrderKind;
  source: TaskOrderSource;
  status: TaskOrderStatus;
  title: string;
  summary: string | null;
  rawInput: string | null;
  originStrategyId: string;
  ownerUserId: string;
  strategySnapshot: {
    direction: "BUY" | "SHORT" | "SKIP";
    symbol: string;
    tradeType: "SPOT" | "SWAP";
    leverage: number;
    positionSize: number;
    stopLoss: number | null;
    takeProfit: number | null;
    frequency: TaskOrderFrequency;
    confidence: number | null;
  };
  createdAt: string;
  updatedAt: string;
  appliedAt: string;
}

export interface StrategyExecutionRunDraft {
  strategyExecutionRunId: string;
  strategyTaskOrderId: string;
  triggerType: StrategyRunTriggerType;
  status: StrategyExecutionStatus;
  startedAt: string | null;
  endedAt: string | null;
  reason: string | null;
}

export function buildTaskOrderFromStrategy(input: {
  strategy: StrategyLike;
  uid: string;
  frequency: TaskOrderFrequency;
  nowIso: string;
}): StrategyTaskOrderDraft {
  return {
    strategyTaskOrderId: randomUUID(),
    strategyType: input.strategy.type === "RECOMMENDED" ? "system" : "custom",
    source: input.strategy.type === "RECOMMENDED" ? "a4_push" : "user_created",
    status: "applied",
    title: input.strategy.name,
    summary: input.strategy.description,
    rawInput: input.strategy.rawInput,
    originStrategyId: input.strategy.id,
    ownerUserId: input.uid,
    strategySnapshot: {
      direction: input.strategy.direction,
      symbol: input.strategy.symbol,
      tradeType: input.strategy.tradeType,
      leverage: input.strategy.leverage,
      positionSize: input.strategy.positionSize,
      stopLoss: input.strategy.stopLoss,
      takeProfit: input.strategy.takeProfit,
      frequency: input.frequency,
      confidence: input.strategy.confidence,
    },
    createdAt: input.nowIso,
    updatedAt: input.nowIso,
    appliedAt: input.nowIso,
  };
}

export function buildQueuedExecutionRun(input: {
  strategyTaskOrderId: string;
  triggerType: StrategyRunTriggerType;
  nowIso: string;
}): StrategyExecutionRunDraft {
  void input.nowIso;

  return {
    strategyExecutionRunId: randomUUID(),
    strategyTaskOrderId: input.strategyTaskOrderId,
    triggerType: input.triggerType,
    status: "queued",
    startedAt: null,
    endedAt: null,
    reason: null,
  };
}
