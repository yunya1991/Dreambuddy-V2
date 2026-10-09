/**
 * GraphStructureTrainingLoop — G层图结构训练循环
 * ==========================================
 * SPEC-20261009 §4.2.4 P1-6
 *
 * 训练数据：topics.md 决策 + project_memory.md 规则
 * 训练方法：① 决策→图节点映射 ② 规则→图边映射 ③ 压缩模式学习（频繁子图→模板）
 * 触发节奏：桶满 60 条触发（v0.3 G层差异化）
 * 复现目标：图覆盖率 ≥ 70%
 * 依赖：独立可训练（与 S层并行）
 *
 * 位置: 3.1-FRONTEND/src/lib/g-graph-training-loop.ts
 */

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
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 60; // SPEC v0.3: G层差异化

// ============================================================
// 3. GraphStructureTrainingLoop 主类
// ============================================================

export class GraphStructureTrainingLoop {
  readonly bucketThreshold: number;
  private bucket: GraphTrainingData[] = [];

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
  }

  get bucketCount(): number {
    return this.bucket.length;
  }

  addTrainingData(data: GraphTrainingData): void {
    this.bucket.push(data);
  }

  shouldTrain(): boolean {
    return this.bucket.length >= this.bucketThreshold;
  }

  /**
   * 执行训练
   * ① 决策→图节点映射（每个唯一决策是一个节点）
   * ② 规则→图边映射（规则描述两个决策的关系）
   * ③ 压缩模式学习（频繁子图→模板）
   */
  train(): GraphTrainingResult {
    const count = this.bucket.length;

    if (count < this.bucketThreshold) {
      return {
        trained: false,
        bucket_count: count,
        bucket_threshold: this.bucketThreshold,
        graph_coverage: 0,
        node_count: 0,
        edge_count: 0,
        compression_ratio: 0,
        timestamp: Date.now(),
      };
    }

    // Step 1: 决策→图节点映射
    const nodeSet = new Set<string>();
    for (const d of this.bucket) {
      for (const dec of d.decisions) {
        nodeSet.add(dec);
      }
    }
    const nodes = Array.from(nodeSet);

    // Step 2: 规则→图边映射
    // 简化：同一条训练数据中的决策之间建立边
    const edgeSet = new Set<string>();
    for (const d of this.bucket) {
      // 同一数据项中的决策两两建立边
      for (let i = 0; i < d.decisions.length; i++) {
        for (let j = i + 1; j < d.decisions.length; j++) {
          const edge = [d.decisions[i], d.decisions[j]].sort().join('→');
          edgeSet.add(edge);
        }
      }
      // 规则连接到相关决策（简化：规则→所有决策）
      for (const rule of d.rules) {
        for (const dec of d.decisions) {
          const edge = [rule, dec].sort().join('→');
          edgeSet.add(edge);
        }
      }
    }
    const edges = Array.from(edgeSet);

    // Step 3: 图覆盖率（nodes 中有边连接的节点比例）
    const connectedNodes = new Set<string>();
    for (const edge of edges) {
      const [a, b] = edge.split('→');
      if (nodeSet.has(a)) connectedNodes.add(a);
      if (nodeSet.has(b)) connectedNodes.add(b);
    }
    const graphCoverage = nodes.length > 0 ? connectedNodes.size / nodes.length : 0;

    // Step 4: 压缩模式学习（频繁子图→模板）
    // 简化：统计频繁出现的节点组合
    const subgraphCounts: Record<string, number> = {};
    for (const d of this.bucket) {
      if (d.decisions.length >= 2) {
        const subgraph = d.decisions.sort().join('+');
        subgraphCounts[subgraph] = (subgraphCounts[subgraph] || 0) + 1;
      }
    }
    // 频繁子图（出现≥2次）→ 模板
    const templates = Object.entries(subgraphCounts).filter(([, cnt]) => cnt >= 2);
    const totalSubgraphs = Object.keys(subgraphCounts).length;
    const compressionRatio = totalSubgraphs > 0 ? templates.length / totalSubgraphs : 0;

    // 清空桶
    this.bucket = [];

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      graph_coverage: graphCoverage,
      node_count: nodes.length,
      edge_count: edges.length,
      compression_ratio: compressionRatio,
      timestamp: Date.now(),
    };
  }

  clear(): void {
    this.bucket = [];
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
