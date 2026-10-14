/**
 * 36-通信系统层 - 摘要聚合（Digest）
 * 职责：同类信号在时间窗口内超阈值时聚合为一条摘要
 * 依据 SPEC.md v1.0 第 5.3 节
 */
import type { SignalEnvelope, SignalType, Severity } from './types';

/** 聚合窗口（ms） */
const WINDOW_MS = 5 * 60 * 1000;
/** 窗口内触发聚合的条数阈值 */
const THRESHOLD = 10;
/** 聚合刷新间隔（ms）：达到阈值后每 N 条刷新一次摘要 */
const REFRESH_EVERY = 10;

interface WindowState {
  count: number;
  firstTs: number;
  lastEnvelope: SignalEnvelope;
  /** 已发送摘要的条数快照 */
  summarizedAt: number;
}

const windows = new Map<string, WindowState>();

function windowKey(type: SignalType, severity: Severity): string {
  return `${type}:${severity}`;
}

export interface DigestDecision {
  /** true = 逐条投递；false = 已并入聚合，不单独投递 */
  passThrough: boolean;
  /** 聚合摘要就绪时应投递的摘要信号（替换原信号投递） */
  digestEnvelope?: SignalEnvelope;
}

/**
 * 判定一条信号是逐条投递还是聚合
 * - critical 级别永不聚合
 * - 窗口内同类信号未超阈值：逐条投递
 * - 超过阈值后：并入聚合，每 REFRESH_EVERY 条推送一次摘要
 */
export function applyDigest(envelope: SignalEnvelope): DigestDecision {
  if (envelope.severity === 'critical') {
    return { passThrough: true };
  }

  const key = windowKey(envelope.type, envelope.severity);
  const now = envelope.ts;
  let state = windows.get(key);

  // 窗口过期重置
  if (state && now - state.firstTs > WINDOW_MS) {
    state = undefined;
    windows.delete(key);
  }

  if (!state) {
    windows.set(key, {
      count: 1,
      firstTs: now,
      lastEnvelope: envelope,
      summarizedAt: 0,
    });
    return { passThrough: true };
  }

  state.count++;
  state.lastEnvelope = envelope;

  if (state.count <= THRESHOLD) {
    return { passThrough: true };
  }

  // 已超阈值：并入聚合
  const sinceLastSummary = state.count - state.summarizedAt;
  if (sinceLastSummary >= REFRESH_EVERY) {
    state.summarizedAt = state.count;
    const digestEnvelope: SignalEnvelope = {
      ...envelope,
      id: `digest_${envelope.id}`,
      payload: {
        digest: true,
        signalType: envelope.type,
        severity: envelope.severity,
        windowMinutes: WINDOW_MS / 60000,
        count: state.count,
        latest: envelope.payload,
      },
    };
    return { passThrough: false, digestEnvelope };
  }

  return { passThrough: false };
}

/** 查询聚合窗口状态（监控用） */
export function digestStats(): Array<{ key: string; count: number; firstTs: number }> {
  return Array.from(windows.entries()).map(([key, s]) => ({
    key,
    count: s.count,
    firstTs: s.firstTs,
  }));
}
