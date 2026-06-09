import {
  buildQueuedExecutionRun,
  buildTaskOrderFromStrategy,
  type StrategyExecutionRunDraft,
  type StrategyRunTriggerType,
  type StrategyTaskOrderDraft,
  type TaskOrderFrequency,
} from "./strategy-task-order";

type StrategyLike = Parameters<typeof buildTaskOrderFromStrategy>[0]["strategy"];

interface StrategyTaskOrderPersistenceTx {
  strategyTaskOrder: {
    create(args: { data: StrategyTaskOrderDraft }): Promise<unknown>;
  };
  strategyExecutionRun: {
    create(args: { data: StrategyExecutionRunDraft }): Promise<unknown>;
  };
  strategyTask: {
    update(args: {
      where: { id: string };
      data: { taskOrderId: string };
    }): Promise<unknown>;
  };
}

export interface StrategyTaskOrderPersistenceClient {
  $transaction<T>(
    callback: (tx: StrategyTaskOrderPersistenceTx) => Promise<T>,
  ): Promise<T>;
}

export async function persistStrategyTaskOrder(input: {
  prisma: StrategyTaskOrderPersistenceClient;
  strategyTaskId: string;
  strategy: StrategyLike;
  uid: string;
  frequency: TaskOrderFrequency;
  triggerType: StrategyRunTriggerType;
  nowIso: string;
}): Promise<{
  taskOrder: StrategyTaskOrderDraft;
  executionRun: StrategyExecutionRunDraft;
}> {
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

  await input.prisma.$transaction(async (tx) => {
    await tx.strategyTaskOrder.create({ data: taskOrder });
    await tx.strategyExecutionRun.create({ data: executionRun });
    await tx.strategyTask.update({
      where: { id: input.strategyTaskId },
      data: { taskOrderId: taskOrder.strategyTaskOrderId },
    });
  });

  return {
    taskOrder,
    executionRun,
  };
}
