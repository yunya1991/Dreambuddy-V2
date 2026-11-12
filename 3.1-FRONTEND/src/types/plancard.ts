// ============================================
// PlanCard 运行时契约 — 52/schemas/plancard.schema.json 的 zod 镜像
// ============================================
// 单一事实源：52-lobehub协议集成/schemas/plancard.schema.json
// 本文件只做「运行时校验 + 类型推导」，不生成代码、不读 JSON 文件（route.ts 禁止 fs）。

import { z } from 'zod';

/** plan_steps[].tool 必须引用 47 registry 已注册工具：l0.<shell>.mcp.<tool> */
export const PLAN_TOOL_PATTERN = /^l0\.[a-z0-9_-]+\.mcp\.[a-z0-9_]+$/;

/** validation.evaluator_refs 形如 45.<evaluator>@<semver> */
export const EVALUATOR_REF_PATTERN = /^45\.[a-z0-9_]+@\d+\.\d+\.\d+$/;

export const planStepSchema = z.object({
  step: z.number().int().min(1),
  action: z.string().min(1),
  tool: z.string().regex(PLAN_TOOL_PATTERN, '工具名必须为 l0.<shell>.mcp.<tool>'),
  args_hint: z.record(z.unknown()).optional(),
});

export const planCardSchema = z.object({
  id: z.string().regex(/^pc-/, 'id 必须以 pc- 开头'),
  intent: z.string().min(1).max(500),
  context_refs: z.array(z.string()).optional(),
  plan_steps: z.array(planStepSchema).min(1),
  evidence_refs: z.array(z.string()).optional(),
  risk_flags: z.array(z.string()).optional(),
  cost_estimate: z
    .object({
      tokens: z.number().int().min(0).optional(),
      tool_calls: z.number().int().min(0).optional(),
    })
    .optional(),
  expected_outcome: z.string().max(1000).optional(),
  validation: z.object({
    evaluator_refs: z.array(z.string().regex(EVALUATOR_REF_PATTERN)),
    acceptance_checks: z.array(z.string()).optional(),
    outcome: z.string().optional(),
  }),
  debate_meta: z
    .object({
      debate_id: z.string().optional(),
      side: z.enum(['A', 'B']).optional(),
      verdict: z.enum(['WIN', 'LOSE', 'INCONCLUSIVE']).optional(),
    })
    .optional(),
});

/**
 * 视图层宽松 schema：仅放宽 plan_steps[].tool 的命名规范。
 * 原因：契约要求工具名“必须已注册”，但视图需要把未注册工具「标红展示」而不是整卡降级（SPEC-B §3.5）。
 * 严格契约仍以 planCardSchema 为准（批次 4 漂移校验使用它）。
 */
export const planCardViewSchema = planCardSchema.extend({
  plan_steps: z.array(planStepSchema.extend({ tool: z.string().min(1) })).min(1),
});

export type PlanCard = z.infer<typeof planCardSchema>;
export type PlanCardViewData = z.infer<typeof planCardViewSchema>;
export type PlanStep = z.infer<typeof planStepSchema>;
export type PlanCardVerdict = NonNullable<PlanCard['debate_meta']>['verdict'];

/**
 * 工具名是否为「已知工具」。
 * - 未提供 knownTools 时按 schema 的命名规范判定（格式合法即视为已注册）；
 * - 提供 knownTools 时要求精确命中注册表（用于未来接 47 registry）。
 */
export function isKnownPlanTool(tool: string, knownTools?: Iterable<string>): boolean {
  if (knownTools) {
    const set = knownTools instanceof Set ? knownTools : new Set(knownTools);
    return set.has(tool);
  }
  return PLAN_TOOL_PATTERN.test(tool);
}
