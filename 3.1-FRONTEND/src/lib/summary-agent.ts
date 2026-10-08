/**
 * SummaryAgent — DSH 汇总 Agent
 * ====================================
 * 汇总所有 SubAgent 结果 + C-Drive 结论 → 最终输出。
 *
 * 设计原则（SPEC §4.8）:
 *   1. 汇总 Agent 不重新执行，只做格式化（不调用 SubAgent，只调用 SynthesizerAgent）
 *   2. 复用 Python SynthesizerAgent.synthesize（LLM 综合 + 规则降级 FAIL-OPEN）
 *   3. 返回 FinalOutput: 含 intent_type / content / confidence / sources / execution_time_ms
 *   4. 置信度 ≤ 0.4 时 human_review_required = true
 *
 * 位置: 3.1-FRONTEND/src/lib/summary-agent.ts
 *
 * 复用（避免重复造轮子）:
 *   - Python 侧: synthesizer_agent.SynthesizerAgent.synthesize（LLM 综合 + 规则降级）
 *   - Python 侧: synthesizer_agent.handle_synthesizer_agent（IPC handler）
 *   - IPC 桥接: dsh_adapter.py 'synthesizer' 路由
 *   - TS 侧: callDshHandler（从 dsh-execution-engine.ts 导入）
 *   - TS 侧: SkillResult 类型（从 dsh-execution-engine.ts 导入）
 */

import { callDshHandler } from './dsh-execution-engine';
import type { CognitiveContext } from './cognitive-context-builder';
import type { SkillResult } from './dsh-execution-engine';
import type { CDriveDecision } from './c-drive';

// ============================================================
// 1. 类型定义（对齐 SPEC §4.8）
// ============================================================

/** 最终输出（SPEC §4.8 FinalOutput） */
export interface FinalOutput {
  intent_type: string;
  content: any;                          // 按意图类型结构化
  confidence: number;                     // 0.0 ~ 1.0
  sources: SourceRef[];                   // 数据来源列表
  execution_time_ms: number;
  human_review_required: boolean;         // 置信度 ≤ 0.4 时为 true
}

/** 数据来源引用（SPEC §4.8 SourceRef） */
export interface SourceRef {
  subagent_id: string;                   // 来源 SubAgent
  source_type: 'node' | 'llm' | 'mixed'; // 数据来源类型
  description: string;                   // 来源说明
}

/** SynthesizedCard（对齐 Python SynthesizedCard.to_dict()） */
interface SynthesizedCard {
  card_type: 'insight' | 'recommendation';
  title: string;
  content: string;
  signals_ref: any[];
  charts_ref: any[];
  confidence: number;
  source_modules: string[];
}

// ============================================================
// 2. 配置
// ============================================================

const SUMMARY_CONFIG = {
  timeout_ms: 20000,   // LLM 综合可能较慢，给 20s
  human_review_threshold: 0.4,  // 置信度 ≤ 0.4 触发人工复核
};

// ============================================================
// 3. SummaryAgent 主类
// ============================================================

/**
 * DSH 汇总 Agent
 *
 * 用法:
 *   const agent = new SummaryAgent();
 *   const output = await agent.summarize(
 *     'market_query',
 *     skillResults,
 *     cdriveDecision,
 *     context,
 *   );
 *   if (output.human_review_required) {
 *     // 提示用户人工复核
 *   }
 */
export class SummaryAgent {
  /**
   * 汇总所有 SubAgent 结果 + C-Drive 结论 → 最终输出
   *
   * 流程:
   *   1. 从 SkillResult[] 构造 aggregated dict（summaries/signals/consensus/confidence/modules）
   *   2. 通过 IPC 调用 Python SynthesizerAgent.synthesize（LLM 综合 + 规则降级）
   *   3. 把 SynthesizedCard[] 转换为 FinalOutput（含 sources 来源标注）
   *   4. 置信度 ≤ 0.4 时 human_review_required = true
   *
   * @param intent_type - 意图类型
   * @param subagent_results - DSHExecutionEngine.execute_plan 的结果
   * @param aggregator_conclusion - C-Drive 决策结论（可选）
   * @param context - 认知上下文（可选，用于 sources 标注）
   */
  async summarize(
    intent_type: string,
    subagent_results: SkillResult[],
    aggregator_conclusion?: CDriveDecision | null,
    context?: CognitiveContext | null,
  ): Promise<FinalOutput> {
    const startTime = Date.now();

    // ── Step 1: 构造 aggregated dict ──────────────────
    const aggregated = this._buildAggregated(subagent_results, aggregator_conclusion);

    // ── Step 2: IPC 调用 SynthesizerAgent ────────────
    const ipcResult = await callDshHandler(
      'synthesizer',
      { aggregated },
      SUMMARY_CONFIG.timeout_ms,
    );

    // ── Step 3: 构造 FinalOutput ─────────────────────
    const sources = this._buildSources(subagent_results);
    // 兼容两种返回格式:
    //   - 顶层 cards (synthesizer handler 原始返回 {ok:true, cards:[...]})
    //   - output.cards (理论包装格式,防御性兼容)
    const cards: SynthesizedCard[] = ipcResult.ok
      ? (Array.isArray(ipcResult.output?.cards)
          ? ipcResult.output.cards
          : (Array.isArray((ipcResult as any).cards) ? (ipcResult as any).cards : []))
      : [];

    // 置信度: 优先用 C-Drive 决策的置信度，否则用卡片平均，最后兜底 0.3
    const confidence = this._computeConfidence(aggregator_conclusion, cards, subagent_results);

    // 如果 SynthesizerAgent 失败（无卡片），用降级内容
    const content = cards.length > 0
      ? cards
      : this._fallbackContent(subagent_results, aggregator_conclusion, ipcResult.error);

    return {
      intent_type,
      content,
      confidence,
      sources,
      execution_time_ms: Date.now() - startTime,
      human_review_required: confidence <= SUMMARY_CONFIG.human_review_threshold,
    };
  }

  // ── 内部方法 ────────────────────────────────────────

  /**
   * 从 SkillResult[] 构造 aggregated dict
   * 对齐 Python aggregator.aggregate_subagent_outputs() 的返回值结构
   */
  private _buildAggregated(
    results: SkillResult[],
    conclusion?: CDriveDecision | null,
  ): Record<string, any> {
    const modules: string[] = [];
    const summaries: string[] = [];
    const allSignals: any[] = [];
    const allCharts: any[] = [];
    const raw_data_by_module: Record<string, any> = {};
    let long_count = 0;
    let short_count = 0;

    for (const result of results) {
      const module = result.skill_id;
      modules.push(module);

      const content = result.content || {};
      const summary = content.summary || content.direction || '无摘要';
      summaries.push(typeof summary === 'string' ? summary : JSON.stringify(summary));

      if (Array.isArray(content.signals)) {
        allSignals.push(...content.signals);
        for (const sig of content.signals) {
          if (sig.direction === 'LONG') long_count++;
          else if (sig.direction === 'SHORT') short_count++;
        }
      }
      if (Array.isArray(content.charts)) {
        allCharts.push(...content.charts);
      }
      raw_data_by_module[module] = content;
    }

    // 共识方向: 从 C-Drive 结论取，否则从信号投票
    let consensus_direction = 'neutral';
    let avg_confidence = 0.5;

    if (conclusion) {
      // C-Drive 的 synthesized_cards 可能已含共识
      consensus_direction = conclusion.action === 'supplement' ? 'neutral' : 'long';
      avg_confidence = conclusion.confidence;
    }
    if (long_count > short_count) consensus_direction = 'long';
    else if (short_count > long_count) consensus_direction = 'short';

    // top_signals: 按置信度降序取前 5
    const top_signals = [...allSignals]
      .sort((a, b) => (b.confidence || 0.5) - (a.confidence || 0.5))
      .slice(0, 5);

    // 如果有 C-Drive 的 charts，合并进来
    if (conclusion?.charts) {
      allCharts.push(...conclusion.charts);
    }

    return {
      summaries,
      all_signals: allSignals,
      all_charts: allCharts,
      modules,
      consensus_direction,
      avg_confidence,
      top_signals,
      long_count,
      short_count,
      raw_data_by_module,
    };
  }

  /**
   * 从 SkillResult[] 构造 SourceRef[]（来源标注）
   */
  private _buildSources(results: SkillResult[]): SourceRef[] {
    return results.map((r) => ({
      subagent_id: r.skill_id,
      source_type: r.source,
      description: r.content?.summary || r.content?.direction || `SubAgent ${r.skill_id}`,
    }));
  }

  /**
   * 计算最终置信度
   * 优先级: C-Drive 决策置信度 > 卡片平均置信度 > SkillResult 平均
   */
  private _computeConfidence(
    conclusion: CDriveDecision | null | undefined,
    cards: SynthesizedCard[],
    results: SkillResult[],
  ): number {
    if (conclusion && typeof conclusion.confidence === 'number') {
      return conclusion.confidence;
    }
    if (cards.length > 0) {
      const sum = cards.reduce((acc, c) => acc + (c.confidence || 0), 0);
      return sum / cards.length;
    }
    if (results.length > 0) {
      const sum = results.reduce((acc, r) => acc + (r.confidence || 0), 0);
      return sum / results.length;
    }
    return 0.3;
  }

  /**
   * FAIL-OPEN 降级内容（SynthesizerAgent IPC 失败时）
   */
  private _fallbackContent(
    results: SkillResult[],
    conclusion: CDriveDecision | null | undefined,
    error?: string,
  ): { degraded: boolean; reason: string; summaries: string[]; consensus?: string } {
    const summaries = results.map((r) => {
      const content = r.content || {};
      return `[${r.skill_id}] ${content.summary || content.direction || '无摘要'}`;
    });

    return {
      degraded: true,
      reason: `SynthesizerAgent IPC 失败 (${error || 'unknown'})，规则降级`,
      summaries,
      consensus: conclusion?.action,
    };
  }
}

// ============================================================
// 4. 单例导出
// ============================================================

let _instance: SummaryAgent | null = null;

export function getSummaryAgent(): SummaryAgent {
  if (!_instance) _instance = new SummaryAgent();
  return _instance;
}
