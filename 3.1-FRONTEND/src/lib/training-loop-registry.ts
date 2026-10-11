/**
 * TrainingLoopRegistry — 5 层训练循环单例注册表
 * ==========================================
 * 为 34-前端应用训练系统 的 Python 编排层提供 HTTP API 背后的单例管理。
 *
 * 5 层训练循环:
 *   S   — IntentTrainingLoop (桶满 50)
 *   DSH — ExecutionPathTrainingLoop (桶满 50)
 *   C   — ReflectionTrainingLoop (桶满 50)
 *   G   — GraphStructureTrainingLoop (桶满 60)
 *   LLM — PromptOptimizationLoop (桶满 30)
 *
 * 每层统一暴露:
 *   - addTrainingData(data)
 *   - shouldTrain()
 *   - train()
 *   - get bucketCount
 *   - get bucketThreshold
 */
import { IntentTrainingLoop } from './s-intent-training-loop';
import { ExecutionPathTrainingLoop } from './dsh-path-training-loop';
import { ReflectionTrainingLoop } from './c-reflection-training-loop';
import { GraphStructureTrainingLoop } from './g-graph-training-loop';
import { PromptOptimizationLoop } from './llm-prompt-training-loop';
import { LAYER_MICRO_BATCH } from './replay-buffer';
import type { CheckpointMeta } from './model-checkpoint';

export type LayerName = 'S' | 'DSH' | 'C' | 'G' | 'LLM';

export interface TrainingLoopStatus {
  layer: LayerName;
  bucketCount: number;
  bucketThreshold: number;
  shouldTrain: boolean;
  /** v0.5 P3.4: 增量训练步数（数据到达即学习证据） */
  step?: number;
  /** v0.5 P3.4: buffer 统计（EWMA 衰减证据） */
  bufferStats?: {
    size: number;
    capacity: number;
    avgWeight: number;
    oldestAge: number;
    qualityDistribution: Record<string, number>;
  };
}

let _instances: Record<LayerName, unknown> | null = null;

function getInstances(): Record<LayerName, unknown> {
  if (_instances === null) {
    _instances = {
      S: new IntentTrainingLoop(),
      DSH: new ExecutionPathTrainingLoop(),
      C: new ReflectionTrainingLoop(),
      G: new GraphStructureTrainingLoop(),
      LLM: new PromptOptimizationLoop(),
    };
  }
  return _instances;
}

export function getTrainingLoop(layer: LayerName): unknown {
  return getInstances()[layer];
}

export function getTrainingLoopStatus(layer: LayerName): TrainingLoopStatus | null {
  const loop = getInstances()[layer];
  if (!loop) return null;
  const l = loop as {
    bucketCount: number;
    bucketThreshold: number;
    shouldTrain: () => boolean;
    step?: number;
    getBufferStats?: () => TrainingLoopStatus['bufferStats'];
  };
  const status: TrainingLoopStatus = {
    layer,
    bucketCount: l.bucketCount,
    bucketThreshold: l.bucketThreshold,
    shouldTrain: l.shouldTrain(),
  };
  // v0.5 P3.4: 暴露 step + bufferStats 给持续训练脚本
  if (typeof l.step === 'number') {
    status.step = l.step;
  }
  if (typeof l.getBufferStats === 'function') {
    status.bufferStats = l.getBufferStats();
  }
  return status;
}

export function getAllStatus(): TrainingLoopStatus[] {
  return (Object.keys(getInstances()) as LayerName[])
    .map((layer) => getTrainingLoopStatus(layer)!)
    .filter(Boolean);
}

/**
 * 向指定层添加训练数据。
 * data 字段结构按层不同，由调用方（Python 适配器）负责转换。
 */
export function addTrainingData(layer: LayerName, data: Record<string, unknown>): boolean {
  const loop = getInstances()[layer];
  if (!loop) return false;
  (loop as { addTrainingData: (d: Record<string, unknown>) => void }).addTrainingData(data);
  return true;
}

/**
 * 触发指定层训练。返回训练结果（各层结构不同）。
 */
export function trainLayer(layer: LayerName): Record<string, unknown> | null {
  const loop = getInstances()[layer];
  if (!loop) return null;
  const result = (loop as { train: () => Record<string, unknown> }).train();
  return result;
}

// ============================================================
// v0.5 P2: 增量训练 / Checkpoint / Restore / ModelSnapshot
// ============================================================

/**
 * P2.1: 触发增量训练。
 * 从 ReplayBuffer 采样微批量数据，调用 trainIncremental()。
 */
export function trainIncrementalLayer(layer: LayerName): Record<string, unknown> | null {
  const loop = getInstances()[layer];
  if (!loop) return null;
  const l = loop as {
    replayBuffer: { sample: (n: number) => { data: Record<string, unknown> }[]; size: number };
    trainIncremental: (batch: Record<string, unknown>[]) => Record<string, unknown>;
  };
  const microBatch = LAYER_MICRO_BATCH[layer];
  const entries = l.replayBuffer.sample(microBatch);
  const batch = entries.map((e) => e.data);
  return l.trainIncremental(batch);
}

/**
 * P2.1: 保存模型状态检查点。
 */
export function checkpointLayer(
  layer: LayerName,
): { checkpointed: boolean; state: Record<string, unknown>; meta: CheckpointMeta } | null {
  const loop = getInstances()[layer];
  if (!loop) return null;
  const l = loop as {
    getModelSnapshot: () => Record<string, unknown>;
    checkpoint: { checkpoint: (layer: string, state: Record<string, unknown>) => CheckpointMeta };
  };
  const state = l.getModelSnapshot();
  const meta = l.checkpoint.checkpoint(layer, state);
  return { checkpointed: true, state, meta };
}

/**
 * P2.1: 恢复模型状态。
 */
export function restoreLayer(
  layer: LayerName,
  state: Record<string, unknown>,
): { restored: boolean } | null {
  const loop = getInstances()[layer];
  if (!loop) return null;
  if (!state || Object.keys(state).length === 0) return { restored: false };
  const l = loop as { restoreModel: (state: Record<string, unknown>) => void };
  l.restoreModel(state);
  return { restored: true };
}

/**
 * P2.2: 获取模型状态快照。
 */
export function getModelSnapshot(layer: LayerName): Record<string, unknown> | null {
  const loop = getInstances()[layer];
  if (!loop) return null;
  const l = loop as { getModelSnapshot: () => Record<string, unknown> };
  return l.getModelSnapshot();
}
