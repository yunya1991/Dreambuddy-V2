'use client';

import { V3Card, V3Badge, V3StatusDot } from '@/components';
import { useMonitorStore } from '@/stores';

const layers = [
  { key: 'S' as const, label: '感知层', desc: '意图识别 · 市场感知 · 多源数据融合', variant: 'sacg-s' as const, color: 'border-purple-500/20' },
  { key: 'A' as const, label: '编排层', desc: 'Chain 编排 · DAG 调度 · 并行执行', variant: 'sacg-a' as const, color: 'border-blue-500/20' },
  { key: 'C' as const, label: '执行层', desc: '交易执行 · 风控守卫 · 订单管理', variant: 'sacg-c' as const, color: 'border-green-500/20' },
  { key: 'G' as const, label: '存储层', desc: '图记忆 · BAC 压缩 · 持久化', variant: 'sacg-g' as const, color: 'border-amber-500/20' },
];

export function SACGOverview() {
  const { sLayerEvents, aLayerEvents, cLayerEvents, gLayerEvents, pipelineThroughput, sseConnection } = useMonitorStore();

  const eventMap = { S: sLayerEvents, A: aLayerEvents, C: cLayerEvents, G: gLayerEvents };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">SACG 四层总览</h2>
        <V3StatusDot status={sseConnection.status === 'connected' ? 'success' : sseConnection.status === 'connecting' ? 'loading' : 'idle'} size="sm" label={`SSE: ${sseConnection.status}`} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        {layers.map(layer => {
          const events = eventMap[layer.key];
          const recent = events.slice(-3).reverse();
          return (
            <V3Card key={layer.key} className={`border ${layer.color}`} padding="md">
              <div className="flex items-center gap-2 mb-2">
                <V3Badge variant={layer.variant} dot pulse label={layer.key} />
                <span className="text-sm font-medium text-slate-200">{layer.label}</span>
                <span className="ml-auto text-[10px] text-slate-500">{events.length} 事件</span>
              </div>
              <p className="text-[10px] text-slate-500 mb-3">{layer.desc}</p>
              {recent.length > 0 ? (
                <div className="space-y-1.5">
                  {recent.map(e => (
                    <div key={e.id} className="flex items-center justify-between text-[10px]">
                      <span className="text-slate-400 truncate">{e.description}</span>
                      <span className="text-slate-600 ml-2 flex-shrink-0">{e.duration || 0}ms</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[10px] text-slate-600 text-center py-2">暂无事件</p>
              )}
            </V3Card>
          );
        })}
      </div>
      <V3Card title="管道吞吐量" padding="sm">
        <div className="grid grid-cols-4 gap-4">
          <div className="text-center">
            <p className="text-lg font-semibold text-slate-200">{pipelineThroughput.totalProcessed}</p>
            <p className="text-[10px] text-slate-500">已处理</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-emerald-400">{(pipelineThroughput.successRate * 100).toFixed(0)}%</p>
            <p className="text-[10px] text-slate-500">成功率</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-slate-200">{pipelineThroughput.avgLatencyMs}ms</p>
            <p className="text-[10px] text-slate-500">平均延迟</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-blue-400">{pipelineThroughput.activeCount}</p>
            <p className="text-[10px] text-slate-500">活跃任务</p>
          </div>
        </div>
      </V3Card>
    </div>
  );
}
