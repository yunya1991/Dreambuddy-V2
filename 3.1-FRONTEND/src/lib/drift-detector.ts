/**
 * DriftDetector — SPL 分布漂移检测器
 * ==========================================
 * SPEC-20261009 §3.5 P3
 *
 * Online-LoRA 启发的漂移检测：
 *   1. 维护 codebook 索引频率的滑动窗口分布（window_size=50）
 *   2. 计算当前窗口与基线的 KL 散度
 *   3. KL 散度 > 阈值（0.15）→ 触发增量训练
 *
 * 增量训练动作：
 *   1. 重置 codebook：用最近 window_size 条数据重新聚类码字
 *   2. 更新检索参数：用 verify 历史重新调优 α/β/γ/δ/λ
 *   3. 记录漂移事件
 *
 * 非每轮训练：只在分布变化时触发训练，避免高频场景下的计算浪费。
 *
 * 位置: 3.1-FRONTEND/src/lib/drift-detector.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export interface DriftState {
  window_size: number;
  baseline_distribution: Map<string, number>;
  current_distribution: Map<string, number>;
  drift_score: number; // KL 散度
  drift_detected: boolean;
}

export type DriftActionType =
  | 'reset_codebook'
  | 'update_retrieval_params'
  | 'record_drift_event';

export interface DriftAction {
  type: DriftActionType;
  description: string;
  payload?: Record<string, unknown>;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_WINDOW_SIZE = 50;
const DEFAULT_KL_THRESHOLD = 0.15;

// ============================================================
// 3. 工具函数
// ============================================================

/**
 * 计算频率分布（Map<索引, 频率>）
 */
function computeDistribution(samples: number[][]): Map<string, number> {
  const freq = new Map<string, number>();
  let total = 0;
  for (const sample of samples) {
    for (const idx of sample) {
      const key = String(idx);
      freq.set(key, (freq.get(key) || 0) + 1);
      total++;
    }
  }
  // 归一化为概率分布
  if (total > 0) {
    for (const [k, v] of freq) {
      freq.set(k, v / total);
    }
  }
  return freq;
}

/**
 * KL 散度（Kullback-Leibler divergence）
 * KL(P || Q) = Σ P(x) * log(P(x) / Q(x))
 *
 * 处理零概率：加 epsilon 平滑
 */
function klDivergence(p: Map<string, number>, q: Map<string, number>): number {
  const epsilon = 1e-10;
  let kl = 0;

  // 获取所有键的并集
  const allKeys = new Set([...p.keys(), ...q.keys()]);

  for (const key of allKeys) {
    const px = p.get(key) || epsilon;
    const qx = q.get(key) || epsilon;
    kl += px * Math.log(px / qx);
  }

  return Math.max(0, kl); // KL 散度非负
}

// ============================================================
// 4. DriftDetector 主类
// ============================================================

export class DriftDetector {
  readonly windowSize: number;
  readonly klThreshold: number;

  private baseline: number[][] = [];
  private baselineDistribution: Map<string, number> = new Map();
  private window: number[][] = [];

  constructor(opts?: { windowSize?: number; klThreshold?: number }) {
    this.windowSize = opts?.windowSize ?? DEFAULT_WINDOW_SIZE;
    this.klThreshold = opts?.klThreshold ?? DEFAULT_KL_THRESHOLD;
  }

  /**
   * 设置基线分布
   * 用初始数据建立 codebook 索引频率基线
   */
  setBaseline(samples: number[][]): void {
    this.baseline = samples;
    this.baselineDistribution = computeDistribution(samples);
  }

  /**
   * 添加样本到滑动窗口
   * 窗口满后淘汰最旧数据
   */
  addSample(codebookIndex: number[]): void {
    this.window.push(codebookIndex);
    if (this.window.length > this.windowSize) {
      this.window.shift(); // 淘汰最旧
    }
  }

  /**
   * 获取当前窗口样本数
   */
  get windowCount(): number {
    return this.window.length;
  }

  /**
   * 计算当前窗口与基线的 KL 散度
   */
  computeKL(): number {
    if (this.window.length === 0 || this.baselineDistribution.size === 0) {
      return 0;
    }
    const currentDistribution = computeDistribution(this.window);
    return klDivergence(currentDistribution, this.baselineDistribution);
  }

  /**
   * 检测漂移
   * KL > 阈值 → drift_detected=true
   * 有数据和基线时即可检测（不强制窗口满）
   */
  detectDrift(): DriftState {
    const driftScore = this.computeKL();
    // 有数据且 KL > 阈值 → 检测到漂移
    const hasData = this.window.length > 0 && this.baselineDistribution.size > 0;
    const driftDetected = hasData && driftScore > this.klThreshold;

    return {
      window_size: this.windowSize,
      baseline_distribution: this.baselineDistribution,
      current_distribution: computeDistribution(this.window),
      drift_score: driftScore,
      drift_detected: driftDetected,
    };
  }

  /**
   * 获取漂移触发的增量训练动作
   */
  getDriftActions(): DriftAction[] {
    const state = this.detectDrift();
    if (!state.drift_detected) {
      return [];
    }

    return [
      {
        type: 'reset_codebook',
        description: '用最近 window_size 条数据重新聚类码字',
        payload: { window_size: this.windowSize },
      },
      {
        type: 'update_retrieval_params',
        description: '用 verify 历史重新调优 α/β/γ/δ/λ',
        payload: { kl_score: state.drift_score },
      },
      {
        type: 'record_drift_event',
        description: `[SPL漂移] KL=${state.drift_score.toFixed(4)}, 触发重聚类`,
        payload: { kl_score: state.drift_score },
      },
    ];
  }

  /**
   * 获取当前漂移状态
   */
  getState(): DriftState {
    return this.detectDrift();
  }

  /**
   * 重置检测器（清空窗口和基线）
   */
  reset(): void {
    this.baseline = [];
    this.baselineDistribution = new Map();
    this.window = [];
  }
}

// ============================================================
// 5. 单例
// ============================================================

let _instance: DriftDetector | null = null;

export function getDriftDetector(): DriftDetector {
  if (!_instance) _instance = new DriftDetector();
  return _instance;
}
