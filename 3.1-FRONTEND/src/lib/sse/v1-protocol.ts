// ============================================
// SSE 协议 v1 — 客户端兼容层（SPEC C §3.3 / T-C3）
//
// 职责：把任意形态的 SSE 事件归一化为 v1 结构，并提供
// 去重（LRU 200）/ 乱序检测 / 未知类型忽略 / 顺序告警。
// 不接管连接与分发：由 sse-client.ts 在解析阶段调用。
// ============================================

/** SPEC C §3.3 定义的 8 类 v1 事件 */
export const SSE_V1_TYPES = [
  'started',
  'thinking',
  'progress',
  'step',
  'report',
  'done',
  'error',
  'heartbeat',
] as const;

export type SSEV1Type = (typeof SSE_V1_TYPES)[number];

/** v1 事件结构（字段可增不可删） */
export interface SSEEventV1<T = unknown> {
  id: string;
  seq: number;
  type: SSEV1Type | string;
  trace_id: string;
  session_id?: string;
  ts: number;
  payload: T;
}

/** 归一化输入：来自 SSE 帧的原始字段 */
export interface RawSSEFrame {
  /** `event:` 行 */
  event?: string;
  /** `id:` 行 */
  id?: string;
  /** `data:` 行解析后的对象 */
  data?: Record<string, unknown>;
  /** 到达时刻（默认取 Date.now()） */
  receivedAt?: number;
}

export interface NormalizedEvent<T = unknown> extends SSEEventV1<T> {
  /** true 表示缺少 seq/type，来自旧格式 */
  legacy: boolean;
}

/** 稳定短哈希（djb2），用于 id 缺失时构造去重键 */
function djb2(input: string): string {
  let hash = 5381;
  for (let i = 0; i < input.length; i += 1) {
    hash = ((hash << 5) + hash + input.charCodeAt(i)) >>> 0;
  }
  return hash.toString(36);
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value) ?? '';
  } catch {
    return String(value);
  }
}

function pickString(data: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  return undefined;
}

function pickNumber(data: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return undefined;
}

/**
 * 归一化一帧 SSE 数据。
 * - type 优先取 `event:`，其次 data.type
 * - seq/type 缺失 → legacy=true
 * - id 缺失 → `type+ts+hash(payload)` 生成稳定键
 */
export function normalizeSSEEvent<T = unknown>(frame: RawSSEFrame): NormalizedEvent<T> {
  const data = frame.data ?? {};
  const ts = pickNumber(data, ['ts', 'timestamp']) ?? frame.receivedAt ?? Date.now();
  const type = frame.event ?? pickString(data, ['type']) ?? 'unknown';
  const seq = pickNumber(data, ['seq']);
  const traceId = pickString(data, ['trace_id', 'traceId']) ?? '';
  const sessionId = pickString(data, ['session_id', 'sessionId']);
  const payload = (data.payload !== undefined ? data.payload : data) as T;

  const legacy =
    seq === undefined || (frame.event === undefined && typeof data.type !== 'string');

  const id =
    frame.id ??
    pickString(data, ['id']) ??
    `${type}:${ts}:${djb2(safeStringify(payload))}`;

  return {
    id,
    seq: seq ?? -1,
    type,
    trace_id: traceId,
    session_id: sessionId,
    ts,
    payload,
    legacy,
  };
}

/** LRU 去重器：容量 200（SPEC C §3.3 规则 2） */
export class SSEDeduper {
  private readonly capacity: number;
  private readonly order: string[] = [];
  private readonly set = new Set<string>();
  private duplicateCount = 0;

  constructor(capacity = 200) {
    this.capacity = capacity;
  }

  /** 返回 true 表示该 id 已出现过（应丢弃） */
  seen(id: string): boolean {
    if (this.set.has(id)) {
      this.duplicateCount += 1;
      // 命中后刷新 LRU 位置
      const index = this.order.indexOf(id);
      if (index >= 0) {
        this.order.splice(index, 1);
        this.order.push(id);
      }
      return true;
    }

    this.set.add(id);
    this.order.push(id);
    if (this.order.length > this.capacity) {
      const evicted = this.order.shift();
      if (evicted !== undefined) this.set.delete(evicted);
    }
    return false;
  }

  get duplicates(): number {
    return this.duplicateCount;
  }

  get size(): number {
    return this.set.size;
  }
}

/** 乱序检测器：按 session_id 记录最后 seq */
export class SeqTracker {
  private readonly lastBySession = new Map<string, number>();
  private outOfOrderCount = 0;

  /** 返回 true 表示该事件乱序（应丢弃） */
  isOutOfOrder(event: { seq: number; session_id?: string; legacy: boolean }): boolean {
    // legacy 事件、缺 session_id、缺 seq 均不参与乱序判定
    if (event.legacy || !event.session_id || event.seq < 0) return false;

    const last = this.lastBySession.get(event.session_id);
    if (last !== undefined && event.seq <= last) {
      this.outOfOrderCount += 1;
      return true;
    }
    this.lastBySession.set(event.session_id, event.seq);
    return false;
  }

  get outOfOrder(): number {
    return this.outOfOrderCount;
  }

  /** monitor 重连时可读取最后 seq */
  getLastSeq(sessionId: string): number | undefined {
    return this.lastBySession.get(sessionId);
  }
}

/** 未知类型计数器（SPEC C §3.3 规则 5） */
export class UnknownTypeCounter {
  private count = 0;
  private readonly seenTypes = new Set<string>();

  /** 返回 true 表示未知类型（应忽略） */
  isUnknown(type: string): boolean {
    if ((SSE_V1_TYPES as readonly string[]).includes(type)) return false;
    // 交易域扩展事件（cross_validation / text_delta / data_card / artifact_ref / action_required）
    // 不属于 v1 8 类，但属于已知扩展，不算未知
    if (KNOWN_EXTENSIONS.has(type)) return false;
    this.count += 1;
    this.seenTypes.add(type);
    return true;
  }

  get unknownCount(): number {
    return this.count;
  }

  get types(): string[] {
    return [...this.seenTypes];
  }
}

const KNOWN_EXTENSIONS = new Set([
  'cross_validation',
  'text_delta',
  'data_card',
  'artifact_ref',
  'action_required',
]);

/** 顺序告警（规则 6）：越级只 warn，不阻断 */
export class OrderMonitor {
  private started = false;
  private terminated = false;
  private readonly warned = new Set<string>();

  check(type: string, id: string): void {
    if (this.terminated) {
      this.warn(`事件 ${type} 出现在终态 ${this.terminated} 之后`, id);
      return;
    }
    if (type === 'started') {
      this.started = true;
      return;
    }
    if (!this.started && type !== 'heartbeat') {
      this.warn(`事件 ${type} 出现在 started 之前`, id);
    }
    if (type === 'done' || type === 'error') {
      this.terminated = true;
    }
  }

  private warn(message: string, id: string): void {
    if (this.warned.has(message)) return;
    this.warned.add(message);
    // eslint-disable-next-line no-console
    console.warn(`[sse-v1] ${message}（id=${id}）`);
  }

  get isTerminated(): boolean {
    return this.terminated;
  }
}

/** 协议状态聚合：一次流式会话内持有 */
export class SSEProtocolState {
  readonly deduper = new SSEDeduper();
  readonly seqTracker = new SeqTracker();
  readonly unknownTypes = new UnknownTypeCounter();
  readonly order = new OrderMonitor();
  private lastEventIdValue: string | undefined;

  /**
   * 处理一帧。返回 null 表示应丢弃（重复/乱序/未知类型）。
   */
  process<T = unknown>(frame: RawSSEFrame): NormalizedEvent<T> | null {
    const event = normalizeSSEEvent<T>(frame);

    if (this.deduper.seen(event.id)) return null;
    // 未知类型必须先于 seq 判定：被忽略的事件不得抬高 seq 水位
    if (this.unknownTypes.isUnknown(event.type)) return null;
    if (this.seqTracker.isOutOfOrder(event)) return null;

    this.order.check(event.type, event.id);
    this.lastEventIdValue = event.id;
    return event;
  }

  /** monitor 重连使用 */
  get lastEventId(): string | undefined {
    return this.lastEventIdValue;
  }

  get stats() {
    return {
      duplicates: this.deduper.duplicates,
      outOfOrder: this.seqTracker.outOfOrder,
      unknownTypes: this.unknownTypes.unknownCount,
      lastEventId: this.lastEventIdValue,
    };
  }
}
