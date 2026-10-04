/**
 * F4: Bull/Bear 辩论 UI 组件
 *
 * 展示 C-Drive-Agent 四步循环中 Step 2 (Bull/Bear 辩论) 的结果。
 * 数据来源: CDriveDecision.bull_argument / bear_argument / bull_confidence / bear_confidence
 * 触发条件: 节点 confidence < 0.65 (对齐 CDriveAgent.CONF_RECALL_ONLY)
 */

import { useState } from 'react';

export interface BullBearDebateData {
  bull_argument: string;
  bear_argument: string;
  bull_confidence: number;
  bear_confidence: number;
  jury_verdict?: string;
}

interface BullBearDebateProps {
  debate: BullBearDebateData;
  defaultExpanded?: boolean;
}

export function BullBearDebate({ debate, defaultExpanded = false }: BullBearDebateProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const bullPct = Math.round(debate.bull_confidence * 100);
  const bearPct = Math.round(debate.bear_confidence * 100);
  const bullWins = debate.bull_confidence >= debate.bear_confidence;

  return (
    <div className="mt-1.5 rounded-lg border border-slate-700/40 bg-slate-900/40 overflow-hidden">
      {/* 标题栏 (可点击展开) */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-2 py-1.5 hover:bg-slate-800/40 transition-colors text-left"
      >
        <span className="text-[10px] font-medium text-slate-300 flex items-center gap-1">
          <span>⚖️</span>
          <span>Bull/Bear 辩论</span>
          {bullWins ? (
            <span className="text-emerald-400 text-[9px]">Bull {bullPct}%</span>
          ) : (
            <span className="text-rose-400 text-[9px]">Bear {bearPct}%</span>
          )}
        </span>
        <span className="text-[10px] text-slate-500">{expanded ? '▼' : '▶'}</span>
      </button>

      {expanded && (
        <div className="px-2 pb-2 space-y-2">
          {/* 置信度对比条 */}
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-emerald-400 w-8 text-right">{bullPct}%</span>
            <div className="flex-1 h-1.5 rounded-full bg-slate-700 overflow-hidden flex">
              <div
                className="h-full bg-emerald-500/70 transition-all"
                style={{ width: `${(debate.bull_confidence / (debate.bull_confidence + debate.bear_confidence)) * 100}%` }}
              />
              <div
                className="h-full bg-rose-500/70 transition-all"
                style={{ width: `${(debate.bear_confidence / (debate.bull_confidence + debate.bear_confidence)) * 100}%` }}
              />
            </div>
            <span className="text-[9px] text-rose-400 w-8">{bearPct}%</span>
          </div>

          {/* Bull 论据 */}
          <div className="rounded bg-emerald-500/5 border border-emerald-500/20 p-1.5">
            <div className="text-[9px] font-semibold text-emerald-400 mb-0.5">🐂 Bull 多头</div>
            <p className="text-[10px] text-slate-300 leading-relaxed">{debate.bull_argument}</p>
          </div>

          {/* Bear 论据 */}
          <div className="rounded bg-rose-500/5 border border-rose-500/20 p-1.5">
            <div className="text-[9px] font-semibold text-rose-400 mb-0.5">🐻 Bear 空头</div>
            <p className="text-[10px] text-slate-300 leading-relaxed">{debate.bear_argument}</p>
          </div>

          {/* 陪审团裁决 */}
          {debate.jury_verdict && (
            <div className="rounded bg-amber-500/5 border border-amber-500/20 p-1.5">
              <div className="text-[9px] font-semibold text-amber-400 mb-0.5">🎯 陪审团裁决</div>
              <p className="text-[10px] text-slate-300">{debate.jury_verdict}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
