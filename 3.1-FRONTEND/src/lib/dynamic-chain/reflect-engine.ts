/**
 * Dynamic Chain - Reflect Engine
 *
 * 读取 graph-reflection-bridge 的 GraphReflectionState：
 * - architectureNodes 的 confidence/riskScore/issuesFound
 * - compressionSignal 的 highValueNodes / compressibleNodes
 * - dynamicChain.iteration 控制反射次数上限
 *
 * 输出 5 种决策：CONTINUE / REDO / INSERT_BEFORE / JUMP_TO / EARLY_TERMINATE
 */

import type { GraphReflectionState } from '../graph-reflection-bridge';
import type {
  DynamicChainContext,
  DynamicPlan,
  PlanStep,
  ReflectDecision,
  StepExecutionResult,
} from './types';

const MAX_ITERATIONS = 8;
const MAX_REFLECTIONS_PER_STEP = 3;

// ============================================================
// 反射决策
// ============================================================

/**
 * 执行一次反射决策（增强版 — 决策多样性优化）。
 *
 * 决策层次：
 *  1) 防御兜底（iteration/step 达上限）
 *  2) REDO：confidence < 0.55 | risk > 0.7 | issues >= 2
 *  3) INSERT_BEFORE：S3 无止损/止盈时补充数据步骤
 *  4) JUMP_TO：S3 高置信度(≥0.78) 且无 issues，跳过 S4 直接到 S5
 *  5) REDO_CONFIRM：confidence ≥ 0.80 且 issues=0 → 提升后续节点置信度（影子分）
 *  6) EARLY_TERMINATE：步骤基本完成且 avg ≥ 0.65
 *  7) CONTINUE：默认
 */
export function reflect(
  plan: DynamicPlan,
  graphState: GraphReflectionState,
  justExecuted: StepExecutionResult | null,
  ctx: DynamicChainContext,
  iteration: number,
  reflectionCountOnStep: number,
): ReflectDecision {
  // ── 防御：达上限 → CONTINUE ──────────────────────────────────────
  if (reflectionCountOnStep >= MAX_REFLECTIONS_PER_STEP || iteration >= MAX_ITERATIONS) {
    return {
      type: 'CONTINUE',
      reason: iteration >= MAX_ITERATIONS
        ? `迭代达上限 (${MAX_ITERATIONS})，强制推进`
        : `步骤反射达上限 (${MAX_REFLECTIONS_PER_STEP})，强制推进`,
    };
  }

  if (!justExecuted) {
    return { type: 'CONTINUE', reason: '首次执行，正常进入下一步' };
  }

  const justFinishedNode = graphState.architectureNodes.get(justExecuted.stepId);
  const conf = justFinishedNode?.confidence ?? justExecuted.confidence;
  const risk = justFinishedNode?.riskScore ?? justExecuted.riskScore;
  const issues = (justFinishedNode?.issuesFound?.length ?? 0) + justExecuted.issuesFound.length;

  // ── 2) REDO：置信度过低 / 风险过高 / 问题过多 ──────────────────────
  // 新阈值：confidence < 0.55（宽松版，原来 0.45 几乎无法触发）
  if (conf < 0.55 || risk > 0.70 || issues >= 2) {
    return {
      type: 'REDO',
      targetStepId: justExecuted.stepId,
      reason: conf < 0.55
        ? `confidence=${conf.toFixed(2)} < 0.55 → 重做 ${justExecuted.stepId}`
        : risk > 0.70
        ? `risk=${risk.toFixed(2)} > 0.70 → 重做 ${justExecuted.stepId}`
        : `issues=${issues} ≥ 2 → 重做 ${justExecuted.stepId}`,
    };
  }

  // ── 3) INSERT_BEFORE：S3 缺少风控设计，补数据步骤 ──────────────────
  if (justExecuted.stepId === 'S3_DESIGN') {
    const content = justExecuted.content;
    const lacksStopLoss = !/止损|stop[\s-]?loss/i.test(content);
    const lacksTakeProfit = !/止盈|take[\s-]?profit/i.test(content);
    const lacksEntry = !/入场|开仓|入场点/i.test(content);

    if (lacksStopLoss || lacksTakeProfit || lacksEntry) {
      return {
        type: 'INSERT_BEFORE',
        targetStepId: justExecuted.stepId,
        reason: `S3 缺少风控设计（止损:${lacksStopLoss}, 止盈:${lacksTakeProfit}, 入场:${lacksEntry}）→ 插入补充步骤`,
        newStep: {
          id: 'S3.5_RISK_SUPPLEMENT',
          name: 'S3.5 风控补充',
          description: '补充止损位 / 止盈位 / 仓位大小的具体量化设计',
          estimatedMs: 8000,
          credits: 15,
          tools: ['market'],
          inputs: ['S3_DESIGN'],
        },
      };
    }
  }

  // ── 4) JUMP_TO：S3 高置信度，跳过 S4 验证（阈值从 0.85 降到 0.78） ──
  if (justExecuted.stepId === 'S3_DESIGN' && conf >= 0.78 && issues <= 1 && risk < 0.5) {
    const s3Index = plan.steps.findIndex((s) => s.id === 'S3_DESIGN');
    const nextStep = plan.steps[s3Index + 1];
    if (nextStep?.id === 'S4_VALIDATE') {
      const afterS4 = plan.steps[s3Index + 2];
      return {
        type: 'JUMP_TO',
        targetStepId: afterS4?.id ?? 'S5_EXECUTE',
        reason: `S3 置信度 ${conf.toFixed(2)}（≥0.78）且 issues=${issues} ≤ 1，risk=${risk.toFixed(2)} < 0.5 → 跳过 S4 验证，直接进入 ${afterS4?.id ?? 'S5_EXECUTE'}`,
      };
    }
  }

  // ── 5) REDO_CONFIRM：极高置信度，标记为高置信确认（可用于后续决策参考） ─
  if (conf >= 0.85 && issues === 0 && risk < 0.35) {
    // 不触发 REDO，但记录为"强确认"，在 graphState 中打标记
    try {
      const node = graphState.architectureNodes.get(justExecuted.stepId);
      if (node) {
        (node as any).__strongConfirm = true;
      }
    } catch { /* ignore */ }

    // 对于强确认的 S3 → 可以 JUMP，即使置信度没达到 0.78
    if (justExecuted.stepId === 'S3_DESIGN') {
      const s3Index = plan.steps.findIndex((s) => s.id === 'S3_DESIGN');
      const nextStep = plan.steps[s3Index + 1];
      if (nextStep?.id === 'S4_VALIDATE') {
        const afterS4 = plan.steps[s3Index + 2];
        return {
          type: 'JUMP_TO',
          targetStepId: afterS4?.id ?? 'S5_EXECUTE',
          reason: `S3 强确认（conf=${conf.toFixed(2)}，issues=0，risk=${risk.toFixed(2)}）→ 跳过 S4 验证`,
        };
      }
    }
  }

  // ── 6) EARLY_TERMINATE：步骤基本完成且质量达标（阈值从 0.75 降到 0.65） ─
  const completedNodes = Array.from(graphState.architectureNodes.values()).filter(
    (n) => n.status === 'completed'
  );
  const completedCount = completedNodes.length;
  const expectedCompletions = plan.steps.filter((s) =>
    graphState.architectureNodes.has(s.id)
  ).length;

  if (completedCount >= Math.max(1, expectedCompletions - 1) && iteration >= plan.steps.length - 2) {
    const avgConf = completedCount > 0
      ? completedNodes.reduce((s, n) => s + (n.confidence ?? 0), 0) / completedCount
      : conf;

    if (avgConf >= 0.65) {
      return {
        type: 'EARLY_TERMINATE',
        reason: `完成 ${completedCount}/${expectedCompletions} 步，平均置信度 ${avgConf.toFixed(2)}（≥0.65）→ 提前结束`,
      };
    }
  }

  // ── 7) CONTINUE ──────────────────────────────────────────────────
  return {
    type: 'CONTINUE',
    reason: `正常推进：${justExecuted.stepId} conf=${conf.toFixed(2)}, risk=${risk.toFixed(2)}, issues=${issues}`,
  };
}

// ============================================================
// 工具函数
// ============================================================



// ============================================================
// 导出常量
// ============================================================

export const DYNAMIC_CHAIN_CONSTANTS = {
  MAX_ITERATIONS,
  MAX_REFLECTIONS_PER_STEP,
  // REDO 触发阈值（conf < 此值时重做）
  MIN_CONFIDENCE_TO_CONTINUE: 0.55,
  // CONTINUE 的最大风险
  MAX_RISK_TO_CONTINUE: 0.70,
  // CONTINUE 的最多问题数
  MAX_ISSUES_TO_CONTINUE: 2,
  // JUMP_TO S4 的 S3 最低置信度
  MIN_CONFIDENCE_TO_JUMP_S4: 0.78,
  // EARLY_TERMINATE 的最低平均置信度
  MIN_AVG_CONFIDENCE_TO_TERMINATE: 0.65,
  // 强确认阈值（conf >= 此值时额外触发 JUMP_TO）
  STRONG_CONFIRM_THRESHOLD: 0.85,
};

export type { ReflectDecision as ReflectDecisionExport };
