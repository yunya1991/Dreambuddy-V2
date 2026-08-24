import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import {
  fetchRegimeEvolutionLatest, fetchRegimeWeightsLatest,
  REGIME_EVOLUTION_ORDER, REGIME_EVOLUTION_COLORS,
  type RegimeEvolutionLatestResponse, type RegimeWeightsLatestResponse,
} from '../lib/api';
import { EvolutionProvider, useEvolution } from './evolution/EvolutionContext';
import { EvolutionTrajectoryPanel } from './evolution/EvolutionTrajectoryPanel';
import { DotplotPanel } from './evolution/DotplotPanel';
import { RegimeProbAreaPanel } from './evolution/RegimeProbAreaPanel';
import { IndicatorDiagnosticPanel } from './evolution/IndicatorDiagnosticPanel';
import { BcrmParamsPanel } from './evolution/BcrmParamsPanel';

function _top1(probs: Record<string, number>): { name: string; p: number } {
  let name = 'RANGE_BOUND';
  let p = 0;
  for (const r of REGIME_EVOLUTION_ORDER) {
    const v = probs[r] || 0;
    if (v > p) { p = v; name = r; }
  }
  return { name, p };
}

const SnapshotBar: React.FC<{ data: RegimeEvolutionLatestResponse | undefined }> = ({ data }) => {
  if (!data?.snapshot) return null;
  const snap = data.snapshot;
  const top = _top1(snap.regime_probs || {});
  return (
    <Card className="mb-3">
      <CardContent className="flex flex-wrap items-center gap-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">日期</span>
          <Badge variant="outline">{snap.t}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">价格</span>
          <span className="font-mono text-sm font-semibold">${snap.price?.toFixed(0)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Level</span>
          <span className="font-mono text-sm font-semibold" style={{ color: snap.level_smooth >= 0 ? '#16a34a' : '#ef4444' }}>
            {snap.level_smooth?.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Trend</span>
          <span className="font-mono text-sm font-semibold" style={{ color: snap.trend_smooth >= 0 ? '#16a34a' : '#ef4444' }}>
            {snap.trend_smooth?.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">主导态</span>
          <Badge style={{ backgroundColor: REGIME_EVOLUTION_COLORS[top.name], color: 'white' }}>
            {top.name} ({(top.p * 100).toFixed(0)}%)
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">共识度</span>
          <span className="font-mono text-sm font-semibold">{(snap.consensus * 100).toFixed(1)}%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">HMM</span>
          <span className="font-mono text-sm">{snap.hmm_state === 2 ? 'Bull' : snap.hmm_state === 0 ? 'Bear' : 'Neutral'}</span>
        </div>
      </CardContent>
    </Card>
  );
};

const WeightsBar: React.FC<{ data: RegimeWeightsLatestResponse | undefined }> = ({ data }) => {
  if (!data?.weights) return null;
  const w = data.weights;
  return (
    <Card className="mb-3">
      <CardHeader className="pb-1">
        <CardTitle className="text-sm">在线学习权重（周: {w.week_start}）</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-4 py-2">
        <div className="text-xs text-slate-500">目标函数: <span className="font-mono font-semibold text-slate-800">{w.objective?.toFixed(4)}</span></div>
        <div className="text-xs text-slate-500">MAX_DAILY_DELTA: <span className="font-mono">{w.max_daily_delta?.toFixed(2)}</span></div>
        <div className="text-xs text-slate-500">状态: <span className="font-medium">{w.comment || '-'}</span></div>
        <div className="flex gap-1">
          {Object.entries(w.level_weights || {}).slice(0, 4).map(([k, v]) => (
            <Badge key={k} variant="outline" className="text-[10px]">{k.split('_')[0]}: {v.toFixed(1)}</Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};

const EvolutionInner: React.FC = () => {
  const [window, setWindow] = useState(90);
  const { setData, setLoading, setError } = useEvolution();

  const { data, isLoading, error } = useQuery({
    queryKey: ['regime-evolution-latest', window],
    queryFn: () => fetchRegimeEvolutionLatest({ window }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
  });

  const { data: weightsData } = useQuery({
    queryKey: ['regime-weights-latest'],
    queryFn: () => fetchRegimeWeightsLatest(),
    refetchInterval: 300000,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (data) {
      setData(data);
      setError(null);
    } else if (error) {
      setError(String(error));
    }
    setLoading(isLoading);
  }, [data, error, isLoading, setData, setError, setLoading]);

  return (
    <div className="space-y-3 p-4">
      {/* 工具栏 */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-800">市场形态演化引擎</h2>
        <div className="flex items-center gap-2">
          {[30, 60, 90, 180].map((w) => (
            <Button
              key={w}
              variant={window === w ? 'default' : 'outline'}
              size="sm"
              onClick={() => setWindow(w)}
              className="text-xs"
            >
              {w}天
            </Button>
          ))}
        </div>
      </div>

      {/* 快照 */}
      <SnapshotBar data={data} />
      <WeightsBar data={weightsData} />

      {/* 4 面板 2×2 网格 */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <EvolutionTrajectoryPanel />
        <DotplotPanel />
        <RegimeProbAreaPanel />
        <IndicatorDiagnosticPanel />
      </div>

      {/* Panel 5: BCRM 2.0 参数输出（独立全宽行） */}
      <div className="mt-3">
        <BcrmParamsPanel />
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          加载失败: {String(error)}
        </div>
      )}
      {isLoading && !data && (
        <div className="flex h-32 items-center justify-center text-sm text-slate-400">加载中...</div>
      )}
    </div>
  );
};

export const RegimeEvolutionPage: React.FC = () => (
  <EvolutionProvider>
    <EvolutionInner />
  </EvolutionProvider>
);
