/**
 * 52-LobeHub 协议集成 Phase 4.5 — side-A PlanCard 变体（variant）解析。
 *
 * 脑暴编排器按 `--n-per-side` 对 `/api/agent/plan` 发起 N 次调用，
 * 每次携带 `variant: { focus, seed }`；本模块把 focus 映射为提示词约束，
 * 未知/缺失 variant 一律返回 null（保持向后兼容）。
 */

export type PlanFocus = 'risk-first' | 'cost-first' | 'speed-first';

export interface PlanVariant {
  focus: PlanFocus;
  seed: number;
}

export const FOCUS_DIRECTIVES: Record<PlanFocus, string> = {
  'risk-first': '优先风险控制与可回滚：先设计失败回退与风控验证步骤，再考虑效率。',
  'cost-first': '优先最少步骤与最低 token：压缩 tool_calls，合并可合并的步骤。',
  'speed-first': '优先最短路径与并行：识别可并行步骤，减少串行等待。',
};

/** 校验并归一化请求体 variant；非法/缺省 → null（向后兼容）。 */
export function normalizeVariant(raw: unknown): PlanVariant | null {
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as { focus?: unknown; seed?: unknown };
  const focus = typeof record.focus === 'string' ? record.focus.trim() : '';
  if (!(focus in FOCUS_DIRECTIVES)) return null;
  const seed =
    typeof record.seed === 'number' && Number.isInteger(record.seed) && record.seed >= 0
      ? record.seed
      : 0;
  return { focus: focus as PlanFocus, seed };
}

/** 生成提示词中的变体约束段（空 variant → 空数组）。 */
export function buildVariantPromptSection(variant: PlanVariant | null): string[] {
  if (!variant) return [];
  return [
    `变体聚焦（${variant.focus}）：${FOCUS_DIRECTIVES[variant.focus]}`,
    `变体种子 seed=${variant.seed}：同一 seed 保持同一取舍倾向。`,
  ];
}
