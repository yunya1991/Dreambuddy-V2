/**
 * ImitationCounter 单元测试 — RED 阶段
 * 验证 SKILL_IMITATION_EVOLUTION_SPEC §3.2.4 + §3.4 + §6.7 + §6.10
 *
 * 覆盖：
 *   - normalizePattern() 5 条正则归一化规则 (m-2 修复, §6.10)
 *   - increment() 计数 + N=3 阈值触发沉淀 (§3.4)
 *   - sedimentation_triggered 防重复触发 (M-1 修复)
 *   - 独立计数：历史不清零 (M-1 修复, §6.7)
 */

import { ImitationCounter, getImitationCounter } from './imitation-counter';

describe('ImitationCounter', () => {
  let counter: ImitationCounter;

  beforeEach(() => {
    counter = getImitationCounter();
    // 清理状态，确保每个测试独立
    counter.reset();
  });

  // ============================================================
  // §6.10 m-2 修复: normalizePattern — 5 条正则归一化规则
  // ============================================================
  describe('normalizePattern (m-2 正则归一化)', () => {
    it('应将数字替换为 {number}', () => {
      const pattern = counter.normalizePattern('价格是 69000 元');
      expect(pattern).toBe('价格是 {number} 元');
    });

    it('应将已知 symbol 替换为 {symbol}', () => {
      const pattern1 = counter.normalizePattern('查询比特币 69000 的支撑位');
      const pattern2 = counter.normalizePattern('查询以太坊 3500 的支撑位');
      // 两者归一化后应一致（symbol + number 都被替换）
      expect(pattern1).toBe(pattern2);
      expect(pattern1).toContain('{symbol}');
      expect(pattern1).toContain('{number}');
    });

    it('应将百分比替换为 {pct}', () => {
      const pattern = counter.normalizePattern('跌了 5% 怎么办');
      expect(pattern).toBe('跌了 {pct} 怎么办');
    });

    it('应将时间表达式替换为 {time}', () => {
      const pattern1 = counter.normalizePattern('昨天的行情分析');
      const pattern2 = counter.normalizePattern('2026-10-08 的行情分析');
      expect(pattern1).toContain('{time}');
      expect(pattern2).toContain('{time}');
      expect(pattern1).toBe(pattern2);
    });

    it('应转小写 + 去多余空格', () => {
      const pattern = counter.normalizePattern('  How  To  Configure  BSK  ');
      expect(pattern).toBe('how to configure bsk');
    });
  });

  // ============================================================
  // §3.4 沉淀门槛 N=3 + increment
  // ============================================================
  describe('increment + N=3 阈值触发 (§3.4)', () => {
    it('第 1 次模仿应计数 1 且不触发沉淀', () => {
      const result = counter.increment(
        '查询比特币 69000 的支撑位',
        ['/docs/bsk-config.md'],
        '{"steps":[]}',
      );
      expect(result.current_count).toBe(1);
      expect(result.triggered).toBe(false);
    });

    it('第 2 次同类模仿应计数 2 且不触发沉淀', () => {
      counter.increment('查询比特币 69000 的支撑位', ['/docs/a.md'], '{}');
      const result = counter.increment(
        '查询以太坊 3500 的支撑位', // 归一化后同模式
        ['/docs/b.md'],
        '{}',
      );
      expect(result.current_count).toBe(2);
      expect(result.triggered).toBe(false);
    });

    it('第 3 次同类模仿应计数 3 且触发沉淀', () => {
      counter.increment('查询比特币 69000 的支撑位', ['/a.md'], '{}');
      counter.increment('查询以太坊 3500 的支撑位', ['/b.md'], '{}');
      const result = counter.increment(
        '查询 BTC 100000 的支撑位', // 归一化后同模式
        ['/docs/c.md'],
        '{}',
      );
      expect(result.current_count).toBe(3);
      expect(result.triggered).toBe(true);
    });

    it('N 值应可通过环境变量 IMITATION_THRESHOLD 配置', () => {
      const original = process.env.IMITATION_THRESHOLD;
      process.env.IMITATION_THRESHOLD = '2';
      counter.reset();
      counter.increment('查询比特币 69000 的支撑位', ['/a.md'], '{}');
      const result = counter.increment('查询以太坊 3500 的支撑位', ['/b.md'], '{}');
      expect(result.triggered).toBe(true);
      process.env.IMITATION_THRESHOLD = original;
    });
  });

  // ============================================================
  // §6.7 M-1 修复: 循环依赖隔离边界
  // ============================================================
  describe('M-1 循环依赖隔离 (§6.7)', () => {
    it('沉淀触发后应标记 sedimentation_triggered=true 防重复触发', () => {
      counter.increment('查询比特币 69000 的支撑位', ['/a.md'], '{}');
      counter.increment('查询以太坊 3500 的支撑位', ['/b.md'], '{}');
      const result = counter.increment('查询 BTC 100000 的支撑位', ['/c.md'], '{}');
      expect(result.triggered).toBe(true);

      // 第 4 次同类 query 不应再次触发沉淀
      const result2 = counter.increment('查询 SOL 50000 的支撑位', ['/d.md'], '{}');
      expect(result2.triggered).toBe(false);
    });

    it('已沉淀归档的 pattern 不再参与后续计数', () => {
      counter.increment('查询比特币 69000 的支撑位', ['/a.md'], '{}');
      counter.increment('查询以太坊 3500 的支撑位', ['/b.md'], '{}');
      counter.increment('查询 BTC 100000 的支撑位', ['/c.md'], '{}');

      // 归档后，该 pattern 的记录应有 sedimentation_triggered=true
      const records = counter.getRecords();
      const archived = records.find(r => r.query_pattern.includes('{symbol}'));
      expect(archived?.sedimentation_triggered).toBe(true);
    });

    it('独立计数：历史不清零 (即使外部索引更新导致走路径A，计数保留)', () => {
      counter.increment('查询比特币 69000 的支撑位', ['/a.md'], '{}');
      expect(counter.getCount('查询比特币 69000 的支撑位')).toBe(1);

      // 模拟"外部索引更新后同类 query 走路径 A"——ImitationCounter 不应清零
      counter.increment('查询以太坊 3500 的支撑位', ['/b.md'], '{}');
      expect(counter.getCount('查询比特币 69000 的支撑位')).toBe(2);
    });

    it('不同 pattern 的计数互不影响', () => {
      counter.increment('查询比特币 69000 的支撑位', ['/a.md'], '{}');
      counter.increment('如何配置 bsk 认证', ['/b.md'], '{}');
      expect(counter.getCount('查询比特币 69000 的支撑位')).toBe(1);
      expect(counter.getCount('如何配置 bsk 认证')).toBe(1);
    });
  });

  // ============================================================
  // 持久化
  // ============================================================
  describe('持久化', () => {
    it('increment 后应写盘到 imitation-counter.json', () => {
      counter.increment('查询比特币 69000 的支撑位', ['/a.md'], '{}');
      const records = counter.getRecords();
      expect(records.length).toBeGreaterThan(0);
      expect(records[0].document_sources).toContain('/a.md');
      expect(records[0].first_seen).toBeGreaterThan(0);
      expect(records[0].last_seen).toBeGreaterThanOrEqual(records[0].first_seen);
    });

    it('execution_plan_examples 最多保留 3 条', () => {
      counter.increment('pattern one', ['/a.md'], 'plan1');
      counter.increment('pattern one', ['/b.md'], 'plan2');
      counter.increment('pattern one', ['/c.md'], 'plan3');
      counter.increment('pattern one', ['/d.md'], 'plan4');
      const record = counter.getRecords().find(r => r.query_pattern === 'pattern one');
      expect(record?.execution_plan_examples.length).toBeLessThanOrEqual(3);
    });
  });
});
