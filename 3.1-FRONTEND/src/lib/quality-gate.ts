/**
 * Quality Gate — C-Drive 数据质量评判门
 * =====================================
 * 在置信度阈值之外，增加内容质量评判维度，确保子系统输出有充足数据支撑。
 *
 * 5 维评判:
 *   D1 数据丰富度 (Critical): 是否包含具体指标值，非仅 direction+confidence
 *   D2 维度完整性 (Cosmetic): 技术面/资金面/情绪面/基本面/宏观/链上 覆盖度
 *   D3 分析深度 (Cosmetic): 是否有 analysis 过程文本
 *   D4 数据可信度 (Critical): 来源+时间戳+新鲜度+跨维度一致性
 *   D5 结构化程度 (Critical): 传给LLM的数据格式规范、字段完整
 *
 * 决策:
 *   - Critical 全部通过 + Cosmetic 加权通过 → CONTINUE
 *   - 不通过 → SUPPLEMENT 到对应 SubAgent
 *   - 超限降级 → 标注"数据不足"
 */

import type { SkillResult } from './dsh-execution-engine';

// ============================================================
// 1. 类型定义
// ============================================================

export type EffortLevel = 'light' | 'standard' | 'deep';

export interface QualityGateScores {
  D1_data_richness: number;       // 0-1
  D2_dimensional_completeness: number;  // 0-1
  D3_analytical_depth: number;    // 0-1
  D4_data_credibility: number;    // 0-1
  D5_structuredness: number;      // 0-1
}

export interface QualityGateThresholds {
  D1: number;
  D2: number;
  D3: number;
  D4: number;
  D5: number;
  cosmetic: number;  // D2*0.5 + D3*0.5 的阈值
}

export interface QualityGateResult {
  passed: boolean;
  scores: QualityGateScores;
  missing_dimensions: string[];
  supplement_targets: string[];
  reason: string;
  effort_level: EffortLevel;
  low_data_quality?: boolean;
}

interface SubsystemOutput {
  skillId: string;
  skillName: string;
  direction?: string;
  confidence: number;
  outputs: Record<string, unknown>;
  answer?: string;
}

// ============================================================
// 2. 配置
// ============================================================

const DEFAULT_THRESHOLDS: QualityGateThresholds = {
  D1: 0.50,
  D2: 0.50,
  D3: 0.30,
  D4: 0.60,
  D5: 0.40,
  cosmetic: 0.40,
};

const MAX_SUPPLEMENT_ATTEMPTS = 2;

// 6 个目标维度
const TARGET_DIMENSIONS = ['technical', 'flow', 'sentiment', 'valuation', 'macro', 'onchain'];

// 具体指标关键词（用于判断数据丰富度）
const METRIC_KEYWORDS = [
  'rsi', 'macd', 'ma', 'ema', 'boll', 'kdj', 'atr', 'volume',
  'price', 'close', 'open', 'high', 'low',
  'funding_rate', 'oi', 'long_short', 'inflow', 'outflow',
  'fear_greed', 'sentiment',
  'pe', 'pb', 'dcf', 'nav', 'mcap',
  'active_address', 'large_tx', 'gas',
];

// ============================================================
// 3. 核心评判函数
// ============================================================

/**
 * 评估子系统输出的数据质量
 *
 * @param results - 子系统输出集合
 * @param effortLevel -  effort 级别
 * @param thresholds - 阈值（可选，默认值见 DEFAULT_THRESHOLDS）
 * @returns QualityGateResult
 */
export function evaluateDataQuality(
  results: SkillResult[],
  effortLevel: EffortLevel,
  thresholds: QualityGateThresholds = DEFAULT_THRESHOLDS
): QualityGateResult {
  // light 模式直接通过
  if (effortLevel === 'light') {
    return {
      passed: true,
      scores: { D1_data_richness: 1, D2_dimensional_completeness: 1, D3_analytical_depth: 1, D4_data_credibility: 1, D5_structuredness: 1 },
      missing_dimensions: [],
      supplement_targets: [],
      reason: 'light模式跳过质量门',
      effort_level: effortLevel,
    };
  }

  const outputs = extractSubsystemOutputs(results);
  const scores = calcScores(outputs);

  // Critical 检查 (D1, D4, D5)
  const criticalPass =
    scores.D1_data_richness >= thresholds.D1 &&
    scores.D4_data_credibility >= thresholds.D4 &&
    scores.D5_structuredness >= thresholds.D5;

  // Cosmetic 加权平均 (D2, D3)
  const cosmeticScore = scores.D2_dimensional_completeness * 0.5 + scores.D3_analytical_depth * 0.5;
  const cosmeticPass = cosmeticScore >= thresholds.cosmetic;

  // standard 模式 FAIL-OPEN：只记录不阻断
  if (effortLevel === 'standard') {
    return {
      passed: true,
      scores,
      missing_dimensions: getMissingDimensions(scores, thresholds),
      supplement_targets: getSupplementTargets(scores, thresholds),
      reason: `standard模式: critical=${criticalPass}, cosmetic=${cosmeticPass}（仅记录不阻断）`,
      effort_level: effortLevel,
    };
  }

  // deep 模式：真正阻断
  const passed = criticalPass && cosmeticPass;
  return {
    passed,
    scores,
    missing_dimensions: getMissingDimensions(scores, thresholds),
    supplement_targets: passed ? [] : getSupplementTargets(scores, thresholds),
    reason: passed ? '质量门通过' : `质量门未通过: D1=${scores.D1_data_richness.toFixed(2)}, D4=${scores.D4_data_credibility.toFixed(2)}, D5=${scores.D5_structuredness.toFixed(2)}, cosmetic=${cosmeticScore.toFixed(2)}`,
    effort_level: effortLevel,
    low_data_quality: !passed,
  };
}

/**
 * 获取最大补充尝试次数
 */
export function getMaxSupplementAttempts(): number {
  return MAX_SUPPLEMENT_ATTEMPTS;
}

// ============================================================
// 4. 5 维评分计算
// ============================================================

function extractSubsystemOutputs(results: SkillResult[]): SubsystemOutput[] {
  return results.map(r => {
    const content = r.content || {};
    return {
      skillId: r.skill_id,
      skillName: content.skillName || r.skill_id,
      direction: content.direction,
      confidence: r.confidence,
      outputs: content.outputs || content,
      answer: content.answer,
    };
  });
}

function calcScores(outputs: SubsystemOutput[]): QualityGateScores {
  return {
    D1_data_richness: calcDataRichness(outputs),
    D2_dimensional_completeness: calcDimensionalCompleteness(outputs),
    D3_analytical_depth: calcAnalyticalDepth(outputs),
    D4_data_credibility: calcDataCredibility(outputs),
    D5_structuredness: calcStructuredness(outputs),
  };
}

/**
 * D1 数据丰富度: 有具体指标值的子系统占比
 */
function calcDataRichness(outputs: SubsystemOutput[]): number {
  if (outputs.length === 0) return 0;
  let withMetrics = 0;
  for (const out of outputs) {
    if (hasConcreteMetrics(out.outputs)) {
      withMetrics++;
    }
  }
  return withMetrics / outputs.length;
}

function hasConcreteMetrics(outputs: Record<string, unknown>): boolean {
  const flat = flattenOutputs(outputs);
  for (const key of Object.keys(flat)) {
    const lowerKey = key.toLowerCase();
    if (METRIC_KEYWORDS.some(kw => lowerKey.includes(kw))) {
      const val = flat[key];
      if (typeof val === 'number' || (typeof val === 'string' && val.trim() !== '')) {
        return true;
      }
    }
  }
  return false;
}

/**
 * D2 维度完整性: 已覆盖维度数 / 6
 */
function calcDimensionalCompleteness(outputs: SubsystemOutput[]): number {
  const covered = new Set<string>();
  for (const out of outputs) {
    const dim = mapSkillToDimension(out.skillId, out.skillName);
    if (dim) covered.add(dim);
  }
  return covered.size / TARGET_DIMENSIONS.length;
}

function mapSkillToDimension(skillId: string, skillName: string): string | null {
  const text = `${skillId} ${skillName}`.toLowerCase();
  if (text.includes('technical') || text.includes('技术') || text.includes('regime') || text.includes('ma') || text.includes('rsi')) return 'technical';
  if (text.includes('flow') || text.includes('资金') || text.includes('intel') || text.includes('情报')) return 'flow';
  if (text.includes('sentiment') || text.includes('情绪')) return 'sentiment';
  if (text.includes('valuation') || text.includes('估值') || text.includes('fundamental') || text.includes('基本面')) return 'valuation';
  if (text.includes('macro') || text.includes('宏观')) return 'macro';
  if (text.includes('onchain') || text.includes('链上')) return 'onchain';
  return null;
}

/**
 * D3 分析深度: 有 analysis 文本的子系统占比
 */
function calcAnalyticalDepth(outputs: SubsystemOutput[]): number {
  if (outputs.length === 0) return 0;
  let withAnalysis = 0;
  for (const out of outputs) {
    const analysis = out.outputs.analysis || out.answer;
    if (analysis && typeof analysis === 'string' && analysis.length > 20) {
      withAnalysis++;
    }
  }
  return withAnalysis / outputs.length;
}

/**
 * D4 数据可信度: 来源占比(0.4) + 新鲜度(0.3) + 一致性(0.3)
 */
function calcDataCredibility(outputs: SubsystemOutput[]): number {
  if (outputs.length === 0) return 0;

  // 来源占比
  let withSource = 0;
  for (const out of outputs) {
    if (out.outputs.source || out.outputs.timestamp || out.outputs.dataSource) {
      withSource++;
    }
  }
  const sourceRatio = withSource / outputs.length;

  // 新鲜度: 有 timestamp 且不超过30分钟 = 1.0, 有timestamp但过期 = 0.5, 无 = 0
  let freshness = 0;
  let hasTimestamp = false;
  for (const out of outputs) {
    if (out.outputs.timestamp) {
      hasTimestamp = true;
      try {
        const ts = typeof out.outputs.timestamp === 'number' ? out.outputs.timestamp : new Date(String(out.outputs.timestamp)).getTime();
        const ageMin = (Date.now() - ts) / 60000;
        if (ageMin <= 5) freshness = Math.max(freshness, 1.0);
        else if (ageMin <= 30) freshness = Math.max(freshness, 0.5);
        else freshness = Math.max(freshness, 0.0);
      } catch { freshness = Math.max(freshness, 0.3); }
    }
  }
  if (!hasTimestamp) freshness = 0.2; // 无时间戳给低分

  // 一致性: 各维度 direction 无矛盾 = 1.0
  const directions = outputs.map(o => o.direction).filter(Boolean) as string[];
  let consistency = 1.0;
  if (directions.length >= 2) {
    const uniqueDirs = new Set(directions.map(d => d.toUpperCase()));
    if (uniqueDirs.size === 1) consistency = 1.0;
    else if (uniqueDirs.size === 2 && (uniqueDirs.has('NEUTRAL') || uniqueDirs.has('HOLD'))) consistency = 0.7;
    else consistency = 0.3;
  }

  return sourceRatio * 0.4 + freshness * 0.3 + consistency * 0.3;
}

/**
 * D5 结构化程度: 结构化指标条目数 / 最低阈值(10)
 */
function calcStructuredness(outputs: SubsystemOutput[]): number {
  let metricCount = 0;
  for (const out of outputs) {
    const flat = flattenOutputs(out.outputs);
    for (const [key, val] of Object.entries(flat)) {
      if (typeof val === 'number' || (typeof val === 'string' && !isNaN(Number(val)))) {
        metricCount++;
      }
    }
  }
  return Math.min(1, metricCount / 10);
}

// ============================================================
// 5. 辅助函数
// ============================================================

function flattenOutputs(obj: Record<string, unknown>, prefix = ''): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(obj)) {
    const newKey = prefix ? `${prefix}_${key}` : key;
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      Object.assign(result, flattenOutputs(val as Record<string, unknown>, newKey));
    } else {
      result[newKey] = val;
    }
  }
  return result;
}

function getMissingDimensions(scores: QualityGateScores, thresholds: QualityGateThresholds): string[] {
  const missing: string[] = [];
  if (scores.D1_data_richness < thresholds.D1) missing.push('D1数据丰富度');
  if (scores.D2_dimensional_completeness < thresholds.D2) missing.push('D2维度完整性');
  if (scores.D3_analytical_depth < thresholds.D3) missing.push('D3分析深度');
  if (scores.D4_data_credibility < thresholds.D4) missing.push('D4数据可信度');
  if (scores.D5_structuredness < thresholds.D5) missing.push('D5结构化程度');
  return missing;
}

function getSupplementTargets(scores: QualityGateScores, thresholds: QualityGateThresholds): string[] {
  const targets: string[] = [];
  if (scores.D1_data_richness < thresholds.D1) {
    targets.push('technical', 'flow');
  }
  if (scores.D2_dimensional_completeness < thresholds.D2) {
    // 补充缺失维度（优先 technical/flow/sentiment）
    targets.push('technical', 'sentiment');
  }
  if (scores.D3_analytical_depth < thresholds.D3) {
    targets.push('technical');
  }
  if (scores.D4_data_credibility < thresholds.D4) {
    targets.push('technical');
  }
  if (scores.D5_structuredness < thresholds.D5) {
    targets.push('technical', 'flow');
  }
  return Array.from(new Set(targets));
}
