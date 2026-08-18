type StrategyType = "RECOMMENDED" | "CUSTOM";
type StrategyStatus = "DRAFT" | "APPROVED" | "APPLIED" | "PAUSED" | "EXPIRED";
type Direction = "BUY" | "SHORT" | "SKIP";
type TradeType = "SPOT" | "SWAP";
type TaskOrderStatus = "configured" | "applied" | "paused" | "completed" | "failed";
type TaskStatus = "ACTIVE" | "PAUSED" | "COMPLETED" | "FAILED";
type RunStatus = "queued" | "running" | "skipped" | "completed" | "failed";
type TaskOrderFrequency = "ONE_H" | "FOUR_H" | "ONE_D";

interface StrategyTaskRecord {
  id: string;
  status: TaskStatus;
  executionFrequency?: TaskOrderFrequency;
  nextExecutionAt?: string | null;
  lastExecutionAt?: string | null;
  executionCount?: number;
  tradeCount?: number;
  skipCount?: number;
}

interface StrategyRunRecord {
  strategyExecutionRunId: string;
  status: RunStatus;
  createdAt?: string;
  startedAt?: string | null;
  endedAt?: string | null;
}

interface StrategyTaskOrderRecord {
  strategyTaskOrderId: string;
  status: TaskOrderStatus;
  title: string;
  summary?: string | null;
  rawInput?: string | null;
  originStrategyId: string;
  createdAt?: string;
  updatedAt?: string;
  appliedAt?: string;
  strategySnapshot?: {
    direction?: Direction;
    symbol?: string;
    tradeType?: TradeType;
    leverage?: number;
    positionSize?: number;
    stopLoss?: number | null;
    takeProfit?: number | null;
    frequency?: TaskOrderFrequency;
    confidence?: number | null;
  };
  strategyTasks?: StrategyTaskRecord[];
  executionRuns?: StrategyRunRecord[];
}

interface StrategyRecord {
  id: string;
  type: StrategyType;
  status?: StrategyStatus;
  name: string;
  description?: string | null;
  direction?: Direction;
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
  isRead?: boolean;
  createdAt?: string;
  updatedAt?: string;
  tasks?: StrategyTaskRecord[];
  taskOrders?: StrategyTaskOrderRecord[];
}

export interface StrategyListItemViewModel {
  strategyId: string;
  type: StrategyType;
  status: StrategyStatus;
  name: string;
  description: string | null;
  direction: Direction;
  symbol: string | null;
  tradeType: TradeType | null;
  leverage: number | null;
  positionSize: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  confidence: number | null;
  edgeScore: number | null;
  regime: string | null;
  source: string | null;
  rawInput: string | null;
  isRead: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface AppliedStrategyViewModel {
  strategyId: string;
  taskOrderId: string;
  status: TaskOrderStatus;
  title: string;
  summary: string | null;
  rawInput: string | null;
  direction: Direction;
  symbol: string | null;
  tradeType: TradeType | null;
  leverage: number | null;
  positionSize: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  confidence: number | null;
  frequency: TaskOrderFrequency | null;
  frequencyLabel: string;
  appliedAt: string | null;
}

export interface ActiveStrategyViewModel extends AppliedStrategyViewModel {
  taskStatus: TaskStatus | null;
  runStatus: RunStatus | null;
  nextExecutionAt: string | null;
  lastExecutionAt: string | null;
  executionCount: number;
  tradeCount: number;
  skipCount: number;
}

export interface StrategyPanelViewModel {
  recommended: StrategyListItemViewModel[];
  custom: StrategyListItemViewModel[];
  drafts: StrategyListItemViewModel[];
  applied: AppliedStrategyViewModel[];
  active: ActiveStrategyViewModel[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asBoolean(value: unknown): boolean {
  return value === true;
}

function asArray<T>(value: unknown, mapItem: (item: unknown) => T | null): T[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => mapItem(item))
    .filter((item): item is T => item !== null);
}

function normalizeStrategyStatus(value: unknown): StrategyStatus {
  return value === "APPROVED" ||
    value === "APPLIED" ||
    value === "PAUSED" ||
    value === "EXPIRED"
    ? value
    : "DRAFT";
}

function normalizeStrategyType(value: unknown): StrategyType | null {
  return value === "RECOMMENDED" || value === "CUSTOM" ? value : null;
}

function normalizeDirection(value: unknown): Direction {
  return value === "SHORT" || value === "SKIP" ? value : "BUY";
}

function normalizeTradeType(value: unknown): TradeType | null {
  return value === "SPOT" || value === "SWAP" ? value : null;
}

function normalizeTaskOrderStatus(value: unknown): TaskOrderStatus | null {
  return value === "configured" ||
    value === "applied" ||
    value === "paused" ||
    value === "completed" ||
    value === "failed"
    ? value
    : null;
}

function normalizeTaskStatus(value: unknown): TaskStatus | null {
  return value === "ACTIVE" ||
    value === "PAUSED" ||
    value === "COMPLETED" ||
    value === "FAILED"
    ? value
    : null;
}

function normalizeRunStatus(value: unknown): RunStatus | null {
  return value === "queued" ||
    value === "running" ||
    value === "skipped" ||
    value === "completed" ||
    value === "failed"
    ? value
    : null;
}

function normalizeFrequency(value: unknown): TaskOrderFrequency | null {
  return value === "ONE_H" || value === "FOUR_H" || value === "ONE_D" ? value : null;
}

function formatFrequencyLabel(value: TaskOrderFrequency | null): string {
  if (value === "ONE_H") {
    return "1小时";
  }
  if (value === "ONE_D") {
    return "1天";
  }
  if (value === "FOUR_H") {
    return "4小时";
  }

  return "未设置";
}

function toStrategyTaskRecord(value: unknown): StrategyTaskRecord | null {
  const source = asRecord(value);
  if (!source) {
    return null;
  }

  const id = asString(source.id);
  const status = normalizeTaskStatus(source.status);
  if (!id || !status) {
    return null;
  }

  return {
    id,
    status,
    executionFrequency: normalizeFrequency(source.executionFrequency) ?? undefined,
    nextExecutionAt: asString(source.nextExecutionAt),
    lastExecutionAt: asString(source.lastExecutionAt),
    executionCount: asNumber(source.executionCount) ?? undefined,
    tradeCount: asNumber(source.tradeCount) ?? undefined,
    skipCount: asNumber(source.skipCount) ?? undefined,
  };
}

function toStrategyRunRecord(value: unknown): StrategyRunRecord | null {
  const source = asRecord(value);
  if (!source) {
    return null;
  }

  const strategyExecutionRunId = asString(source.strategyExecutionRunId);
  const status = normalizeRunStatus(source.status);
  if (!strategyExecutionRunId || !status) {
    return null;
  }

  return {
    strategyExecutionRunId,
    status,
    createdAt: asString(source.createdAt) ?? undefined,
    startedAt: asString(source.startedAt),
    endedAt: asString(source.endedAt),
  };
}

function toStrategyTaskOrderRecord(value: unknown): StrategyTaskOrderRecord | null {
  const source = asRecord(value);
  if (!source) {
    return null;
  }

  const strategyTaskOrderId = asString(source.strategyTaskOrderId);
  const status = normalizeTaskOrderStatus(source.status);
  const title = asString(source.title);
  const originStrategyId = asString(source.originStrategyId);
  if (!strategyTaskOrderId || !status || !title || !originStrategyId) {
    return null;
  }

  const snapshot = asRecord(source.strategySnapshot);

  return {
    strategyTaskOrderId,
    status,
    title,
    summary: asString(source.summary),
    rawInput: asString(source.rawInput),
    originStrategyId,
    createdAt: asString(source.createdAt) ?? undefined,
    updatedAt: asString(source.updatedAt) ?? undefined,
    appliedAt: asString(source.appliedAt) ?? undefined,
    strategySnapshot: snapshot
      ? {
          direction: normalizeDirection(snapshot.direction),
          symbol: asString(snapshot.symbol) ?? undefined,
          tradeType: normalizeTradeType(snapshot.tradeType) ?? undefined,
          leverage: asNumber(snapshot.leverage) ?? undefined,
          positionSize: asNumber(snapshot.positionSize) ?? undefined,
          stopLoss: asNumber(snapshot.stopLoss),
          takeProfit: asNumber(snapshot.takeProfit),
          frequency: normalizeFrequency(snapshot.frequency) ?? undefined,
          confidence: asNumber(snapshot.confidence),
        }
      : undefined,
    strategyTasks: asArray(source.strategyTasks, toStrategyTaskRecord),
    executionRuns: asArray(source.executionRuns, toStrategyRunRecord),
  };
}

function toStrategyRecord(value: unknown): StrategyRecord | null {
  const source = asRecord(value);
  if (!source) {
    return null;
  }

  const id = asString(source.id);
  const type = normalizeStrategyType(source.type);
  const name = asString(source.name);
  if (!id || !type || !name) {
    return null;
  }

  return {
    id,
    type,
    status: normalizeStrategyStatus(source.status),
    name,
    description: asString(source.description),
    direction: normalizeDirection(source.direction),
    symbol: asString(source.symbol) ?? undefined,
    tradeType: normalizeTradeType(source.tradeType) ?? undefined,
    leverage: asNumber(source.leverage) ?? undefined,
    positionSize: asNumber(source.positionSize) ?? undefined,
    stopLoss: asNumber(source.stopLoss),
    takeProfit: asNumber(source.takeProfit),
    confidence: asNumber(source.confidence),
    edgeScore: asNumber(source.edgeScore),
    regime: asString(source.regime),
    source: asString(source.source),
    rawInput: asString(source.rawInput),
    isRead: asBoolean(source.isRead),
    createdAt: asString(source.createdAt) ?? undefined,
    updatedAt: asString(source.updatedAt) ?? undefined,
    tasks: asArray(source.tasks, toStrategyTaskRecord),
    taskOrders: asArray(source.taskOrders, toStrategyTaskOrderRecord),
  };
}

function pickPrimaryTaskOrder(strategy: StrategyRecord): StrategyTaskOrderRecord | null {
  const taskOrders = strategy.taskOrders ?? [];
  const appliedTaskOrders = taskOrders.filter((taskOrder) => taskOrder.status === "applied");
  if (appliedTaskOrders.length > 0) {
    return appliedTaskOrders.sort((left, right) =>
      (right.appliedAt ?? right.updatedAt ?? right.createdAt ?? "").localeCompare(
        left.appliedAt ?? left.updatedAt ?? left.createdAt ?? "",
      ),
    )[0] ?? null;
  }

  return null;
}

function pickPrimaryTask(taskOrder: StrategyTaskOrderRecord): StrategyTaskRecord | null {
  const tasks = taskOrder.strategyTasks ?? [];
  return tasks.sort((left, right) =>
    (right.nextExecutionAt ?? "").localeCompare(left.nextExecutionAt ?? ""),
  )[0] ?? null;
}

function pickLatestRun(taskOrder: StrategyTaskOrderRecord): StrategyRunRecord | null {
  const runs = taskOrder.executionRuns ?? [];
  return runs.sort((left, right) =>
    (right.createdAt ?? right.startedAt ?? "").localeCompare(left.createdAt ?? left.startedAt ?? ""),
  )[0] ?? null;
}

function toStrategyListItemViewModel(strategy: StrategyRecord): StrategyListItemViewModel {
  return {
    strategyId: strategy.id,
    type: strategy.type,
    status: strategy.status ?? "DRAFT",
    name: strategy.name,
    description: strategy.description ?? null,
    direction: strategy.direction ?? "BUY",
    symbol: strategy.symbol ?? null,
    tradeType: strategy.tradeType ?? null,
    leverage: strategy.leverage ?? null,
    positionSize: strategy.positionSize ?? null,
    stopLoss: strategy.stopLoss ?? null,
    takeProfit: strategy.takeProfit ?? null,
    confidence: strategy.confidence ?? null,
    edgeScore: strategy.edgeScore ?? null,
    regime: strategy.regime ?? null,
    source: strategy.source ?? null,
    rawInput: strategy.rawInput ?? null,
    isRead: strategy.isRead ?? false,
    createdAt: strategy.createdAt ?? null,
    updatedAt: strategy.updatedAt ?? null,
  };
}

function toAppliedStrategyViewModel(
  strategy: StrategyRecord,
  taskOrder: StrategyTaskOrderRecord,
): AppliedStrategyViewModel {
  const snapshot = taskOrder.strategySnapshot;
  const frequency = snapshot?.frequency ?? null;

  return {
    strategyId: strategy.id,
    taskOrderId: taskOrder.strategyTaskOrderId,
    status: taskOrder.status,
    title: taskOrder.title,
    summary: taskOrder.summary ?? strategy.description ?? null,
    rawInput: taskOrder.rawInput ?? strategy.rawInput ?? null,
    direction: snapshot?.direction ?? strategy.direction ?? "BUY",
    symbol: snapshot?.symbol ?? strategy.symbol ?? null,
    tradeType: snapshot?.tradeType ?? strategy.tradeType ?? null,
    leverage: snapshot?.leverage ?? strategy.leverage ?? null,
    positionSize: snapshot?.positionSize ?? strategy.positionSize ?? null,
    stopLoss: snapshot?.stopLoss ?? strategy.stopLoss ?? null,
    takeProfit: snapshot?.takeProfit ?? strategy.takeProfit ?? null,
    confidence: snapshot?.confidence ?? strategy.confidence ?? null,
    frequency,
    frequencyLabel: formatFrequencyLabel(frequency),
    appliedAt: taskOrder.appliedAt ?? taskOrder.updatedAt ?? taskOrder.createdAt ?? null,
  };
}

function toActiveStrategyViewModel(
  strategy: StrategyRecord,
  taskOrder: StrategyTaskOrderRecord,
): ActiveStrategyViewModel {
  const applied = toAppliedStrategyViewModel(strategy, taskOrder);
  const task = pickPrimaryTask(taskOrder);
  const run = pickLatestRun(taskOrder);

  return {
    ...applied,
    taskStatus: task?.status ?? null,
    runStatus: run?.status ?? null,
    nextExecutionAt: task?.nextExecutionAt ?? null,
    lastExecutionAt: task?.lastExecutionAt ?? null,
    executionCount: task?.executionCount ?? 0,
    tradeCount: task?.tradeCount ?? 0,
    skipCount: task?.skipCount ?? 0,
  };
}

function getStrategyRecords(input: unknown): StrategyRecord[] {
  if (Array.isArray(input)) {
    return asArray(input, toStrategyRecord);
  }

  const source = asRecord(input);
  if (!source) {
    return [];
  }

  if (Array.isArray(source.strategies)) {
    return asArray(source.strategies, toStrategyRecord);
  }

  return [];
}

export function buildStrategyPanelViewModel(input: unknown): StrategyPanelViewModel {
  const strategies = getStrategyRecords(input);
  const recommended = strategies
    .filter((strategy) => strategy.type === "RECOMMENDED")
    .map(toStrategyListItemViewModel);
  const custom = strategies
    .filter((strategy) => strategy.type === "CUSTOM")
    .map(toStrategyListItemViewModel);
  const drafts = custom.filter((strategy) => strategy.status === "DRAFT");

  const applied = strategies
    .filter((strategy) => strategy.type === "CUSTOM")
    .map((strategy) => {
      const taskOrder = pickPrimaryTaskOrder(strategy);
      return taskOrder ? toAppliedStrategyViewModel(strategy, taskOrder) : null;
    })
    .filter((item): item is AppliedStrategyViewModel => item !== null)
    .sort((left, right) => (right.appliedAt ?? "").localeCompare(left.appliedAt ?? ""));

  const active = strategies
    .filter((strategy) => strategy.type === "CUSTOM")
    .map((strategy) => {
      const taskOrder = pickPrimaryTaskOrder(strategy);
      if (!taskOrder) {
        return null;
      }

      const task = pickPrimaryTask(taskOrder);
      const run = pickLatestRun(taskOrder);
      const isRunning =
        task?.status === "ACTIVE" ||
        run?.status === "running" ||
        run?.status === "queued";

      return isRunning ? toActiveStrategyViewModel(strategy, taskOrder) : null;
    })
    .filter((item): item is ActiveStrategyViewModel => item !== null)
    .sort((left, right) => (right.appliedAt ?? "").localeCompare(left.appliedAt ?? ""));

  return {
    recommended,
    custom,
    drafts,
    applied,
    active,
  };
}
