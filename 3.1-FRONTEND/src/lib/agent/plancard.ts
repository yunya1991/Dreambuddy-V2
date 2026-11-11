/**
 * 52-LobeHub 协议集成 Phase 4（R8 / 铁律⑦）— PlanCard 类型与手写校验。
 *
 * 契约唯一事实源：52-lobehub协议集成/schemas/plancard.schema.json
 * 本文件为 3.1 协议层侧的等价实现（不引三方校验依赖），与 Python 侧
 * 52-lobehub协议集成/orchestrator/plancard.py 保持同规则。
 *
 * 边界（硬约束）：PlanCard 只做规划层产物交接，不携带任何执行/交易语义；
 * plan_steps[].tool 必须形如 l0.<shell>.mcp.<tool>（47 registry 已注册工具）。
 */

export interface PlanStep {
  step: number;
  action: string;
  tool: string;
  args_hint?: Record<string, unknown>;
}

export interface PlanCostEstimate {
  tokens?: number;
  tool_calls?: number;
}

export interface PlanValidation {
  evaluator_refs: string[];
  acceptance_checks?: string[];
  /** 执行后回填 */
  outcome?: string;
}

export interface PlanDebateMeta {
  debate_id?: string;
  side?: 'A' | 'B';
  verdict?: 'WIN' | 'LOSE' | 'INCONCLUSIVE';
}

export interface PlanCard {
  id: string;
  intent: string;
  context_refs?: string[];
  plan_steps: PlanStep[];
  evidence_refs?: string[];
  risk_flags?: string[];
  cost_estimate?: PlanCostEstimate;
  expected_outcome?: string;
  validation: PlanValidation;
  debate_meta?: PlanDebateMeta;
}

export interface PlanCardValidationResult {
  ok: boolean;
  errors: string[];
}

export const PLAN_CARD_ID_PREFIX = 'pc-';
export const PLAN_CARD_INTENT_MAX = 500;
export const PLAN_CARD_OUTCOME_MAX = 1000;

/** l0.<shell>.mcp.<tool>（与 schema pattern 对齐） */
const TOOL_PATTERN = /^l0\.[a-z0-9_-]+\.mcp\.[a-z0-9_]+$/;
/** 45.<name>@<major>.<minor>.<patch>（与 schema pattern 对齐） */
const EVALUATOR_PATTERN = /^45\.[a-z0-9_]+@\d+\.\d+\.\d+$/;

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string');
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonNegativeInt(value: unknown): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

/**
 * 手写校验（与 plancard.schema.json 等价）。
 * unknown 字段容错（schema 未声明 additionalProperties=false）。
 */
export function validatePlanCard(obj: unknown): PlanCardValidationResult {
  const errors: string[] = [];

  if (!isPlainObject(obj)) {
    return { ok: false, errors: ['root_not_object'] };
  }

  // 必填：id / intent / plan_steps / validation
  const id = obj.id;
  if (typeof id !== 'string' || !id.startsWith(PLAN_CARD_ID_PREFIX)) {
    errors.push(`id_invalid_prefix:${String(id)}`);
  }

  const intent = obj.intent;
  if (typeof intent !== 'string' || intent.length === 0) {
    errors.push('intent_required');
  } else if (intent.length > PLAN_CARD_INTENT_MAX) {
    errors.push(`intent_too_long:${intent.length}>${PLAN_CARD_INTENT_MAX}`);
  }

  if (obj.context_refs !== undefined && !isStringArray(obj.context_refs)) {
    errors.push('context_refs_not_string_array');
  }
  if (obj.evidence_refs !== undefined && !isStringArray(obj.evidence_refs)) {
    errors.push('evidence_refs_not_string_array');
  }
  if (obj.risk_flags !== undefined && !isStringArray(obj.risk_flags)) {
    errors.push('risk_flags_not_string_array');
  }

  const steps = obj.plan_steps;
  if (!Array.isArray(steps) || steps.length === 0) {
    errors.push('plan_steps_empty');
  } else {
    steps.forEach((raw, index) => {
      if (!isPlainObject(raw)) {
        errors.push(`plan_steps[${index}]_not_object`);
        return;
      }
      if (typeof raw.step !== 'number' || !Number.isInteger(raw.step) || raw.step < 1) {
        errors.push(`plan_steps[${index}].step_invalid`);
      }
      if (typeof raw.action !== 'string' || raw.action.length === 0) {
        errors.push(`plan_steps[${index}].action_required`);
      }
      if (typeof raw.tool !== 'string' || !TOOL_PATTERN.test(raw.tool)) {
        errors.push(`plan_steps[${index}].tool_invalid:${String(raw.tool)}`);
      }
      if (raw.args_hint !== undefined && !isPlainObject(raw.args_hint)) {
        errors.push(`plan_steps[${index}].args_hint_not_object`);
      }
    });
  }

  if (obj.cost_estimate !== undefined) {
    if (!isPlainObject(obj.cost_estimate)) {
      errors.push('cost_estimate_not_object');
    } else {
      const { tokens, tool_calls: toolCalls } = obj.cost_estimate;
      if (tokens !== undefined && !isNonNegativeInt(tokens)) {
        errors.push('cost_estimate.tokens_invalid');
      }
      if (toolCalls !== undefined && !isNonNegativeInt(toolCalls)) {
        errors.push('cost_estimate.tool_calls_invalid');
      }
    }
  }

  if (obj.expected_outcome !== undefined) {
    if (typeof obj.expected_outcome !== 'string') {
      errors.push('expected_outcome_not_string');
    } else if (obj.expected_outcome.length > PLAN_CARD_OUTCOME_MAX) {
      errors.push(`expected_outcome_too_long:${obj.expected_outcome.length}`);
    }
  }

  const validation = obj.validation;
  if (!isPlainObject(validation)) {
    errors.push('validation_required');
  } else {
    const refs = validation.evaluator_refs;
    if (!Array.isArray(refs)) {
      errors.push('validation.evaluator_refs_not_array');
    } else {
      refs.forEach((ref, index) => {
        if (typeof ref !== 'string' || !EVALUATOR_PATTERN.test(ref)) {
          errors.push(`validation.evaluator_refs[${index}]_invalid:${String(ref)}`);
        }
      });
    }
    if (validation.acceptance_checks !== undefined && !isStringArray(validation.acceptance_checks)) {
      errors.push('validation.acceptance_checks_not_string_array');
    }
    if (validation.outcome !== undefined && typeof validation.outcome !== 'string') {
      errors.push('validation.outcome_not_string');
    }
  }

  if (obj.debate_meta !== undefined) {
    if (!isPlainObject(obj.debate_meta)) {
      errors.push('debate_meta_not_object');
    } else {
      const { debate_id: debateId, side, verdict } = obj.debate_meta;
      if (debateId !== undefined && typeof debateId !== 'string') {
        errors.push('debate_meta.debate_id_not_string');
      }
      if (side !== undefined && side !== 'A' && side !== 'B') {
        errors.push('debate_meta.side_invalid');
      }
      if (verdict !== undefined && verdict !== 'WIN' && verdict !== 'LOSE' && verdict !== 'INCONCLUSIVE') {
        errors.push('debate_meta.verdict_invalid');
      }
    }
  }

  return { ok: errors.length === 0, errors };
}

/** 生成 PlanCard id：pc-<毫秒时间戳 base36><随机后缀>（ulid-ish，单调可读，不引依赖）。 */
export function newPlanCardId(): string {
  const time = Date.now().toString(36);
  let suffix = '';
  for (let i = 0; i < 10; i += 1) {
    suffix += Math.floor(Math.random() * 36).toString(36);
  }
  return `${PLAN_CARD_ID_PREFIX}${time}${suffix}`;
}
