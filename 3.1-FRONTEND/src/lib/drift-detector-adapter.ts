/**
 * DriftDetectorAdapter — SPL v0.5 分布漂移检测适配层
 * ==========================================
 * SPEC-v0.5-continual-training §4.4 P1
 *
 * 适配 5 层异构数据格式 → 统一概率分布向量 → KL 散度漂移检测
 *
 * 各层数据格式:
 *   S:   intentFreq (Map<intent, count>)
 *   DSH: pathFreq   (Map<path, count>)
 *   C:   rules[]    (array of { outcome: 'success'|'partial'|'failure' })
 *   G:   graph.nodes (Map<nodeId, { edges: [] }>)
 *   LLM: promptTemplates[] (array of { usage_count })
 *
 * 各层 KL 阈值差异化:
 *   S: 0.15  DSH: 0.15  C: 0.20  G: 0.25  LLM: 0.15
 *
 * 位置: 3.1-FRONTEND/src/lib/drift-detector-adapter.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export type LayerName = 'S' | 'DSH' | 'C' | 'G' | 'LLM';

export interface AdapterDriftState {
  drift_detected: boolean;
  kl_score: number;
  layer: LayerName;
  baseline_size: number;
  window_size: number;
}

// ============================================================
// 2. 常量
// ============================================================

const LAYER_KL_THRESHOLD: Record<LayerName, number> = {
  S: 0.15,
  DSH: 0.15,
  C: 0.20,
  G: 0.25,
  LLM: 0.15,
};

const DEFAULT_WINDOW_SIZE = 50;
const EPSILON = 1e-10;

// ============================================================
// 3. DriftDetectorAdapter 主类
// ============================================================

export class DriftDetectorAdapter {
  readonly layer: LayerName;
  readonly klThreshold: number;
  private windowSize: number;

  private baselineDist: number[] = [];
  private window: number[][] = [];

  constructor(layer: string) {
    this.layer = layer as LayerName;
    this.klThreshold = LAYER_KL_THRESHOLD[this.layer];
    this.windowSize = DEFAULT_WINDOW_SIZE;
  }

  // ----------------------------------------------------------
  // 快照 → 概率分布向量
  // ----------------------------------------------------------

  /**
   * 将模型快照转换为概率分布向量
   * 各层格式不同，统一输出 number[]（归一化，sum=1）
   */
  toDistribution(snapshot: Record<string, unknown>): number[] {
    if (!snapshot || Object.keys(snapshot).length === 0) return [];

    switch (this.layer) {
      case 'S':
        return this.distFromFreqMap(snapshot.intentFreq as Record<string, number> | undefined);
      case 'DSH':
        return this.distFromFreqMap(snapshot.pathFreq as Record<string, number> | undefined);
      case 'C':
        return this.distFromRules(snapshot.rules as Array<{ outcome?: string }> | undefined);
      case 'G':
        return this.distFromGraph(snapshot.graph as { nodes?: Record<string, { edges?: unknown[] }> } | undefined);
      case 'LLM':
        return this.distFromTemplates(snapshot.promptTemplates as Array<{ usage_count?: number }> | undefined);
      default:
        return [];
    }
  }

  /** S/DSH 层: freqMap → 归一化概率向量 */
  private distFromFreqMap(freqMap: Record<string, number> | undefined): number[] {
    if (!freqMap) return [];
    const values = Object.values(freqMap);
    if (values.length === 0) return [];
    const sum = values.reduce((a, b) => a + b, 0);
    if (sum === 0) return [];
    return values.map(v => v / sum);
  }

  /** C 层: rules[].outcome → outcome 分布 */
  private distFromRules(rules: Array<{ outcome?: string }> | undefined): number[] {
    if (!rules || !Array.isArray(rules) || rules.length === 0) return [];
    const counts: Record<string, number> = {};
    for (const r of rules) {
      const outcome = r.outcome || 'unknown';
      counts[outcome] = (counts[outcome] || 0) + 1;
    }
    const values = Object.values(counts);
    const sum = values.reduce((a, b) => a + b, 0);
    if (sum === 0) return [];
    return values.map(v => v / sum);
  }

  /** G 层: graph.nodes → degree 直方图 */
  private distFromGraph(graph: { nodes?: Record<string, { edges?: unknown[] }> } | undefined): number[] {
    if (!graph || !graph.nodes) return [];
    const degreeCounts: Record<number, number> = {};
    for (const node of Object.values(graph.nodes)) {
      const degree = node?.edges ? node.edges.length : 0;
      degreeCounts[degree] = (degreeCounts[degree] || 0) + 1;
    }
    const values = Object.values(degreeCounts);
    const sum = values.reduce((a, b) => a + b, 0);
    if (sum === 0) return [];
    return values.map(v => v / sum);
  }

  /** LLM 层: promptTemplates[].usage_count → 使用频率分布 */
  private distFromTemplates(templates: Array<{ usage_count?: number }> | undefined): number[] {
    if (!templates || !Array.isArray(templates) || templates.length === 0) return [];
    const values = templates.map(t => t.usage_count || 0);
    const sum = values.reduce((a, b) => a + b, 0);
    if (sum === 0) return [];
    return values.map(v => v / sum);
  }

  // ----------------------------------------------------------
  // 基线 / 窗口管理
  // ----------------------------------------------------------

  /**
   * 设置基线分布（从模型快照转换）
   */
  setBaseline(snapshot: Record<string, any>): void {
    this.baselineDist = this.toDistribution(snapshot);
  }

  /**
   * 添加样本到滑动窗口
   */
  addSample(snapshot: Record<string, unknown>): void {
    const dist = this.toDistribution(snapshot);
    this.window.push(dist);
    if (this.window.length > this.windowSize) {
      this.window.shift();
    }
  }

  // ----------------------------------------------------------
  // KL 散度计算
  // ----------------------------------------------------------

  /**
   * KL 散度: KL(P || Q) = Σ P(x) * log(P(x) / Q(x))
   * P = baseline, Q = current
   * 零概率用 epsilon 平滑
   */
  private computeKL(p: number[], q: number[]): number {
    if (p.length === 0 || q.length === 0) return 0;
    const len = Math.max(p.length, q.length);
    let kl = 0;
    for (let i = 0; i < len; i++) {
      const px = i < p.length ? Math.max(p[i], EPSILON) : EPSILON;
      const qx = i < q.length ? Math.max(q[i], EPSILON) : EPSILON;
      kl += px * Math.log(px / qx);
    }
    return Math.max(0, kl);
  }

  // ----------------------------------------------------------
  // 漂移检测
  // ----------------------------------------------------------

  /**
   * 检测漂移: 将 snapshot 转为分布，与基线计算 KL
   * KL > klThreshold → drift_detected = true
   */
  detectDrift(snapshot: Record<string, any>): AdapterDriftState {
    const currentDist = this.toDistribution(snapshot);

    if (this.baselineDist.length === 0 || currentDist.length === 0) {
      return {
        drift_detected: false,
        kl_score: 0,
        layer: this.layer,
        baseline_size: this.baselineDist.length,
        window_size: this.window.length,
      };
    }

    const kl = this.computeKL(this.baselineDist, currentDist);

    return {
      drift_detected: kl > this.klThreshold,
      kl_score: kl,
      layer: this.layer,
      baseline_size: this.baselineDist.length,
      window_size: this.window.length,
    };
  }

  // ----------------------------------------------------------
  // 重置
  // ----------------------------------------------------------

  /**
   * 重置检测器（清空基线和窗口）
   */
  reset(): void {
    this.baselineDist = [];
    this.window = [];
  }
}
