/**
 * SPEC-20261011 v0.5 P0: ReplayBuffer (持续训练数据缓冲区) 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖:
 *   - ReplayBuffer 类存在性 + 可实例化
 *   - BufferEntry 接口: data/quality/weight/timestamp/age/decayedWeight
 *   - add: 添加数据 + 质量权重 + 容量淘汰
 *   - sample: 优先级采样（轮盘赌，非 Top-K）
 *   - decayAll: age++ + weight *= exp(-DECAY_RATE)
 *   - getAll: 获取全量数据
 *   - getStats: 统计信息
 *   - 各层差异化容量: S=200/DSH=300/C=200/G=500/LLM=100
 *   - 各层差异化微批量: S=5/DSH=10/C=10/G=15/LLM=5
 *   - 冷启动守卫: size=0 时不触发
 */

import {
  ReplayBuffer,
  type BufferEntry,
  type QualityLevel,
  LAYER_CAPACITY,
  LAYER_MICRO_BATCH,
} from '../replay-buffer';

describe('SPEC v0.5 P0: ReplayBuffer 持续训练数据缓冲区', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('ReplayBuffer 类应可导入且可实例化', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      expect(buf).toBeInstanceOf(ReplayBuffer);
    });

    it('BufferEntry 接口应包含必要字段', () => {
      const entry: BufferEntry = {
        data: { message: 'test', intent_type: 'query' },
        quality: 'S' as QualityLevel,
        weight: 1.0,
        timestamp: Date.now(),
        age: 0,
        decayedWeight: 1.0,
      };
      expect(entry.quality).toBe('S');
      expect(entry.weight).toBe(1.0);
      expect(entry.age).toBe(0);
    });

    it('LAYER_CAPACITY 应包含 5 层差异化容量', () => {
      expect(LAYER_CAPACITY.S).toBe(200);
      expect(LAYER_CAPACITY.DSH).toBe(300);
      expect(LAYER_CAPACITY.C).toBe(200);
      expect(LAYER_CAPACITY.G).toBe(500);
      expect(LAYER_CAPACITY.LLM).toBe(100);
    });

    it('LAYER_MICRO_BATCH 应包含 5 层差异化微批量', () => {
      expect(LAYER_MICRO_BATCH.S).toBe(5);
      expect(LAYER_MICRO_BATCH.DSH).toBe(10);
      expect(LAYER_MICRO_BATCH.C).toBe(10);
      expect(LAYER_MICRO_BATCH.G).toBe(15);
      expect(LAYER_MICRO_BATCH.LLM).toBe(5);
    });
  });

  // ----------------------------------------------------------
  // 2. add 添加数据 + 质量权重
  // ----------------------------------------------------------
  describe('add 添加数据 + 质量权重', () => {
    it('添加 S 级数据应有权重 1.0', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ message: 'test', intent_type: 'query' }, 'S');
      expect(buf.size).toBe(1);
      const all = buf.getAll();
      expect(all[0].quality).toBe('S');
      expect(all[0].weight).toBe(1.0);
    });

    it('添加 A 级数据应有权重 0.8', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ message: 'test' }, 'A');
      expect(buf.getAll()[0].weight).toBe(0.8);
    });

    it('添加 B 级数据应有权重 0.5', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ message: 'test' }, 'B');
      expect(buf.getAll()[0].weight).toBe(0.5);
    });

    it('添加 C 级数据应有权重 0.2', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ message: 'test' }, 'C');
      expect(buf.getAll()[0].weight).toBe(0.2);
    });

    it('默认质量应为 C', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ message: 'test' });
      expect(buf.getAll()[0].quality).toBe('C');
    });
  });

  // ----------------------------------------------------------
  // 3. 容量淘汰
  // ----------------------------------------------------------
  describe('容量淘汰', () => {
    it('超过 capacity 时应淘汰 age 最大 + weight 最小的条目', () => {
      const buf = new ReplayBuffer(3, 5, 0.95);
      buf.add({ msg: 'A' }, 'S');   // weight=1.0
      buf.add({ msg: 'B' }, 'C');   // weight=0.2
      buf.add({ msg: 'C' }, 'A');   // weight=0.8
      expect(buf.size).toBe(3);

      // 添加第 4 条，应淘汰最旧+最小权重（B: age最大 weight最小）
      buf.add({ msg: 'D' }, 'S');

      expect(buf.size).toBe(3); // 容量不变
      const msgs = buf.getAll().map(e => e.data.msg);
      expect(msgs).not.toContain('B'); // B 被淘汰
      expect(msgs).toContain('A');
      expect(msgs).toContain('C');
      expect(msgs).toContain('D');
    });
  });

  // ----------------------------------------------------------
  // 4. sample 优先级采样
  // ----------------------------------------------------------
  describe('sample 优先级采样（轮盘赌）', () => {
    it('应返回指定数量的样本', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      for (let i = 0; i < 20; i++) {
        buf.add({ msg: `item-${i}` }, 'C');
      }
      const batch = buf.sample(5);
      expect(batch).toHaveLength(5);
    });

    it('样本应来自 buffer 中的数据', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      for (let i = 0; i < 10; i++) {
        buf.add({ msg: `item-${i}` }, 'S');
      }
      const batch = buf.sample(3);
      for (const entry of batch) {
        expect(entry.data.msg).toMatch(/^item-\d+$/);
      }
    });

    it('S 级数据被采样概率应高于 C 级（统计验证）', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      // 10 条 S 级 + 10 条 C 级
      for (let i = 0; i < 10; i++) buf.add({ msg: `S-${i}` }, 'S');
      for (let i = 0; i < 10; i++) buf.add({ msg: `C-${i}` }, 'C');

      // 采样 1000 次，统计 S 级被选中次数
      let sCount = 0;
      let cCount = 0;
      for (let i = 0; i < 1000; i++) {
        const batch = buf.sample(1);
        if (batch[0].quality === 'S') sCount++;
        else cCount++;
      }
      // S weight=1.0, C weight=0.2 → S 概率应远高于 C
      expect(sCount).toBeGreaterThan(cCount * 2);
    });

    it('buffer 数据不足时返回全部可用数据', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ msg: 'only' }, 'S');
      const batch = buf.sample(5);
      expect(batch).toHaveLength(1);
    });
  });

  // ----------------------------------------------------------
  // 5. decayAll 衰减
  // ----------------------------------------------------------
  describe('decayAll 衰减', () => {
    it('衰减后 age 应 +1', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ msg: 'test' }, 'S');
      expect(buf.getAll()[0].age).toBe(0);

      buf.decayAll();
      expect(buf.getAll()[0].age).toBe(1);

      buf.decayAll();
      expect(buf.getAll()[0].age).toBe(2);
    });

    it('衰减后 weight 应按 exp(-DECAY_RATE) 递减', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ msg: 'test' }, 'S'); // weight=1.0
      const initialWeight = buf.getAll()[0].weight;

      buf.decayAll();
      // decayedWeight = weight * exp(-age * (1 - lambda))
      // lambda=0.95, DECAY_RATE = 1-0.95 = 0.05
      // after 1 decay: weight * exp(-1 * 0.05) = 1.0 * 0.9512... ≈ 0.9512
      const afterDecay = buf.getAll()[0].decayedWeight;
      expect(afterDecay).toBeLessThan(initialWeight);
      expect(afterDecay).toBeCloseTo(1.0 * Math.exp(-0.05), 2);
    });

    it('多次衰减后 weight 应持续递减但不为 0', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ msg: 'test' }, 'S');

      for (let i = 0; i < 10; i++) {
        buf.decayAll();
      }
      const entry = buf.getAll()[0];
      // 10 次衰减后 weight 应小于初始值但大于 0
      expect(entry.decayedWeight).toBeLessThan(1.0);
      expect(entry.decayedWeight).toBeGreaterThan(0);
    });
  });

  // ----------------------------------------------------------
  // 6. getStats 统计信息
  // ----------------------------------------------------------
  describe('getStats 统计信息', () => {
    it('应返回正确的 size 和 capacity', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      for (let i = 0; i < 10; i++) {
        buf.add({ msg: `item-${i}` }, 'C');
      }
      const stats = buf.getStats();
      expect(stats.size).toBe(10);
      expect(stats.capacity).toBe(200);
    });

    it('应返回质量分布', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ msg: '1' }, 'S');
      buf.add({ msg: '2' }, 'A');
      buf.add({ msg: '3' }, 'B');
      buf.add({ msg: '4' }, 'C');
      const stats = buf.getStats();
      expect(stats.qualityDistribution.S).toBe(1);
      expect(stats.qualityDistribution.A).toBe(1);
      expect(stats.qualityDistribution.B).toBe(1);
      expect(stats.qualityDistribution.C).toBe(1);
    });

    it('应返回 oldestAge', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      buf.add({ msg: '1' }, 'C');
      buf.add({ msg: '2' }, 'C');
      buf.decayAll();
      buf.decayAll();
      const stats = buf.getStats();
      expect(stats.oldestAge).toBe(2);
    });

    it('空 buffer 应返回零值统计', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      const stats = buf.getStats();
      expect(stats.size).toBe(0);
      expect(stats.avgWeight).toBe(0);
      expect(stats.oldestAge).toBe(0);
    });
  });

  // ----------------------------------------------------------
  // 7. 冷启动守卫
  // ----------------------------------------------------------
  describe('冷启动守卫', () => {
    it('空 buffer 的 size 应为 0', () => {
      const buf = new ReplayBuffer(200, 5, 0.95);
      expect(buf.size).toBe(0);
    });

    it('buffer.size < microBatchSize 时不应有数据可采样', () => {
      const microBatch = 5;
      const buf = new ReplayBuffer(200, microBatch, 0.95);
      // 只添加 3 条（< microBatch=5）
      buf.add({ msg: '1' }, 'C');
      buf.add({ msg: '2' }, 'C');
      buf.add({ msg: '3' }, 'C');
      expect(buf.size).toBeLessThan(microBatch);
      // sample 可以返回数据，但触发逻辑应有 warmup 守卫
      const batch = buf.sample(microBatch);
      expect(batch.length).toBe(3); // 只返回可用的
    });
  });

  // ----------------------------------------------------------
  // 8. 工厂方法: 各层差异化创建
  // ----------------------------------------------------------
  describe('工厂方法: 各层差异化创建', () => {
    it('createForLayer(S) 应创建 S 层专用 buffer', () => {
      const buf = ReplayBuffer.createForLayer('S');
      expect(buf.capacity).toBe(200);
      expect(buf.microBatchSize).toBe(5);
    });

    it('createForLayer(DSH) 应创建 DSH 层专用 buffer', () => {
      const buf = ReplayBuffer.createForLayer('DSH');
      expect(buf.capacity).toBe(300);
      expect(buf.microBatchSize).toBe(10);
    });

    it('createForLayer(G) 应创建 G 层专用 buffer', () => {
      const buf = ReplayBuffer.createForLayer('G');
      expect(buf.capacity).toBe(500);
      expect(buf.microBatchSize).toBe(15);
    });

    it('createForLayer(LLM) 应创建 LLM 层专用 buffer', () => {
      const buf = ReplayBuffer.createForLayer('LLM');
      expect(buf.capacity).toBe(100);
      expect(buf.microBatchSize).toBe(5);
    });
  });
});
