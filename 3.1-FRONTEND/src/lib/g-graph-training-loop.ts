/**
 * GraphStructureTrainingLoop — G层图结构训练循环
 * ==========================================
 * SPEC-20261009 §4.2.4 P1-6
 * SPEC-20261011 v0.5 P0: 持续算法驱动训练 (ReplayBuffer + trainIncremental)
 *
 * 训练数据：topics.md 决策 + project_memory.md 规则
 * 训练方法：① 决策→图节点映射 ② 规则→图边映射 ③ 压缩模式学习（频繁子图→模板）
 * 触发节奏：v0.5 三层触发（微批增量 + 漂移回调 + 优先级触发）
 * 复现目标：图覆盖率 ≥ 70%
 * 依赖：独立可训练（与 S层并行）
 *
 * v0.5 变更:
 *   - bucket → ReplayBuffer（永不清空，循环覆盖）
 *   - 新增 trainIncremental()（增量训练，不清空 buffer）
 *   - 孤立节点标记不删除（weight < 0.05 标记 isolated）
 *   - 新增 checkpoint() / restore()（模型状态持久化）
 *   - 保留 train()（全量训练，向后兼容）
 *
 * 位置: 3.1-FRONTEND/src/lib/g-graph-training-loop.ts
 */

import { ReplayBuffer, type QualityLevel, LAYER_EWMA_LAMBDA, LAYER_MICRO_BATCH } from './replay-buffer';
import { DriftDetectorAdapter } from './drift-detector-adapter';
import { ModelCheckpoint, DEFAULT_PERSIST_DIR } from './model-checkpoint';

// ============================================================
// 1. 类型定义
// ============================================================

export interface GraphTrainingData {
  decisions: string[];
  rules: string[];
}

export interface GraphTrainingResult {
  trained: boolean;
  bucket_count: number;
  bucket_threshold: number;
  graph_coverage: number;
  node_count: number;
  edge_count: number;
  compression_ratio: number;
  timestamp: number;
  /** v0.5 新增: 增量训练步数 */
  incrementalStep?: number;
  /** v0.5 新增: buffer 统计 */
  bufferStats?: ReturnType<ReplayBuffer['getStats']>;
}

/** v0.5: 模型状态（用于 checkpoint/restore） */
export interface GModelState {
  nodes: string[];
  edges: string[];
  nodeWeights: Record<string, number>;
  edgeWeights: Record<string, number>;
  isolatedNodes: string[];
  step: number;
  timestamp: number;
  version: string;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 60; // SPEC v0.3: G层差异化
const CHECKPOINT_INTERVAL = 10; // 每 10 次增量训练后 checkpoint
const ISOLATED_NODE_THRESHOLD = 0.05; // v0.5: 权重低于此值标记为孤立节点

// ============================================================
// 3. GraphStructureTrainingLoop 主类
// ============================================================

export class GraphStructureTrainingLoop {
  readonly bucketThreshold: number;

  /** v0.5: ReplayBuffer 替代 bucket */
  private buffer: ReplayBuffer;

  /** v0.5: 模型状态（增量更新，不重置） */
  private _nodeWeights: Record<string, number> = {};
  private _edgeWeights: Record<string, number> = {};
  private _isolatedNodes: string[] = [];
  private _step = 0;
  private _driftFlag = false;
  private _ewmaLambda: number;

  /** v0.5 P1: 三层触发 */
  private driftAdapter: DriftDetectorAdapter;
  private checkpoint: ModelCheckpoint;
  private _microBatchSize: number;
  private _baselineSet = false;

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
    // v0.5: 创建 G 层专用 ReplayBuffer
    this.buffer = ReplayBuffer.createForLayer('G');
    this._ewmaLambda = LAYER_EWMA_LAMBDA.G;
    // v0.5 P1: 漂移检测 + 检查点
    this.driftAdapter = new DriftDetectorAdapter('G');
    this.checkpoint = new ModelCheckpoint({ persistDir: DEFAULT_PERSIST_DIR });
    this._microBatchSize = LAYER_MICRO_BATCH.G;
    // v0.5.1: 从磁盘 checkpoint 恢复模型状态（热重载/服务重启后）
    // 测试环境跳过：避免测试间状态污染
    // FAIL-OPEN: checkpoint 损坏/格式不兼容时降级为全新状态，不阻塞启动
    if (process.env.NODE_ENV !== 'test') {
      try {
        const latestCkpt = this.checkpoint.restore('G');
        if (latestCkpt) {
          this.restoreModel(latestCkpt.state as unknown as GModelState);
        }
      } catch (e) {
        console.error('[GraphStructureTrainingLoop] checkpoint restore failed, fallback to fresh state:', e);
      }
    }
  }

  /** 获取当前 buffer 中数据量（向后兼容 bucketCount） */
  get bucketCount(): number {
    return this.buffer.size;
  }

  /** v0.5: 获取 buffer 引用 */
  get replayBuffer(): ReplayBuffer {
    return this.buffer;
  }

  /** v0.5: 获取增量训练步数 */
  get step(): number {
    return this._step;
  }

  /**
   * v0.5: 添加训练数据到 buffer（支持 quality 参数）
   * 向后兼容: 不传 quality 时默认 'C'
   */
  addTrainingData(data: GraphTrainingData, quality?: QualityLevel): void {
    const q = quality || 'C';
    this.buffer.add(data, q);
    this._checkTriggers(q);
  }

  /**
   * v0.5 P1: 三层触发检查
   * ① 优先级触发: quality='S' → 立即训练
   * ② 微批触发: buffer.size % microBatchSize === 0 → 训练
   * ③ 漂移触发: KL > 阈值 → 训练
   * 冷启动守卫: buffer.size < microBatchSize → 不触发（优先级除外）
   */
  private _checkTriggers(quality: QualityLevel): void {
    // 优先级触发: quality='S' 绕过冷启动守卫
    if (quality === 'S') {
      this._triggerTrain('priority');
      return;
    }

    // 冷启动守卫
    if (this.buffer.size < this._microBatchSize) return;

    // 首次 warmup 时设置基线
    if (!this._baselineSet) {
      this.driftAdapter.setBaseline(this.getModelSnapshot());
      this._baselineSet = true;
    }

    // 微批触发: 每 N 条数据触发
    if (this.buffer.size % this._microBatchSize === 0) {
      this._triggerTrain('micro-batch');
      return;
    }

    // 漂移触发: KL > 阈值
    const driftResult = this.driftAdapter.detectDrift(this.getModelSnapshot());
    if (driftResult.drift_detected) {
      this._triggerTrain('drift');
    }
  }

  /**
   * v0.5 P1: 执行触发训练 + 检查点
   */
  private _triggerTrain(reason: 'priority' | 'micro-batch' | 'drift'): void {
    const entries = this.buffer.sample(this._microBatchSize);
    const batch = entries.map(e => e.data as GraphTrainingData);
    this.trainIncremental(batch);
    this._driftFlag = (reason === 'drift');

    // 定期检查点
    if (this._step % CHECKPOINT_INTERVAL === 0 && this._step > 0) {
      this.checkpoint.checkpoint('G', this.getModelSnapshot());
    }
  }

  /** 检查桶是否满（向后兼容） */
  shouldTrain(): boolean {
    return this.buffer.size >= this.bucketThreshold;
  }

  // ============================================================
  // v0.5 P0: trainIncremental — 增量训练（不清空 buffer）
  // ============================================================

  /**
   * SPEC v0.5 §3.3.4: G 层增量添加节点/边 + 权重衰减
   *
   * 增量策略:
   *   1. EWMA 衰减旧节点/边权重: weight *= (1-λ)
   *   2. 增量添加节点: decisions → nodeWeights[node] += λ
   *   3. 增量添加边: decisions/rules 之间建立边 → edgeWeights[edge] += λ
   *   4. 孤立节点标记（weight < 0.05 且无边连接）→ isolatedNodes（不删除）
   *   5. buffer.decayAll() — 旧数据权重衰减
   *   6. 保留模型状态，不清空
   */
  trainIncremental(batch: GraphTrainingData[]): GraphTrainingResult {
    if (batch.length === 0) {
      return this._emptyResult();
    }

    // Step 1: EWMA 衰减旧节点/边权重
    for (const node of Object.keys(this._nodeWeights)) {
      this._nodeWeights[node] *= (1 - this._ewmaLambda);
    }
    for (const edge of Object.keys(this._edgeWeights)) {
      this._edgeWeights[edge] *= (1 - this._ewmaLambda);
    }

    // Step 2-3: 增量添加节点和边
    for (const d of batch) {
      // 决策 → 节点
      for (const dec of d.decisions) {
        this._nodeWeights[dec] = (this._nodeWeights[dec] || 0) + this._ewmaLambda;
      }
      // 决策两两 → 边
      for (let i = 0; i < d.decisions.length; i++) {
        for (let j = i + 1; j < d.decisions.length; j++) {
          const edge = [d.decisions[i], d.decisions[j]].sort().join('→');
          this._edgeWeights[edge] = (this._edgeWeights[edge] || 0) + this._ewmaLambda;
        }
      }
      // 规则 → 决策 → 边
      for (const rule of d.rules) {
        this._nodeWeights[rule] = (this._nodeWeights[rule] || 0) + this._ewmaLambda;
        for (const dec of d.decisions) {
          const edge = [rule, dec].sort().join('→');
          this._edgeWeights[edge] = (this._edgeWeights[edge] || 0) + this._ewmaLambda;
        }
      }
    }

    // Step 4: 孤立节点标记（weight < 0.05 且无边连接）
    const edgeNodes = new Set<string>();
    for (const edge of Object.keys(this._edgeWeights)) {
      const [a, b] = edge.split('→');
      edgeNodes.add(a);
      edgeNodes.add(b);
    }
    for (const node of Object.keys(this._nodeWeights)) {
      if (
        this._nodeWeights[node] < ISOLATED_NODE_THRESHOLD &&
        !edgeNodes.has(node) &&
        !this._isolatedNodes.includes(node)
      ) {
        this._isolatedNodes.push(node);
      }
    }

    // Step 5: buffer 衰减（不清空）
    this.buffer.decayAll();

    // Step 6: 更新步数
    this._step++;

    const nodes = Object.keys(this._nodeWeights);
    const edges = Object.keys(this._edgeWeights);
    const connectedNodes = new Set<string>();
    for (const edge of edges) {
      const [a, b] = edge.split('→');
      connectedNodes.add(a);
      connectedNodes.add(b);
    }
    const graphCoverage = nodes.length > 0 ? connectedNodes.size / nodes.length : 0;

    return {
      trained: true,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      graph_coverage: graphCoverage,
      node_count: nodes.length,
      edge_count: edges.length,
      compression_ratio: 0, // 增量训练不重算
      timestamp: Date.now(),
      incrementalStep: this._step,
      bufferStats: this.buffer.getStats(),
    };
  }

  // ============================================================
  // v0.2 向后兼容: train — 全量训练（不清空 buffer）
  // ============================================================

  /**
   * 执行全量训练
   * v0.5 变更: 使用 buffer.getAll() 代替 bucket，训练后不清空
   * ① 决策→图节点映射（每个唯一决策是一个节点）
   * ② 规则→图边映射（规则描述两个决策的关系）
   * ③ 压缩模式学习（频繁子图→模板）
   */
  train(): GraphTrainingResult {
    const allEntries = this.buffer.getAll();
    const count = allEntries.length;

    if (count < this.bucketThreshold) {
      return this._emptyResult();
    }

    // 从 buffer entries 提取 data
    const allData: GraphTrainingData[] = allEntries.map(e => e.data);

    // Step 1: 决策→图节点映射
    const nodeSet = new Set<string>();
    for (const d of allData) {
      for (const dec of d.decisions) {
        nodeSet.add(dec);
      }
    }
    const nodes = Array.from(nodeSet);

    // Step 2: 规则→图边映射
    const edgeSet = new Set<string>();
    for (const d of allData) {
      for (let i = 0; i < d.decisions.length; i++) {
        for (let j = i + 1; j < d.decisions.length; j++) {
          const edge = [d.decisions[i], d.decisions[j]].sort().join('→');
          edgeSet.add(edge);
        }
      }
      for (const rule of d.rules) {
        for (const dec of d.decisions) {
          const edge = [rule, dec].sort().join('→');
          edgeSet.add(edge);
        }
      }
    }
    const edges = Array.from(edgeSet);

    // Step 3: 图覆盖率
    const connectedNodes = new Set<string>();
    for (const edge of edges) {
      const [a, b] = edge.split('→');
      if (nodeSet.has(a)) connectedNodes.add(a);
      if (nodeSet.has(b)) connectedNodes.add(b);
    }
    const graphCoverage = nodes.length > 0 ? connectedNodes.size / nodes.length : 0;

    // Step 4: 压缩模式学习
    const subgraphCounts: Record<string, number> = {};
    for (const d of allData) {
      if (d.decisions.length >= 2) {
        const subgraph = d.decisions.sort().join('+');
        subgraphCounts[subgraph] = (subgraphCounts[subgraph] || 0) + 1;
      }
    }
    const templates = Object.entries(subgraphCounts).filter(([, cnt]) => cnt >= 2);
    const totalSubgraphs = Object.keys(subgraphCounts).length;
    const compressionRatio = totalSubgraphs > 0 ? templates.length / totalSubgraphs : 0;

    // v0.5: 更新模型状态（不清空 buffer）
    this._nodeWeights = {};
    for (const node of nodes) this._nodeWeights[node] = 1.0;
    this._edgeWeights = {};
    for (const edge of edges) this._edgeWeights[edge] = 1.0;
    this._step++;

    // v0.5: 全量训练后也做 buffer 衰减（但不清空）
    this.buffer.decayAll();

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      graph_coverage: graphCoverage,
      node_count: nodes.length,
      edge_count: edges.length,
      compression_ratio: compressionRatio,
      timestamp: Date.now(),
      incrementalStep: this._step,
      bufferStats: this.buffer.getStats(),
    };
  }

  /** v0.5: 只重置模型状态，不清空 buffer */
  clear(): void {
    this._nodeWeights = {};
    this._edgeWeights = {};
    this._isolatedNodes = [];
  }

  // ============================================================
  // v0.5 P1: checkpoint / restore
  // ============================================================

  /** v0.5: 获取模型状态快照 */
  getModelSnapshot(): GModelState {
    return {
      nodes: Object.keys(this._nodeWeights),
      edges: Object.keys(this._edgeWeights),
      nodeWeights: { ...this._nodeWeights },
      edgeWeights: { ...this._edgeWeights },
      isolatedNodes: [...this._isolatedNodes],
      step: this._step,
      timestamp: Date.now(),
      version: 'v0.5-20261011',
    };
  }

  /** v0.5: 恢复模型状态 */
  restoreModel(state: GModelState): void {
    this._nodeWeights = { ...state.nodeWeights };
    this._edgeWeights = { ...state.edgeWeights };
    this._isolatedNodes = [...state.isolatedNodes];
    this._step = state.step;
  }

  /** v0.5: 获取 buffer 统计 */
  getBufferStats() {
    return this.buffer.getStats();
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _emptyResult(): GraphTrainingResult {
    return {
      trained: false,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      graph_coverage: 0,
      node_count: 0,
      edge_count: 0,
      compression_ratio: 0,
      timestamp: Date.now(),
    };
  }
}

// ============================================================
// 4. 单例
// ============================================================

let _instance: GraphStructureTrainingLoop | null = null;

export function getGraphStructureTrainingLoop(): GraphStructureTrainingLoop {
  if (!_instance) _instance = new GraphStructureTrainingLoop();
  return _instance;
}
