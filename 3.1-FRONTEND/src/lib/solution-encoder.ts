/**
 * SolutionEncoder — VQ-VAE 轻量级编码器
 * ==========================================
 * SPEC-20261009 §3.2 P0-2
 *
 * 将 (intent, actions, outcome, learned) 四元组编码为离散 codebook 索引。
 *
 * 设计（轻量级，无 GPU 依赖）：
 *   四元组文本 → 伪 embedding（hash 投影） → 量化器 → codebook 索引序列
 *
 * 量化器：
 *   - codebook 大小：256 个码字
 *   - 码字维度：512（对齐 bge-small-zh）
 *   - 初始化策略：k-means++（首批 100 条数据聚类后初始化）
 *   - 量化方式：最近邻分配 + EMA 更新（α=0.99）
 *   - 塌缩防护：码字使用率 < 1/256 → 重置为最近未分配样本
 *   - 降级：hit rate < 30% → 回退到纯 embedding + LSH 索引
 *
 * 位置: 3.1-FRONTEND/src/lib/solution-encoder.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export interface EncodeInput {
  intent: string;
  actions: string[];
  outcome_text: string;
  learned: string[];
}

export interface EncodeResult {
  codebook_index: number[];      // 4 个索引（intent/actions/outcome/learned）
  embedding: number[];           // 语义向量
  retrieval_mode: 'vq-vae' | 'lsh' | 'fallback';
}

export interface EncoderStats {
  codebook_size: number;
  initialized: boolean;
  total_encoded: number;
  hit_rate: number;
  usage_distribution: number[];  // 每个码字的使用次数
}

// ============================================================
// 2. 常量
// ============================================================

const CODEBOOK_SIZE = 256;
const EMBEDDING_DIM = 512;
const DECAY_RATE = 0.99;             // EMA α
const INIT_THRESHOLD = 100;          // k-means++ 初始化阈值
const COLLAPSE_THRESHOLD = 1 / 256;  // 码字使用率下限
const DEGRADATION_HIT_RATE = 0.3;    // 降级阈值

// ============================================================
// 3. 伪 Embedding 生成器（无 GPU 依赖的 hash 投影）
// ============================================================

/**
 * 将文本转为定长伪 embedding 向量。
 * 使用字符 n-gram + hash 投影，保证：
 *   1. 相同输入 → 相同向量
 *   2. 相似输入 → 相似向量（共享 n-gram）
 *   3. 无外部依赖（不调 Python bge 模型）
 *
 * 生产环境可替换为真实 bge-small-zh embedding。
 */
function textToEmbedding(text: string, dim: number = EMBEDDING_DIM): number[] {
  const vec = new Array(dim).fill(0);
  if (!text) return vec;

  // 字符 n-gram（2-gram + 3-gram）
  const normalized = text.toLowerCase().trim();
  const grams: string[] = [];
  for (let i = 0; i < normalized.length - 1; i++) {
    grams.push(normalized.slice(i, i + 2));
  }
  for (let i = 0; i < normalized.length - 2; i++) {
    grams.push(normalized.slice(i, i + 3));
  }
  // 词级 token 也参与
  const words = normalized.split(/\s+/);
  grams.push(...words);

  // hash 投影到 dim 维
  for (const gram of grams) {
    const hash = simpleHash(gram);
    const idx = Math.abs(hash) % dim;
    const sign = hash > 0 ? 1 : -1;
    vec[idx] += sign;
  }

  // L2 归一化
  const norm = Math.sqrt(vec.reduce((s, v) => s + v * v, 0));
  if (norm > 0) {
    for (let i = 0; i < dim; i++) {
      vec[i] /= norm;
    }
  }
  return vec;
}

function simpleHash(str: string): number {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash) + str.charCodeAt(i);
    hash = hash & hash; // 转 32bit
  }
  return hash;
}

// ============================================================
// 4. k-means++ 初始化
// ============================================================

function kmeansPlusPlusInit(samples: number[][], k: number, dim: number): number[][] {
  // k-means++ 初始化 codebook
  if (samples.length === 0) {
    return Array.from({ length: k }, () => new Array(dim).fill(0));
  }

  const codebook: number[][] = [];

  // 1. 随机选第一个中心
  const firstIdx = Math.floor(Math.random() * samples.length);
  codebook.push([...samples[firstIdx]]);

  // 2. 依次选 k-1 个中心（D2 加权抽样）
  for (let c = 1; c < k && c < samples.length; c++) {
    const distances = samples.map((s) => {
      let minDist = Infinity;
      for (const center of codebook) {
        const d = euclideanDist(s, center);
        if (d < minDist) minDist = d;
      }
      return minDist * minDist; // D²
    });

    const total = distances.reduce((a, b) => a + b, 0);
    if (total === 0) {
      // 所有样本相同，随机选
      codebook.push([...samples[Math.floor(Math.random() * samples.length)]]);
      continue;
    }

    // 加权抽样
    const r = Math.random() * total;
    let acc = 0;
    let chosen = 0;
    for (let i = 0; i < distances.length; i++) {
      acc += distances[i];
      if (acc >= r) {
        chosen = i;
        break;
      }
    }
    codebook.push([...samples[chosen]]);
  }

  // 补齐不足 k 个的情况（用随机样本填充）
  while (codebook.length < k) {
    codebook.push([...samples[Math.floor(Math.random() * samples.length)]]);
  }

  return codebook;
}

function euclideanDist(a: number[], b: number[]): number {
  let sum = 0;
  for (let i = 0; i < a.length; i++) {
    const d = a[i] - b[i];
    sum += d * d;
  }
  return Math.sqrt(sum);
}

// ============================================================
// 5. LSH 索引（降级模式）
// ============================================================

class LSHIndex {
  private tables: Map<string, number[]>[] = [];
  private numTables: number;
  private numBits: number;

  constructor(numTables: number = 4, numBits: number = 8) {
    this.numTables = numTables;
    this.numBits = numBits;
    for (let i = 0; i < numTables; i++) {
      this.tables.push(new Map());
    }
  }

  hash(vec: number[], tableIdx: number): string {
    // 简化 LSH：随机投影 + 符号 hash
    const bits: string[] = [];
    for (let b = 0; b < this.numBits; b++) {
      const seed = (tableIdx * 100 + b) % vec.length;
      const dot = vec[seed] || 0;
      bits.push(dot > 0 ? '1' : '0');
    }
    return bits.join('');
  }

  add(id: number, vec: number[]): void {
    for (let t = 0; t < this.numTables; t++) {
      const key = this.hash(vec, t);
      if (!this.tables[t].has(key)) {
        this.tables[t].set(key, []);
      }
      this.tables[t].get(key)!.push(id);
    }
  }
}

// ============================================================
// 6. SolutionEncoder 主类
// ============================================================

export class SolutionEncoder {
  readonly collapseThreshold = COLLAPSE_THRESHOLD;
  readonly degradationHitRateThreshold = DEGRADATION_HIT_RATE;

  private codebook: number[][] = [];
  private usageCount: number[] = new Array(CODEBOOK_SIZE).fill(0);
  private initialized: boolean = false;
  private totalEncoded: number = 0;
  private hitCount: number = 0;       // 最近邻分配成功（距离 < 阈值）
  private recentHitRate: number = 1.0;
  private pendingSamples: number[][] = [];
  private lshIndex: LSHIndex | null = null;
  private degraded: boolean = false;
  private forceHitRate: number | null;

  constructor(opts?: { forceHitRate?: number }) {
    this.forceHitRate = opts?.forceHitRate ?? null;
  }

  /**
   * 编码四元组 → codebook 索引 + embedding
   * @param input 四元组
   * @param train 是否执行 EMA 更新（默认 true，实时训练模式）。inference-only 时传 false。
   */
  encode(input: EncodeInput, train: boolean = true): EncodeResult {
    if (train) this.totalEncoded++;

    // 生成 4 个 embedding（intent/actions/outcome/learned 各一个）
    const embeddings = [
      textToEmbedding(input.intent),
      textToEmbedding(input.actions.join(' ')),
      textToEmbedding(input.outcome_text),
      textToEmbedding(input.learned.join(' ')),
    ];

    // 冷启动期：未初始化 codebook
    if (!this.initialized) {
      // 收集样本用于 k-means++ 初始化
      this.pendingSamples.push(...embeddings);

      if (this.pendingSamples.length >= INIT_THRESHOLD * 4) {
        this._initializeCodebook();
      }

      return {
        codebook_index: [0, 0, 0, 0],  // 冷启动占位
        embedding: embeddings[0],
        retrieval_mode: 'fallback',
      };
    }

    // 检查降级
    if (this.degraded || (this.forceHitRate !== null && this.forceHitRate < DEGRADATION_HIT_RATE)) {
      return this._encodeLSH(embeddings);
    }

    // 正常 VQ-VAE 编码
    return this._encodeVQVAE(embeddings, train);
  }

  /**
   * EMA 衰减率
   */
  getDecayRate(): number {
    return DECAY_RATE;
  }

  /**
   * 编码器统计
   */
  getStats(): EncoderStats {
    const totalUsage = this.usageCount.reduce((a, b) => a + b, 0);
    const hitRate = this.totalEncoded > 0 ? this.hitCount / this.totalEncoded : 1.0;
    return {
      codebook_size: CODEBOOK_SIZE,
      initialized: this.initialized,
      total_encoded: this.totalEncoded,
      hit_rate: this.forceHitRate ?? this.recentHitRate,
      usage_distribution: [...this.usageCount],
    };
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _initializeCodebook(): void {
    // 合并所有 pending samples 的维度
    const dim = this.pendingSamples[0]?.length || EMBEDDING_DIM;
    this.codebook = kmeansPlusPlusInit(this.pendingSamples, CODEBOOK_SIZE, dim);
    this.usageCount = new Array(CODEBOOK_SIZE).fill(0);
    this.initialized = true;
    this.pendingSamples = [];
  }

  private _encodeVQVAE(embeddings: number[][], train: boolean = true): EncodeResult {
    const indices: number[] = [];

    // Phase 1: 最近邻分配（推理阶段，只读 codebook）
    for (const emb of embeddings) {
      const idx = this._findNearest(emb);
      indices.push(idx);
      if (train) this.usageCount[idx]++;
    }

    // Phase 2: EMA 更新 + 命中统计（训练阶段，写 codebook）
    if (train) {
      for (let i = 0; i < embeddings.length; i++) {
        const idx = indices[i];
        const emb = embeddings[i];
        const dist = euclideanDist(emb, this.codebook[idx]);
        if (dist < 0.5) this.hitCount++;
        this._emaUpdate(idx, emb);
      }

      this.recentHitRate = this.totalEncoded > 0 ? this.hitCount / (this.totalEncoded * 4) : 1.0;
      this._checkCollapse();
      if (this.recentHitRate < DEGRADATION_HIT_RATE) {
        this.degraded = true;
        this.lshIndex = new LSHIndex();
      }
    }

    const mode = this.degraded ? 'lsh' : 'vq-vae';
    return {
      codebook_index: indices,
      embedding: embeddings[0],
      retrieval_mode: mode as 'vq-vae' | 'lsh',
    };
  }

  private _encodeLSH(embeddings: number[][]): EncodeResult {
    // 降级模式：返回伪 codebook 索引（用 LSH bucket hash 作为索引）
    const indices = embeddings.map((emb) => {
      // 简化：用 embedding 的 hash 取模作为伪索引
      let hash = 0;
      for (let i = 0; i < emb.length; i += 7) {
        hash = (hash * 31 + Math.round(emb[i] * 1000)) | 0;
      }
      return Math.abs(hash) % CODEBOOK_SIZE;
    });

    return {
      codebook_index: indices,
      embedding: embeddings[0],
      retrieval_mode: 'lsh',
    };
  }

  private _findNearest(vec: number[]): number {
    let minDist = Infinity;
    let nearestIdx = 0;
    for (let i = 0; i < this.codebook.length; i++) {
      const d = euclideanDist(vec, this.codebook[i]);
      if (d < minDist) {
        minDist = d;
        nearestIdx = i;
      }
    }
    return nearestIdx;
  }

  private _emaUpdate(idx: number, vec: number[]): void {
    // c_i ← α * c_i + (1 - α) * x
    const center = this.codebook[idx];
    const alpha = DECAY_RATE;
    for (let i = 0; i < center.length; i++) {
      center[i] = alpha * center[i] + (1 - alpha) * vec[i];
    }
  }

  private _checkCollapse(): void {
    const total = this.usageCount.reduce((a, b) => a + b, 0);
    if (total < CODEBOOK_SIZE * 10) return; // 数据量不足时不检测

    for (let i = 0; i < CODEBOOK_SIZE; i++) {
      const usageRate = this.usageCount[i] / total;
      if (usageRate < COLLAPSE_THRESHOLD && this.pendingSamples.length > 0) {
        // 重置为最近未分配样本
        const sample = this.pendingSamples.pop();
        if (sample) {
          this.codebook[i] = [...sample];
          this.usageCount[i] = 0;
        }
      }
    }
  }
}

// ============================================================
// 7. 单例
// ============================================================

let _instance: SolutionEncoder | null = null;

export function getSolutionEncoder(): SolutionEncoder {
  if (!_instance) {
    _instance = new SolutionEncoder();
  }
  return _instance;
}
