/**
 * P0-5-S3: 训练事件消费者
 *
 * 职责:
 * 1. 消费 training.dataset / model.update 事件
 * 2. 追加写入 ~/.workbuddy/training_datasets/events.jsonl
 * 3. FAIL-OPEN: 任何异常返回 degraded，不阻塞交易热路径
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-5
 * 边界守护（HC-9 硬约束）:
 * - 只记录事件元数据，不做任何交易判断
 * - 禁止出现交易判断逻辑（技术指标判断、仓位判断、盈亏判断、方向判断）
 * - 不计算 reward（reward 由 DreamOS 内部 EvolutionEngine 独占）
 *
 * 数据格式（每行一条 JSONL）:
 *   {event_type, timestamp, payload, degraded}
 */

import { homedir } from "node:os";
import { resolve } from "node:path";
import { appendFileSync, mkdirSync } from "node:fs";

/**
 * 惰性计算事件目录（支持 HOME 环境变量覆盖，便于测试）
 */
function _getEventsDir(): string {
  return resolve(homedir(), ".workbuddy", "training_datasets");
}

function _getEventsFile(): string {
  return resolve(_getEventsDir(), "events.jsonl");
}

/** 测试中读取实际路径 */
export function getEventsDir(): string {
  return _getEventsDir();
}
export function getEventsFile(): string {
  return _getEventsFile();
}

export type TrainingEventType = "training.dataset" | "model.update";

export interface TrainingEvent<T = unknown> {
  event_type: TrainingEventType;
  payload: T;
}

export interface ConsumeResult {
  written: boolean;
  degraded: boolean;
  reason?: string;
  event_type: TrainingEventType;
}

/**
 * 确保事件目录存在（FAIL-OPEN：失败仅记日志）
 */
function _ensureDir(): void {
  try {
    mkdirSync(_getEventsDir(), { recursive: true });
  } catch {
    // FAIL-OPEN：目录创建失败由调用方捕获
  }
}

/**
 * 消费训练事件 — 追加写入 events.jsonl
 *
 * @param event 训练事件（event_type + payload）
 * @returns 写入结果（FAIL-OPEN 时返回 degraded）
 *
 * HC-9: 此函数只记录事件元数据，不做任何交易判断
 */
export function consumeTrainingEvent<T = unknown>(
  event: TrainingEvent<T>
): ConsumeResult {
  const eventType = event.event_type;
  const payload = event.payload;

  // 输入校验
  if (eventType !== "training.dataset" && eventType !== "model.update") {
    return {
      written: false,
      degraded: true,
      reason: `unsupported event_type: ${eventType}`,
      event_type: eventType,
    };
  }

  try {
    _ensureDir();

    const record = {
      event_type: eventType,
      timestamp: new Date().toISOString(),
      payload,
      degraded: false,
    };

    try {
      appendFileSync(_getEventsFile(), JSON.stringify(record) + "\n", "utf8");
    } catch (e) {
      return {
        written: false,
        degraded: true,
        reason: `append events.jsonl failed: ${e instanceof Error ? e.message : String(e)}`,
        event_type: eventType,
      };
    }

    return {
      written: true,
      degraded: false,
      event_type: eventType,
    };
  } catch (e) {
    return {
      written: false,
      degraded: true,
      reason: `consumeTrainingEvent failed: ${e instanceof Error ? e.message : String(e)}`,
      event_type: eventType,
    };
  }
}

/**
 * 消费 training.dataset 事件 — 便捷封装
 *
 * @param payload 数据集元信息
 * @returns 写入结果
 */
export function consumeTrainingDatasetEvent(
  payload: Record<string, unknown>
): ConsumeResult {
  return consumeTrainingEvent({
    event_type: "training.dataset",
    payload,
  });
}

/**
 * 消费 model.update 事件 — 便捷封装
 *
 * @param payload 模型更新元信息
 * @returns 写入结果
 */
export function consumeModelUpdateEvent(
  payload: Record<string, unknown>
): ConsumeResult {
  return consumeTrainingEvent({
    event_type: "model.update",
    payload,
  });
}

// 导出路径常量供测试使用
export { EVENTS_DIR, EVENTS_FILE };
