/**
 * CrossValidationGateSPL — SPL 交叉验证层
 * ==========================================
 * SPEC-20261009 §11 P0-4
 *
 * 三个组件：
 *   1. PatternAggregator — 从当前 query 提取"现在主范式" A_dim_spl
 *   2. SolutionPatternValidator — 从 TDR 提取"过去主范式" G_dim_spl
 *   3. CrossValidationGateSPL — 五步算法（交叉比对 → 质变 → 层权重调整）
 *
 * 设计原则（与交易域 §10 一致）：
 *   - 最小改动 + 可回退 + 模块化 + FAIL-OPEN
 *   - 4 开关默认全 false
 *   - 冷启动期（TDR < 200）禁用 CVG
 *
 * 位置: 3.1-FRONTEND/src/lib/cross-validation-gate-spl.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export type SPLDimension = 'code-driven' | 'ai-driven' | 'hybrid' | 'lookup' | 'research';

export interface CrossValidationResult {
  confidence_mult: number;
  shift_signal: boolean;
  divergence_count: number;
  quality_change: boolean;
  new_main_dim: SPLDimension | null;
  layer_weight_adjustment: Record<string, number>;
  retrain_trigger: boolean;
}

export interface AggregatorResult {
  dim: SPLDimension | null;
  strength: number;
}

export interface ValidatorResult {
  dim: SPLDimension | null;
  confidence: number;
}

interface TDRCase {
  actions: string[];
  outcome: string;
  quality: string;
}

// ============================================================
// 2. 维度判定关键词（§11.3）
// ============================================================

const DIMENSION_KEYWORDS: Record<SPLDimension, string[]> = {
  'code-driven': ['修改', '创建', '编辑', '实现', '删除', '重构', '部署', '安装', '配置', '编写', '提交', '修复', '更新', '编译', '运行', '测试'],
  'ai-driven': ['分析', '生成', '评估', '推理', '总结', '建议', '解释', '翻译', '摘要', '回答', '规划', '决策', '判断'],
  'hybrid': [], // 特殊：code + AI 同时存在
  'lookup': ['查询', '检索', '搜索', '查找', '读取', '获取', '列出', '浏览', '定位'],
  'research': ['调研', '研究', '验证', '对比', '审查', '探索', '实验', '文献', '综述', '同行评审'],
};

// ============================================================
// 3. PatternAggregator（§11.9 Step 1）
// ============================================================

export class PatternAggregator {
  /**
   * 从 actions 数组判定主范式维度
   * 关键词匹配 + 权重投票
   */
  aggregate(actions: string[]): AggregatorResult {
    if (!actions || actions.length === 0) {
      return { dim: null, strength: 0 };
    }

    const text = actions.join(' ');
    const scores: Record<string, number> = {
      'code-driven': 0,
      'ai-driven': 0,
      'lookup': 0,
      'research': 0,
    };

    for (const [dim, keywords] of Object.entries(DIMENSION_KEYWORDS)) {
      if (dim === 'hybrid') continue;
      for (const kw of keywords) {
        if (text.includes(kw)) {
          scores[dim] += 1;
        }
      }
    }

    const hasCode = scores['code-driven'] > 0;
    const hasAI = scores['ai-driven'] > 0;

    // hybrid: code + AI 同时存在
    if (hasCode && hasAI) {
      return {
        dim: 'hybrid',
        strength: Math.min(1.0, (scores['code-driven'] + scores['ai-driven']) / actions.length),
      };
    }

    // 找最高分维度
    let maxDim: SPLDimension | null = null;
    let maxScore = 0;
    for (const [dim, score] of Object.entries(scores)) {
      if (score > maxScore) {
        maxScore = score;
        maxDim = dim as SPLDimension;
      }
    }

    if (maxScore === 0) {
      return { dim: null, strength: 0 };
    }

    return {
      dim: maxDim,
      strength: Math.min(1.0, maxScore / actions.length),
    };
  }
}

// ============================================================
// 4. SolutionPatternValidator（§11.9 Step 2）
// ============================================================

export class SolutionPatternValidator {
  private aggregator: PatternAggregator;

  constructor() {
    this.aggregator = new PatternAggregator();
  }

  /**
   * 从 TDR 检索结果推断过去主范式
   * 多数投票 + 质量加权
   */
  validate(tdrResults: TDRCase[]): ValidatorResult {
    if (!tdrResults || tdrResults.length === 0) {
      return { dim: null, confidence: 0 };
    }

    // 质量权重
    const qw: Record<string, number> = { S: 4, A: 3, B: 2, C: 1 };

    const dimScores: Record<string, number> = {};
    let totalWeight = 0;

    for (const c of tdrResults) {
      const aggResult = this.aggregator.aggregate(c.actions);
      if (!aggResult.dim) continue;

      const weight = (qw[c.quality] || 1) * aggResult.strength;
      dimScores[aggResult.dim] = (dimScores[aggResult.dim] || 0) + weight;
      totalWeight += weight;
    }

    if (totalWeight === 0) {
      return { dim: null, confidence: 0 };
    }

    // 找最高分维度
    let maxDim: SPLDimension | null = null;
    let maxScore = 0;
    for (const [dim, score] of Object.entries(dimScores)) {
      if (score > maxScore) {
        maxScore = score;
        maxDim = dim as SPLDimension;
      }
    }

    return {
      dim: maxDim,
      confidence: totalWeight > 0 ? maxScore / totalWeight : 0,
    };
  }
}

// ============================================================
// 5. CrossValidationGateSPL（§11.9 Step 3-4）
// ============================================================

// 维度 → 层映射（§11.5 _dimToLayers）
const DIM_TO_LAYERS: Record<SPLDimension, string[]> = {
  'code-driven': ['S', 'DSH'],
  'ai-driven': ['LLM'],
  'hybrid': ['C', 'G'],
  'lookup': ['S'],
  'research': ['C'],
};

// 层权重 floor/ceiling（§11.5 Q2）
const LAYER_FLOOR = 0.5;
const LAYER_CEILING = 2.0;

export class CrossValidationGateSPL {
  readonly persistence_threshold: number;
  readonly confidence_boost: number;
  readonly confidence_penalty: number;
  readonly layer_boost_rate: number;
  readonly layer_decay_rate: number;

  private _divergence_count: number = 0;

  constructor(opts?: {
    persistence_threshold?: number;
    confidence_boost?: number;
    confidence_penalty?: number;
    layer_boost_rate?: number;
    layer_decay_rate?: number;
  }) {
    this.persistence_threshold = opts?.persistence_threshold ?? 5;
    this.confidence_boost = opts?.confidence_boost ?? 1.15;
    this.confidence_penalty = opts?.confidence_penalty ?? 0.9;
    this.layer_boost_rate = opts?.layer_boost_rate ?? 0.3;
    this.layer_decay_rate = opts?.layer_decay_rate ?? 0.2;
  }

  /**
   * §11.5 五步交叉验证算法
   *
   * @param G_dim_spl 过去主范式（来自 SolutionPatternValidator）
   * @param G_conf 过去置信度
   * @param A_dim_spl 现在主范式（来自 PatternAggregator）
   * @param A_strength 现在强度
   * @param drift_detected DriftDetector 是否检测到漂移
   */
  compare(
    G_dim_spl: SPLDimension | null,
    _G_conf: number,
    A_dim_spl: SPLDimension | null,
    _A_strength: number,
    drift_detected: boolean,
  ): CrossValidationResult {
    // FAIL-OPEN: 任一维度为 null → 中性结果
    if (G_dim_spl === null || A_dim_spl === null) {
      return this._neutralResult();
    }

    // === Step 3: 交叉比对 ===
    let confidence_mult: number;
    let shift_signal: boolean;

    if (G_dim_spl === A_dim_spl) {
      confidence_mult = this.confidence_boost;
      shift_signal = false;
      this._divergence_count = 0;
    } else {
      confidence_mult = this.confidence_penalty;
      shift_signal = true;
      this._divergence_count += 1;
    }

    // === Step 4: 质变判定（持续分歧 + 模式漂移）===
    let quality_change = false;
    let retrain_trigger = false;
    let new_main_dim: SPLDimension | null = null;

    if (this._divergence_count >= this.persistence_threshold) {
      if (drift_detected) {
        quality_change = true;
        retrain_trigger = true;
        new_main_dim = A_dim_spl;
        this._divergence_count = 0;
      }
    }

    // === Step 5: 层权重动态调整（仅分歧期间，质变前）===
    const layer_weight_adjustment: Record<string, number> = {};
    if (shift_signal && !quality_change) {
      const progress = Math.min(1.0, this._divergence_count / this.persistence_threshold);
      const A_layers = DIM_TO_LAYERS[A_dim_spl] || [];
      const G_layers = DIM_TO_LAYERS[G_dim_spl] || [];

      for (const layer of A_layers) {
        const val = 1 + this.layer_boost_rate * progress;
        layer_weight_adjustment[layer] = Math.max(LAYER_FLOOR, Math.min(LAYER_CEILING, val));
      }
      for (const layer of G_layers) {
        const val = 1 - this.layer_decay_rate * progress;
        layer_weight_adjustment[layer] = Math.max(LAYER_FLOOR, Math.min(LAYER_CEILING, val));
      }
    }

    return {
      confidence_mult,
      shift_signal,
      divergence_count: this._divergence_count,
      quality_change,
      new_main_dim,
      layer_weight_adjustment,
      retrain_trigger,
    };
  }

  private _neutralResult(): CrossValidationResult {
    return {
      confidence_mult: 1.0,
      shift_signal: false,
      divergence_count: this._divergence_count,
      quality_change: false,
      new_main_dim: null,
      layer_weight_adjustment: {},
      retrain_trigger: false,
    };
  }
}

// ============================================================
// 6. 单例 + 开关控制
// ============================================================

let _cvgInstance: CrossValidationGateSPL | null = null;
let _aggregatorInstance: PatternAggregator | null = null;
let _validatorInstance: SolutionPatternValidator | null = null;

export function getCrossValidationGateSPL(): CrossValidationGateSPL {
  if (!_cvgInstance) {
    _cvgInstance = new CrossValidationGateSPL();
  }
  return _cvgInstance;
}

export function getPatternAggregator(): PatternAggregator {
  if (!_aggregatorInstance) {
    _aggregatorInstance = new PatternAggregator();
  }
  return _aggregatorInstance;
}

export function getSolutionPatternValidator(): SolutionPatternValidator {
  if (!_validatorInstance) {
    _validatorInstance = new SolutionPatternValidator();
  }
  return _validatorInstance;
}
