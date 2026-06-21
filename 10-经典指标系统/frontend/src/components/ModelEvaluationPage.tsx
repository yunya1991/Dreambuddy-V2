
import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchEvaluationData, fetchEvalModels, trainEvalModel, predictEval, fetchFeatureImportance, fetchEvalMetrics, onlineUpdate, fetchEvalHistory, explainEval, saveEvalModel, loadEvalModel, importEvalSamplesV2, fetchEvalEquityCurve, fetchEvalHeatmap, trainEvalCalibrator, trainEvalCommittee, fitEvalThresholds, fetchEvalThresholds, rollingVerifyEval, monteCarloEval, fetchEvaluationHealth, fetchEvaluationAcceptanceStatus, runOnlineUpdate, fetchConfig, setAutomationConfig, updateConfig, type ImportEvalSamplesResponse, type EvalHistoryItem, type JsonRecord, type MonteCarloResult, type EvalHealthOutputSeries, type OnlineUpdateOrchestrationResponse } from '../lib/api';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, AreaChart, Area, BarChart as RBarChart, Bar } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { TrendingUp, Target, BarChart, Percent, ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Badge } from './ui/badge';

export const ModelEvaluationPage: React.FC = () => {
  const queryClient = useQueryClient();
  type RollingVerifyResponse = {
    ok: boolean;
    error?: string;
    avg?: {
      raw?: {
        win_rate?: number;
        sharpe?: number;
      };
    };
  };
  const [evalDataWindow, setEvalDataWindow] = useState<number>(1000);
  const { data, isLoading } = useQuery({ 
    queryKey: ['evaluation', evalDataWindow], 
    queryFn: () => fetchEvaluationData(evalDataWindow),
  });
  const { data: families } = useQuery({ queryKey: ['eval-families'], queryFn: fetchEvalModels });
  const { data: metrics } = useQuery({ queryKey: ['eval-metrics'], queryFn: fetchEvalMetrics, refetchInterval: 10000, refetchOnWindowFocus: false });
  const { data: history } = useQuery({ queryKey: ['eval-history'], queryFn: fetchEvalHistory });
  const [family, setFamily] = useState<string>('lr');
  const [coeffs, setCoeffs] = useState<{feature:string, weight:number}[] | null>(null);
  const [predictResult, setPredictResult] = useState<{p:number, pc:number, threshold:number, decision:string} | null>(null);
  const [explain, setExplain] = useState<{feature:string, value:number}[] | null>(null);
  const [warm, setWarm] = useState<boolean>(false);
  const [resume, setResume] = useState<boolean>(false);
  const [calibrated, setCalibrated] = useState<boolean>(true);
  const [equityWindow, setEquityWindow] = useState<number>(5000);
  const [heatmapWindow, setHeatmapWindow] = useState<number>(2000);
  const [heatmapMetric, setHeatmapMetric] = useState<'mean_return' | 'win_rate' | 'counts'>('mean_return');
  const [calibMethod, setCalibMethod] = useState<'platt' | 'isotonic'>('platt');
  const [calibByRegime, setCalibByRegime] = useState<boolean>(false);
  const [thresholdFitWindow, setThresholdFitWindow] = useState<number>(1000);
  const [thresholdFitResult, setThresholdFitResult] = useState<{ok:boolean, family:string, window:number, fitted?:Record<string, unknown>, errors?:Record<string, unknown>} | null>(null);
  const [rollingFolds, setRollingFolds] = useState<number>(5);
  const [rollingResult, setRollingResult] = useState<RollingVerifyResponse | null>(null);
  const [mcRuns, setMcRuns] = useState<number>(300);
  const [mcWindow, setMcWindow] = useState<number>(5000);
  const [mcPNoise, setMcPNoise] = useState<number>(0.02);
  const [mcRetNoise, setMcRetNoise] = useState<number>(0.0);
  const [mcCostPct, setMcCostPct] = useState<number>(0.0);
  const [mcBootstrap, setMcBootstrap] = useState<boolean>(true);
  const [mcDropFrac, setMcDropFrac] = useState<number>(0.0);
  const [mcSeed, setMcSeed] = useState<number>(1);
  const [mcResult, setMcResult] = useState<MonteCarloResult | null>(null);
  const [importing, setImporting] = useState<boolean>(false);
  const [importResult, setImportResult] = useState<ImportEvalSamplesResponse | null>(null);
  const [healthOutputWindow, setHealthOutputWindow] = useState<number>(2000);
  const [healthOutputBins, setHealthOutputBins] = useState<number>(40);
  const [healthOutputPlot, setHealthOutputPlot] = useState<boolean>(false);
  const [acceptanceWindow, setAcceptanceWindow] = useState<number>(2000);
  const [acceptanceRecentMinutes, setAcceptanceRecentMinutes] = useState<number>(60);
  const [acceptanceProfitDays, setAcceptanceProfitDays] = useState<number>(30);
  const [onlineOrchMaxLabel, setOnlineOrchMaxLabel] = useState<number>(500);
  const [onlineOrchTrain, setOnlineOrchTrain] = useState<boolean>(true);
  const [onlineOrchForceTrain, setOnlineOrchForceTrain] = useState<boolean>(false);
  const [onlineOrchFamily, setOnlineOrchFamily] = useState<string>('');
  const [onlineOrchConfirmLive, setOnlineOrchConfirmLive] = useState<boolean>(false);
  const [onlineOrchRunning, setOnlineOrchRunning] = useState<boolean>(false);
  const [onlineOrchResult, setOnlineOrchResult] = useState<OnlineUpdateOrchestrationResponse | null>(null);
  const [historyCollapsed, setHistoryCollapsed] = useState<boolean>(false);
  const featureKeys = useMemo(() => ['returns','volatility','dist_ma20','rsi','ret_lag_1','ret_lag_2','ret_lag_3','ret_lag_4','ret_lag_5'], []);
  const [featForm, setFeatForm] = useState<Record<string, number>>({ returns: 0.0, volatility: 0.01, dist_ma20: 0.0, rsi: 50.0, ret_lag_1: 0.0, ret_lag_2: 0.0, ret_lag_3: 0.0, ret_lag_4: 0.0, ret_lag_5: 0.0 });

  const { data: health } = useQuery({
    queryKey: ['eval-health', healthOutputWindow, healthOutputBins, healthOutputPlot],
    queryFn: () => fetchEvaluationHealth({ window: healthOutputWindow, output_window: healthOutputWindow, output_bins: healthOutputBins, output_plot: healthOutputPlot }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });

  const { data: acceptance } = useQuery({
    queryKey: ['eval-acceptance', acceptanceWindow, acceptanceRecentMinutes, acceptanceProfitDays],
    queryFn: () => fetchEvaluationAcceptanceStatus({ window: acceptanceWindow, recent_minutes: acceptanceRecentMinutes, profit_days: acceptanceProfitDays }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });
  const { data: configSnapshot } = useQuery({
    queryKey: ['config-snapshot-eval'],
    queryFn: fetchConfig,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });
  const [configApplyMsg, setConfigApplyMsg] = useState<string>('');
  const [configApplyErr, setConfigApplyErr] = useState<string>('');
  const [onlineTrainOnlyMsg, setOnlineTrainOnlyMsg] = useState<string>('');
  const [onlineTrainOnlyErr, setOnlineTrainOnlyErr] = useState<string>('');

  const automationCfg = useMemo(() => {
    const root = (configSnapshot && typeof configSnapshot === 'object') ? (configSnapshot as unknown as Record<string, unknown>) : {};
    const auto = (root.automation && typeof root.automation === 'object') ? (root.automation as Record<string, unknown>) : {};
    return { root, auto };
  }, [configSnapshot]);

  const coreConfigRows = useMemo(() => {
    const pick = (k: string): unknown => {
      if (Object.prototype.hasOwnProperty.call(automationCfg.auto, k)) return automationCfg.auto[k];
      return automationCfg.root[k];
    };
    return [
      { key: 'enable_training', value: pick('enable_training') },
      { key: 'training_period_minutes', value: pick('training_period_minutes') },
      { key: 'training_family', value: pick('training_family') },
      { key: 'enable_online_train', value: pick('enable_online_train') },
      { key: 'online_train_period_minutes', value: pick('online_train_period_minutes') },
      { key: 'online_train_family', value: pick('online_train_family') },
      { key: 'enable_online_label_settle', value: pick('enable_online_label_settle') },
      { key: 'online_label_settle_period_seconds', value: pick('online_label_settle_period_seconds') },
      { key: 'online_train_min_new_samples', value: pick('online_train_min_new_samples') },
      { key: 'online_label_max_per_run', value: pick('online_label_max_per_run') },
      { key: 'auto_train_min_samples', value: pick('auto_train_min_samples') },
      { key: 'eval_import_hard_scan_multiplier', value: pick('eval_import_hard_scan_multiplier') },
      { key: 'eval_import_time_budget_sec', value: pick('eval_import_time_budget_sec') },
      { key: 'eval_history_max', value: pick('eval_history_max') },
    ];
  }, [automationCfg]);

  const formatCfgValue = (v: unknown): string => {
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '-';
    if (typeof v === 'string') return v;
    if (v === null || v === undefined) return '-';
    return JSON.stringify(v);
  };

  const applyProdPresetMutation = useMutation({
    mutationFn: async () => {
      setConfigApplyMsg('');
      setConfigApplyErr('');
      const traceId = `eval_prod_${Date.now()}`;
      const autoRes = await setAutomationConfig({
        trace_id: traceId,
        confirm_live: true,
        enable_training: true,
        training_period_minutes: 180,
        training_family: 'xgb',
        enable_online_train: true,
        online_train_period_minutes: 120,
        online_train_family: 'xgb',
        enable_online_label_settle: true,
        online_label_settle_period_seconds: 120,
      });
      if (!autoRes?.ok) {
        throw new Error(String(autoRes?.error ?? 'automation_config_failed'));
      }
      const cfgRes = await updateConfig({
        confirm_live: true,
        auto_train_min_samples: 400,
        online_train_min_new_samples: 60,
        online_label_max_per_run: 800,
        eval_import_hard_scan_multiplier: 2,
        eval_import_time_budget_sec: 30,
        eval_history_max: 3000,
      });
      if (!cfgRes?.ok) {
        throw new Error('config_set_failed');
      }
      return { autoRes, cfgRes };
    },
    onSuccess: async () => {
      setConfigApplyMsg('生产参数组合已应用（含 enable_online_train=true）');
      setConfigApplyErr('');
      await queryClient.invalidateQueries({ queryKey: ['config-snapshot-eval'] });
      await queryClient.invalidateQueries({ queryKey: ['eval-history'] });
      await queryClient.invalidateQueries({ queryKey: ['eval-metrics'] });
      await queryClient.invalidateQueries({ queryKey: ['eval-acceptance'] });
    },
    onError: (err: unknown) => {
      setConfigApplyMsg('');
      setConfigApplyErr(String((err as { message?: unknown } | undefined)?.message ?? 'apply_failed'));
    },
  });

  const enableOnlineTrainOnlyMutation = useMutation({
    mutationFn: async () => {
      setOnlineTrainOnlyMsg('');
      setOnlineTrainOnlyErr('');
      const traceId = `eval_online_only_${Date.now()}`;
      const autoRes = await setAutomationConfig({
        trace_id: traceId,
        confirm_live: true,
        enable_online_train: true,
      });
      if (!autoRes?.ok) {
        throw new Error(String(autoRes?.error ?? 'enable_online_train_failed'));
      }
      return autoRes;
    },
    onSuccess: async () => {
      setOnlineTrainOnlyMsg('已启用 enable_online_train=true（最小变更）');
      setOnlineTrainOnlyErr('');
      await queryClient.invalidateQueries({ queryKey: ['config-snapshot-eval'] });
      await queryClient.invalidateQueries({ queryKey: ['eval-acceptance'] });
    },
    onError: (err: unknown) => {
      setOnlineTrainOnlyMsg('');
      setOnlineTrainOnlyErr(String((err as { message?: unknown } | undefined)?.message ?? 'enable_online_train_failed'));
    },
  });

  const healthStatusBadge = (v: boolean | undefined) => {
    if (v === true) return <Badge variant="default">OK</Badge>;
    if (v === false) return <Badge variant="destructive">FAIL</Badge>;
    return <Badge variant="secondary">N/A</Badge>;
  };

  const renderOutputSeries = (title: string, s?: EvalHealthOutputSeries, plotBase64?: string) => {
    const n = Number(s?.n ?? 0);
    return (
      <div className="border rounded p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-medium text-slate-800">{title}</div>
          <div className="text-xs text-slate-500">n {n}</div>
        </div>
        <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-slate-700">
          <div>mean {Number(s?.mean ?? 0).toFixed(4)}</div>
          <div>p10 {Number(s?.p10 ?? 0).toFixed(4)}</div>
          <div>p50 {Number(s?.p50 ?? 0).toFixed(4)}</div>
          <div>p90 {Number(s?.p90 ?? 0).toFixed(4)}</div>
        </div>
        {s?.sparkline && (
          <div className="mt-2 text-[12px] font-mono text-slate-900 break-all">{s.sparkline}</div>
        )}
        {Array.isArray(s?.buckets) && s!.buckets!.length > 0 && (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-[11px] text-slate-500 uppercase bg-slate-50/50">
                <tr>
                  <th className="px-2 py-2">Range</th>
                  <th className="px-2 py-2">Frac</th>
                  <th className="px-2 py-2">N</th>
                </tr>
              </thead>
              <tbody>
                {(s?.buckets ?? []).map((b, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="px-2 py-2 text-slate-700">[{Number(b.lo).toFixed(2)}, {Number(b.hi).toFixed(2)}]</td>
                    <td className="px-2 py-2 text-slate-700">{(Number(b.frac ?? 0) * 100).toFixed(1)}%</td>
                    <td className="px-2 py-2 text-slate-500">{Number(b.n ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {plotBase64 && (
          <div className="mt-3">
            <img className="w-full max-w-[720px] rounded border" src={`data:image/png;base64,${plotBase64}`} alt={title} />
          </div>
        )}
      </div>
    );
  };

  React.useEffect(() => {
    fetchFeatureImportance(family).then(imp => {
        setCoeffs(imp.coefficients ?? (imp.importance?.map(i => ({feature: i.feature, weight: i.gain})) ?? null));
    });
  }, [family]);

  const shownMetrics = useMemo(() => {
    if (!data?.ok) {
      return { auc: 0, brier: 0, win_rate: 0, sharpe: 0 };
    }
    const raw = data.metrics ?? { auc: 0, brier: 0, win_rate: 0, sharpe: 0 };
    return calibrated ? (data.metrics_calibrated ?? raw) : raw;
  }, [calibrated, data]);

  const shownCalibration = useMemo(() => {
    if (!data?.ok) {
      return [];
    }
    const raw = data.calibration ?? [];
    return calibrated ? (data.calibration_calibrated ?? raw) : raw;
  }, [calibrated, data]);

  const shownPnl = useMemo(() => {
    if (!data?.ok) {
      return [];
    }
    const raw = data.pnl ?? [];
    return calibrated ? (data.pnl_calibrated ?? raw) : raw;
  }, [calibrated, data]);

  const { data: equityCurve } = useQuery({
    queryKey: ['eval-equity', family, equityWindow, calibrated],
    queryFn: () => fetchEvalEquityCurve(family, equityWindow, calibrated),
    enabled: !!family,
  });

  const { data: heatmap } = useQuery({
    queryKey: ['eval-heatmap', family, heatmapWindow, calibrated],
    queryFn: () => fetchEvalHeatmap(family, heatmapWindow, calibrated),
    enabled: !!family,
  });

  const { data: thresholds, refetch: refetchThresholds } = useQuery({
    queryKey: ['eval-thresholds'],
    queryFn: fetchEvalThresholds,
    refetchInterval: 5000,
  });

  const heatmapData = useMemo(() => {
    const empty = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
    if (!heatmap?.ok) {
      return empty;
    }
    if (heatmapMetric === 'counts') {
      return heatmap.counts ?? empty;
    }
    if (heatmapMetric === 'win_rate') {
      return heatmap.win_rate ?? empty;
    }
    return heatmap.mean_return ?? empty;
  }, [heatmap, heatmapMetric]);

  const heatmapScale = useMemo(() => {
    let min = 0;
    let max = 0;
    for (const row of heatmapData) {
      for (const v of row) {
        const x = Number.isFinite(v) ? Number(v) : 0;
        if (x < min) min = x;
        if (x > max) max = x;
      }
    }
    return { min, max };
  }, [heatmapData]);

  const heatmapCellStyle = (v: number) => {
    const x = Number.isFinite(v) ? Number(v) : 0;
    if (heatmapMetric === 'counts') {
      const denom = Math.max(1, heatmapScale.max);
      const t = Math.max(0, Math.min(1, x / denom));
      return { backgroundColor: `rgba(59, 130, 246, ${0.08 + 0.70 * t})` };
    }
    if (heatmapMetric === 'win_rate') {
      const t = Math.max(0, Math.min(1, x));
      return { backgroundColor: `rgba(16, 185, 129, ${0.06 + 0.74 * t})` };
    }
    const maxAbs = Math.max(1e-9, Math.max(Math.abs(heatmapScale.min), Math.abs(heatmapScale.max)));
    const t = Math.max(0, Math.min(1, Math.abs(x) / maxAbs));
    if (x >= 0) {
      return { backgroundColor: `rgba(16, 185, 129, ${0.06 + 0.74 * t})` };
    }
    return { backgroundColor: `rgba(239, 68, 68, ${0.06 + 0.74 * t})` };
  };

  if (isLoading) return <div className="p-8 text-center text-slate-500">Loading evaluation data...</div>;

  return (
    <div className="space-y-6">
      {!data?.ok && (
        <div className="border border-amber-200 bg-amber-50 text-amber-900 rounded px-4 py-3 text-sm">
          {data?.error ? `Evaluation unavailable: ${data.error}` : 'Evaluation unavailable'}
        </div>
      )}
      {data?.ok && data?.warn && (
        <div className="border border-amber-200 bg-amber-50 text-amber-900 rounded px-4 py-3 text-sm">
          {String(data.warn)}
        </div>
      )}
      <h2 className="text-2xl font-bold text-slate-900">Model Evaluation & Performance</h2>
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-600">评估窗口</label>
        <select
          className="border rounded px-3 py-1.5 text-sm"
          value={String(evalDataWindow)}
          onChange={(e) => setEvalDataWindow(parseInt(e.target.value, 10) || 5000)}
        >
          <option value="100">100</option>
          <option value="500">500</option>
          <option value="1000">1000</option>
          <option value="5000">5000</option>
          <option value="20000">20000</option>
        </select>
        <span className="text-xs text-slate-500">用于 /evaluation/data 的样本窗口，兼顾性能与统计稳定性</span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Training Automation Config Snapshot</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2 items-center mb-3">
            <Button
              variant="outline"
              onClick={() => { enableOnlineTrainOnlyMutation.mutate(); }}
              disabled={enableOnlineTrainOnlyMutation.isPending}
            >
              {enableOnlineTrainOnlyMutation.isPending ? 'Applying…' : '仅启用 online_train（最小变更）'}
            </Button>
            <Button
              onClick={() => { applyProdPresetMutation.mutate(); }}
              disabled={applyProdPresetMutation.isPending}
            >
              {applyProdPresetMutation.isPending ? 'Applying…' : '应用建议生产参数组合'}
            </Button>
            {onlineTrainOnlyMsg && <span className="text-xs text-emerald-700">{onlineTrainOnlyMsg}</span>}
            {onlineTrainOnlyErr && <span className="text-xs text-red-700">{onlineTrainOnlyErr}</span>}
            {configApplyMsg && <span className="text-xs text-emerald-700">{configApplyMsg}</span>}
            {configApplyErr && <span className="text-xs text-red-700">{configApplyErr}</span>}
          </div>
          <div className="text-xs text-slate-600 mb-2">
            组合目标：低频主训练 + 高频在线增量学习（含自动标签结算），加速模型更新且保留稳定性。
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 uppercase bg-gray-50/50">
                <tr>
                  <th className="px-4 py-3">Key</th>
                  <th className="px-4 py-3">Current</th>
                </tr>
              </thead>
              <tbody>
                {coreConfigRows.map((row) => (
                  <tr key={row.key} className="border-b last:border-0 hover:bg-slate-50/50">
                    <td className="px-4 py-3 font-medium text-gray-900">{row.key}</td>
                    <td className="px-4 py-3 text-gray-500">{formatCfgValue(row.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="flex flex-col items-center p-6">
            <Target className="h-8 w-8 text-blue-500 mb-2" />
            <div className="text-2xl font-bold text-slate-900">{Number(shownMetrics.auc ?? 0).toFixed(3)}</div>
            <div className="text-sm text-slate-500">AUC Score</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex flex-col items-center p-6">
            <BarChart className="h-8 w-8 text-purple-500 mb-2" />
            <div className="text-2xl font-bold text-slate-900">{Number(shownMetrics.brier ?? 0).toFixed(3)}</div>
            <div className="text-sm text-slate-500">Brier Score</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex flex-col items-center p-6">
            <Percent className="h-8 w-8 text-green-500 mb-2" />
            <div className="text-2xl font-bold text-slate-900">{(Number(shownMetrics.win_rate ?? 0) * 100).toFixed(1)}%</div>
            <div className="text-sm text-slate-500">Win Rate</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex flex-col items-center p-6">
            <TrendingUp className="h-8 w-8 text-orange-500 mb-2" />
            <div className="text-2xl font-bold text-slate-900">{Number(shownMetrics.sharpe ?? 0).toFixed(2)}</div>
            <div className="text-sm text-slate-500">Sharpe Ratio</div>
          </CardContent>
        </Card>
      </div>

      {/* Family selector + Train */}
      <Card>
        <CardHeader>
          <CardTitle>Model Family & Training</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col md:flex-row gap-3 items-end">
            <div className="flex-1">
              <label className="text-sm text-slate-600">Select Family</label>
              <select className="w-full border rounded px-3 py-2"
                value={family}
                onChange={(e) => setFamily(e.target.value)}>
                {(Array.isArray(families?.families) ? families.families : ['lr', 'rf', 'xgb', 'nn', 'lstm', 'committee']).map((f: string) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-3">
              <label className="text-sm text-slate-600 flex items-center gap-2">
                <input type="checkbox" checked={warm} onChange={(e) => setWarm(e.target.checked)} />
                Warm Start
              </label>
              <label className="text-sm text-slate-600 flex items-center gap-2">
                <input type="checkbox" checked={calibrated} onChange={(e) => setCalibrated(e.target.checked)} />
                Calibrated
              </label>
              {family === 'xgb' && (
                <label className="text-sm text-slate-600 flex items-center gap-2">
                  <input type="checkbox" checked={resume} onChange={(e) => setResume(e.target.checked)} />
                  Resume
                </label>
              )}
            </div>
            <Button onClick={async () => {
              const params: JsonRecord = { warm_start: warm, resume };
              if (family === 'lr') {
                params.scale = 0.1;
                params.bias = 0;
              }
              await trainEvalModel(family, params, undefined);
              const imp = await fetchFeatureImportance(family);
              setCoeffs(imp.coefficients ?? (imp.importance?.map(i => ({feature: i.feature, weight: i.gain})) ?? null));
            }}>Train</Button>
            <Button variant="outline" disabled={importing} onClick={async () => {
              setImporting(true);
              try {
                const res = await importEvalSamplesV2(50, 20000, true);
                setImportResult(res);
                await queryClient.invalidateQueries({ queryKey: ['evaluation'] });
                await queryClient.invalidateQueries({ queryKey: ['eval-metrics'] });
                await queryClient.invalidateQueries({ queryKey: ['eval-history'] });
                await queryClient.invalidateQueries({ queryKey: ['eval-equity'] });
                await queryClient.invalidateQueries({ queryKey: ['eval-heatmap'] });
              } finally {
                setImporting(false);
              }
            }}>{importing ? 'Importing…' : 'Import Backtests'}</Button>
            {family === 'xgb' && (
              <>
                <Button variant="outline" onClick={async () => { await saveEvalModel('xgb'); }}>Save</Button>
                <Button variant="outline" onClick={async () => { await loadEvalModel(); }}>Load</Button>
              </>
            )}
          </div>
          {metrics?.metrics && (
            <div className="mt-4 text-sm text-slate-600">
              Active: {families?.active ?? family} · AUC {Number(metrics.metrics.auc ?? 0).toFixed(3)} · Win {((Number(metrics.metrics.win_rate ?? 0))*100).toFixed(1)}% · Brier {Number(metrics.metrics.brier ?? 0).toFixed(3)}
            </div>
          )}

          {importResult && (
            <div className="mt-2 text-xs text-slate-600">
              {importResult.ok ? (
                <span>
                  Imported {importResult.added} samples · Total {importResult.total} · Duplicates {importResult.duplicates ?? 0} · Outliers {importResult.dropped_outliers ?? 0} · Files {importResult.scanned} · Trades {importResult.scanned_trades ?? 0} · {importResult.elapsed_ms ?? 0}ms
                </span>
              ) : (
                <span className="text-red-600">Import failed: {importResult.error ?? 'unknown_error'}</span>
              )}
            </div>
          )}

          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="border rounded p-3">
              <div className="text-sm font-medium text-slate-800 mb-2">Calibration</div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-[160px]">
                  <label className="text-xs text-slate-600">Method</label>
                  <select className="w-full border rounded px-3 py-2" value={calibMethod} onChange={(e) => setCalibMethod(e.target.value as 'platt' | 'isotonic')}>
                    <option value="platt">Platt</option>
                    <option value="isotonic">Isotonic</option>
                  </select>
                </div>
                <label className="text-xs text-slate-600 flex items-center gap-2">
                  <input type="checkbox" checked={calibByRegime} onChange={(e) => setCalibByRegime(e.target.checked)} />
                  By Regime
                </label>
                <Button variant="outline" onClick={async () => {
                  await trainEvalCalibrator(family, calibMethod, calibByRegime);
                  await queryClient.invalidateQueries({ queryKey: ['evaluation'] });
                  await queryClient.invalidateQueries({ queryKey: ['eval-metrics'] });
                }}>Train Calibrator</Button>
              </div>
            </div>

            <div className="border rounded p-3">
              <div className="text-sm font-medium text-slate-800 mb-2">Thresholds & Committee</div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-[160px]">
                  <label className="text-xs text-slate-600">Fit Window</label>
                  <Input type="number" value={thresholdFitWindow} onChange={(e) => setThresholdFitWindow(parseInt(e.target.value || '0', 10) || 0)} />
                </div>
                <Button variant="outline" onClick={async () => {
                  const res = await fitEvalThresholds(family, thresholdFitWindow);
                  setThresholdFitResult(res);
                  await refetchThresholds();
                }}>Fit Thresholds</Button>
                <Button variant="outline" onClick={async () => {
                  const res = await trainEvalCommittee();
                  if (res.ok) {
                    setFamily('committee');
                    await queryClient.invalidateQueries({ queryKey: ['evaluation'] });
                    await queryClient.invalidateQueries({ queryKey: ['eval-metrics'] });
                  }
                }}>Train Committee</Button>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                Static: trend {Number(thresholds?.static?.trend ?? 0).toFixed(2)} · chop {Number(thresholds?.static?.chop ?? 0).toFixed(2)}
              </div>
              {thresholdFitResult && !thresholdFitResult.ok && (
                <div className="mt-2 text-xs text-red-600">Threshold fit failed</div>
              )}
            </div>
          </div>

          <div className="mt-4 border rounded p-3">
            <div className="text-sm font-medium text-slate-800 mb-2">Rolling Verify</div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">Folds</label>
                <Input type="number" value={rollingFolds} onChange={(e) => setRollingFolds(parseInt(e.target.value || '0', 10) || 0)} />
              </div>
              <Button variant="outline" onClick={async () => {
                const res = await rollingVerifyEval(family, rollingFolds, calibrated ? calibMethod : undefined);
                setRollingResult(res as unknown as RollingVerifyResponse);
              }}>Run</Button>
              {rollingResult?.ok === false && (
                <div className="text-xs text-red-600">{String(rollingResult.error ?? 'failed')}</div>
              )}
              {rollingResult?.ok === true && (
                <div className="text-xs text-slate-600">Avg win {(Number(rollingResult.avg?.raw?.win_rate ?? 0) * 100).toFixed(1)}% · Sharpe {Number(rollingResult.avg?.raw?.sharpe ?? 0).toFixed(2)}</div>
              )}
            </div>
          </div>

          <div className="mt-4 border rounded p-3">
            <div className="text-sm font-medium text-slate-800 mb-2">Monte Carlo</div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">Runs</label>
                <Input type="number" value={mcRuns} onChange={(e) => setMcRuns(parseInt(e.target.value || '0', 10) || 0)} />
              </div>
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">Window</label>
                <Input type="number" value={mcWindow} onChange={(e) => setMcWindow(parseInt(e.target.value || '0', 10) || 0)} />
              </div>
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">P Noise σ</label>
                <Input type="number" step="0.01" value={mcPNoise} onChange={(e) => setMcPNoise(parseFloat(e.target.value || '0') || 0)} />
              </div>
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">Ret Noise σ</label>
                <Input type="number" step="0.01" value={mcRetNoise} onChange={(e) => setMcRetNoise(parseFloat(e.target.value || '0') || 0)} />
              </div>
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">Cost %</label>
                <Input type="number" step="0.001" value={mcCostPct} onChange={(e) => setMcCostPct(parseFloat(e.target.value || '0') || 0)} />
              </div>
              <label className="text-xs text-slate-600 flex items-center gap-2">
                <input type="checkbox" checked={mcBootstrap} onChange={(e) => setMcBootstrap(e.target.checked)} />
                Bootstrap
              </label>
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">Drop</label>
                <Input type="number" step="0.05" value={mcDropFrac} onChange={(e) => setMcDropFrac(parseFloat(e.target.value || '0') || 0)} />
              </div>
              <div className="min-w-[160px]">
                <label className="text-xs text-slate-600">Seed</label>
                <Input type="number" value={mcSeed} onChange={(e) => setMcSeed(parseInt(e.target.value || '0', 10) || 0)} />
              </div>
              <Button variant="outline" onClick={async () => {
                const res = await monteCarloEval({
                  family,
                  runs: mcRuns,
                  window: mcWindow,
                  calibrated,
                  p_noise_std: mcPNoise,
                  ret_noise_std: mcRetNoise,
                  cost_pct: mcCostPct,
                  bootstrap: mcBootstrap,
                  drop_frac: mcDropFrac,
                  seed: mcSeed,
                });
                setMcResult(res);
              }}>Run</Button>
              {mcResult?.ok === false && (
                <div className="text-xs text-red-600">{String(mcResult.error ?? 'failed')}</div>
              )}
              {mcResult?.ok === true && (
                <div className="text-xs text-slate-600">
                  Sharpe p05 {Number(mcResult.metrics?.p05?.sharpe ?? 0).toFixed(2)} · p50 {Number(mcResult.metrics?.p50?.sharpe ?? 0).toFixed(2)} · p95 {Number(mcResult.metrics?.p95?.sharpe ?? 0).toFixed(2)}
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Calibration Curve */}
        <Card>
          <CardHeader>
            <CardTitle>Calibration Curve</CardTitle>
          </CardHeader>
          <CardContent className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={shownCalibration ?? []} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="prob" type="number" domain={[0, 1]} tickFormatter={(v) => v.toFixed(1)} label={{ value: 'Predicted Probability', position: 'insideBottom', offset: -5 }} />
                <YAxis domain={[0, 1]} label={{ value: 'Actual Fraction', angle: -90, position: 'insideLeft' }} />
                <Tooltip />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#ccc" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="actual" stroke="#2563eb" strokeWidth={2} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* PnL Curve */}
        <Card>
          <CardHeader>
            <CardTitle>Cumulative PnL (7 Days)</CardTitle>
          </CardHeader>
          <CardContent className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={shownPnl ?? []} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <defs>
                  <linearGradient id="colorPnl" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.8}/>
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Area type="monotone" dataKey="cum_pnl" stroke="#10b981" fillOpacity={1} fill="url(#colorPnl)" />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Equity Curve</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2 items-end mb-3">
              <div className="flex-1">
                <label className="text-xs text-slate-600">Window</label>
                <Input type="number" value={equityWindow} onChange={(e) => setEquityWindow(parseInt(e.target.value || '0', 10) || 0)} />
              </div>
            </div>
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={equityCurve?.curve ?? []} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" tickFormatter={(v) => new Date(v).toLocaleString()} />
                  <YAxis />
                  <Tooltip labelFormatter={(v) => new Date(Number(v)).toLocaleString()} />
                  <Line type="monotone" dataKey="cum_pnl" stroke="#10b981" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Signal Heatmap (Weekday × Hour)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2 items-end mb-3">
              <div className="flex-1">
                <label className="text-xs text-slate-600">Window</label>
                <Input type="number" value={heatmapWindow} onChange={(e) => setHeatmapWindow(parseInt(e.target.value || '0', 10) || 0)} />
              </div>
              <div className="flex-1">
                <label className="text-xs text-slate-600">Metric</label>
                <select className="w-full border rounded px-3 py-2" value={heatmapMetric} onChange={(e) => setHeatmapMetric(e.target.value as 'mean_return' | 'win_rate' | 'counts')}>
                  <option value="mean_return">Mean Return</option>
                  <option value="win_rate">Win Rate</option>
                  <option value="counts">Counts</option>
                </select>
              </div>
            </div>

            <div className="overflow-x-auto">
              <div className="min-w-[920px]">
                <div className="grid grid-cols-[80px_repeat(24,minmax(30px,1fr))] gap-px bg-slate-200 rounded overflow-hidden">
                  <div className="bg-white p-2 text-xs text-slate-600">Day/Hour</div>
                  {Array.from({ length: 24 }).map((_, h) => (
                    <div key={h} className="bg-white p-2 text-xs text-slate-600 text-center">{h}</div>
                  ))}
                  {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((d, di) => (
                    <React.Fragment key={d}>
                      <div className="bg-white p-2 text-xs text-slate-700 font-medium">{d}</div>
                      {Array.from({ length: 24 }).map((_, h) => {
                        const v = heatmapData?.[di]?.[h] ?? 0;
                        const label = heatmapMetric === 'counts'
                          ? String(Math.round(v))
                          : heatmapMetric === 'win_rate'
                            ? (Number(v) * 100).toFixed(0)
                            : Number(v).toFixed(2);
                        return (
                          <div key={`${di}-${h}`} className="p-2 text-[11px] text-slate-900 text-center" style={heatmapCellStyle(Number(v))}>
                            {label}
                          </div>
                        );
                      })}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Coefficients / Importance */}
      <Card>
        <CardHeader>
          <CardTitle>{family.toUpperCase()} Coefficients / Importance</CardTitle>
        </CardHeader>
        <CardContent className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={(coeffs ?? []).map(c => ({ name: c.feature, value: c.weight }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Area type="monotone" dataKey="value" stroke="#6366f1" fill="#c7d2fe" />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Explain (SHAP/IG)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 mb-3">
            <Button onClick={async () => {
              const ex = await explainEval(family, featForm);
              setExplain(ex.contribs ?? null);
            }}>Explain</Button>
          </div>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <RBarChart data={(explain ?? []).map(c => ({ name: c.feature, value: c.value }))}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="value" fill="#10b981" />
              </RBarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>Training History</CardTitle>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1"
            onClick={() => setHistoryCollapsed((prev) => !prev)}
          >
            {historyCollapsed ? (
              <>
                <ChevronDown className="h-4 w-4" />
                Expand
              </>
            ) : (
              <>
                <ChevronUp className="h-4 w-4" />
                Collapse
              </>
            )}
          </Button>
        </CardHeader>
        {!historyCollapsed && (
          <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 uppercase bg-gray-50/50">
                <tr>
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Family</th>
                  <th className="px-4 py-3">AUC</th>
                  <th className="px-4 py-3">Win</th>
                  <th className="px-4 py-3">Brier</th>
                </tr>
              </thead>
              <tbody>
                {(history?.history ?? []).slice().reverse().map((h: EvalHistoryItem) => (
                  <tr key={h.id ?? h.ts} className="border-b last:border-0 hover:bg-slate-50/50">
                    <td className="px-4 py-3 text-gray-500">{h.ts ? new Date(h.ts).toLocaleString() : '-'}</td>
                    <td className="px-4 py-3 font-medium text-gray-900">{String(h.family ?? '').toUpperCase()}</td>
                    <td className="px-4 py-3 text-gray-500">{Number(h.metrics?.auc ?? 0).toFixed(3)}</td>
                    <td className="px-4 py-3 text-gray-500">{(Number(h.metrics?.win_rate ?? 0) * 100).toFixed(1)}%</td>
                    <td className="px-4 py-3 text-gray-500">{Number(h.metrics?.brier ?? 0).toFixed(3)}</td>
                  </tr>
                ))}
                {(!history?.history || history.history.length === 0) && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-500">No training history</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          </CardContent>
        )}
      </Card>

      {/* Predictions & Online Learning */}
      <Card>
        <CardHeader>
          <CardTitle>Prediction & Online Learning</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div className="grid grid-cols-2 gap-2">
                {featureKeys.map(k => (
                  <div key={k}>
                    <label className="text-xs text-slate-600">{k}</label>
                    <Input type="number" value={featForm[k] ?? 0} onChange={(e) => setFeatForm(prev => ({...prev, [k]: parseFloat(e.target.value)}))} />
                  </div>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                <Button variant="secondary" onClick={async () => {
                  const res = await predictEval(family, featForm);
                  setPredictResult({ p: res.p, pc: res.pc, threshold: res.threshold, decision: res.decision });
                }}>Predict</Button>
                <Button onClick={async () => {
                  await onlineUpdate(family, featForm, 1);
                }}>Online +1</Button>
                <Button variant="outline" onClick={async () => {
                  await onlineUpdate(family, featForm, 0);
                }}>Online 0</Button>
              </div>
              {predictResult && (
                <div className="mt-3 text-sm">
                  p {predictResult.p.toFixed(3)} · pc {predictResult.pc.toFixed(3)} · thr {predictResult.threshold.toFixed(2)} · decision {predictResult.decision}
                </div>
              )}
            </div>
            <div>
              {metrics?.metrics && (
                <div className="text-sm">
                  <div>Win Rate: {((Number(metrics.metrics.win_rate ?? 0))*100).toFixed(1)}%</div>
                  <div>Brier: {Number(metrics.metrics.brier ?? 0).toFixed(3)}</div>
                  <div>AUC: {Number(metrics.metrics.auc ?? 0).toFixed(3)}</div>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Output Distribution Health</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[160px]">
              <label className="text-xs text-slate-600">Output Window</label>
              <Input type="number" value={healthOutputWindow} onChange={(e) => setHealthOutputWindow(parseInt(e.target.value || '0', 10) || 0)} />
            </div>
            <div className="min-w-[160px]">
              <label className="text-xs text-slate-600">Bins</label>
              <Input type="number" value={healthOutputBins} onChange={(e) => setHealthOutputBins(parseInt(e.target.value || '0', 10) || 0)} />
            </div>
            <label className="text-xs text-slate-600 flex items-center gap-2">
              <input type="checkbox" checked={healthOutputPlot} onChange={(e) => setHealthOutputPlot(e.target.checked)} />
              Plots
            </label>
            <Button variant="outline" onClick={async () => {
              await queryClient.invalidateQueries({ queryKey: ['eval-health'] });
            }}>Refresh</Button>
          </div>

          {Array.isArray(health?.issues) && health!.issues!.length > 0 && (
            <div className="mt-3 space-y-1">
              {health!.issues!.slice(0, 8).map((it, i) => (
                <div key={i} className={`text-xs ${String(it.level) === 'error' ? 'text-red-700' : String(it.level) === 'warn' ? 'text-amber-700' : 'text-slate-700'}`}>
                  {String(it.level).toUpperCase()} · {String(it.code)} · {String(it.msg)}
                </div>
              ))}
            </div>
          )}

          <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
            {renderOutputSeries('pc', health?.output?.pc, typeof health?.output?.plots?.pc_hist_png_base64 === 'string' ? health?.output?.plots?.pc_hist_png_base64 : undefined)}
            {renderOutputSeries('threshold', health?.output?.threshold, typeof health?.output?.plots?.threshold_hist_png_base64 === 'string' ? health?.output?.plots?.threshold_hist_png_base64 : undefined)}
            {renderOutputSeries('pc-threshold', health?.output?.margin, typeof health?.output?.plots?.margin_hist_png_base64 === 'string' ? health?.output?.plots?.margin_hist_png_base64 : undefined)}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Acceptance Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[160px]">
              <label className="text-xs text-slate-600">Window</label>
              <Input type="number" value={acceptanceWindow} onChange={(e) => setAcceptanceWindow(parseInt(e.target.value || '0', 10) || 0)} />
            </div>
            <div className="min-w-[160px]">
              <label className="text-xs text-slate-600">Recent Minutes</label>
              <Input type="number" value={acceptanceRecentMinutes} onChange={(e) => setAcceptanceRecentMinutes(parseInt(e.target.value || '0', 10) || 0)} />
            </div>
            <div className="min-w-[160px]">
              <label className="text-xs text-slate-600">Profit Days</label>
              <Input type="number" value={acceptanceProfitDays} onChange={(e) => setAcceptanceProfitDays(parseInt(e.target.value || '0', 10) || 0)} />
            </div>
            <Button variant="outline" onClick={async () => {
              await queryClient.invalidateQueries({ queryKey: ['eval-acceptance'] });
            }}>Refresh</Button>
          </div>

          <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="border rounded p-3">
              <div className="text-sm font-medium text-slate-800 mb-2">Sampling Phase</div>
              <div className="flex items-center justify-between text-xs text-slate-700 py-1">
                <span>Signals/Orders/Rejects visible</span>
                {healthStatusBadge(acceptance?.acceptance?.sampling_phase?.signals_orders_rejects_visible)}
              </div>
              <div className="flex items-center justify-between text-xs text-slate-700 py-1">
                <span>Reject reason stats</span>
                {healthStatusBadge(acceptance?.acceptance?.sampling_phase?.reject_reason_stats)}
              </div>
              <div className="flex items-center justify-between text-xs text-slate-700 py-1">
                <span>Signal traceable</span>
                {healthStatusBadge(acceptance?.acceptance?.sampling_phase?.signal_traceable)}
              </div>
              <div className="flex items-center justify-between text-xs text-slate-700 py-1">
                <span>/online/update trains</span>
                {healthStatusBadge(acceptance?.acceptance?.sampling_phase?.online_update_training)}
              </div>
            </div>

            <div className="border rounded p-3">
              <div className="text-sm font-medium text-slate-800 mb-2">Profit Phase</div>
              <div className="text-xs text-slate-700">Window days: {Number(acceptance?.acceptance?.profit_phase?.window_days ?? acceptanceProfitDays)}</div>
              <div className="mt-2 flex items-center justify-between text-xs text-slate-700 py-1">
                <span>Has stats</span>
                {healthStatusBadge(acceptance?.acceptance?.profit_phase?.has_stats)}
              </div>
              <div className="mt-2 text-xs text-slate-700">
                PF {(acceptance?.profit_window?.profit_factor_inf ? 'inf' : Number(acceptance?.profit_window?.profit_factor ?? 0).toFixed(3))} · maxDD {Number(acceptance?.profit_window?.max_drawdown_ratio ?? 0).toFixed(3)} · n {Number(acceptance?.profit_window?.n ?? 0)}
              </div>
            </div>

            <div className="border rounded p-3">
              <div className="text-sm font-medium text-slate-800 mb-2">Rollback</div>
              <div className="text-xs text-slate-700">Points: {Number(acceptance?.acceptance?.rollback?.points ?? 0)}</div>
              <div className="mt-3 text-xs text-slate-700">
                Recent: signals {Number(acceptance?.recent?.signals ?? 0)} · orders {Number(acceptance?.recent?.orders ?? 0)} ({Number(acceptance?.recent?.minutes ?? acceptanceRecentMinutes)}m)
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Online Update Orchestration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[160px]">
              <label className="text-xs text-slate-600">max_label</label>
              <Input type="number" value={onlineOrchMaxLabel} onChange={(e) => setOnlineOrchMaxLabel(parseInt(e.target.value || '0', 10) || 0)} />
            </div>
            <div className="min-w-[160px]">
              <label className="text-xs text-slate-600">family</label>
              <Input value={onlineOrchFamily} placeholder="(auto)" onChange={(e) => setOnlineOrchFamily(e.target.value)} />
            </div>
            <label className="text-xs text-slate-600 flex items-center gap-2">
              <input type="checkbox" checked={onlineOrchTrain} onChange={(e) => setOnlineOrchTrain(e.target.checked)} />
              train
            </label>
            <label className="text-xs text-slate-600 flex items-center gap-2">
              <input type="checkbox" checked={onlineOrchForceTrain} onChange={(e) => setOnlineOrchForceTrain(e.target.checked)} />
              force_train
            </label>
            <label className="text-xs text-slate-600 flex items-center gap-2">
              <input type="checkbox" checked={onlineOrchConfirmLive} onChange={(e) => setOnlineOrchConfirmLive(e.target.checked)} />
              confirm_live
            </label>
            <Button
              disabled={onlineOrchRunning}
              onClick={async () => {
                setOnlineOrchRunning(true);
                try {
                  const payload: Record<string, unknown> = {
                    max_label: onlineOrchMaxLabel,
                    train: onlineOrchTrain,
                    force_train: onlineOrchForceTrain,
                  };
                  const fam = String(onlineOrchFamily || '').trim();
                  if (fam) payload.family = fam;
                  if (onlineOrchConfirmLive) payload.confirm_live = true;
                  const res = await runOnlineUpdate(payload);
                  setOnlineOrchResult(res);
                  await queryClient.invalidateQueries({ queryKey: ['eval-acceptance'] });
                  await queryClient.invalidateQueries({ queryKey: ['eval-health'] });
                } finally {
                  setOnlineOrchRunning(false);
                }
              }}
            >
              Run /online/update
            </Button>
          </div>

          {onlineOrchResult && (
            <div className="mt-3 text-xs text-slate-700 space-y-1">
              <div>ok {String(onlineOrchResult.ok)} · ts {onlineOrchResult.ts ? new Date(onlineOrchResult.ts).toLocaleString() : '-'}</div>
              <div>
                label.added {Number(onlineOrchResult.label?.added ?? 0)} · label.matured {Number(onlineOrchResult.label?.matured ?? 0)} · total_samples {Number(onlineOrchResult.label?.total_samples ?? 0)}
              </div>
              <div>
                train.trained {String(Boolean(onlineOrchResult.train?.trained))} · train.family {String(onlineOrchResult.train?.family ?? '')}
              </div>
              <div>
                state.last_train_ms {Number(onlineOrchResult.state?.last_train_ms ?? 0)} · state.train_sample_count {Number(onlineOrchResult.state?.train_sample_count ?? 0)}
              </div>
              {onlineOrchResult.error && (
                <div className="text-red-700">error {String(onlineOrchResult.error)}</div>
              )}
              {onlineOrchResult.train?.error && (
                <div className="text-red-700">train.error {String(onlineOrchResult.train.error)}</div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
