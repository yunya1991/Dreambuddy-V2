/**
 * EvalLayer — SPL 评估层
 * ==========================================
 * SPEC-20261009 §4.5 P4-1
 *
 * 各层独立评估（vs Trae Code Baseline）：
 *   - S层: intent 一致率 ≥ 80%（复现）
 *   - DSH: 编辑距离比 ≤ 0.3（复现）
 *   - C层: 决策一致率 ≥ 75%（复现）
 *   - LLM: 语义相似度 ≥ 0.7（复现）
 *   - G层: 图覆盖率 ≥ 70%（复现）
 *
 * "复现"定义: 各层输出与 Baseline 的一致率 ≥ 该层阈值
 * "超越"定义: 各层输出质量 > Baseline（指标更优）
 *
 * 位置: 3.1-FRONTEND/src/lib/eval-layer.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export type LayerName = 'S' | 'DSH' | 'C' | 'LLM' | 'G';

export interface LayerEvalInput {
  metric: number;       // 该层当前指标（一致率/编辑距离比/覆盖率等）
  baseline: number;     // Trae Code Baseline 指标
}

export interface LayerEvalResult {
  layer: LayerName;
  metric: number;
  baseline: number;
  threshold: number;
  reproduced: boolean;  // 是否达到复现目标
  surpassed: boolean;   // 是否超越 Baseline
}

export interface EvalSummary {
  layer_results: LayerEvalResult[];
  all_reproduced: boolean;
  all_surpassed: boolean;
  reproduction_rate: number;   // 复现层数 / 总层数
  surpass_rate: number;        // 超越层数 / 总层数
  timestamp: number;
}

export interface EvalThresholds {
  S: number;    // intent 一致率 ≥ 0.8
  DSH: number;  // 编辑距离比 ≤ 0.3
  C: number;    // 决策一致率 ≥ 0.75
  LLM: number;  // 语义相似度 ≥ 0.7
  G: number;    // 图覆盖率 ≥ 0.7
}

// ============================================================
// 2. 常量
// ============================================================

// 各层复现阈值（SPEC §4.5，v0.3 降级为待验证目标）
const DEFAULT_THRESHOLDS: EvalThresholds = {
  S: 0.8,
  DSH: 0.3,
  C: 0.75,
  LLM: 0.7,
  G: 0.7,
};

// 各层指标方向：'higher' = 越高越好（一致率/覆盖率），'lower' = 越低越好（编辑距离比）
const METRIC_DIRECTION: Record<LayerName, 'higher' | 'lower'> = {
  S: 'higher',
  DSH: 'lower',
  C: 'higher',
  LLM: 'higher',
  G: 'higher',
};

// ============================================================
// 3. EvalLayer 主类
// ============================================================

export class EvalLayer {
  readonly thresholds: EvalThresholds;

  constructor(opts?: { thresholds?: Partial<EvalThresholds> }) {
    this.thresholds = { ...DEFAULT_THRESHOLDS, ...opts?.thresholds };
  }

  /**
   * 评估单层
   * @param layer 层名
   * @param input { metric: 当前指标, baseline: Baseline 指标 }
   * @returns LayerEvalResult
   */
  evaluateLayer(layer: LayerName, input: LayerEvalInput): LayerEvalResult {
    const threshold = this.thresholds[layer];
    const direction = METRIC_DIRECTION[layer];

    // 复现判定
    let reproduced: boolean;
    if (direction === 'higher') {
      // 越高越好: metric ≥ threshold
      reproduced = input.metric >= threshold;
    } else {
      // 越低越好: metric ≤ threshold
      reproduced = input.metric <= threshold;
    }

    // 超越判定: 当前指标优于 Baseline
    let surpassed: boolean;
    if (direction === 'higher') {
      surpassed = input.metric > input.baseline;
    } else {
      surpassed = input.metric < input.baseline;
    }

    return {
      layer,
      metric: input.metric,
      baseline: input.baseline,
      threshold,
      reproduced,
      surpassed,
    };
  }

  /**
   * 评估所有层
   * @param inputs 各层评估输入
   * @returns EvalSummary 汇总结果
   */
  evaluateAll(inputs: Partial<Record<LayerName, LayerEvalInput>>): EvalSummary {
    const allLayers: LayerName[] = ['S', 'DSH', 'C', 'LLM', 'G'];
    const layerResults: LayerEvalResult[] = [];

    for (const layer of allLayers) {
      const input = inputs[layer];
      if (input) {
        layerResults.push(this.evaluateLayer(layer, input));
      }
    }

    const reproducedCount = layerResults.filter((r) => r.reproduced).length;
    const surpassedCount = layerResults.filter((r) => r.surpassed).length;
    const total = layerResults.length;

    return {
      layer_results: layerResults,
      all_reproduced: total > 0 && reproducedCount === total,
      all_surpassed: total > 0 && surpassedCount === total,
      reproduction_rate: total > 0 ? reproducedCount / total : 0,
      surpass_rate: total > 0 ? surpassedCount / total : 0,
      timestamp: Date.now(),
    };
  }
}

// ============================================================
// 4. 单例
// ============================================================

let _instance: EvalLayer | null = null;

export function getEvalLayer(): EvalLayer {
  if (!_instance) _instance = new EvalLayer();
  return _instance;
}
