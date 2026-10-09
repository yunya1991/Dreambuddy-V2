/**
 * ExecutionPathTrainingLoop — DSH 执行路径训练循环
 * ==========================================
 * SPEC-20261009 §4.2.2 P2-1
 *
 * 训练数据：session_memory 中 actions 序列 + outcome
 * 训练方法：① 序列模式挖掘（频繁项集→路径模板）② 成功率加权（outcome=success 权重↑）③ 路径模板蒸馏为规则
 * 触发节奏：桶满 50 条触发
 * 复现目标：actions 编辑距离比 ≤ 0.3
 * 依赖：S层先训
 *
 * 位置: 3.1-FRONTEND/src/lib/dsh-path-training-loop.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export interface PathTrainingData {
  task: string;
  node_sequence: string[];
  outcome: 'success' | 'failure' | 'partial';
}

export interface PathTemplate {
  path: string[];
  count: number;
  success_count: number;
  success_rate: number;
  weight: number;
}

export interface PathTrainingResult {
  trained: boolean;
  bucket_count: number;
  bucket_threshold: number;
  path_templates: PathTemplate[];
  avg_path_length: number;
  success_rate: number;
  edit_distance_ratio: number;
  timestamp: number;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 50; // SPEC v0.3 DSH
const OUTCOME_WEIGHTS: Record<string, number> = {
  success: 1.0,
  partial: 0.5,
  failure: 0.1,
};

// ============================================================
// 3. 工具函数
// ============================================================

/**
 * 编辑距离（Levenshtein）
 * 用于计算路径间相似度
 */
function editDistance(a: string[], b: string[]): number {
  const m = a.length;
  const n = b.length;
  if (m === 0) return n;
  if (n === 0) return m;

  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
    }
  }
  return dp[m][n];
}

/**
 * 路径签名（用于去重和统计）
 */
function pathSignature(path: string[]): string {
  return path.join('→');
}

// ============================================================
// 4. ExecutionPathTrainingLoop 主类
// ============================================================

export class ExecutionPathTrainingLoop {
  readonly bucketThreshold: number;
  private bucket: PathTrainingData[] = [];

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
  }

  get bucketCount(): number {
    return this.bucket.length;
  }

  addTrainingData(data: PathTrainingData): void {
    this.bucket.push(data);
  }

  shouldTrain(): boolean {
    return this.bucket.length >= this.bucketThreshold;
  }

  /**
   * 执行训练
   * ① 序列模式挖掘：统计频繁路径
   * ② 成功率加权：success 路径权重↑
   * ③ 计算平均路径长度和编辑距离比
   */
  train(): PathTrainingResult {
    const count = this.bucket.length;

    if (count < this.bucketThreshold) {
      return {
        trained: false,
        bucket_count: count,
        bucket_threshold: this.bucketThreshold,
        path_templates: [],
        avg_path_length: 0,
        success_rate: 0,
        edit_distance_ratio: 1,
        timestamp: Date.now(),
      };
    }

    // Step 1: 序列模式挖掘 — 统计路径频率
    const pathStats: Record<string, { path: string[]; count: number; success_count: number; weight: number }> = {};
    let totalPathLength = 0;
    let successCount = 0;

    for (const d of this.bucket) {
      const sig = pathSignature(d.node_sequence);
      if (!pathStats[sig]) {
        pathStats[sig] = { path: d.node_sequence, count: 0, success_count: 0, weight: 0 };
      }
      pathStats[sig].count += 1;
      const outcomeWeight = OUTCOME_WEIGHTS[d.outcome] ?? 0.5;
      pathStats[sig].weight += outcomeWeight;
      if (d.outcome === 'success') {
        pathStats[sig].success_count += 1;
        successCount += 1;
      }
      totalPathLength += d.node_sequence.length;
    }

    // Step 2: 构建路径模板（按权重降序）
    const pathTemplates: PathTemplate[] = Object.values(pathStats)
      .map((s) => ({
        path: s.path,
        count: s.count,
        success_count: s.success_count,
        success_rate: s.count > 0 ? s.success_count / s.count : 0,
        weight: s.weight,
      }))
      .sort((a, b) => b.weight - a.weight);

    // Step 3: 计算指标
    const avgPathLength = count > 0 ? totalPathLength / count : 0;
    const successRate = count > 0 ? successCount / count : 0;

    // 编辑距离比：各路径与主模板（权重最高）的平均编辑距离 / 主模板长度
    let editDistanceRatio = 1;
    if (pathTemplates.length > 0) {
      const mainPath = pathTemplates[0].path;
      const mainLen = mainPath.length;
      if (mainLen > 0) {
        let totalEditDist = 0;
        for (const t of pathTemplates) {
          totalEditDist += editDistance(mainPath, t.path) * t.count;
        }
        editDistanceRatio = Math.min(1, totalEditDist / (count * mainLen));
      }
    }

    // 清空桶
    this.bucket = [];

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      path_templates: pathTemplates,
      avg_path_length: avgPathLength,
      success_rate: successRate,
      edit_distance_ratio: editDistanceRatio,
      timestamp: Date.now(),
    };
  }

  clear(): void {
    this.bucket = [];
  }
}

// ============================================================
// 5. 单例
// ============================================================

let _instance: ExecutionPathTrainingLoop | null = null;

export function getExecutionPathTrainingLoop(): ExecutionPathTrainingLoop {
  if (!_instance) _instance = new ExecutionPathTrainingLoop();
  return _instance;
}
