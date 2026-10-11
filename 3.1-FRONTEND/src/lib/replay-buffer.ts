/**
 * SPEC-20261011 v0.5 P0: ReplayBuffer — 持续训练数据缓冲区
 *
 * 替代传统 bucket（桶满→清空），实现:
 *   - 永不清空，循环覆盖（capacity-bounded）
 *   - 质量权重（S/A/B/C 分级）
 *   - EWMA 时间衰减（旧数据渐淡，不清除）
 *   - 优先级采样（轮盘赌，非 Top-K）
 *
 * 设计借鉴:
 *   - RLlib PrioritizedReplayBuffer (capacity + 优先级采样)
 *   - DQN Experience Replay (固定容量 + 循环覆盖)
 *   - 金融 EWMA 衰减 (旧数据权重渐淡)
 *   - River learn_one (原地更新，不清空)
 */

// ============================================================
// 类型定义
// ============================================================

export type QualityLevel = 'S' | 'A' | 'B' | 'C';

export interface BufferEntry {
  /** 原始训练数据 */
  data: any;
  /** 质量等级 */
  quality: QualityLevel;
  /** 质量权重 (S=1.0, A=0.8, B=0.5, C=0.2) */
  weight: number;
  /** 到达时间 (Date.now()) */
  timestamp: number;
  /** 在 buffer 中的训练轮次（初始0，每次 decayAll 后++） */
  age: number;
  /** 衰减后权重 = weight × exp(-age × DECAY_RATE) */
  decayedWeight: number;
}

export interface BufferStats {
  size: number;
  capacity: number;
  avgWeight: number;
  oldestAge: number;
  qualityDistribution: Record<QualityLevel, number>;
}

// ============================================================
// 各层差异化配置
// ============================================================

export const LAYER_CAPACITY: Record<string, number> = {
  S: 200,
  DSH: 300,
  C: 200,
  G: 500,
  LLM: 100,
};

export const LAYER_MICRO_BATCH: Record<string, number> = {
  S: 5,
  DSH: 10,
  C: 10,
  G: 15,
  LLM: 5,
};

/** 各层 EWMA lambda */
export const LAYER_EWMA_LAMBDA: Record<string, number> = {
  S: 0.95,
  DSH: 0.95,
  C: 0.90,
  G: 0.99,
  LLM: 0.90,
};

/** 质量等级 → 权重映射 */
const QUALITY_WEIGHTS: Record<QualityLevel, number> = {
  S: 1.0,
  A: 0.8,
  B: 0.5,
  C: 0.2,
};

// ============================================================
// ReplayBuffer 主体
// ============================================================

export class ReplayBuffer {
  private entries: BufferEntry[] = [];
  readonly capacity: number;
  readonly microBatchSize: number;
  readonly ewmaLambda: number;
  /** DECAY_RATE = 1 - ewmaLambda（评审修复 m6） */
  readonly decayRate: number;

  constructor(capacity: number, microBatchSize: number, ewmaLambda: number = 0.95) {
    this.capacity = capacity;
    this.microBatchSize = microBatchSize;
    this.ewmaLambda = ewmaLambda;
    this.decayRate = 1 - ewmaLambda;
  }

  /**
   * 工厂方法: 按层名创建差异化 buffer
   */
  static createForLayer(layer: string): ReplayBuffer {
    const cap = LAYER_CAPACITY[layer] ?? 200;
    const micro = LAYER_MICRO_BATCH[layer] ?? 5;
    const lambda = LAYER_EWMA_LAMBDA[layer] ?? 0.95;
    return new ReplayBuffer(cap, micro, lambda);
  }

  /**
   * 添加数据到 buffer
   * 超过 capacity → 淘汰 age 最大 + decayedWeight 最小的条目
   */
  add(data: any, quality: QualityLevel = 'C'): void {
    const weight = QUALITY_WEIGHTS[quality] ?? 0.2;
    const now = Date.now();

    const entry: BufferEntry = {
      data,
      quality,
      weight,
      timestamp: now,
      age: 0,
      decayedWeight: weight,
    };

    this.entries.push(entry);

    // 容量淘汰: 超过 capacity 时淘汰 age 最大 + weight 最小的
    if (this.entries.length > this.capacity) {
      // 找到淘汰候选: age 最大（最旧）的条目中 weight 最小的
      let victimIdx = 0;
      let victimScore = -Infinity; // score = age - weight（age 越大 weight 越小 → 越优先淘汰）

      for (let i = 0; i < this.entries.length; i++) {
        const e = this.entries[i];
        // 淘汰优先级: age 越大越优先 + decayedWeight 越小越优先
        const score = e.age * 2 - e.decayedWeight;
        if (score > victimScore) {
          victimScore = score;
          victimIdx = i;
        }
      }

      this.entries.splice(victimIdx, 1);
    }
  }

  /**
   * 优先级采样（轮盘赌算法）
   * 按 decayedWeight 比例随机采样 batchSize 条
   * 避免总是采样高权重，保证低权重也有机会
   */
  sample(batchSize: number): BufferEntry[] {
    const available = this.entries.length;
    if (available === 0) return [];

    const count = Math.min(batchSize, available);
    if (available <= count) {
      // 数据不足，返回全部（浅拷贝）
      return [...this.entries];
    }

    // 轮盘赌采样
    const result: BufferEntry[] = [];
    const pool = [...this.entries]; // 可选池

    for (let i = 0; i < count; i++) {
      // 计算总权重
      const totalWeight = pool.reduce((s, e) => s + e.decayedWeight, 0);
      if (totalWeight <= 0) {
        // 所有权重为 0，随机选
        const idx = Math.floor(Math.random() * pool.length);
        result.push(pool[idx]);
        pool.splice(idx, 1);
        continue;
      }

      // 轮盘赌: 随机一个 [0, totalWeight) 的值
      let r = Math.random() * totalWeight;
      let idx = 0;
      for (let j = 0; j < pool.length; j++) {
        r -= pool[j].decayedWeight;
        if (r <= 0) {
          idx = j;
          break;
        }
        idx = j;
      }

      result.push(pool[idx]);
      pool.splice(idx, 1); // 无放回采样
    }

    return result;
  }

  /**
   * 获取全量数据（用于全量重训练）
   */
  getAll(): BufferEntry[] {
    return this.entries;
  }

  /**
   * 衰减所有条目
   * 每次训练后调用: age++, decayedWeight = weight × exp(-age × DECAY_RATE)
   */
  decayAll(): void {
    for (const entry of this.entries) {
      entry.age++;
      entry.decayedWeight = entry.weight * Math.exp(-entry.age * this.decayRate);
    }
  }

  /**
   * 获取当前大小
   */
  get size(): number {
    return this.entries.length;
  }

  /**
   * 获取统计信息
   */
  getStats(): BufferStats {
    const size = this.entries.length;

    if (size === 0) {
      return {
        size: 0,
        capacity: this.capacity,
        avgWeight: 0,
        oldestAge: 0,
        qualityDistribution: { S: 0, A: 0, B: 0, C: 0 },
      };
    }

    const totalDecayedWeight = this.entries.reduce((s, e) => s + e.decayedWeight, 0);
    const maxAge = this.entries.reduce((m, e) => Math.max(m, e.age), 0);

    const dist: Record<QualityLevel, number> = { S: 0, A: 0, B: 0, C: 0 };
    for (const e of this.entries) {
      dist[e.quality]++;
    }

    return {
      size,
      capacity: this.capacity,
      avgWeight: totalDecayedWeight / size,
      oldestAge: maxAge,
      qualityDistribution: dist,
    };
  }
}
