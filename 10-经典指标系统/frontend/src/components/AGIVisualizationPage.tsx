import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, ReferenceLine, AreaChart, Area, ScatterChart, Scatter, ZAxis,
} from 'recharts';
import {
  fetchAgiSnapshot, fetchAgiStatus,
  type AgiSnapshot,
} from '../lib/api';

// ========== L1: 感知层快照栏 ==========
const PerceptionBar: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  if (!snapshots.length) return null;
  const latest = snapshots[snapshots.length - 1];
  const sdeBackend = latest.neural_sde_backend || 'unavailable';
  const sdeTrained = latest.neural_sde_trained ? '✅ 已训练' : '❌ 未训练';
  const rlActivated = latest.shadow_rl_activated ? '✅ Phase3' : '⏸ 待激活';
  const rlSamples = latest.shadow_rl_samples ?? 0;

  return (
    <Card className="mb-3">
      <CardContent className="flex flex-wrap items-center gap-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">时间</span>
          <Badge variant="outline">{latest.ts}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Symbol</span>
          <Badge variant="outline">{latest.symbol}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">d*</span>
          <span className="font-mono text-sm font-semibold" style={{ color: latest.d_star === 'long' ? '#16a34a' : latest.d_star === 'short' ? '#ef4444' : '#94a3b8' }}>
            {latest.d_star || '-'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">RI</span>
          <span className="font-mono text-sm font-semibold">{latest.ri?.toFixed(4)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Action</span>
          <Badge variant="secondary">{latest.action || '-'}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Tier</span>
          <Badge variant="outline">{latest.tier || '-'}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Regime</span>
          <span className="font-mono text-sm">{latest.regime || '-'}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">SDE</span>
          <Badge style={{ backgroundColor: sdeBackend === 'unavailable' ? '#94a3b8' : '#3b82f6', color: 'white' }}>
            {sdeBackend}
          </Badge>
          <span className="text-xs text-slate-600">{sdeTrained}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">ShadowRL</span>
          <span className="text-xs text-slate-600">{rlActivated} ({rlSamples} samples)</span>
        </div>
      </CardContent>
    </Card>
  );
};

// ========== L2: Signature 范数趋势 ==========
const SignaturePanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const data = useMemo(() => snapshots
    .filter(s => s.agi_signature)
    .map(s => ({ ts: s.ts.split('T')[1] || s.ts, norm: s.agi_signature!.norm, dim: s.agi_signature!.first })), [snapshots]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L2 Signature 范数趋势</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {data.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">无 Signature 数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="ts" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Area type="monotone" dataKey="norm" stroke="#8b5cf6" fill="#8b5cf633" name="Norm" />
              <Line type="monotone" dataKey="dim" stroke="#06b6d4" name="First" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};

// ========== L2: Neural SDE 后端状态 ==========
const NeuralSDEPanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const sdeBackends = useMemo(() => {
    const counts: Record<string, number> = {};
    snapshots.forEach(s => {
      const b = s.neural_sde_backend || 'unavailable';
      counts[b] = (counts[b] || 0) + 1;
    });
    return Object.entries(counts).map(([name, count]) => ({ name, count }));
  }, [snapshots]);

  const latest = snapshots[snapshots.length - 1];
  const trained = latest?.neural_sde_trained;
  const backend = latest?.neural_sde_backend || 'unavailable';

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L2 Neural SDE 后端状态</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-center gap-3 mb-2">
          <Badge style={{ backgroundColor: backend === 'torchsde' ? '#16a34a' : backend === 'euler_maruyama' ? '#3b82f6' : backend === 'garch' ? '#f59e0b' : '#94a3b8', color: 'white' }}>
            {backend}
          </Badge>
          <span className="text-xs text-slate-600">{trained ? '✅ 权重已加载' : '❌ 未训练'}</span>
        </div>
        {sdeBackends.length > 0 && (
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={sdeBackends}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};

// ========== L3: 路径阻力分布 ==========
const PathResistancePanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const data = useMemo(() => snapshots
    .filter(s => s.agi_path_integral)
    .map(s => ({
      ts: s.ts.split('T')[1] || s.ts,
      resistance: s.agi_path_integral!.min_resistance_action,
      vol: s.agi_path_integral!.volatility,
      n_paths: s.agi_path_integral!.n_paths,
    })), [snapshots]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L3 路径阻力 (min resistance action)</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {data.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">无路径积分数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="ts" tick={{ fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Line type="monotone" dataKey="resistance" stroke="#ef4444" name="阻力" dot={false} strokeWidth={2} />
              <ReferenceLine y={0.5} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: '中性', fontSize: 10 }} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};

// ========== L3: 蒙特卡洛路径散点 ==========
const MonteCarloPanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const data = useMemo(() => snapshots
    .filter(s => s.agi_path_integral)
    .map(s => ({
      vol: s.agi_path_integral!.volatility,
      resistance: s.agi_path_integral!.min_resistance_action,
      expected_end: s.agi_path_integral!.expected_end_price,
      start: s.agi_path_integral!.start_price,
      ts: s.ts.split('T')[1] || s.ts,
    })), [snapshots]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L3 蒙特卡洛 波动率 vs 阻力</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {data.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">无数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" dataKey="vol" name="波动率" tick={{ fontSize: 10 }} />
              <YAxis type="number" dataKey="resistance" name="阻力" domain={[0, 1]} tick={{ fontSize: 10 }} />
              <ZAxis range={[60, 60]} />
              <Tooltip cursor={{ strokeDasharray: '3 3' }} />
              <Scatter data={data} fill="#8b5cf6" />
            </ScatterChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};

// ========== L4: 不确定性 Gate ==========
const UncertaintyGatePanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const data = useMemo(() => snapshots
    .filter(s => s.agi_uncertainty)
    .map(s => ({
      ts: s.ts.split('T')[1] || s.ts,
      score: s.agi_uncertainty!.uncertainty_score,
      level: s.agi_uncertainty!.level,
      multiplier: s.agi_gate_decision?.position_multiplier ?? 1,
    })), [snapshots]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L4 不确定性 Gate</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {data.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">无不确定性数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="ts" tick={{ fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Line type="monotone" dataKey="score" stroke="#f59e0b" name="不确定性" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="multiplier" stroke="#06b6d4" name="仓位乘数" dot={false} strokeWidth={2} />
              <ReferenceLine y={0.5} stroke="#94a3b8" strokeDasharray="3 3" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};

// ========== L4: 元认知决策分布 ==========
const GateDecisionPanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const decisions = useMemo(() => {
    const counts: Record<string, number> = {};
    snapshots.forEach(s => {
      const d = s.agi_gate_decision?.decision || 'unknown';
      counts[d] = (counts[d] || 0) + 1;
    });
    return Object.entries(counts).map(([name, count]) => ({ name, count }));
  }, [snapshots]);

  const colors: Record<string, string> = { proceed: '#16a34a', reduce: '#f59e0b', block: '#ef4444', unknown: '#94a3b8' };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L4 元认知 Gate 决策分布</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {decisions.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">无 Gate 数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={decisions}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6">
                {decisions.map((entry, index) => (
                  <rect key={index} fill={colors[entry.name] || '#3b82f6'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};

// ========== L5: ShadowRL 训练进度 ==========
const ShadowRLPanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const data = useMemo(() => snapshots
    .filter(s => s.shadow_rl_samples !== undefined)
    .map(s => ({
      ts: s.ts.split('T')[1] || s.ts,
      samples: s.shadow_rl_samples!,
      activated: s.shadow_rl_activated,
    })), [snapshots]);

  const latest = data[data.length - 1];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L5 ShadowRL 训练进度</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {data.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">无 ShadowRL 数据</div>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-2">
              <Badge style={{ backgroundColor: latest?.activated ? '#16a34a' : '#94a3b8', color: 'white' }}>
                {latest?.activated ? 'Phase3 已激活' : '待激活'}
              </Badge>
              <span className="text-sm font-mono">{latest?.samples} samples</span>
            </div>
            <ResponsiveContainer width="100%" height={120}>
              <AreaChart data={data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Area type="monotone" dataKey="samples" stroke="#16a34a" fill="#16a34a33" name="样本数" />
              </AreaChart>
            </ResponsiveContainer>
          </>
        )}
      </CardContent>
    </Card>
  );
};

// ========== L1: 形态 + BTC Regime ==========
const RegimePanel: React.FC<{ snapshots: AgiSnapshot[] }> = ({ snapshots }) => {
  const regimes = useMemo(() => {
    const counts: Record<string, number> = {};
    snapshots.forEach(s => {
      const r = s.agi_btc_regime || s.regime || 'unknown';
      counts[r] = (counts[r] || 0) + 1;
    });
    return Object.entries(counts).map(([name, count]) => ({ name, count }));
  }, [snapshots]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">L1 Regime 分布</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {regimes.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">无 Regime 数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={regimes} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={120} />
              <Tooltip />
              <Bar dataKey="count" fill="#06b6d4" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};

// ========== 主页面 ==========
const AGIVisualizationPage: React.FC = () => {
  const [n, setN] = useState(200);
  const [symbol, setSymbol] = useState<string | undefined>(undefined);

  const { data, isLoading, error } = useQuery({
    queryKey: ['agi-snapshot', n, symbol],
    queryFn: () => fetchAgiSnapshot({ n, symbol }),
    refetchInterval: 10000,
    refetchOnWindowFocus: false,
  });

  const { data: statusData } = useQuery({
    queryKey: ['agi-status'],
    queryFn: () => fetchAgiStatus(),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });

  const snapshots = data?.snapshots ?? [];

  return (
    <div className="space-y-3 p-4">
      {/* 工具栏 */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-800">AGI 自进化系统仪表盘</h2>
        <div className="flex items-center gap-2">
          {[50, 100, 200, 500].map((v) => (
            <Button
              key={v}
              variant={n === v ? 'default' : 'outline'}
              size="sm"
              onClick={() => setN(v)}
              className="text-xs"
            >
              {v}条
            </Button>
          ))}
          {statusData?.symbols && (
            <select
              className="border rounded px-2 py-1 text-xs"
              value={symbol || ''}
              onChange={(e) => setSymbol(e.target.value || undefined)}
            >
              <option value="">全部</option>
              {statusData.symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* 全局状态 */}
      {statusData && (
        <Card className="mb-3">
          <CardContent className="flex flex-wrap items-center gap-4 py-2">
            <span className="text-xs text-slate-500">总快照数:</span>
            <span className="font-mono text-sm font-semibold">{statusData.total_snapshots}</span>
            <span className="text-xs text-slate-500">Symbols:</span>
            <div className="flex gap-1">
              {statusData.symbols.map((s) => (
                <Badge key={s} variant="outline" className="text-[10px]">{s}</Badge>
              ))}
            </div>
            <span className="text-xs text-slate-500">SDE 后端:</span>
            <Badge style={{ backgroundColor: statusData.neural_sde_backend === 'unavailable' ? '#94a3b8' : '#3b82f6', color: 'white' }}>
              {statusData.neural_sde_backend}
            </Badge>
          </CardContent>
        </Card>
      )}

      {/* L1 感知层快照栏 */}
      <PerceptionBar snapshots={snapshots} />

      {/* L1-L2 行 */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <RegimePanel snapshots={snapshots} />
        <SignaturePanel snapshots={snapshots} />
      </div>

      {/* L2-L3 行 */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <NeuralSDEPanel snapshots={snapshots} />
        <PathResistancePanel snapshots={snapshots} />
      </div>

      {/* L3 行 */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <MonteCarloPanel snapshots={snapshots} />
        <UncertaintyGatePanel snapshots={snapshots} />
      </div>

      {/* L4-L5 行 */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <GateDecisionPanel snapshots={snapshots} />
        <ShadowRLPanel snapshots={snapshots} />
      </div>

      {/* 错误和加载态 */}
      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          加载失败: {String(error)}
        </div>
      )}
      {isLoading && snapshots.length === 0 && (
        <div className="flex h-32 items-center justify-center text-sm text-slate-400">
          加载中...（若长时间无数据，请确认 polling_trader 已重启并产生 AGI 快照）
        </div>
      )}
    </div>
  );
};

export default AGIVisualizationPage;
