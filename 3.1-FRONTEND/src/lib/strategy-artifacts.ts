import fs from "node:fs";
import path from "node:path";

type TaskOrderFrequency = "ONE_H" | "FOUR_H" | "ONE_D";
type StrategyType = "RECOMMENDED" | "CUSTOM";
type Direction = "BUY" | "SHORT" | "SKIP";
type TradeType = "SPOT" | "SWAP";
type StrategyStatus = "DRAFT" | "APPROVED" | "APPLIED" | "PAUSED" | "EXPIRED";
type StrategyTaskStatus = "ACTIVE" | "PAUSED" | "COMPLETED" | "FAILED";
type StrategyRunTriggerType = "manual" | "scheduled" | "signal";
type StrategyExecutionStatus = "queued" | "running" | "skipped" | "completed" | "failed";

export interface StrategyArtifactStrategy {
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

export interface StrategyArtifactTaskOrder {
  strategyTaskOrderId: string;
  strategyType: "system" | "custom";
  source: "a4_push" | "system_generated" | "user_created";
  status: "configured" | "applied" | "paused" | "completed" | "failed";
  title: string;
  summary: string | null;
  rawInput: string | null;
  originStrategyId: string;
  ownerUserId: string;
  strategySnapshot: {
    direction: Direction;
    symbol: string;
    tradeType: TradeType;
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

export interface StrategyArtifactTask {
  id: string;
  strategyId: string;
  uid: string;
  executionFrequency: TaskOrderFrequency;
  status: StrategyTaskStatus;
  nextExecutionAt: Date | null;
  taskOrderId?: string | null;
}

export interface StrategyArtifactExecutionRun {
  strategyExecutionRunId: string;
  strategyTaskOrderId: string;
  triggerType: StrategyRunTriggerType;
  status: StrategyExecutionStatus;
  startedAt: string | null;
  endedAt: string | null;
  reason: string | null;
}

export interface StrategyTaskOrderArtifactInput {
  strategy: StrategyArtifactStrategy;
  taskOrder: StrategyArtifactTaskOrder;
  strategyTask: StrategyArtifactTask;
  executionRun: StrategyArtifactExecutionRun;
  nextExecutionAt: string;
}

export interface StrategyTaskOrderArtifactIndexRecord {
  artifact_id: string;
  title: string;
  file: string;
  filename: string;
  type: "strategy_task_order";
  status: string;
  date: string;
  chain_phase: "A9";
  tags: string[];
  workflow_id: string;
  workflow_type: "trading_v2";
  trace_id: string;
  department: "trading";
  excerpt: string;
}

export interface StrategyTaskOrderFeedItem {
  [key: string]: unknown;
  id: string;
  file: string;
  title: string;
  date: string;
  type: "strategy_task_order";
  chain_phase: "A9";
  tags: string[];
  status: string;
  artifact_id: string;
  category: "trading";
  artifactId: string;
  department: "trading";
  departmentLabel: "交易部";
  typeLabel: "strategy_task_order";
  chainPhase: "A9";
  url: string;
  workflow_id: string;
  workflow_type: "trading_v2";
  trace_id: string;
}

export interface StrategyTaskOrderArtifactDocument {
  artifactId: string;
  category: "trading";
  generatedAt: string;
  strategyTaskOrderId: string;
  nextExecutionAt: string;
  strategy: StrategyArtifactStrategy;
  taskOrder: StrategyArtifactTaskOrder;
  strategyTask: Omit<StrategyArtifactTask, "nextExecutionAt"> & {
    nextExecutionAt: string | null;
  };
  strategySnapshot: StrategyArtifactTaskOrder["strategySnapshot"];
  executionRun: StrategyArtifactExecutionRun;
}

export interface StrategyTaskOrderArtifactWriteResult {
  artifactId: string;
  filename: string;
  filePath: string;
  record: StrategyTaskOrderArtifactIndexRecord;
  document: StrategyTaskOrderArtifactDocument;
  feedItem: StrategyTaskOrderFeedItem;
}

export interface StrategyTaskOrderArtifactWriter {
  writeStrategyTaskOrderArtifact(
    input: StrategyTaskOrderArtifactInput,
  ): StrategyTaskOrderArtifactWriteResult;
}

interface StrategyTaskOrderIndexFile {
  last_updated: string;
  artifacts: StrategyTaskOrderArtifactIndexRecord[];
}

function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function buildArtifactId(taskOrderId: string): string {
  return `strategy-task-order-${taskOrderId}`;
}

function buildFilename(taskOrderId: string): string {
  return `strategy_task_order_${taskOrderId}.json`;
}

function buildExcerpt(input: StrategyTaskOrderArtifactInput): string {
  const summary = input.taskOrder.summary ?? input.strategy.description ?? "Strategy task order ready";
  return [
    input.strategy.symbol,
    input.taskOrder.strategySnapshot.direction,
    input.taskOrder.strategySnapshot.frequency,
    summary,
  ].join(" | ");
}

function buildFeedItemFromRecord(record: StrategyTaskOrderArtifactIndexRecord): StrategyTaskOrderFeedItem {
  const artifactId = record.artifact_id.replace(/^trading\//, "");

  return {
    id: record.artifact_id,
    file: `trading/${record.file}`,
    title: record.title,
    date: record.date,
    type: "strategy_task_order",
    chain_phase: "A9",
    tags: Array.isArray(record.tags) ? record.tags : [],
    status: record.status,
    artifact_id: record.artifact_id,
    category: "trading",
    artifactId,
    department: "trading",
    departmentLabel: "交易部",
    typeLabel: "strategy_task_order",
    chainPhase: "A9",
    url: `/feed/trading/${artifactId}`,
    workflow_id: record.workflow_id,
    workflow_type: "trading_v2",
    trace_id: record.trace_id,
  };
}

export function buildStrategyTaskOrderArtifact(
  input: StrategyTaskOrderArtifactInput,
): Omit<StrategyTaskOrderArtifactWriteResult, "filePath"> {
  const artifactId = buildArtifactId(input.taskOrder.strategyTaskOrderId);
  const filename = buildFilename(input.taskOrder.strategyTaskOrderId);
  const artifactRef = `trading/${artifactId}`;
  const excerpt = buildExcerpt(input);

  const record: StrategyTaskOrderArtifactIndexRecord = {
    artifact_id: artifactRef,
    title: `Strategy Task Order: ${input.taskOrder.title}`,
    file: filename,
    filename,
    type: "strategy_task_order",
    status: input.taskOrder.status,
    date: input.taskOrder.appliedAt,
    chain_phase: "A9",
    tags: [
      "strategy_task_order",
      input.taskOrder.strategySnapshot.direction,
      input.taskOrder.strategySnapshot.symbol,
      input.taskOrder.strategySnapshot.frequency,
      input.taskOrder.strategyType,
    ],
    workflow_id: input.strategy.id,
    workflow_type: "trading_v2",
    trace_id: input.taskOrder.strategyTaskOrderId,
    department: "trading",
    excerpt,
  };

  const document: StrategyTaskOrderArtifactDocument = {
    artifactId: artifactRef,
    category: "trading",
    generatedAt: input.taskOrder.updatedAt,
    strategyTaskOrderId: input.taskOrder.strategyTaskOrderId,
    nextExecutionAt: input.nextExecutionAt,
    strategy: input.strategy,
    taskOrder: input.taskOrder,
    strategyTask: {
      ...input.strategyTask,
      nextExecutionAt: input.strategyTask.nextExecutionAt?.toISOString() ?? null,
    },
    strategySnapshot: input.taskOrder.strategySnapshot,
    executionRun: input.executionRun,
  };

  return {
    artifactId,
    filename,
    record,
    document,
    feedItem: buildFeedItemFromRecord(record),
  };
}

function readIndexFile(indexPath: string): StrategyTaskOrderIndexFile {
  if (!fs.existsSync(indexPath)) {
    return {
      last_updated: new Date(0).toISOString(),
      artifacts: [],
    };
  }

  try {
    const parsed = JSON.parse(fs.readFileSync(indexPath, "utf-8")) as Partial<StrategyTaskOrderIndexFile>;
    return {
      last_updated:
        typeof parsed.last_updated === "string" ? parsed.last_updated : new Date(0).toISOString(),
      artifacts: Array.isArray(parsed.artifacts)
        ? parsed.artifacts.filter(
            (item): item is StrategyTaskOrderArtifactIndexRecord =>
              Boolean(item) &&
              typeof item.artifact_id === "string" &&
              typeof item.file === "string" &&
              typeof item.type === "string",
          )
        : [],
    };
  } catch {
    return {
      last_updated: new Date(0).toISOString(),
      artifacts: [],
    };
  }
}

export function writeStrategyTaskOrderArtifact(
  input: StrategyTaskOrderArtifactInput & { artifactsDir: string },
): StrategyTaskOrderArtifactWriteResult {
  const built = buildStrategyTaskOrderArtifact(input);
  const tradingDir = path.join(input.artifactsDir, "trading");
  const filePath = path.join(tradingDir, built.filename);
  const indexPath = path.join(tradingDir, "index.json");

  ensureDir(tradingDir);
  fs.writeFileSync(filePath, JSON.stringify(built.document, null, 2), "utf-8");

  const currentIndex = readIndexFile(indexPath);
  const filteredArtifacts = currentIndex.artifacts.filter(
    (item) => item.artifact_id !== built.record.artifact_id,
  );

  const nextIndex: StrategyTaskOrderIndexFile = {
    last_updated: built.record.date,
    artifacts: [built.record, ...filteredArtifacts].sort((left, right) =>
      right.date.localeCompare(left.date),
    ),
  };

  fs.writeFileSync(indexPath, JSON.stringify(nextIndex, null, 2), "utf-8");

  return {
    ...built,
    filePath,
  };
}

export function createStrategyTaskOrderArtifactWriter(
  artifactsDir: string,
): StrategyTaskOrderArtifactWriter {
  return {
    writeStrategyTaskOrderArtifact(input) {
      return writeStrategyTaskOrderArtifact({
        artifactsDir,
        ...input,
      });
    },
  };
}

export function collectStrategyTaskOrderFeedItems(input: {
  artifactsDir: string;
}): StrategyTaskOrderFeedItem[] {
  const indexPath = path.join(input.artifactsDir, "trading", "index.json");
  const index = readIndexFile(indexPath);

  return index.artifacts
    .filter((item) => item.type === "strategy_task_order")
    .map((item) => buildFeedItemFromRecord(item))
    .sort((left, right) => right.date.localeCompare(left.date));
}
