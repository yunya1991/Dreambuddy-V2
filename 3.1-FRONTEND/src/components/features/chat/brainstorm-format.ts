/**
 * Phase 4.6 — 择优脑暴结果的前端展示格式化（纯函数，便于单测）。
 *
 * 约束：路由中文名与拦截提示必须与 SPEC §7.6 五分流一致；
 * 交易执行 / 高风险必须在界面上明确提示"已拦截"。
 */

export const ROUTE_LABELS: Record<string, string> = {
  trade_deny: '交易拦截（不进辩论）',
  high_risk_human: '高风险（需人工审批）',
  debate: '择优辩论',
  workers: '单边规划（workers）',
  direct_answer: '直答（省 token）',
};

const INTERCEPT_HINTS: Record<string, string> = {
  trade_deny: '已拦截：交易执行不进辩论（铁律④）',
  high_risk_human: '已拦截：需人工审批（13 风控域）',
};

export interface BrainstormSummary {
  ok?: boolean;
  route?: string;
  skipped?: boolean;
  reason?: string | null;
  mode?: string;
  winner?: string | null;
  trace_id?: string;
  outbox_written?: number;
  error?: string;
  degraded?: boolean;
  decision?: { score?: number; kind?: string } | null;
}

/** 路由 → 中文名（未知路由回退原文）。 */
export function routeLabel(route?: string | null): string {
  if (!route) return '未知路由';
  return ROUTE_LABELS[route] ?? route;
}

/** 交易/高风险路由的拦截提示；其他路由返回 null。 */
export function interceptHint(route?: string | null): string | null {
  if (!route) return null;
  return INTERCEPT_HINTS[route] ?? null;
}

/** 脑暴摘要 → 一条助手消息文本（Markdown）。 */
export function formatBrainstormMessage(summary: BrainstormSummary): string {
  if (summary.ok === false || summary.degraded) {
    return `### 择优脑暴 · 调用降级\n\n- 错误：${summary.error ?? 'unknown'}\n- 提示：可改为常规对话继续，或稍后重试。`;
  }

  const label = routeLabel(summary.route);
  const status = summary.skipped
    ? `已跳过（${summary.reason ?? '路由拦截'}）`
    : `已执行（${summary.mode ?? 'debate'}）`;
  const score = summary.decision?.score;
  const winner = summary.winner
    ? `${summary.winner}${typeof score === 'number' ? ` · score ${score}` : ''}`
    : '无（未产出可执行方案）';
  const hint = interceptHint(summary.route);

  return [
    `### 择优脑暴 · ${label}`,
    '',
    `- 路由：${label}（${summary.route}）`,
    `- 状态：${status}`,
    `- 胜出方案：${winner}`,
    `- 蒸馏写入：${summary.outbox_written ?? 0} 条`,
    `- trace：${summary.trace_id ?? '—'}`,
    hint ? `\n> ${hint}` : '',
  ]
    .filter(Boolean)
    .join('\n');
}
