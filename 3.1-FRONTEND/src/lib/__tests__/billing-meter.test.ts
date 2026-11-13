/**
 * SPEC-52 F4 — CU 计量与账本单测
 */
import { mkdtemp, rm } from 'fs/promises';
import os from 'os';
import path from 'path';
import {
  CU_COEFFICIENTS,
  cuFor,
  estimateChatCu,
  reserveCu,
  reservedCu,
  settleReservation,
  summarizeUsage,
} from '@/lib/billing/meter';

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(path.join(os.tmpdir(), 'usage-ledger-'));
  process.env.PRODUCT_USAGE_DIR = dir;
});

afterEach(async () => {
  delete process.env.PRODUCT_USAGE_DIR;
  delete process.env.PRODUCT_AI_TRADING_BALANCE_CU;
  await rm(dir, { recursive: true, force: true });
});

describe('CU 系数', () => {
  it('按 SPEC 首版系数换算', () => {
    expect(cuFor('llm_input', 1500)).toBe(1.5);
    expect(cuFor('llm_output', 1000)).toBe(4);
    expect(cuFor('tool_call', 2)).toBe(2);
    expect(cuFor('tool_call_heavy', 1)).toBe(10);
    expect(CU_COEFFICIENTS.backtest_cpu.cu).toBe(1);
  });

  it('非法数量返回 0', () => {
    expect(cuFor('llm_input', 0)).toBe(0);
    expect(cuFor('llm_input', -5)).toBe(0);
    expect(cuFor('llm_input', Number.NaN)).toBe(0);
  });
});

describe('预扣 → 结算', () => {
  it('结算写账本并释放预扣', async () => {
    const reservation = reserveCu('trace-1', estimateChatCu(0));
    expect(reservedCu()).toBeGreaterThan(0);

    const entries = await settleReservation(reservation, [
      { dimension: 'llm_input', quantity: 2000, ref: 'agent_chat' },
      { dimension: 'llm_output', quantity: 500, ref: 'agent_chat' },
      { dimension: 'tool_call', quantity: 1, ref: 'platform' },
    ]);

    expect(entries.map((entry) => entry.cu_cost)).toEqual([2, 2, 1]);
    expect(reservedCu()).toBe(0);

    const summary = await summarizeUsage();
    expect(summary.spent_cu).toBe(5);
    expect(summary.balance_cu).toBe(995);
    expect(summary.records).toHaveLength(3);
    expect(summary.totals.llm_input).toEqual({ quantity: 2000, cu_cost: 2 });
  });

  it('无实际用量时只释放预扣、不写账本', async () => {
    const reservation = reserveCu('trace-2');
    await settleReservation(reservation, []);
    expect(reservedCu()).toBe(0);
    const summary = await summarizeUsage();
    expect(summary.records).toHaveLength(0);
    expect(summary.spent_cu).toBe(0);
  });

  it('初始额度可由 env 覆盖', async () => {
    process.env.PRODUCT_AI_TRADING_BALANCE_CU = '100';
    const summary = await summarizeUsage();
    expect(summary.base_cu).toBe(100);
    expect(summary.balance_cu).toBe(100);
  });
});
