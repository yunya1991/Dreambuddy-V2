/**
 * 36-通信系统层（Signal Bus）核心总线 v1.2（P2）
 * 职责：信号收口 → 校验 → 幂等 → 摘要聚合 → 订阅路由 + 默认路由 → 降级挂起/恢复重放
 * 依据 SPEC.md v1.0 第 3、5 章（P2：多渠道订阅 + digest）
 */
import type { SignalEnvelope, SignalType, EmitResult } from './types';
import { NOTIFY_TYPES, INTERACTIVE_TYPES } from './types';
import { sendToFeishu } from './adapters/feishu';
import { sendToHermes } from './adapters/hermes';
import { sendToChannel } from './adapters/multichannel';
import { getHealthState, onHealthStateChange } from './health';
import { querySubscriptions } from './store';
import type { SubscriptionChannel } from './store';
import { applyDigest } from './digest';
import * as fs from 'fs';
import * as path from 'path';

/** 幂等缓存：dedupKey → 过期时间 */
const dedupCache = new Map<string, number>();
const DEDUP_TTL_MS = 10 * 60 * 1000;

/** 挂起队列持久化文件（JSONL） */
const OUTBOX_DIR = process.env.SIGNAL_BUS_OUTBOX_DIR || '/home/luke/logs/signal-bus';
const OUTBOX_FILE = path.join(OUTBOX_DIR, 'outbox.jsonl');

function ensureOutboxFile(): void {
  try {
    fs.mkdirSync(OUTBOX_DIR, { recursive: true });
    if (!fs.existsSync(OUTBOX_FILE)) fs.writeFileSync(OUTBOX_FILE, '', 'utf-8');
  } catch {
    // 持久化失败时降级为内存模式，不阻断主流程
  }
}

/** 追加信号到挂起队列（持久化） */
function enqueueOutbox(envelope: SignalEnvelope): void {
  try {
    ensureOutboxFile();
    fs.appendFileSync(OUTBOX_FILE, JSON.stringify(envelope) + '\n', 'utf-8');
  } catch {
    // 持久化失败仅记录
  }
}

/** 读取全部挂起信号（按时间顺序）并清空文件 */
function drainOutbox(): SignalEnvelope[] {
  try {
    if (!fs.existsSync(OUTBOX_FILE)) return [];
    const content = fs.readFileSync(OUTBOX_FILE, 'utf-8');
    fs.writeFileSync(OUTBOX_FILE, '', 'utf-8');
    const items: SignalEnvelope[] = [];
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        items.push(JSON.parse(trimmed) as SignalEnvelope);
      } catch {
        // 跳过损坏行
      }
    }
    items.sort((a, b) => a.ts - b.ts);
    return items;
  } catch {
    return [];
  }
}

/** 校验信号信封 */
function validateEnvelope(envelope: Partial<SignalEnvelope>): string | null {
  if (!envelope.type) return '缺少 type';
  if (!envelope.severity) return '缺少 severity';
  if (!envelope.source) return '缺少 source';
  if (!envelope.payload || typeof envelope.payload !== 'object') return '缺少 payload';
  if (!NOTIFY_TYPES.has(envelope.type as SignalType) && !INTERACTIVE_TYPES.has(envelope.type as SignalType)) {
    return `未知信号类型: ${envelope.type}`;
  }
  return null;
}

/** 幂等检查：重复信号返回 true（应跳过） */
function isDuplicate(envelope: SignalEnvelope): boolean {
  if (!envelope.dedupKey) return false;
  const now = Date.now();
  for (const [key, expireAt] of dedupCache) {
    if (expireAt < now) dedupCache.delete(key);
  }
  if (dedupCache.has(envelope.dedupKey)) return true;
  dedupCache.set(envelope.dedupKey, now + DEDUP_TTL_MS);
  return false;
}

/** 生成 ULID 风格唯一 ID（时间有序） */
function generateId(): string {
  const ts = Date.now().toString(36).padStart(10, '0');
  const rand = Math.random().toString(36).slice(2, 12).padEnd(10, '0');
  return `sig_${ts}${rand}`;
}

/** 分发到 API 直推通道（飞书默认路由） */
async function dispatchApi(envelope: SignalEnvelope): Promise<string> {
  const result = await sendToFeishu(envelope);
  if (!result.ok) {
    throw new Error(`API 直推失败: ${result.error}`);
  }
  return `api:feishu:${result.chatId}`;
}

/** 分发到 Hermes 智能通道 */
async function dispatchHermes(envelope: SignalEnvelope, chatId?: string): Promise<string> {
  const result = await sendToHermes(envelope, chatId ? { chatId } : {});
  if (!result.ok) {
    throw new Error(`Hermes 投递失败: ${result.error}`);
  }
  return `hermes:${result.chatId}`;
}

/** 分发到订阅的多渠道 */
async function dispatchSubscription(
  envelope: SignalEnvelope,
  channel: SubscriptionChannel,
  target: string
): Promise<string> {
  if (channel === 'FEISHU') {
    const result = await sendToFeishu(envelope, { chatId: target });
    if (!result.ok) throw new Error(`飞书订阅投递失败: ${result.error}`);
    return `sub:feishu:${target}`;
  }
  if (channel === 'HERMES') {
    const result = await sendToHermes(envelope, { chatId: target });
    if (!result.ok) throw new Error(`Hermes 订阅投递失败: ${result.error}`);
    return `sub:hermes:${target}`;
  }
  const result = await sendToChannel(channel, envelope, target);
  if (!result.ok) throw new Error(`${channel} 订阅投递失败: ${result.error}`);
  return `sub:${channel}:${target}`;
}

/**
 * 信号收口入口
 * 所有信号源统一调用此函数（或经 POST /api/signal-bus/emit）
 */
export async function emit(input: Partial<SignalEnvelope>): Promise<EmitResult> {
  // 1. 校验
  const validationError = validateEnvelope(input);
  if (validationError) {
    throw new Error(`信号校验失败: ${validationError}`);
  }

  // 2. 补全信封
  const envelope: SignalEnvelope = {
    id: input.id || generateId(),
    type: input.type!,
    severity: input.severity!,
    source: input.source!,
    ts: input.ts || Date.now(),
    payload: input.payload!,
    dedupKey: input.dedupKey,
  };

  // 3. 幂等检查
  if (isDuplicate(envelope)) {
    return { id: envelope.id, dispatched: [], queued: ['dedup:skipped'] };
  }

  // 4. 摘要聚合：超阈值信号并入聚合，仅投递摘要
  const digestDecision = applyDigest(envelope);
  const effective = digestDecision.digestEnvelope || envelope;
  if (!digestDecision.passThrough && !digestDecision.digestEnvelope) {
    return { id: envelope.id, dispatched: [], queued: ['digest:aggregated'] };
  }

  // 5. 分发决策
  const dispatched: string[] = [];
  const queued: string[] = [];
  const health = getHealthState();
  const errors: string[] = [];

  // 5.1 用户订阅优先：该信号类型的所有启用订阅逐个投递
  const subscriptions = querySubscriptions({ signalType: effective.type });
  const hasSubscriptions = subscriptions.length > 0;
  for (const sub of subscriptions) {
    try {
      if (sub.channel === 'HERMES' && !health.healthy) {
        // Hermes 订阅在降级期间挂起
        enqueueOutbox(effective);
        queued.push(`hermes:outbox:${effective.id}`);
        continue;
      }
      dispatched.push(await dispatchSubscription(effective, sub.channel, sub.target));
    } catch (err) {
      errors.push(`${sub.channel}:${err instanceof Error ? err.message : 'failed'}`);
    }
  }

  // 5.2 默认路由：无任何订阅时按静态划分走默认通道
  if (!hasSubscriptions) {
    if (NOTIFY_TYPES.has(effective.type)) {
      try {
        dispatched.push(await dispatchApi(effective));
      } catch (err) {
        errors.push(err instanceof Error ? err.message : 'api dispatch failed');
      }
    }
    if (INTERACTIVE_TYPES.has(effective.type)) {
      if (health.healthy) {
        try {
          dispatched.push(await dispatchHermes(effective));
        } catch {
          enqueueOutbox(effective);
          queued.push(`hermes:outbox:${effective.id}`);
        }
      } else {
        enqueueOutbox(effective);
        queued.push(`hermes:outbox:${effective.id}`);
      }
    }
  }

  // 5.3 部分投递失败：返回警告但不视为整体失败
  if (errors.length > 0 && dispatched.length === 0 && queued.length === 0) {
    throw new Error(errors.join('; '));
  }

  return {
    id: effective.id,
    dispatched,
    queued: queued.length ? queued : undefined,
  };
}

/** 重放挂起队列（模型恢复后调用） */
export async function replayOutbox(): Promise<{ replayed: number; failed: number }> {
  const items = drainOutbox();
  let replayed = 0;
  let failed = 0;
  const failedItems: SignalEnvelope[] = [];
  for (const envelope of items) {
    try {
      await dispatchHermes(envelope);
      replayed++;
    } catch {
      failed++;
      failedItems.push(envelope);
    }
  }
  for (const item of failedItems) {
    enqueueOutbox(item);
  }
  return { replayed, failed };
}

/** 查询挂起队列长度（监控用） */
export function outboxSize(): number {
  try {
    if (!fs.existsSync(OUTBOX_FILE)) return 0;
    const content = fs.readFileSync(OUTBOX_FILE, 'utf-8');
    return content.split('\n').filter((l) => l.trim()).length;
  } catch {
    return 0;
  }
}

/** 恢复时自动重放（模块加载时注册回调） */
let replaying = false;
onHealthStateChange(async (healthy) => {
  if (healthy && !replaying) {
    replaying = true;
    try {
      await replayOutbox();
    } finally {
      replaying = false;
    }
  }
});
