/**
 * C-Drive 协调器 — C 层反射 + 聚合驱动
 * ====================================
 * 在 DSHExecutionEngine 执行 SKILL 后，进行反射决策：
 *   - CONTINUE: 正常继续执行下一个 SKILL
 *   - REDO: 重新执行当前 SKILL（置信度低但可挽救）
 *   - JUMP: 跳转到其他 SKILL（预算不足/当前路径无效）
 *   - SUPPLEMENT: 插入补充 SubAgent（矛盾/缺失上下文）
 *   - DEBATE: 触发 Bull/Bear 辩论（方向分歧大）
 *
 * 设计原则（HC-2: 节点优先 + LLM 兜底, HC-8: Bull/Bear 辩论）:
 *   1. 复用 Python CDriveAgent 四步循环（不重新实现 Reflector/Aggregator 决策规则）
 *   2. 薄 IPC 包装器: 通过 dsh_adapter.py 调用 handle_c_drive_agent
 *   3. FAIL-OPEN: IPC 失败时返回 CONTINUE（不阻塞执行链）
 *   4. 认知上下文注入: intent_type 传入 C-Drive，影响 effort_level
 *
 * SPEC §3.4 要求:
 *   - Reflector 6 种决策复用（Python CDriveAgent 已封装）
 *   - INSERT_BEFORE 只能插入 SubAgent（CDriveAgent.supplement_module 限定为 8 个 SubAgent 之一）
 *
 * 位置: 3.1-FRONTEND/src/lib/c-drive.ts
 *
 * 复用（避免重复造轮子）:
 *   - Python 侧: c_drive_agent.CDriveAgent（四步循环: recall → reflect → jeval → supplement/debate）
 *   - Python 侧: c_drive_agent.handle_c_drive_agent（IPC handler）
 *   - IPC 桥接: dsh_adapter.py 'c_drive' 路由
 *   - TS 侧: callDshHandler（从 dsh-execution-engine.ts 导入）
 */

import { callDshHandler } from './dsh-execution-engine';
import type { CognitiveContext } from './cognitive-context-builder';
import type { SkillExecutionPlan } from './skill-selector';
import type { SkillResult } from './dsh-execution-engine';

// ============================================================
// 1. 类型定义（对齐 Python CDriveDecision.to_dict()）
// ============================================================

/** C-Drive 决策动作（对齐 CDriveAction enum） */
type CDriveAction = 'continue' | 'redo' | 'jump' | 'supplement' | 'debate';

/** C-Drive 决策结果（对齐 CDriveDecision dataclass） */
export interface CDriveDecision {
  action: CDriveAction;
  reason: string;
  confidence: number;
  suggestions: string[];
  // Bull/Bear 辩论结果 (HC-8)
  bull_argument: string | null;
  bear_argument: string | null;
  bull_confidence: number | null;
  bear_confidence: number | null;
  // JUMP 目标
  jump_to: string | null;
  // SUPPLEMENT 路由目标
  supplement_module: string | null;
  // jeval 结果
  jeval_noul: number | null;
  // 执行步骤追踪
  steps_executed: string[];
  // 分级 effort 级别 (light/standard/deep)
  effort_level: string;
  // Bull/Bear 多轮辩论轮次
  debate_rounds: number;
  // LLM 综合卡片
  synthesized_cards: any[];
  // SKILL 增强提示
  enhancement_hints: any[];
  // subagent 产出的图表
  charts: any[];
}

/** C-Drive 反射请求参数 */
export interface CDriveRequest {
  node_id: string;
  confidence: number;
  direction: string;
  signals: Array<{
    name: string;
    value: string;
    direction: string;
    confidence: number;
  }>;
  intent_type?: string;
}

// ============================================================
// 2. 配置
// ============================================================

const CDRIVE_CONFIG = {
  timeout_ms: 20000,  // C-Drive 可能触发 supplement + synthesize，给 20s
  // FAIL-OPEN 默认决策
  fallback_action: 'continue' as CDriveAction,
  fallback_confidence: 0.5,
};

// ============================================================
// 3. CDriveCoordinator 主类
// ============================================================

/**
 * C-Drive 协调器
 *
 * 用法:
 *   const coordinator = new CDriveCoordinator();
 *   const decision = await coordinator.reflect({
 *     node_id: 'DSH_TECHNICAL',
 *     confidence: 0.8,
 *     direction: 'LONG',
 *     signals: [{name:'EMA', value:'多头', direction:'LONG', confidence:0.85}],
 *     intent_type: 'market_query',
 *   });
 *   if (coordinator.shouldContinue(decision)) {
 *     // 继续执行下一个 SKILL
 *   }
 */
export class CDriveCoordinator {
  /**
   * 反射决策（SPEC §3.4 Reflector 复用）
   *
   * 调用 Python CDriveAgent.run() 四步循环:
   *   recall → reflect → jeval → supplement/debate
   *
   * @param request - 反射请求（node_id/confidence/direction/signals）
   * @returns CDriveDecision，IPC 失败时返回 CONTINUE（FAIL-OPEN）
   */
  async reflect(request: CDriveRequest): Promise<CDriveDecision> {
    const ipcResult = await callDshHandler(
      'c_drive',
      {
        node_id: request.node_id,
        confidence: request.confidence,
        direction: request.direction,
        signals: request.signals,
        intent_type: request.intent_type,
      },
      CDRIVE_CONFIG.timeout_ms,
    );

    // 兼容两种返回格式:
    //   - 顶层 decision (c_drive handler 原始返回 {ok:true, decision:{...}})
    //   - output.decision (理论包装格式,防御性兼容)
    if (ipcResult.ok) {
      const decision = ipcResult.output?.decision ?? (ipcResult as any).decision;
      if (decision) {
        return decision as CDriveDecision;
      }
    }

    // FAIL-OPEN: IPC 失败时返回 CONTINUE，不阻塞执行链
    return this._fallbackDecision(request, ipcResult.error || 'ipc_failed');
  }

  /**
   * 从 SkillResult 提取参数并反射决策
   *
   * @param result - DSHExecutionEngine 的 SkillResult
   * @param intent_type - 意图类型（影响 effort_level）
   */
  async decideFromResult(
    result: SkillResult,
    intent_type?: string,
  ): Promise<CDriveDecision> {
    const content = result.content || {};
    const signals = Array.isArray(content.signals) ? content.signals : [];

    return this.reflect({
      node_id: result.skill_id,
      confidence: result.confidence,
      direction: content.direction || 'NEUTRAL',
      signals: signals.map((s: any) => ({
        name: s.name || '',
        value: String(s.value || ''),
        direction: s.direction || 'NEUTRAL',
        confidence: typeof s.confidence === 'number' ? s.confidence : 0.5,
      })),
      intent_type,
    });
  }

  /**
   * 从多个 SkillResult 聚合后做整体反射决策
   *
   * 聚合策略（复用 Aggregator 方向投票 + 置信度加权）:
   *   - 取所有 SkillResult 的加权平均置信度
   *   - 方向投票: 多数胜出
   *   - 信号合并: 收集所有 signals
   *
   * @param results - DSHExecutionEngine.execute_plan 的结果
   * @param intent_type - 意图类型
   */
  async decideFromResults(
    results: SkillResult[],
    intent_type?: string,
  ): Promise<CDriveDecision> {
    if (results.length === 0) {
      return this._fallbackDecision({ node_id: 'none' } as CDriveRequest, 'empty_results');
    }

    // 聚合: 加权平均置信度 + 方向投票 + 信号合并
    const allSignals: CDriveRequest['signals'] = [];
    const directionScores: Record<string, number> = { LONG: 0, SHORT: 0, NEUTRAL: 0, HOLD: 0 };
    let totalConfidence = 0;
    let totalWeight = 0;

    for (const result of results) {
      const weight = result.confidence > 0 ? result.confidence : 0.5;
      totalWeight += weight;
      totalConfidence += result.confidence * weight;

      const direction = result.content?.direction || 'NEUTRAL';
      directionScores[direction] = (directionScores[direction] || 0) + weight;

      if (Array.isArray(result.content?.signals)) {
        allSignals.push(...result.content.signals.map((s: any) => ({
          name: s.name || '',
          value: String(s.value || ''),
          direction: s.direction || 'NEUTRAL',
          confidence: typeof s.confidence === 'number' ? s.confidence : 0.5,
        })));
      }
    }

    // 方向投票: 多数胜出
    const sortedDirections = Object.entries(directionScores)
      .sort(([, a], [, b]) => b - a);
    const consensusDirection = sortedDirections[0]?.[0] || 'NEUTRAL';
    const avgConfidence = totalWeight > 0 ? totalConfidence / totalWeight : 0.5;

    // 用第一个 skill_id 作为 node_id（C-Drive 的 SUPPLEMENT 路由会用 supplement_module）
    const primaryNodeId = results[0].skill_id;

    return this.reflect({
      node_id: primaryNodeId,
      confidence: avgConfidence,
      direction: consensusDirection,
      signals: allSignals,
      intent_type,
    });
  }

  /**
   * 判断是否继续执行下一个 SKILL
   *
   * @param decision - C-Drive 决策
   * @returns true 表示继续，false 表示停止/跳转/重做
   */
  shouldContinue(decision: CDriveDecision): boolean {
    return decision.action === 'continue';
  }

  /**
   * 判断是否需要重做当前 SKILL
   */
  shouldRedo(decision: CDriveDecision): boolean {
    return decision.action === 'redo';
  }

  /**
   * 判断是否需要跳转到其他 SKILL
   */
  shouldJump(decision: CDriveDecision): boolean {
    return decision.action === 'jump' && decision.jump_to !== null;
  }

  /**
   * 判断是否需要补充 SubAgent（SPEC §3.4: INSERT_BEFORE 只能插入 SubAgent）
   */
  shouldSupplement(decision: CDriveDecision): boolean {
    return decision.action === 'supplement' && decision.supplement_module !== null;
  }

  /**
   * 判断是否需要触发 Bull/Bear 辩论（HC-8）
   */
  shouldDebate(decision: CDriveDecision): boolean {
    return decision.action === 'debate';
  }

  // ── 内部方法 ────────────────────────────────────────

  /**
   * FAIL-OPEN 降级决策
   * IPC 失败时返回 CONTINUE，不阻塞执行链
   */
  private _fallbackDecision(request: CDriveRequest, reason: string): CDriveDecision {
    return {
      action: CDRIVE_CONFIG.fallback_action,
      reason: `C-Drive IPC 降级 (${reason})，默认 CONTINUE 不阻塞`,
      confidence: CDRIVE_CONFIG.fallback_confidence,
      suggestions: [],
      bull_argument: null,
      bear_argument: null,
      bull_confidence: null,
      bear_confidence: null,
      jump_to: null,
      supplement_module: null,
      jeval_noul: null,
      steps_executed: request.node_id ? [request.node_id] : [],
      effort_level: 'light',
      debate_rounds: 0,
      synthesized_cards: [],
      enhancement_hints: [],
      charts: [],
    };
  }
}

// ============================================================
// 4. 单例导出
// ============================================================

let _instance: CDriveCoordinator | null = null;

export function getCDriveCoordinator(): CDriveCoordinator {
  if (!_instance) _instance = new CDriveCoordinator();
  return _instance;
}
