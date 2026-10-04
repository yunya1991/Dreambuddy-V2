'use client';

import { V3Card, V3Badge, V3Empty } from '@/components';
import { useChainStore } from '@/stores';

/**
 * C 层交叉验证面板
 * 对应 SPEC §C: /dashboard/monitor/compute
 * 数据源: useChainStore.crossValidations
 */

const resultStyles: Record<string, { bg: string; text: string; label: string }> = {
  pass: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', label: '通过' },
  fail: { bg: 'bg-rose-500/15', text: 'text-rose-400', label: '失败' },
  partial: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: '部分' },
};

export function CrossValidationPanel() {
  const { crossValidations } = useChainStore();

  const total = crossValidations.length;
  const passCount = crossValidations.filter(cv => cv.result === 'pass').length;
  const failCount = crossValidations.filter(cv => cv.result === 'fail').length;
  const passRate = total > 0 ? (passCount / total) * 100 : 0;
  const avgConfidence = total > 0
    ? crossValidations.reduce((s, cv) => s + cv.confidence, 0) / total
    : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">C 层 — 交叉验证</h2>
        <V3Badge variant="sacg-c" dot>CV</V3Badge>
      </div>

      {/* 验证统计 */}
      <div className="grid grid-cols-4 gap-2">
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">总数</p>
          <p className="text-lg font-bold text-slate-200">{total}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">通过</p>
          <p className="text-lg font-bold text-emerald-400">{passCount}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">失败</p>
          <p className="text-lg font-bold text-rose-400">{failCount}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">通过率</p>
          <p className="text-lg font-bold text-blue-400">{passRate.toFixed(0)}%</p>
        </V3Card>
      </div>

      {/* 平均置信度 */}
      {total > 0 && (
        <V3Card title="平均验证置信度" padding="sm">
          <div className="flex items-center gap-3">
            <div className="flex-1 h-2 rounded-full bg-slate-700 overflow-hidden">
              <div
                className={`h-full ${avgConfidence >= 0.7 ? 'bg-emerald-500' : avgConfidence >= 0.5 ? 'bg-amber-500' : 'bg-rose-500'} transition-all`}
                style={{ width: `${avgConfidence * 100}%` }}
              />
            </div>
            <span className="text-sm font-bold text-slate-200">
              {(avgConfidence * 100).toFixed(1)}%
            </span>
          </div>
        </V3Card>
      )}

      {/* 验证结果列表 */}
      <V3Card title="验证结果" padding="sm">
        {crossValidations.length > 0 ? (
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {crossValidations.slice().reverse().map((cv, i) => {
              const style = resultStyles[cv.result] || resultStyles.partial;
              return (
                <div key={i} className="p-2 rounded bg-slate-800/30">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] text-slate-500 truncate">{cv.chainId}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded ${style.bg} ${style.text}`}>
                      {style.label}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1 rounded-full bg-slate-700 overflow-hidden">
                      <div
                        className={`h-full ${cv.confidence >= 0.7 ? 'bg-emerald-500' : cv.confidence >= 0.5 ? 'bg-amber-500' : 'bg-rose-500'}`}
                        style={{ width: `${cv.confidence * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-400">
                      {(cv.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  {cv.disagreements.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {cv.disagreements.map((d, j) => (
                        <span key={j} className="text-[10px] text-rose-400/70 bg-rose-500/10 px-1.5 py-0.5 rounded">
                          {d}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <V3Empty title="暂无交叉验证" description="等待 CrossValidator 运行" />
        )}
      </V3Card>
    </div>
  );
}
