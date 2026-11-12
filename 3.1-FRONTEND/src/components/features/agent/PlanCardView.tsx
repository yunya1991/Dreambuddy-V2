'use client';

// ============================================
// PlanCardView — 单一事实源驱动的方案卡片视图（SPEC-20261111-B §3.5）
// ============================================
// 契约来源：52-lobehub协议集成/schemas/plancard.schema.json（zod 镜像见 types/plancard.ts）。
// 非法数据不白屏：zod 校验失败 → JSON 折叠降级（SPEC B R-B3）。

import React, { useEffect, useState } from 'react';
import { IconCopy } from '@/components';
import { isKnownPlanTool, planCardViewSchema, type PlanCardVerdict } from '@/types/plancard';

const VERDICT_META: Record<NonNullable<PlanCardVerdict>, { label: string; tone: string }> = {
  WIN: { label: '胜出', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  LOSE: { label: '落败', tone: 'bg-red-500/15 text-red-300 border-red-500/40' },
  INCONCLUSIVE: { label: '未决', tone: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
};

interface PlanCardViewProps {
  /** 原始卡片数据（未校验，视图内部做 zod 校验） */
  card: unknown;
  /** 可选：注册表工具清单；缺省时按 schema 命名规范判定 */
  knownTools?: Iterable<string>;
}

export function PlanCardView({ card, knownTools }: PlanCardViewProps) {
  const parsed = planCardViewSchema.safeParse(card);
  const [copiedRef, setCopiedRef] = useState<string | null>(null);

  useEffect(() => {
    if (!parsed.success) {
      console.warn('[PlanCardView] 非法 PlanCard，降级为 JSON 折叠：', parsed.error.issues);
    }
  }, [parsed.success]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!parsed.success) {
    return (
      <details
        data-testid="plan-card-fallback"
        className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-200"
      >
        <summary className="cursor-pointer">PlanCard 数据不符合契约（点击查看原始 JSON）</summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] text-slate-300">
          {safeStringify(card)}
        </pre>
      </details>
    );
  }

  const data = parsed.data;
  const verdict = data.debate_meta?.verdict;
  const verdictMeta = verdict ? VERDICT_META[verdict] : null;

  async function copyRef(ref: string) {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(ref);
      setCopiedRef(ref);
      setTimeout(() => setCopiedRef((v) => (v === ref ? null : v)), 1500);
    } catch {
      /* 复制失败静默：P0 只做文本展示 */
    }
  }

  return (
    <div data-testid="plan-card" className="rounded-lg border border-indigo-500/30 bg-slate-900/60 text-xs">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-700/60 px-3 py-2">
        <span className="font-mono text-[11px] text-slate-500">{data.id}</span>
        <span className="font-medium text-slate-200">{data.intent}</span>
        {verdictMeta && (
          <span
            data-testid="plan-verdict"
            className={`rounded border px-1.5 py-0.5 text-[11px] ${verdictMeta.tone}`}
          >
            {verdictMeta.label}
          </span>
        )}
        {data.debate_meta?.side && (
          <span className="text-[11px] text-slate-500">辩方 {data.debate_meta.side}</span>
        )}
      </div>

      <div className="px-3 py-2 space-y-3">
        <ol className="space-y-1.5">
          {data.plan_steps.map((step) => {
            const known = isKnownPlanTool(step.tool, knownTools);
            return (
              <li key={`${step.step}-${step.tool}`} className="flex items-start gap-2">
                <span className="mt-0.5 w-4 shrink-0 text-right text-slate-500">{step.step}</span>
                <div className="min-w-0">
                  <div className="text-slate-200">{step.action}</div>
                  <div
                    data-testid="plan-step-tool"
                    className={`font-mono text-[11px] ${known ? 'text-indigo-300' : 'text-red-400'}`}
                  >
                    {step.tool}
                    {!known && <span data-testid="plan-tool-unknown" className="ml-1 text-red-400">（未注册工具）</span>}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>

        {data.risk_flags && data.risk_flags.length > 0 && (
          <div data-testid="plan-risk-flags" className="rounded border border-red-500/30 bg-red-500/5 px-2 py-1.5">
            <div className="mb-1 text-[11px] text-red-300">风险标记</div>
            <ul className="list-disc pl-4 text-red-200">
              {data.risk_flags.map((flag) => (
                <li key={flag}>{flag}</li>
              ))}
            </ul>
          </div>
        )}

        {data.validation.evaluator_refs.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] text-slate-500">验收引用</div>
            <ul className="space-y-0.5">
              {data.validation.evaluator_refs.map((ref) => (
                <li key={ref} className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-slate-300">{ref}</span>
                  <button
                    type="button"
                    onClick={() => copyRef(ref)}
                    className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-300"
                  >
                    <IconCopy className="w-3 h-3" />
                    {copiedRef === ref ? '已复制' : '复制'}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {data.expected_outcome && (
          <div className="text-slate-400">预期结果：{data.expected_outcome}</div>
        )}
      </div>
    </div>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

export default PlanCardView;
