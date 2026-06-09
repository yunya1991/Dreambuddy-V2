import {
  buildQueuedExecutionRun,
  buildTaskOrderFromStrategy,
  type StrategyExecutionRunDraft,
  type StrategyRunTriggerType,
  type StrategyTaskOrderDraft,
  type TaskOrderFrequency,
} from "./strategy-task-order";
import type {
  StrategyTaskOrderArtifactWriteResult,
  StrategyTaskOrderArtifactWriter,
} from "./strategy-artifacts";

type StrategyType = "RECOMMENDED" | "CUSTOM";
type Direction = "BUY" | "SHORT" | "SKIP";
type TradeType = "SPOT" | "SWAP";
type StrategyStatus = "DRAFT" | "APPROVED" | "APPLIED" | "PAUSED" | "EXPIRED";
type StrategyTaskStatus = "ACTIVE" | "PAUSED" | "COMPLETED" | "FAILED";

export interface StrategyLifecycleStrategy {
  id: string;
  uid: string;
  type: StrategyType;
  name: string;
  description: string | null;
  direction: Direction;
  symbol: string;
  tradeType: TradeType;
  leverage: number;
  positionSize: number;
  stopLoss: number | null;
  takeProfit: number | null;
  confidence: number | null;
  source: string | null;
  rawInput: string | null;
  status: StrategyStatus;
}

export interface StrategyLifecycleTask {
  id: string;
  strategyId: string;
  uid: string;
  executionFrequency: TaskOrderFrequency;
  status: StrategyTaskStatus;
  nextExecutionAt: Date | null;
  taskOrderId?: string | null;
}

export interface StrategyCreatePayload {
  type?: StrategyType;
  name: string;
  description?: string | null;
  direction: Direction;
  symbol?: string;
  tradeType?: TradeType;
  leverage?: number;
  positionSize?: number;
  stopLoss?: number | null;
  takeProfit?: number | null;
  confidence?: number | null;
  edgeScore?: number | null;
  regime?: string | null;
  source?: string | null;
  rawInput?: string | null;
}

interface StrategyLifecycleTx {
  strategy: {
    create(args: {
      data: {
        uid: string;
        type: StrategyType;
        name: string;
        description: string | null;
        direction: Direction;
        symbol: string;
        tradeType: TradeType;
        leverage: number;
        positionSize: number;
        stopLoss: number | null;
        takeProfit: number | null;
        confidence: number | null;
        edgeScore: number | null;
        regime: string | null;
        source: string | null;
        rawInput: string | null;
        status: "DRAFT";
      };
    }): Promise<StrategyLifecycleStrategy>;
    update(args: {
      where: { id: string };
      data: { status: "APPLIED" | "PAUSED" };
    }): Promise<StrategyLifecycleStrategy>;
  };
  strategyTask: {
    create(args: {
      data: {
        strategyId: string;
        uid: string;
        executionFrequency: TaskOrderFrequency;
        status: "ACTIVE";
        nextExecutionAt: Date;
      };
    }): Promise<StrategyLifecycleTask>;
    update(args: {
      where: { id: string };
      data: { taskOrderId: string };
    }): Promise<StrategyLifecycleTask>;
    updateMany(args: {
      where: { strategyId: string };
      data: { status: "PAUSED" };
    }): Promise<{ count: number }>;
  };
  strategyTaskOrder: {
    create(args: { data: StrategyTaskOrderDraft }): Promise<unknown>;
    updateMany(args: {
      where: { originStrategyId: string };
      data: { status: "paused"; updatedAt: string };
    }): Promise<{ count: number }>;
  };
  strategyExecutionRun: {
    create(args: { data: StrategyExecutionRunDraft }): Promise<unknown>;
  };
}

export interface StrategyLifecycleClient {
  $transaction<T>(callback: (tx: StrategyLifecycleTx) => Promise<T>): Promise<T>;
}

export interface AppliedStrategyResult {
  strategy: StrategyLifecycleStrategy;
  strategyTask: StrategyLifecycleTask;
  taskOrder: StrategyTaskOrderDraft;
  executionRun: StrategyExecutionRunDraft;
  nextExecutionAt: string;
  artifact?: StrategyTaskOrderArtifactWriteResult;
}

export interface PausedStrategyResult {
  strategy: StrategyLifecycleStrategy;
  pausedTaskOrdersCount: number;
  pausedStrategyTasksCount: number;
}

export interface CreatedStrategyResult {
  strategy: StrategyLifecycleStrategy;
  taskOrder?: StrategyTaskOrderDraft;
  strategyTask?: StrategyLifecycleTask;
  executionRun?: StrategyExecutionRunDraft;
  nextExecutionAt?: string;
  artifact?: StrategyTaskOrderArtifactWriteResult;
}

export function normalizeStrategyFrequency(
  input?: string | null,
): TaskOrderFrequency | null {
  if (input === "ONE_H" || input === "FOUR_H" || input === "ONE_D") {
    return input;
  }

  return null;
}

export function resolveStrategyFrequency(input: {
  requestedFrequency?: string | null;
  preferredFrequency?: string | null;
  fallback?: TaskOrderFrequency;
}): TaskOrderFrequency {
  return (
    normalizeStrategyFrequency(input.requestedFrequency) ??
    normalizeStrategyFrequency(input.preferredFrequency) ??
    input.fallback ??
    "FOUR_H"
  );
}

export function calculateNextExecutionAt(
  nowIso: string,
  frequency: TaskOrderFrequency,
): string {
  const now = new Date(nowIso);
  const offsetMs =
    frequency === "ONE_H"
      ? 60 * 60 * 1000
      : frequency === "ONE_D"
        ? 24 * 60 * 60 * 1000
        : 4 * 60 * 60 * 1000;

  return new Date(now.getTime() + offsetMs).toISOString();
}

function buildStrategyCreateData(input: {
  uid: string;
  strategy: StrategyCreatePayload;
}) {
  return {
    uid: input.uid,
    type: input.strategy.type ?? "CUSTOM",
    name: input.strategy.name,
    description: input.strategy.description ?? null,
    direction: input.strategy.direction,
    symbol: input.strategy.symbol ?? "BTC-USDT-SWAP",
    tradeType: input.strategy.tradeType ?? "SPOT",
    leverage: input.strategy.leverage ?? 1,
    positionSize: input.strategy.positionSize ?? 0,
    stopLoss: input.strategy.stopLoss ?? null,
    takeProfit: input.strategy.takeProfit ?? null,
    confidence: input.strategy.confidence ?? null,
    edgeScore: input.strategy.edgeScore ?? null,
    regime: input.strategy.regime ?? null,
    source: input.strategy.source ?? null,
    rawInput: input.strategy.rawInput ?? null,
    status: "DRAFT" as const,
  };
}

async function applyStrategyWithinTx(input: {
  tx: StrategyLifecycleTx;
  strategy: StrategyLifecycleStrategy;
  uid: string;
  frequency: TaskOrderFrequency;
  triggerType: StrategyRunTriggerType;
  nowIso: string;
}): Promise<AppliedStrategyResult> {
  const taskOrder = buildTaskOrderFromStrategy({
    strategy: input.strategy,
    uid: input.uid,
    frequency: input.frequency,
    nowIso: input.nowIso,
  });
  const executionRun = buildQueuedExecutionRun({
    strategyTaskOrderId: taskOrder.strategyTaskOrderId,
    triggerType: input.triggerType,
    nowIso: input.nowIso,
  });
  const nextExecutionAt = calculateNextExecutionAt(input.nowIso, input.frequency);

  const strategy = await input.tx.strategy.update({
    where: { id: input.strategy.id },
    data: { status: "APPLIED" },
  });
  const createdTask = await input.tx.strategyTask.create({
    data: {
      strategyId: input.strategy.id,
      uid: input.uid,
      executionFrequency: input.frequency,
      status: "ACTIVE",
      nextExecutionAt: new Date(nextExecutionAt),
    },
  });

  await input.tx.strategyTaskOrder.create({ data: taskOrder });
  await input.tx.strategyExecutionRun.create({ data: executionRun });

  const strategyTask = await input.tx.strategyTask.update({
    where: { id: createdTask.id },
    data: { taskOrderId: taskOrder.strategyTaskOrderId },
  });

  return {
    strategy,
    strategyTask,
    taskOrder,
    executionRun,
    nextExecutionAt,
  };
}

export async function applyStrategyWithTaskOrder(input: {
  prisma: StrategyLifecycleClient;
  strategy: StrategyLifecycleStrategy;
  uid: string;
  frequency: TaskOrderFrequency;
  triggerType: StrategyRunTriggerType;
  nowIso: string;
  artifactWriter?: StrategyTaskOrderArtifactWriter;
}): Promise<AppliedStrategyResult> {
  const applied = await input.prisma.$transaction((tx) =>
    applyStrategyWithinTx({
      tx,
      strategy: input.strategy,
      uid: input.uid,
      frequency: input.frequency,
      triggerType: input.triggerType,
      nowIso: input.nowIso,
    }),
  );

  if (!input.artifactWriter) {
    return applied;
  }

  return {
    ...applied,
    artifact: input.artifactWriter.writeStrategyTaskOrderArtifact({
      strategy: applied.strategy,
      taskOrder: applied.taskOrder,
      strategyTask: applied.strategyTask,
      executionRun: applied.executionRun,
      nextExecutionAt: applied.nextExecutionAt,
    }),
  };
}

export async function pauseStrategyWithTaskOrder(input: {
  prisma: StrategyLifecycleClient;
  strategyId: string;
  nowIso: string;
}): Promise<PausedStrategyResult> {
  return input.prisma.$transaction(async (tx) => {
    const strategy = await tx.strategy.update({
      where: { id: input.strategyId },
      data: { status: "PAUSED" },
    });
    const pausedTaskOrders = await tx.strategyTaskOrder.updateMany({
      where: { originStrategyId: input.strategyId },
      data: { status: "paused", updatedAt: input.nowIso },
    });
    const pausedStrategyTasks = await tx.strategyTask.updateMany({
      where: { strategyId: input.strategyId },
      data: { status: "PAUSED" },
    });

    return {
      strategy,
      pausedTaskOrdersCount: pausedTaskOrders.count,
      pausedStrategyTasksCount: pausedStrategyTasks.count,
    };
  });
}

export async function createStrategyWithLifecycle(input: {
  prisma: StrategyLifecycleClient;
  uid: string;
  strategy: StrategyCreatePayload;
  apply?: boolean;
  requestedFrequency?: string | null;
  preferredFrequency?: string | null;
  triggerType?: StrategyRunTriggerType;
  nowIso: string;
  artifactWriter?: StrategyTaskOrderArtifactWriter;
}): Promise<CreatedStrategyResult> {
  const created: CreatedStrategyResult = await input.prisma.$transaction(
    async (tx): Promise<CreatedStrategyResult> => {
    const createdStrategy = await tx.strategy.create({
      data: buildStrategyCreateData({
        uid: input.uid,
        strategy: input.strategy,
      }),
    });

    if (!input.apply) {
      return { strategy: createdStrategy };
    }

    const applied = await applyStrategyWithinTx({
      tx,
      strategy: createdStrategy,
      uid: input.uid,
      frequency: resolveStrategyFrequency({
        requestedFrequency: input.requestedFrequency,
        preferredFrequency: input.preferredFrequency,
      }),
      triggerType: input.triggerType ?? "manual",
      nowIso: input.nowIso,
    });

    return applied;
    },
  );

  if (!input.apply || !input.artifactWriter || !created.taskOrder || !created.strategyTask || !created.executionRun || !created.nextExecutionAt) {
    return created;
  }

  return {
    ...created,
    artifact: input.artifactWriter.writeStrategyTaskOrderArtifact({
      strategy: created.strategy,
      taskOrder: created.taskOrder,
      strategyTask: created.strategyTask,
      executionRun: created.executionRun,
      nextExecutionAt: created.nextExecutionAt,
    }),
  };
}
