/**
 * SPEC-52 F4 / §9.1 — 算力计量（CU）与 usage_ledger
 *
 * 设计（与 SPEC 一致）：
 *  - 计量与定价分离：CU 只做成本归一，单价 unit_price_cny 独立配置；
 *  - 流程 reserve（预扣，内存）→ 执行 → settle（结算，追加写 JSONL）；
 *  - 账本只追加、不更新；余额 = entitlement 初始 CU - 已结算 - 活跃预扣；
 *  - 单账户本地：固定 user_id=local。
 *
 * 存储：`52-lobehub协议集成/runtime/usage_ledger.jsonl`（可用 PRODUCT_USAGE_DIR 覆盖）。
 */
import { appendFile, mkdir, readFile } from 'fs/promises';
import path from 'path';
import { randomUUID } from 'crypto';
import { getEntitlement, LOCAL_OWNER_ID, AI_TRADING_PRODUCT } from '@/lib/product/entitlement';

export type UsageDimension =
  | 'llm_input'
  | 'llm_output'
  | 'tool_call'
  | 'tool_call_heavy'
  | 'backtest_cpu'
  | 'data_query'
  | 'plugin_runtime';

/** CU 系数（SPEC-52 §9.1 首版） */
export const CU_COEFFICIENTS: Record<UsageDimension, { per: number; cu: number }> = {
  llm_input: { per: 1000, cu: 1.0 },
  llm_output: { per: 1000, cu: 4.0 },
  tool_call: { per: 1, cu: 1.0 },
  tool_call_heavy: { per: 1, cu: 10.0 },
  backtest_cpu: { per: 1, cu: 1.0 },
  data_query: { per: 1000, cu: 1.0 },
  plugin_runtime: { per: 10, cu: 1.0 },
};

export const UNIT_PRICE_CNY = Number(process.env.PRODUCT_CU_UNIT_PRICE_CNY ?? '0.003');
const SINGLE_REQUEST_RESERVE_CU = 60;
const RESERVE_MULTIPLIER = 1.2;

export interface UsageEntry {
  id: string;
  user_id: string;
  product_id: string;
  dimension: UsageDimension;
  quantity: number;
  cu_cost: number;
  ref: string;
  trace_id: string;
  created_at: string;
}

export interface UsageInput {
  dimension: UsageDimension;
  /** 原始计量单位（tokens / 次数 / CPU 分钟 / 行 / 秒） */
  quantity: number;
  ref?: string;
}

export interface UsageSummary {
  balance_cu: number;
  base_cu: number;
  spent_cu: number;
  reserved_cu: number;
  unit_price_cny: number;
  totals: Record<string, { quantity: number; cu_cost: number }>;
  records: UsageEntry[];
}

export function cuFor(dimension: UsageDimension, quantity: number): number {
  if (!Number.isFinite(quantity) || quantity <= 0) return 0;
  const rule = CU_COEFFICIENTS[dimension];
  return round((quantity / rule.per) * rule.cu);
}

function round(value: number): number {
  return Math.round(value * 10000) / 10000;
}

export function usageDir(): string {
  if (process.env.PRODUCT_USAGE_DIR) return process.env.PRODUCT_USAGE_DIR;
  const root = process.env.DREAMBUDDY_ROOT || path.resolve(process.cwd(), '..');
  return path.join(root, '52-lobehub协议集成', 'runtime');
}

export function ledgerPath(): string {
  return path.join(usageDir(), 'usage_ledger.jsonl');
}

/** 预扣记录（进程内存；重启失效，与 SPEC「预扣→结算」一致） */
const reservations = new Map<string, number>();

export interface Reservation {
  id: string;
  cu: number;
  trace_id: string;
}

export function reserveCu(traceId: string, estimateCu = SINGLE_REQUEST_RESERVE_CU): Reservation {
  const cu = round(Math.min(estimateCu * RESERVE_MULTIPLIER, 500));
  const reservation: Reservation = { id: randomUUID(), cu, trace_id: traceId };
  reservations.set(reservation.id, cu);
  return reservation;
}

export function releaseReservation(id: string): void {
  reservations.delete(id);
}

export function reservedCu(): number {
  let total = 0;
  for (const cu of reservations.values()) total += cu;
  return round(total);
}

/** 结算：把实际消耗追加写账本，并释放预扣。 */
export async function settleReservation(
  reservation: Reservation,
  inputs: UsageInput[],
): Promise<UsageEntry[]> {
  releaseReservation(reservation.id);
  if (inputs.length === 0) return [];

  const createdAt = new Date().toISOString();
  const entries: UsageEntry[] = inputs
    .filter((item) => Number.isFinite(item.quantity) && item.quantity > 0)
    .map((item) => ({
      id: randomUUID(),
      user_id: LOCAL_OWNER_ID,
      product_id: AI_TRADING_PRODUCT,
      dimension: item.dimension,
      quantity: round(item.quantity),
      cu_cost: cuFor(item.dimension, item.quantity),
      ref: item.ref ?? '',
      trace_id: reservation.trace_id,
      created_at: createdAt,
    }));

  if (entries.length > 0) {
    await mkdir(usageDir(), { recursive: true });
    await appendFile(
      ledgerPath(),
      entries.map((entry) => JSON.stringify(entry)).join('\n') + '\n',
      'utf-8',
    );
  }
  return entries;
}

async function readAllEntries(): Promise<UsageEntry[]> {
  try {
    const raw = await readFile(ledgerPath(), 'utf-8');
    return raw
      .split('\n')
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [JSON.parse(line) as UsageEntry];
        } catch {
          return [];
        }
      });
  } catch {
    return [];
  }
}

export async function summarizeUsage(limit = 50): Promise<UsageSummary> {
  const all = await readAllEntries();
  const totals: Record<string, { quantity: number; cu_cost: number }> = {};
  for (const entry of all) {
    const bucket = totals[entry.dimension] ?? { quantity: 0, cu_cost: 0 };
    bucket.quantity = round(bucket.quantity + entry.quantity);
    bucket.cu_cost = round(bucket.cu_cost + entry.cu_cost);
    totals[entry.dimension] = bucket;
  }
  const spent = round(all.reduce((sum, entry) => sum + entry.cu_cost, 0));
  const reserved = reservedCu();
  const base = getEntitlement().balance_cu;
  return {
    balance_cu: round(base - spent - reserved),
    base_cu: base,
    spent_cu: spent,
    reserved_cu: reserved,
    unit_price_cny: UNIT_PRICE_CNY,
    totals,
    records: all.slice(-limit).reverse(),
  };
}

/** 交易产品是否还有可用 CU（余额 = 0 时锁定付费能力）。 */
export async function hasCompute(): Promise<boolean> {
  const summary = await summarizeUsage(1);
  return summary.balance_cu > 0;
}

/** chat 请求预扣估算：基础费 + 每步工具调用。 */
export function estimateChatCu(toolCount = 0): number {
  return round(SINGLE_REQUEST_RESERVE_CU + toolCount * CU_COEFFICIENTS.tool_call.cu);
}
