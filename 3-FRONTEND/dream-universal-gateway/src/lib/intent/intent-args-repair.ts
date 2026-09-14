/**
 * intent-args-repair.ts — FC 参数修复级联
 * PROP-20260828B · Phase 2（Z3 §2 管线第②级附属）
 *
 * LLM Function Calling 返回的 arguments 可能缺字段/类型错误/意图值非法。
 * 修复级联：能修则修（留审计痕迹），修不了返回 intent=null 交给规则兜底。
 * 设计目标（Z4 L1）：解析异常 = 0。
 */

import { IntentCanon, aliasToCanon } from './intent-schema';

export interface RepairOutcome {
  /** 修复后的正典意图；null = 无法修复，调用方走兜底 */
  intent: IntentCanon | null;
  confidence: number;
  entities: Record<string, string>;
  complexity: 'simple' | 'moderate' | 'complex';
  reasoning: string;
  /** 审计：本条消息触发的修复动作列表 */
  repairs: string[];
}

export function repairIntentArgs(raw: unknown): RepairOutcome {
  const repairs: string[] = [];
  const obj: Record<string, unknown> =
    raw && typeof raw === 'object' && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : (() => { repairs.push('args_not_object'); return {}; })();

  // ── intent：trim/lowercase → 别名映射 → 正典 ──
  let intent: IntentCanon | null = null;
  const rawIntent = typeof obj.intent === 'string' ? obj.intent.trim().toLowerCase() : '';
  if (!rawIntent) {
    repairs.push('intent_missing');
  } else {
    intent = aliasToCanon(rawIntent);
    if (!intent) {
      repairs.push(`intent_unknown:${rawIntent}`);
    } else if (intent !== (rawIntent as string)) {
      repairs.push(`intent_alias:${rawIntent}->${intent}`);
    }
  }

  // ── confidence：数值化 + [0,1] 钳制 ──
  let confidence = typeof obj.confidence === 'number' ? obj.confidence : NaN;
  if (Number.isNaN(confidence)) {
    confidence = 0.6;
    repairs.push('confidence_missing_default_0.6');
  } else if (confidence < 0 || confidence > 1) {
    confidence = Math.max(0, Math.min(1, confidence));
    repairs.push('confidence_clamped');
  }

  // ── entities：仅保留字符串值的键 ──
  const entities: Record<string, string> = {};
  if (obj.entities && typeof obj.entities === 'object' && !Array.isArray(obj.entities)) {
    for (const [k, v] of Object.entries(obj.entities as Record<string, unknown>)) {
      if (typeof v === 'string' && v.length > 0) entities[k] = v;
      else if (typeof v === 'number' || typeof v === 'boolean') entities[k] = String(v);
    }
  } else if (obj.entities !== undefined) {
    repairs.push('entities_not_object');
  }
  // symbol 规范化（大写）
  if (entities.symbol) entities.symbol = entities.symbol.toUpperCase();

  // ── complexity ──
  const complexity = (['simple', 'moderate', 'complex'] as const).includes(obj.complexity as never)
    ? (obj.complexity as 'simple' | 'moderate' | 'complex')
    : 'moderate';
  if (complexity !== obj.complexity) repairs.push('complexity_default');

  const reasoning = typeof obj.reasoning === 'string' ? obj.reasoning : '';

  return { intent, confidence, entities, complexity, reasoning, repairs };
}
