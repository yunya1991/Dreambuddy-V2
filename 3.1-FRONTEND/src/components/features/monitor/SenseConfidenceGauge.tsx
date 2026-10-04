'use client';

import { V3Card, V3Badge, V3Empty } from '@/components';
import { useMonitorStore } from '@/stores';
import { useChainStore } from '@/stores';

/**
 * S 层感知置信度仪表盘
 * 对应 SPEC §C: /dashboard/monitor/sense
 * 数据源: useMonitorStore.sLayerEvents + useChainStore.chainTrace.intent
 */

const confidenceColor = (conf: number) => {
  if (conf >= 0.75) return { text: 'text-emerald-400', bar: 'bg-emerald-500', label: '高置信' };
  if (conf >= 0.5) return { text: 'text-amber-400', bar: 'bg-amber-500', label: '中置信' };
  return { text: 'text-rose-400', bar: 'bg-rose-500', label: '低置信' };
};

const intentTypeLabels: Record<string, string> = {
  execute_trade: '执行交易',
  market_query: '市场查询',
  analysis: '分析',
  strategy: '策略',
  risk: '风控',
  dialog: '对话',
};

export function SenseConfidenceGauge() {
  const { sLayerEvents } = useMonitorStore();
  const { chainTrace } = useChainStore();

  const intent = chainTrace?.intent;
  const sEvents = sLayerEvents.slice(-10).reverse();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">S 层 — 感知置信度</h2>
        <V3Badge variant="sacg-s" dot pulse>S</V3Badge>
      </div>

      {/* 意图识别置信度仪表盘 */}
      <V3Card title="意图识别置信度" padding="md">
        {intent ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-slate-500">意图类型</p>
                <p className="text-sm font-medium text-slate-200">
                  {intentTypeLabels[intent.type] || intent.type}
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">识别方法</p>
                <p className="text-xs text-slate-400">{intent.method}</p>
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-slate-500">置信度</span>
                <span className={`text-sm font-bold ${confidenceColor(intent.confidence).text}`}>
                  {(intent.confidence * 100).toFixed(1)}%
                </span>
              </div>
              <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
                <div
                  className={`h-full ${confidenceColor(intent.confidence).bar} transition-all`}
                  style={{ width: `${intent.confidence * 100}%` }}
                />
              </div>
              <p className={`text-[10px] mt-1 ${confidenceColor(intent.confidence).text}`}>
                {confidenceColor(intent.confidence).label}
                {intent.confidence >= 0.9 && ' · 前端规则引擎跳过 LLM'}
              </p>
            </div>
          </div>
        ) : (
          <V3Empty title="暂无意图识别数据" description="等待意图识别引擎运行" />
        )}
      </V3Card>

      {/* S 层事件流 */}
      <V3Card title="S 层事件流" padding="sm">
        {sEvents.length > 0 ? (
          <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
            {sEvents.map(e => (
              <div key={e.id} className="flex items-center justify-between text-[10px] p-2 rounded bg-slate-800/30">
                <span className="text-slate-400 truncate">{e.description}</span>
                <span className="text-slate-600 ml-2 flex-shrink-0">
                  {e.duration ? `${e.duration}ms` : new Date(e.timestamp).toLocaleTimeString('zh-CN')}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <V3Empty title="暂无 S 层事件" description="等待感知层事件流入" />
        )}
      </V3Card>
    </div>
  );
}
