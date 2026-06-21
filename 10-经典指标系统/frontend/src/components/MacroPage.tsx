import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link } from 'react-router-dom';
import { fetchExitLatestFeatures, fetchMacroBtcEthOverview, fetchMacroBtcRegimeBacktest, fetchMacroViz, updateConfig } from '../lib/api';
import type { ExitLatestFeaturesItem, ExitLatestFeaturesResponse, MacroBtcEthOverviewResponse, MacroBtcRegimeBacktestResponse, MacroEnergyRow, MacroFlowRow, MacroTrendRow, MacroVizResponse, MacroVizSignalTagRow, MacroVizShapeHistoryRow } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Input } from './ui/input';

function _toNum(v: unknown, d = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

function _fmt2(x: number, digits = 4): string {
  if (!Number.isFinite(x)) return '-';
  return x.toFixed(digits);
}

function _fmtPct(x: number, digits = 2): string {
  if (!Number.isFinite(x)) return '-';
  return `${(x * 100).toFixed(digits)}%`;
}

function _trendShape(r: MacroTrendRow | null): string {
  if (!r) return '-';
  const v = (r as Record<string, unknown>)['trend_shape_5'];
  return typeof v === 'string' && v.trim() ? v : '-';
}

function _fmtDate(ms: number): string {
  const t = Number(ms);
  if (!Number.isFinite(t) || t <= 0) return '';
  const d = new Date(t);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function _fmtDateTime(ms: number): string {
  const t = Number(ms);
  if (!Number.isFinite(t) || t <= 0) return '';
  const d = new Date(t);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function _regimeToNum(r: unknown): number {
  const s = String(r ?? '').toUpperCase().trim();
  if (s === 'R1') return 1;
  if (s === 'R2') return 2;
  if (s === 'R3') return 3;
  if (s === 'R4') return 4;
  if (s === 'R5') return 5;
  return 3;
}

function _sign3(v: number, dz: number = 0): number {
  if (!Number.isFinite(v)) return 0;
  if (v > dz) return 1;
  if (v < -dz) return -1;
  return 0;
}

function _dcs(x0: number, x1: number, x2: number, dz: number = 0): { dir: number; chg_dir: number; chg_speed: number } {
  const v0 = Number(x0);
  const v1 = Number(x1);
  const v2 = Number(x2);
  if (!Number.isFinite(v0) || !Number.isFinite(v1) || !Number.isFinite(v2)) return { dir: 0, chg_dir: 0, chg_speed: 0 };
  const d0 = v0 - v1;
  const d1 = v1 - v2;
  const dir = _sign3(d0, dz);
  const chg_dir = _sign3(d0 - d1, dz);
  const eps = 1e-12;
  const chg_speed = Math.log(Math.abs(d0) + eps) - Math.log(Math.abs(d1) + eps);
  return { dir, chg_dir, chg_speed };
}

type FactorRow = {
  factor: string;
  value_t: string;
  value_t1: string;
  delta: string;
  direction: string;
  change_direction: string;
  speed: string;
  bucket: string;
};

function _fmtFactorRowNum(v: number | null | undefined, digits = 6): string {
  if (v === null || v === undefined) return '-';
  const x = Number(v);
  if (!Number.isFinite(x)) return '-';
  return _fmt2(x, digits);
}

function _timeFactorRows(rows: MacroTrendRow[]): FactorRow[] {
  const n = rows.length;
  if (n <= 0) return [];
  const r0 = rows[n - 1];
  const r1 = n >= 2 ? rows[n - 2] : null;
  const r2 = n >= 3 ? rows[n - 3] : null;

  const num = (r: MacroTrendRow | null, k: keyof MacroTrendRow): number => {
    if (!r) return Number.NaN;
    const v = (r as Record<string, unknown>)[String(k)];
    const x = Number(v);
    return Number.isFinite(x) ? x : Number.NaN;
  };

  const dirNum = (r: MacroTrendRow | null, k: keyof MacroTrendRow): number => {
    if (!r) return Number.NaN;
    const v = (r as Record<string, unknown>)[String(k)];
    const x = Number(v);
    return Number.isFinite(x) ? x : Number.NaN;
  };

  const makeNumRow = (factor: string, k: keyof MacroTrendRow, kDir?: keyof MacroTrendRow): FactorRow => {
    const v0 = num(r0, k);
    const v1 = num(r1, k);
    const v2 = num(r2, k);
    const d = _dcs(v0, v1, v2);
    const delta = v0 - v1;
    const dir = kDir ? dirNum(r0, kDir) : _sign3(v0, 0);
    return {
      factor,
      value_t: _fmtFactorRowNum(v0),
      value_t1: _fmtFactorRowNum(v1),
      delta: _fmtFactorRowNum(delta),
      direction: String(dir),
      change_direction: String(d.chg_dir),
      speed: _fmtFactorRowNum(d.chg_speed),
      bucket: _trendShape(r0),
    };
  };

  const shapeRow: FactorRow = {
    factor: 'time.trend_shape_5',
    value_t: _trendShape(r0),
    value_t1: _trendShape(r1),
    delta: '-',
    direction: '-',
    change_direction: '-',
    speed: '-',
    bucket: _trendShape(r0),
  };

  return [
    shapeRow,
    makeNumRow('time.trend_w_slope', 'trend_w_slope', 'trend_w_dir'),
    makeNumRow('time.trend_d_slope', 'trend_d_slope', 'trend_d_dir'),
    makeNumRow('time.trend_rate_change_dw', 'trend_rate_change_dw'),
    makeNumRow('time.trend_w_dir', 'trend_w_dir'),
    makeNumRow('time.trend_d_dir', 'trend_d_dir'),
  ];
}

function _energyFactorRows(rows: MacroEnergyRow[], bucket: string): FactorRow[] {
  const n = rows.length;
  if (n <= 0) return [];
  const r0 = rows[n - 1];
  const r1 = n >= 2 ? rows[n - 2] : null;
  const r2 = n >= 3 ? rows[n - 3] : null;

  const num = (r: MacroEnergyRow | null, k: keyof MacroEnergyRow): number => {
    if (!r) return Number.NaN;
    const v = (r as Record<string, unknown>)[String(k)];
    const x = Number(v);
    return Number.isFinite(x) ? x : Number.NaN;
  };

  const obsRow = (factor: string, dirK: keyof MacroEnergyRow, chgDirK: keyof MacroEnergyRow, spK: keyof MacroEnergyRow): FactorRow => {
    const v0 = num(r0, dirK);
    const v1 = num(r1, dirK);
    const delta = v0 - v1;
    const chgDir = num(r0, chgDirK);
    const sp = num(r0, spK);
    return {
      factor,
      value_t: _fmtFactorRowNum(v0, 0),
      value_t1: _fmtFactorRowNum(v1, 0),
      delta: _fmtFactorRowNum(delta, 0),
      direction: Number.isFinite(v0) ? String(Math.trunc(v0)) : '-',
      change_direction: Number.isFinite(chgDir) ? String(Math.trunc(chgDir)) : '-',
      speed: _fmtFactorRowNum(sp),
      bucket,
    };
  };

  const makeNumRow = (factor: string, k: keyof MacroEnergyRow): FactorRow => {
    const v0 = num(r0, k);
    const v1 = num(r1, k);
    const v2 = num(r2, k);
    const d = _dcs(v0, v1, v2);
    const delta = v0 - v1;
    return {
      factor,
      value_t: _fmtFactorRowNum(v0),
      value_t1: _fmtFactorRowNum(v1),
      delta: _fmtFactorRowNum(delta),
      direction: String(d.dir),
      change_direction: String(d.chg_dir),
      speed: _fmtFactorRowNum(d.chg_speed),
      bucket,
    };
  };

  return [
    obsRow('vol.vol_dir', 'vol_dir', 'vol_chg_dir', 'vol_chg_speed'),
    obsRow('mom.mom_dir', 'mom_dir', 'mom_chg_dir', 'mom_chg_speed'),
    obsRow('pot.pot_dir', 'pot_dir', 'pot_chg_dir', 'pot_chg_speed'),
    makeNumRow('mom.macd_hist', 'macd_hist'),
    makeNumRow('mom.ret_1d', 'ret_1d'),
    makeNumRow('mom.ret_3d', 'ret_3d'),
    makeNumRow('mom.rsi_14', 'rsi_14'),
    makeNumRow('vol.volume_ratio', 'volume_ratio'),
    makeNumRow('vol.volume_z', 'volume_z'),
    makeNumRow('pot.adx_14', 'adx_14'),
    makeNumRow('pot.atr_pct', 'atr_pct'),
    makeNumRow('pot.dist_to_ema50', 'dist_to_ema50'),
    makeNumRow('energy.kin_ma', 'kin_ma'),
    makeNumRow('energy.vol_ma', 'vol_ma'),
    makeNumRow('energy.pot_ma', 'pot_ma'),
    makeNumRow('energy.risk_baseline', 'risk_baseline'),
  ];
}

function _flowFactorRows(rows: MacroFlowRow[], bucket: string): FactorRow[] {
  const n = rows.length;
  if (n <= 0) return [];
  const r0 = rows[n - 1];
  const r1 = n >= 2 ? rows[n - 2] : null;
  const r2 = n >= 3 ? rows[n - 3] : null;

  const num = (r: MacroFlowRow | null, k: keyof MacroFlowRow): number => {
    if (!r) return Number.NaN;
    const v = (r as Record<string, unknown>)[String(k)];
    const x = Number(v);
    return Number.isFinite(x) ? x : Number.NaN;
  };

  const makeNumRow = (factor: string, k: keyof MacroFlowRow): FactorRow => {
    const v0 = num(r0, k);
    const v1 = num(r1, k);
    const v2 = num(r2, k);
    const d = _dcs(v0, v1, v2);
    const delta = v0 - v1;
    return {
      factor,
      value_t: _fmtFactorRowNum(v0),
      value_t1: _fmtFactorRowNum(v1),
      delta: _fmtFactorRowNum(delta),
      direction: String(d.dir),
      change_direction: String(d.chg_dir),
      speed: _fmtFactorRowNum(d.chg_speed),
      bucket,
    };
  };

  const obsRow = (factor: string, dirK: keyof MacroFlowRow, chgDirK: keyof MacroFlowRow, spK: keyof MacroFlowRow): FactorRow => {
    const v0 = num(r0, dirK);
    const v1 = num(r1, dirK);
    const delta = v0 - v1;
    const chgDir = num(r0, chgDirK);
    const sp = num(r0, spK);
    return {
      factor,
      value_t: _fmtFactorRowNum(v0, 0),
      value_t1: _fmtFactorRowNum(v1, 0),
      delta: _fmtFactorRowNum(delta, 0),
      direction: Number.isFinite(v0) ? String(Math.trunc(v0)) : '-',
      change_direction: Number.isFinite(chgDir) ? String(Math.trunc(chgDir)) : '-',
      speed: _fmtFactorRowNum(sp),
      bucket,
    };
  };

  return [
    obsRow('flow.macro_flow_dir', 'macro_flow_dir', 'macro_flow_chg_dir', 'macro_flow_chg_speed'),
    makeNumRow('flow.rs_btc_vs_mkt', 'rs_btc_vs_mkt'),
    makeNumRow('flow.rs_eth_vs_mkt', 'rs_eth_vs_mkt'),
    makeNumRow('flow.rs_btc_vs_eth', 'rs_btc_vs_eth'),
  ];
}

export const MacroPage: React.FC = () => {
  const qc = useQueryClient();
  const [btLookbackDays, setBtLookbackDays] = useState<number>(400);
  const [btFlowLookbackDays, setBtFlowLookbackDays] = useState<number>(240);
  const [btRmidQ, setBtRmidQ] = useState<number>(0.6);
  const [btRhighQ, setBtRhighQ] = useState<number>(0.8);
  const [btAtrP80Q, setBtAtrP80Q] = useState<number>(0.8);
  const [btAtrP95Q, setBtAtrP95Q] = useState<number>(0.95);
  const [btDomQ, setBtDomQ] = useState<number>(0.8);

  const [vizShapeN, setVizShapeN] = useState<number>(60);
  const [vizSignalWindowH, setVizSignalWindowH] = useState<number>(6);
  const [budgetTargetMode, setBudgetTargetMode] = useState<'tri_layer' | 'shape12h_baseline' | 'dual'>('dual');
  const [cfgWriteMsg, setCfgWriteMsg] = useState<string>('');

  const [btApplied, setBtApplied] = useState<{
    lookback_days: number;
    flow_lookback_days: number;
    r_mid_q: number;
    r_high_q: number;
    atr_p80_q: number;
    atr_p95_q: number;
    dom_q: number;
  }>(() => ({
    lookback_days: 400,
    flow_lookback_days: 240,
    r_mid_q: 0.6,
    r_high_q: 0.8,
    atr_p80_q: 0.8,
    atr_p95_q: 0.95,
    dom_q: 0.8,
  }));

  const { data } = useQuery({
    queryKey: ['macro', 'btceth', 400, 240],
    queryFn: () => fetchMacroBtcEthOverview({ lookback_days: 400, flow_lookback_days: 240 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
  });

  const cfgMutation = useMutation({
    mutationFn: (payload: { entry_macro_btceth_hard_gate_enabled?: boolean; entry_macro_btceth_shape_enabled?: boolean }) => updateConfig(payload),
    onMutate: () => {
      setCfgWriteMsg('saving…');
    },
    onSuccess: (res) => {
      const applied = (res && typeof res === 'object' && 'applied_keys' in res) ? (res as { applied_keys?: unknown }).applied_keys : undefined;
      const n = Array.isArray(applied) ? applied.length : 0;
      setCfgWriteMsg(n > 0 ? `saved (${String(n)})` : 'saved');
      qc.invalidateQueries({ queryKey: ['macro', 'btceth'] });
    },
    onError: (err) => {
      const resp = typeof err === 'object' && err && 'response' in err ? (err as { response?: unknown }).response : undefined;
      const status = typeof resp === 'object' && resp && 'status' in resp ? (resp as { status?: unknown }).status : undefined;
      const data0 = typeof resp === 'object' && resp && 'data' in resp ? (resp as { data?: unknown }).data : undefined;
      const apiError = typeof data0 === 'object' && data0 && 'error' in data0 ? (data0 as { error?: unknown }).error : undefined;
      const message = typeof err === 'object' && err && 'message' in err ? (err as { message?: unknown }).message : undefined;
      const msg = String(apiError ?? message ?? err);
      if (String(status ?? '') === '403' || msg.toLowerCase().includes('forbidden')) {
        setCfgWriteMsg('forbidden: 需要 execute_token');
      } else {
        setCfgWriteMsg(`error: ${msg}`);
      }
    },
  });

  const { data: bt } = useQuery({
    queryKey: ['macro', 'btc', 'regime_backtest', btApplied],
    queryFn: () => fetchMacroBtcRegimeBacktest(btApplied),
    refetchInterval: 0,
    refetchOnWindowFocus: false,
  });

  const { data: exitLatest } = useQuery({
    queryKey: ['exit', 'features', 'latest', 'macro', true],
    queryFn: () => fetchExitLatestFeatures({ include_macro: true }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
  });

  const { data: viz } = useQuery({
    queryKey: ['macro', 'viz', vizShapeN, vizSignalWindowH],
    queryFn: () => fetchMacroViz({ shape_n: Math.max(1, Math.min(240, Math.trunc(vizShapeN || 60))), signal_window_h: Math.max(1, Math.min(168, Math.trunc(vizSignalWindowH || 6))) }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
  });

  const d = (data as MacroBtcEthOverviewResponse | undefined);

  const btcTrend = useMemo(() => (d?.btc?.trend?.rows ?? []) as MacroTrendRow[], [d]);
  const ethTrend = useMemo(() => (d?.eth?.trend?.rows ?? []) as MacroTrendRow[], [d]);
  const btcEnergy = useMemo(() => (d?.btc?.energy?.rows ?? []) as MacroEnergyRow[], [d]);
  const ethEnergy = useMemo(() => (d?.eth?.energy?.rows ?? []) as MacroEnergyRow[], [d]);
  const flow = useMemo(() => (d?.flow?.rows ?? []) as MacroFlowRow[], [d]);

  const btD = (bt as MacroBtcRegimeBacktestResponse | undefined);
  const btRows = useMemo(() => (btD?.rows ?? []).filter((r) => Number(r?.ts ?? 0) > 0), [btD]);
  const btChart = useMemo(() => {
    return btRows.map((r) => {
      const ts = Number(r.ts);
      const close = r.close === null || r.close === undefined ? null : Number(r.close);
      const regime = String(r.regime ?? 'R3');
      const regime_num = _regimeToNum(regime);
      return {
        ts,
        close: Number.isFinite(close) ? close : null,
        regime,
        regime_num,
        fwd_ret_1d: r.fwd_ret_1d === null || r.fwd_ret_1d === undefined ? null : Number(r.fwd_ret_1d),
      };
    });
  }, [btRows]);

  const lastFlow = flow.length ? flow[flow.length - 1] : null;
  const lastBtcTrend = btcTrend.length ? btcTrend[btcTrend.length - 1] : null;
  const lastEthTrend = ethTrend.length ? ethTrend[ethTrend.length - 1] : null;
  const lastBtcEnergy = btcEnergy.length ? btcEnergy[btcEnergy.length - 1] : null;
  const lastEthEnergy = ethEnergy.length ? ethEnergy[ethEnergy.length - 1] : null;

  const std1h = d?.std_1h;
  const std12h = d?.std_12h;
  const std1d = d?.std_1d;
  const stdShape = d?.std_shape;
  const stdShapeUpdateHours = (typeof d?.std_shape_update_hours === 'number' && Number.isFinite(d.std_shape_update_hours))
    ? Math.max(1, Math.trunc(d.std_shape_update_hours))
    : null;
  const stdShapeLabel = (stdShapeUpdateHours !== null && stdShapeUpdateHours > 1) ? `std${String(stdShapeUpdateHours)}h` : 'std1h';
  const showStdShape = (stdShapeUpdateHours !== null && stdShapeUpdateHours > 1);

  const std1hTs = _toNum(std1h?.ts, 0);
  const std1hBtcRisk = std1h?.btc?.risk_pct ?? null;
  const std1hBtcValue = std1h?.btc?.value_pct ?? null;
  const std1hBtcDir = typeof std1h?.btc?.dir === 'number' ? Number(std1h?.btc?.dir) : null;
  const std1hEthRisk = std1h?.eth?.risk_pct ?? null;
  const std1hEthValue = std1h?.eth?.value_pct ?? null;
  const std1hValid = (std1h?.valid === true);

  const std12hBtcRisk = std12h?.btc?.risk_pct ?? null;
  const std12hBtcValue = std12h?.btc?.value_pct ?? null;
  const std12hBtcDir = typeof std12h?.btc?.dir === 'number' ? Number(std12h?.btc?.dir) : null;
  const std12hEthRisk = std12h?.eth?.risk_pct ?? null;
  const std12hEthValue = std12h?.eth?.value_pct ?? null;
  const std1dTs = _toNum(std1d?.ts, 0);
  const std1dBtcRisk = std1d?.btc?.risk_pct ?? null;
  const std1dBtcValue = std1d?.btc?.value_pct ?? null;

  const stdShapeTs = _toNum(stdShape?.ts, 0);

  const macroShape = d?.macro_btceth_shape ?? null;
  const macroShapeEnabled = macroShape?.enabled === true;
  const macroShapeValid = macroShape?.valid === true;
  const macroShapeName = typeof macroShape?.shape === 'string' && macroShape.shape.trim() ? macroShape.shape.trim() : null;
  const macroShapeRiskBucket = typeof macroShape?.risk_bucket === 'string' && macroShape.risk_bucket.trim() ? macroShape.risk_bucket.trim() : null;
  const macroShapeValueBucket = typeof macroShape?.value_bucket === 'string' && macroShape.value_bucket.trim() ? macroShape.value_bucket.trim() : null;
  const macroShapeNext = typeof macroShape?.shape_next === 'string' && macroShape.shape_next.trim() ? macroShape.shape_next.trim() : null;
  const macroShapeRiskBucketNext = typeof macroShape?.risk_bucket_next === 'string' && macroShape.risk_bucket_next.trim() ? macroShape.risk_bucket_next.trim() : null;
  const macroShapeValueBucketNext = typeof macroShape?.value_bucket_next === 'string' && macroShape.value_bucket_next.trim() ? macroShape.value_bucket_next.trim() : null;
  const macroShapeCand = typeof macroShape?.shape_candidate === 'string' && macroShape.shape_candidate.trim() ? macroShape.shape_candidate.trim() : null;
  const macroShapeCandN = (typeof macroShape?.shape_candidate_n === 'number' && Number.isFinite(macroShape.shape_candidate_n)) ? Math.trunc(macroShape.shape_candidate_n) : null;
  const macroShapePersistBars = (typeof macroShape?.shape_persist_bars === 'number' && Number.isFinite(macroShape.shape_persist_bars)) ? Math.trunc(macroShape.shape_persist_bars) : null;
  const macroShapePending = (macroShapeNext && macroShapeName && macroShapeNext !== macroShapeName) ? macroShapeNext : null;

  const gateStd1h = d?.gate_std1h ?? null;
  const gateStd1hRec = typeof gateStd1h?.recommend === 'string' && gateStd1h.recommend.trim() ? gateStd1h.recommend.trim() : null;
  const gateStd1hEffRec = typeof gateStd1h?.effective_recommend === 'string' && gateStd1h.effective_recommend.trim()
    ? gateStd1h.effective_recommend.trim()
    : null;
  const gateCfg = d?.gate_config ?? null;
  const gateEnabled = gateCfg?.enabled === true;
  const triLayer = d?.macro_tri_layer ?? null;
  const triTs = _toNum(triLayer?.ts, 0);
  const trendDirW = _toNum(triLayer?.dir_w, _toNum(triLayer?.dir_h, 0));
  const trendDirD = _toNum(triLayer?.dir_d, _toNum(triLayer?.dir_h, 0));
  const chgDirW = _toNum(triLayer?.chg_dir_w, 0);
  const chgDirD = _toNum(triLayer?.chg_dir_d, 0);
  const chgDir1hN = _toNum(triLayer?.dir_short, 0);
  const chgSpeedW = _toNum(triLayer?.chg_speed_w, Number.NaN);
  const chgSpeedD = _toNum(triLayer?.chg_speed_d, Number.NaN);
  const chgStrength1h = _toNum(triLayer?.chg_strength, Number.NaN);
  const riskD = _toNum(triLayer?.risk_d, Number.NaN);
  const risk1h = _toNum(triLayer?.risk_1h, Number.NaN);
  const riskBudgetTier = String(triLayer?.risk_budget_tier ?? '-');
  const crashSwitch = triLayer?.crash_switch === true;
  const triTargetNetBias = _toNum(triLayer?.target_net_bias, Number.NaN);
  const triMaxNetExposure = _toNum(triLayer?.max_net_exposure, Number.NaN);
  const triAllowOpen = triLayer?.allow_open === true;
  const triAllowAddon = triLayer?.allow_addon === true;
  const std12hTs = _toNum(std12h?.ts, 0);
  const dayRiskBtcView = Number.isFinite(riskD) ? riskD : _toNum(std1dBtcRisk, _toNum(std12hBtcRisk, Number.NaN));
  const dayValueBtcView = _toNum(std1dBtcValue, _toNum(std12hBtcValue, Number.NaN));
  const h1RiskBtcView = Number.isFinite(risk1h) ? risk1h : _toNum(std1hBtcRisk, Number.NaN);
  const h1ValueBtcView = _toNum(std1hBtcValue, Number.NaN);

  const rsBtc = lastFlow?.rs_btc_vs_mkt ?? null;
  const rsEth = lastFlow?.rs_eth_vs_mkt ?? null;
  const rsBtcEth = lastFlow?.rs_btc_vs_eth ?? null;

  const btcTimeRows = useMemo(() => _timeFactorRows(btcTrend), [btcTrend]);
  const ethTimeRows = useMemo(() => _timeFactorRows(ethTrend), [ethTrend]);

  const btcEnergyRows = useMemo(() => _energyFactorRows(btcEnergy, _trendShape(lastBtcTrend)), [btcEnergy, lastBtcTrend]);
  const ethEnergyRows = useMemo(() => _energyFactorRows(ethEnergy, _trendShape(lastEthTrend)), [ethEnergy, lastEthTrend]);

  const flowRows = useMemo(() => _flowFactorRows(flow, _trendShape(lastBtcTrend)), [flow, lastBtcTrend]);

  const exitD = (exitLatest as ExitLatestFeaturesResponse | undefined);
  const exitItems = useMemo(() => (exitD?.items ?? []) as ExitLatestFeaturesItem[], [exitD]);
  const exitRows = useMemo(() => {
    const rows: {
      pair: string;
      side: string | null;
      owner: string | null;
      mrd_dir: string | null;
      p_dir: number | null;
      hold_risk: number | null;
      hold_value: number | null;
      action: string | null;
      reason: string | null;
    }[] = [];
    for (const it of exitItems) {
      const pair = String(it?.pair ?? '').trim();
      if (!pair) continue;

      const sideRaw = typeof it?.side === 'string' ? it.side.trim() : '';
      const side = sideRaw ? sideRaw : null;

      const ownerRaw = typeof it?.exit_owner === 'string' ? it.exit_owner.trim() : '';
      const owner = ownerRaw ? ownerRaw : null;

      const hr = typeof it?.hold_risk === 'number' && Number.isFinite(it.hold_risk) ? it.hold_risk : null;
      const hv = typeof it?.hold_value === 'number' && Number.isFinite(it.hold_value) ? it.hold_value : null;

      const feats = (it?.features ?? {}) as Record<string, unknown>;
      const mrdDirRaw = feats?.macro_mrd_dir;
      const mrd_dir = typeof mrdDirRaw === 'string' && mrdDirRaw ? mrdDirRaw : null;
      const pDir = typeof feats?.macro_p_mrd_dir === 'number' ? feats?.macro_p_mrd_dir : Number.NaN;

      const l1 = (it?.l1_decision ?? null) as Record<string, unknown> | null;
      const action = l1 && typeof l1.action === 'string' ? l1.action : null;
      const reason = l1 && typeof l1.reason === 'string' ? l1.reason : null;
      rows.push({
        pair,
        side,
        owner,
        mrd_dir,
        p_dir: Number.isFinite(pDir) ? pDir : null,
        hold_risk: hr,
        hold_value: hv,
        action,
        reason,
      });
    }
    rows.sort((a, b) => {
      const ap = a.p_dir ?? 0;
      const bp = b.p_dir ?? 0;
      return bp - ap;
    });
    return rows.slice(0, 12);
  }, [exitItems]);

  const vizD = (viz as MacroVizResponse | undefined);
  const shapeSnap = (vizD?.shape12h?.snapshot ?? null) as Record<string, unknown> | null;
  const shapeHist = useMemo(() => (vizD?.shape12h?.history ?? []) as MacroVizShapeHistoryRow[], [vizD]);
  const shapeChart = useMemo(() => {
    return shapeHist
      .filter((r) => Number(r?.ts ?? 0) > 0)
      .map((r) => ({
        ts: Number(r.ts),
        risk_w: r.risk_w === null || r.risk_w === undefined ? null : Number(r.risk_w),
        value_w: r.value_w === null || r.value_w === undefined ? null : Number(r.value_w),
        dir_score: r.dir_score === null || r.dir_score === undefined ? null : Number(r.dir_score),
        dir_12h: r.dir_12h === null || r.dir_12h === undefined ? null : Number(r.dir_12h),
        shape: typeof r.shape === 'string' ? r.shape : null,
        shape_tier: r.shape_tier === null || r.shape_tier === undefined ? null : Number(r.shape_tier),
      }));
  }, [shapeHist]);

  const shapeTail = useMemo(() => {
    const xs = shapeChart.filter((r) => Number(r.ts) > 0);
    return xs.slice(Math.max(0, xs.length - 12));
  }, [shapeChart]);

  const snapParams = (shapeSnap?.params ?? null) as Record<string, unknown> | null;
  const snapRiskLow = snapParams ? _toNum(snapParams.risk_low, Number.NaN) : Number.NaN;
  const snapRiskHigh = snapParams ? _toNum(snapParams.risk_high, Number.NaN) : Number.NaN;
  const snapValueBear = snapParams ? _toNum(snapParams.value_bear, Number.NaN) : Number.NaN;
  const snapValueBull = snapParams ? _toNum(snapParams.value_bull, Number.NaN) : Number.NaN;
  const snapScoreMin = _toNum(shapeSnap?.score_min, Number.NaN);

  const snapShape = typeof shapeSnap?.shape === 'string' ? String(shapeSnap.shape) : null;
  const snapTier = typeof shapeSnap?.shape_tier === 'number' && Number.isFinite(shapeSnap.shape_tier) ? Math.trunc(shapeSnap.shape_tier) : null;
  const snapDir = typeof shapeSnap?.dir_12h === 'number' && Number.isFinite(shapeSnap.dir_12h) ? Math.trunc(shapeSnap.dir_12h) : null;
  const snapDirScore = typeof shapeSnap?.dir_score === 'number' && Number.isFinite(shapeSnap.dir_score) ? Number(shapeSnap.dir_score) : null;
  const snapTs = typeof shapeSnap?.ts === 'number' && Number.isFinite(shapeSnap.ts) ? Math.trunc(shapeSnap.ts) : null;
  const triVizSnap = (vizD?.tri_layer?.snapshot ?? null) as Record<string, unknown> | null;
  const triVizDirW = _toNum(triVizSnap?.dir_w, Number.NaN);
  const triVizDirD = _toNum(triVizSnap?.dir_d, Number.NaN);
  const triTrace = (vizD?.tri_layer?.trace ?? null) as Record<string, unknown> | null;
  const triReasonMatch = triTrace?.reason_match === true;
  const triTraceWarning = typeof triTrace?.warning === 'string' ? String(triTrace.warning) : '';
  const triTarget = (vizD?.position_budget?.tri_layer_target ?? null) as Record<string, unknown> | null;
  const triTargetGrossBudget = _toNum(triTarget?.target_gross_budget, Number.NaN);
  const triLayerTargetNetBias = _toNum(triTarget?.target_net_bias, Number.NaN);
  const triTargetLongShare = _toNum(triTarget?.target_long_share, Number.NaN);
  const triTargetShortShare = _toNum(triTarget?.target_short_share, Number.NaN);
  const shapeBaseline = (vizD?.position_budget?.shape12h_baseline ?? null) as Record<string, unknown> | null;
  const shapeBaselineGrossBudget = _toNum(shapeBaseline?.target_gross_budget, Number.NaN);
  const shapeBaselineNetBias = _toNum(shapeBaseline?.target_net_bias, Number.NaN);
  const shapeBaselineLongShare = _toNum(shapeBaseline?.target_long_share, Number.NaN);
  const shapeBaselineShortShare = _toNum(shapeBaseline?.target_short_share, Number.NaN);
  const targetSource = String(vizD?.position_budget?.target?.target_source ?? '');
  const targetIsShapeBaseline = targetSource === 'shape12h_baseline';
  const shapeTriDirConflict = useMemo(() => {
    if (!Number.isFinite(Number(snapDir))) return false;
    const d12 = Math.trunc(Number(snapDir));
    const dw = Number.isFinite(triVizDirW) ? Math.trunc(triVizDirW) : 0;
    const dd = Number.isFinite(triVizDirD) ? Math.trunc(triVizDirD) : 0;
    if (dw !== 0 && d12 !== 0 && dw !== d12) return true;
    if (dd !== 0 && d12 !== 0 && dd !== d12) return true;
    return false;
  }, [snapDir, triVizDirD, triVizDirW]);

  const targetLongShare = _toNum(vizD?.position_budget?.target?.target_long_share, Number.NaN);
  const targetShortShare = _toNum(vizD?.position_budget?.target?.target_short_share, Number.NaN);
  const targetNetBias = _toNum(vizD?.position_budget?.target?.target_net_bias, Number.NaN);
  const targetGrossBudget = _toNum(vizD?.position_budget?.target?.target_gross_budget, Number.NaN);
  const viewTargetGrossBudget = useMemo(() => {
    if (budgetTargetMode === 'tri_layer') return triTargetGrossBudget;
    if (budgetTargetMode === 'shape12h_baseline') return shapeBaselineGrossBudget;
    return targetGrossBudget;
  }, [budgetTargetMode, shapeBaselineGrossBudget, targetGrossBudget, triTargetGrossBudget]);
  const viewTargetNetBias = useMemo(() => {
    if (budgetTargetMode === 'tri_layer') return triLayerTargetNetBias;
    if (budgetTargetMode === 'shape12h_baseline') return shapeBaselineNetBias;
    return targetNetBias;
  }, [budgetTargetMode, shapeBaselineNetBias, targetNetBias, triLayerTargetNetBias]);
  const viewTargetLongShare = useMemo(() => {
    if (budgetTargetMode === 'tri_layer') return triTargetLongShare;
    if (budgetTargetMode === 'shape12h_baseline') return shapeBaselineLongShare;
    return targetLongShare;
  }, [budgetTargetMode, shapeBaselineLongShare, targetLongShare, triTargetLongShare]);
  const viewTargetShortShare = useMemo(() => {
    if (budgetTargetMode === 'tri_layer') return triTargetShortShare;
    if (budgetTargetMode === 'shape12h_baseline') return shapeBaselineShortShare;
    return targetShortShare;
  }, [budgetTargetMode, shapeBaselineShortShare, targetShortShare, triTargetShortShare]);

  const currentLongShare = _toNum(vizD?.position_budget?.current?.long_share, Number.NaN);
  const currentShortShare = _toNum(vizD?.position_budget?.current?.short_share, Number.NaN);
  const currentNetBias = _toNum(vizD?.position_budget?.current?.net_bias, Number.NaN);
  const currentGrossUsdc = _toNum(vizD?.position_budget?.current?.gross_usdc, Number.NaN);
  const currentLongUsdc = _toNum(vizD?.position_budget?.current?.long_usdc, Number.NaN);
  const currentShortUsdc = _toNum(vizD?.position_budget?.current?.short_usdc, Number.NaN);
  const currentNetUsdc = _toNum(vizD?.position_budget?.current?.net_usdc, Number.NaN);

  const targetLongUsdc = useMemo(() => {
    if (!Number.isFinite(viewTargetGrossBudget) || !Number.isFinite(viewTargetLongShare)) return Number.NaN;
    return Number(viewTargetGrossBudget) * Number(viewTargetLongShare);
  }, [viewTargetGrossBudget, viewTargetLongShare]);

  const targetShortUsdc = useMemo(() => {
    if (!Number.isFinite(viewTargetGrossBudget) || !Number.isFinite(viewTargetShortShare)) return Number.NaN;
    return Number(viewTargetGrossBudget) * Number(viewTargetShortShare);
  }, [viewTargetGrossBudget, viewTargetShortShare]);

  const budgetBars = useMemo(() => {
    const rows: { name: string; long: number; short: number }[] = [];
    if ((budgetTargetMode === 'tri_layer' || budgetTargetMode === 'dual') && Number.isFinite(triTargetLongShare) && Number.isFinite(triTargetShortShare)) {
      rows.push({ name: '目标(tri)', long: triTargetLongShare, short: triTargetShortShare });
    }
    if ((budgetTargetMode === 'shape12h_baseline' || budgetTargetMode === 'dual') && Number.isFinite(shapeBaselineLongShare) && Number.isFinite(shapeBaselineShortShare)) {
      rows.push({ name: '目标(shape)', long: shapeBaselineLongShare, short: shapeBaselineShortShare });
    }
    if (budgetTargetMode !== 'dual' && Number.isFinite(viewTargetLongShare) && Number.isFinite(viewTargetShortShare) && rows.length === 0) {
      rows.push({ name: '目标', long: viewTargetLongShare, short: viewTargetShortShare });
    }
    if (Number.isFinite(currentLongShare) && Number.isFinite(currentShortShare)) rows.push({ name: '当前', long: currentLongShare, short: currentShortShare });
    return rows;
  }, [budgetTargetMode, triTargetLongShare, triTargetShortShare, shapeBaselineLongShare, shapeBaselineShortShare, viewTargetLongShare, viewTargetShortShare, currentLongShare, currentShortShare]);

  const budgetAdvice = useMemo(() => {
    const adv: { level: 'ok' | 'warn'; text: string }[] = [];
    const tg = viewTargetGrossBudget;
    const cg = currentGrossUsdc;
    const tn = viewTargetNetBias;
    const cn = currentNetBias;

    if (Number.isFinite(tg) && Number.isFinite(cg) && tg > 0) {
      const ratio = cg / tg;
      if (ratio >= 1.15) adv.push({ level: 'warn', text: '总仓位偏高，建议降 gross' });
      else if (ratio <= 0.80) adv.push({ level: 'warn', text: '总仓位偏低，可能错过行情' });
      else adv.push({ level: 'ok', text: '总仓位接近目标' });
    }

    if (Number.isFinite(tn) && Number.isFinite(cn)) {
      const d = cn - tn;
      if (d >= 0.15) adv.push({ level: 'warn', text: '净偏多偏离，建议减多/加空' });
      else if (d <= -0.15) adv.push({ level: 'warn', text: '净偏空偏离，建议减空/加多' });
      else adv.push({ level: 'ok', text: '净敞口接近目标' });
    }

    return adv.slice(0, 3);
  }, [viewTargetGrossBudget, currentGrossUsdc, viewTargetNetBias, currentNetBias]);

  const signalRows = useMemo(() => (vizD?.signals?.by_tag ?? []) as MacroVizSignalTagRow[], [vizD]);
  const topReasons = useMemo(() => (vizD?.signals?.top_suppressed_reasons ?? []) as { key: string; count: number }[], [vizD]);
  const topMacroReasons = useMemo(() => (vizD?.signals?.top_macro_related_reasons ?? []) as { key: string; count: number }[], [vizD]);
  const topGroups = useMemo(() => (vizD?.signals?.top_suppressed_groups ?? []) as { key: string; count: number }[], [vizD]);
  const topStrategies = useMemo(() => (vizD?.signals?.top_suppressed_strategies ?? []) as { key: string; count: number }[], [vizD]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>宏观可视化</span>
            <div className="flex gap-2 items-center">
              <div className="flex items-center gap-1">
                {[1, 6, 24].map((h) => (
                  <Button
                    key={h}
                    variant={vizSignalWindowH === h ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setVizSignalWindowH(h)}
                  >
                    {h}h
                  </Button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <div className="text-xs text-slate-500">shape_n</div>
                <Input className="w-24" value={String(vizShapeN)} onChange={(e) => setVizShapeN(Number(e.target.value))} />
              </div>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 border rounded p-3 bg-white space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">图 1：中周期趋势方向（12H）</div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">兼容层 Shape12H</Badge>
                  {snapShape ? <Badge variant="outline">{snapShape}{snapTier !== null ? ` / shape_tier ${snapTier}` : ''}</Badge> : <Badge variant="outline">-</Badge>}
                  {snapDir !== null ? <Badge variant={snapDir > 0 ? 'default' : snapDir < 0 ? 'destructive' : 'secondary'}>{snapDir > 0 ? 'LONG' : snapDir < 0 ? 'SHORT' : 'NEUTRAL'}</Badge> : null}
                </div>
              </div>
              {shapeTriDirConflict ? <div className="text-xs text-amber-700">口径提示：Shape12H 的 dir 与 tri-layer 的 DirW/DirD 不一致，请以三维主口径解释交易动作。</div> : null}
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={shapeChart} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="ts" tickFormatter={(v) => _fmtDate(Number(v))} />
                    <YAxis yAxisId="p" domain={[0, 1]} tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`} />
                    <YAxis yAxisId="d" orientation="right" domain={[-0.2, 0.2]} tickFormatter={(v) => _fmt2(Number(v), 3)} />
                    <Tooltip
                      labelFormatter={(v) => _fmtDateTime(Number(v))}
                      formatter={(val: unknown, name?: string) => {
                        const k = String(name ?? '');
                        if (val === null || val === undefined) return '-';
                        if (k === 'dir_score') return _fmt2(Number(val), 4);
                        return _fmtPct(Number(val), 2);
                      }}
                    />
                    <Legend />
                    {Number.isFinite(snapRiskLow) ? <ReferenceLine yAxisId="p" y={snapRiskLow} stroke="#94a3b8" strokeDasharray="3 3" /> : null}
                    {Number.isFinite(snapRiskHigh) ? <ReferenceLine yAxisId="p" y={snapRiskHigh} stroke="#94a3b8" strokeDasharray="3 3" /> : null}
                    {Number.isFinite(snapValueBear) ? <ReferenceLine yAxisId="p" y={snapValueBear} stroke="#cbd5e1" strokeDasharray="3 3" /> : null}
                    {Number.isFinite(snapValueBull) ? <ReferenceLine yAxisId="p" y={snapValueBull} stroke="#cbd5e1" strokeDasharray="3 3" /> : null}
                    {Number.isFinite(snapScoreMin) ? <ReferenceLine yAxisId="d" y={snapScoreMin} stroke="#9ca3af" strokeDasharray="3 3" /> : null}
                    {Number.isFinite(snapScoreMin) ? <ReferenceLine yAxisId="d" y={-snapScoreMin} stroke="#9ca3af" strokeDasharray="3 3" /> : null}
                    <Line yAxisId="p" type="monotone" dataKey="risk_w" name="risk_w" stroke="#f97316" dot={false} strokeWidth={2} />
                    <Line yAxisId="p" type="monotone" dataKey="value_w" name="value_w" stroke="#2563eb" dot={false} strokeWidth={2} />
                    <Line yAxisId="d" type="monotone" dataKey="dir_score" name="dir_score" stroke="#111827" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <div className="flex flex-wrap gap-2 pt-1">
                {shapeTail.map((r) => (
                  <Badge key={String(r.ts)} variant="outline">
                    {_fmtDate(Number(r.ts))} {r.shape ?? '-'}{r.shape_tier === null || r.shape_tier === undefined ? '' : ` / t${String(Math.trunc(Number(r.shape_tier)))}`}
                  </Badge>
                ))}
              </div>
            </div>

            <div className="border rounded p-3 bg-white space-y-2">
              <div className="text-sm font-semibold">快照</div>
              <div className="text-sm grid grid-cols-2 gap-x-4 gap-y-1">
                <div className="flex justify-between"><span className="text-slate-500">ts</span><span>{snapTs !== null ? _fmtDateTime(snapTs) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">persist</span><span>{vizD?.shape12h?.persist_bars ?? '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">risk_sys</span><span>{_fmt2(_toNum(shapeSnap?.risk_sys, Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">risk_stress</span><span>{_fmt2(_toNum(shapeSnap?.risk_stress, Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">risk_w</span><span>{_fmt2(_toNum(shapeSnap?.risk_w, Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">value_w</span><span>{_fmt2(_toNum(shapeSnap?.value_w, Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">dir_score</span><span>{snapDirScore !== null ? _fmt2(snapDirScore, 4) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">score_min</span><span>{Number.isFinite(snapScoreMin) ? _fmt2(snapScoreMin, 4) : '-'}</span></div>
              </div>
              <div className="pt-2">
                <div className="text-xs text-slate-500">dir_score 强度</div>
                <div className="h-2 bg-slate-200 rounded">
                  <div
                    className={`h-2 rounded ${snapDirScore !== null && snapDirScore > 0 ? 'bg-emerald-500' : snapDirScore !== null && snapDirScore < 0 ? 'bg-rose-500' : 'bg-slate-500'}`}
                    style={{
                      width: `${snapDirScore === null ? 0 : Math.max(0, Math.min(100, (Math.abs(snapDirScore) / 0.2) * 100))}%`,
                    }}
                  />
                </div>
              </div>
              <div className="pt-2 text-xs text-slate-500">
                阈值：risk [{Number.isFinite(snapRiskLow) ? _fmt2(snapRiskLow, 3) : '-'}, {Number.isFinite(snapRiskHigh) ? _fmt2(snapRiskHigh, 3) : '-'}] / value [{Number.isFinite(snapValueBear) ? _fmt2(snapValueBear, 3) : '-'}, {Number.isFinite(snapValueBull) ? _fmt2(snapValueBull, 3) : '-'}]
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mt-4">
            <div className="border rounded p-3 bg-white space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">图 2：多空仓位预计比例（目标 vs 当前）</div>
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-1">
                    <Button variant={budgetTargetMode === 'tri_layer' ? 'default' : 'outline'} size="sm" onClick={() => setBudgetTargetMode('tri_layer')}>tri_layer</Button>
                    <Button variant={budgetTargetMode === 'shape12h_baseline' ? 'default' : 'outline'} size="sm" onClick={() => setBudgetTargetMode('shape12h_baseline')}>shape12h_baseline</Button>
                    <Button variant={budgetTargetMode === 'dual' ? 'default' : 'outline'} size="sm" onClick={() => setBudgetTargetMode('dual')}>对照双显</Button>
                  </div>
                  <Badge variant={targetSource === 'tri_layer' ? 'default' : 'destructive'}>target_source {targetSource || '-'}</Badge>
                  {Number.isFinite(viewTargetGrossBudget) ? <Badge variant="outline">目标 gross {_fmt2(viewTargetGrossBudget, 0)}</Badge> : null}
                  {Number.isFinite(currentGrossUsdc) ? <Badge variant="outline">当前 gross {_fmt2(currentGrossUsdc, 0)}</Badge> : null}
                </div>
              </div>
              {targetIsShapeBaseline ? <div className="text-xs text-rose-700">强提醒：当前图2主target来源来自 Shape12H 基线，不是三维目标。</div> : null}
              <div className="text-xs text-slate-500">
                三维对照：gross {Number.isFinite(triTargetGrossBudget) ? _fmt2(triTargetGrossBudget, 0) : '-'} · net_bias {Number.isFinite(triLayerTargetNetBias) ? _fmt2(triLayerTargetNetBias, 3) : '-'} ｜ Shape12H基线：gross {Number.isFinite(shapeBaselineGrossBudget) ? _fmt2(shapeBaselineGrossBudget, 0) : '-'} · net_bias {Number.isFinite(shapeBaselineNetBias) ? _fmt2(shapeBaselineNetBias, 3) : '-'}
              </div>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={budgetBars} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`} />
                    <Tooltip formatter={(val: unknown) => (val === null || val === undefined ? '-' : _fmtPct(Number(val), 1))} />
                    <Legend />
                    <Bar dataKey="long" name="Long" stackId="a" fill="#10b981" />
                    <Bar dataKey="short" name="Short" stackId="a" fill="#ef4444" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="flex flex-wrap gap-2">
                {budgetAdvice.map((x, i) => (
                  <Badge key={String(i)} variant={x.level === 'warn' ? 'destructive' : 'secondary'}>
                    {x.text}
                  </Badge>
                ))}
              </div>

              <div className="text-sm grid grid-cols-2 gap-x-4 gap-y-1">
                <div className="flex justify-between"><span className="text-slate-500">target_net_bias</span><span>{Number.isFinite(viewTargetNetBias) ? _fmt2(viewTargetNetBias, 3) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">current_net_bias</span><span>{Number.isFinite(currentNetBias) ? _fmt2(currentNetBias, 3) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Δ net_bias</span><span>{Number.isFinite(viewTargetNetBias) && Number.isFinite(currentNetBias) ? _fmt2(currentNetBias - viewTargetNetBias, 3) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Δ gross</span><span>{Number.isFinite(viewTargetGrossBudget) && Number.isFinite(currentGrossUsdc) ? _fmt2(currentGrossUsdc - viewTargetGrossBudget, 0) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">target_long_usdc</span><span>{Number.isFinite(targetLongUsdc) ? _fmt2(targetLongUsdc, 0) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">target_short_usdc</span><span>{Number.isFinite(targetShortUsdc) ? _fmt2(targetShortUsdc, 0) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">current_long_usdc</span><span>{Number.isFinite(currentLongUsdc) ? _fmt2(currentLongUsdc, 0) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">current_short_usdc</span><span>{Number.isFinite(currentShortUsdc) ? _fmt2(currentShortUsdc, 0) : '-'}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">current_net_usdc</span><span>{Number.isFinite(currentNetUsdc) ? _fmt2(currentNetUsdc, 0) : '-'}</span></div>
              </div>
            </div>

            <div className="border rounded p-3 bg-white space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">图 3：策略信号占比（按 tag）</div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">window {vizD?.signals?.window_sec ? `${Math.round(Number(vizD.signals.window_sec) / 3600)}h` : '-'}</Badge>
                  <Badge variant={triReasonMatch ? 'outline' : 'destructive'}>tri-trace {triReasonMatch ? 'matched' : 'unmatched'}</Badge>
                </div>
              </div>
              {triTraceWarning ? <div className="text-xs text-amber-700">{triTraceWarning}</div> : null}
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={signalRows.map((r) => {
                      const accepted = Math.max(0, Math.trunc(_toNum(r.accepted_count, 0)));
                      const suppressed = Math.max(0, Math.trunc(_toNum(r.suppressed_count, 0)));
                      const quotaTotal = r.quota_total === null || r.quota_total === undefined ? null : Math.max(0, Math.trunc(Number(r.quota_total)));
                      const base = accepted + suppressed;
                      const total = quotaTotal !== null ? Math.max(quotaTotal, base) : base;
                      const unused = Math.max(0, total - base);
                      return {
                        tag: r.tag,
                        accepted,
                        suppressed,
                        unused,
                        quota_total: quotaTotal,
                      };
                    })}
                    margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="tag" />
                    <YAxis />
                    <Tooltip
                      formatter={(v: unknown, name?: string, item?: { payload?: Record<string, unknown> }) => {
                        const k = String(name ?? '');
                        if (k === 'quota_total') return String(item?.payload?.quota_total ?? '-');
                        return String(v);
                      }}
                    />
                    <Legend />
                    <Bar dataKey="accepted" name="允许" stackId="a" fill="#10b981" />
                    <Bar dataKey="suppressed" name="抑制" stackId="a" fill="#ef4444" />
                    <Bar dataKey="unused" name="未触发" stackId="a" fill="#94a3b8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead>
                    <tr className="text-left">
                      <th className="px-2 py-1">tag</th>
                      <th className="px-2 py-1">signals</th>
                      <th className="px-2 py-1">允许</th>
                      <th className="px-2 py-1">抑制</th>
                      <th className="px-2 py-1">quota_used</th>
                      <th className="px-2 py-1">quota_total</th>
                      <th className="px-2 py-1">quota_remaining</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signalRows.slice(0, 20).map((r) => (
                      <tr key={r.tag} className="border-t">
                        <td className="px-2 py-1">{r.tag}</td>
                        <td className="px-2 py-1">{r.signals_count}</td>
                        <td className="px-2 py-1">{r.accepted_count}</td>
                        <td className="px-2 py-1">{r.suppressed_count}</td>
                        <td className="px-2 py-1">{r.quota_used ?? '-'}</td>
                        <td className="px-2 py-1">{r.quota_total ?? '-'}</td>
                        <td className="px-2 py-1">{r.quota_remaining ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="border rounded p-2">
                  <div className="text-xs font-semibold">抑制原因榜</div>
                  <div className="mt-1 space-y-1">
                    {topReasons.slice(0, 8).map((x) => (
                      <div key={x.key} className="flex justify-between text-xs">
                        <span className="text-slate-600 truncate max-w-[140px]">{x.key}</span>
                        <span>{x.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="border rounded p-2">
                  <div className="text-xs font-semibold">宏观相关抑制原因（追溯）</div>
                  <div className="mt-1 space-y-1">
                    {topMacroReasons.slice(0, 8).map((x) => (
                      <div key={x.key} className="flex justify-between text-xs">
                        <span className="text-slate-600 truncate max-w-[140px]">{x.key}</span>
                        <span>{x.count}</span>
                      </div>
                    ))}
                    {!topMacroReasons.length ? <div className="text-xs text-slate-500">no macro-related blocks in window</div> : null}
                  </div>
                </div>
                <div className="border rounded p-2">
                  <div className="text-xs font-semibold">被抑制最多的组别</div>
                  <div className="mt-1 space-y-1">
                    {topGroups.slice(0, 8).map((x) => (
                      <div key={x.key} className="flex justify-between text-xs">
                        <span className="text-slate-600 truncate max-w-[140px]">{x.key}</span>
                        <span>{x.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="border rounded p-2">
                  <div className="text-xs font-semibold">被抑制最多的策略</div>
                  <div className="mt-1 space-y-1">
                    {topStrategies.slice(0, 8).map((x) => (
                      <div key={x.key} className="flex justify-between text-xs">
                        <span className="text-slate-600 truncate max-w-[140px]">{x.key}</span>
                        <span>{x.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>BTC Regime Backtest</span>
            <div className="flex gap-2 items-center">
              <Badge variant="outline">rows {btRows.length}</Badge>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setBtApplied({
                  lookback_days: Math.max(60, Math.min(2000, Math.trunc(btLookbackDays || 400))),
                  flow_lookback_days: Math.max(30, Math.min(2000, Math.trunc(btFlowLookbackDays || 240))),
                  r_mid_q: Math.max(0.05, Math.min(0.95, btRmidQ || 0.6)),
                  r_high_q: Math.max(0.05, Math.min(0.95, btRhighQ || 0.8)),
                  atr_p80_q: Math.max(0.05, Math.min(0.95, btAtrP80Q || 0.8)),
                  atr_p95_q: Math.max(0.05, Math.min(0.99, btAtrP95Q || 0.95)),
                  dom_q: Math.max(0.05, Math.min(0.99, btDomQ || 0.8)),
                })}
              >
                Apply
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="border rounded p-3 bg-white space-y-3">
              <div className="text-sm font-semibold">Params</div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <div className="text-slate-500">lookback_days</div>
                  <Input value={String(btLookbackDays)} onChange={(e) => setBtLookbackDays(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-slate-500">flow_lookback_days</div>
                  <Input value={String(btFlowLookbackDays)} onChange={(e) => setBtFlowLookbackDays(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-slate-500">r_mid_q</div>
                  <Input value={String(btRmidQ)} onChange={(e) => setBtRmidQ(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-slate-500">r_high_q</div>
                  <Input value={String(btRhighQ)} onChange={(e) => setBtRhighQ(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-slate-500">atr_p80_q</div>
                  <Input value={String(btAtrP80Q)} onChange={(e) => setBtAtrP80Q(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-slate-500">atr_p95_q</div>
                  <Input value={String(btAtrP95Q)} onChange={(e) => setBtAtrP95Q(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-slate-500">dom_q</div>
                  <Input value={String(btDomQ)} onChange={(e) => setBtDomQ(Number(e.target.value))} />
                </div>
                <div className="flex items-end">
                  <div className="text-xs text-slate-500">Applied: {btD?.params ? 'yes' : 'no'}</div>
                </div>
              </div>
            </div>

            <div className="border rounded p-3 bg-white space-y-2">
              <div className="text-sm font-semibold">Thresholds</div>
              <div className="text-sm grid grid-cols-2 gap-x-4 gap-y-1">
                <div className="flex justify-between"><span className="text-slate-500">r_mid</span><span>{_fmt2(Number(btD?.thresholds?.r_mid ?? Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">r_high</span><span>{_fmt2(Number(btD?.thresholds?.r_high ?? Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">atr_p80</span><span>{_fmt2(Number(btD?.thresholds?.atr_p80 ?? Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">atr_p95</span><span>{_fmt2(Number(btD?.thresholds?.atr_p95 ?? Number.NaN), 4)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">r5_dom</span><span>{_fmt2(Number(btD?.thresholds?.r5_dom ?? Number.NaN), 4)}</span></div>
              </div>
              <div className="text-sm font-semibold mt-3">Counts</div>
              <div className="text-sm grid grid-cols-5 gap-2">
                {(['R1', 'R2', 'R3', 'R4', 'R5'] as const).map((k) => (
                  <div key={k} className="border rounded px-2 py-1 flex justify-between bg-slate-50">
                    <span className="text-slate-600">{k}</span>
                    <span>{Number((btD?.counts ?? {})[k] ?? 0)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border rounded p-3 bg-white space-y-2">
              <div className="text-sm font-semibold">Forward 1D Return (by regime)</div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left">
                      <th className="px-2 py-1">regime</th>
                      <th className="px-2 py-1">n</th>
                      <th className="px-2 py-1">mean</th>
                      <th className="px-2 py-1">p10</th>
                      <th className="px-2 py-1">p50</th>
                      <th className="px-2 py-1">p90</th>
                      <th className="px-2 py-1">win</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(['R1', 'R2', 'R3', 'R4', 'R5'] as const).map((k) => {
                      const s = (btD?.per_regime ?? {})[k] as Record<string, unknown> | undefined;
                      const n = Number(s?.n ?? 0);
                      const mean = Number(s?.mean ?? Number.NaN);
                      const p10 = Number(s?.p10 ?? Number.NaN);
                      const p50 = Number(s?.p50 ?? Number.NaN);
                      const p90 = Number(s?.p90 ?? Number.NaN);
                      const win = Number(s?.win_rate ?? Number.NaN);
                      return (
                        <tr key={k} className="border-t">
                          <td className="px-2 py-1">{k}</td>
                          <td className="px-2 py-1">{n}</td>
                          <td className="px-2 py-1">{Number.isFinite(mean) ? _fmtPct(mean, 3) : '-'}</td>
                          <td className="px-2 py-1">{Number.isFinite(p10) ? _fmtPct(p10, 3) : '-'}</td>
                          <td className="px-2 py-1">{Number.isFinite(p50) ? _fmtPct(p50, 3) : '-'}</td>
                          <td className="px-2 py-1">{Number.isFinite(p90) ? _fmtPct(p90, 3) : '-'}</td>
                          <td className="px-2 py-1">{Number.isFinite(win) ? _fmtPct(win, 1) : '-'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 xl:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>BTC Close</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={btChart} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                      <YAxis yAxisId="p" tickFormatter={(v) => String(Math.round(Number(v)))} />
                      <Tooltip
                        labelFormatter={(v) => _fmtDate(Number(v))}
                        formatter={(v: unknown, name?: string) => {
                          const key = String(name ?? '');
                          if (key === 'close') return String(Math.round(_toNum(v, 0)));
                          if (key === 'fwd_ret_1d') return _fmtPct(_toNum(v, 0), 3);
                          if (key === 'regime_num') return String(Math.round(_toNum(v, 0)));
                          return String(v);
                        }}
                      />
                      <Line yAxisId="p" type="monotone" dataKey="close" stroke="#111827" dot={false} strokeWidth={2} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>BTC Regime (1..5)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={btChart} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                      <YAxis domain={[1, 5]} ticks={[1, 2, 3, 4, 5]} />
                      <Tooltip
                        labelFormatter={(v) => _fmtDate(Number(v))}
                        formatter={(v: unknown, name?: string, item?: { payload?: Record<string, unknown> }) => {
                          const key = String(name ?? '');
                          if (key === 'regime_num') {
                            const rg = String(item?.payload?.regime ?? 'R3');
                            return `${rg} (${String(Math.round(_toNum(v, 3)))})`;
                          }
                          return String(v);
                        }}
                      />
                      <Line type="stepAfter" dataKey="regime_num" stroke="#2563eb" dot={false} strokeWidth={2} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>BTC/ETH Macro Overview</span>
            <div className="flex gap-2 items-center">
              <Badge variant="outline">asof {_fmtDate(_toNum(lastFlow?.ts, 0))}</Badge>
              {std1dTs > 0 && <Badge variant="outline">日线 {_fmtDateTime(std1dTs)}</Badge>}
              {std1hTs > 0 && <Badge variant="outline">新版1h {_fmtDateTime(std1hTs)}</Badge>}
              {triTs > 0 && <Badge variant="outline">tri-layer {_fmtDateTime(triTs)}</Badge>}
              <Badge variant={trendDirW > 0 ? 'default' : trendDirW < 0 ? 'destructive' : 'secondary'}>W {trendDirW > 0 ? 'LONG' : trendDirW < 0 ? 'SHORT' : '-'}</Badge>
              <Badge variant={trendDirD > 0 ? 'default' : trendDirD < 0 ? 'destructive' : 'secondary'}>D {trendDirD > 0 ? 'LONG' : trendDirD < 0 ? 'SHORT' : '-'}</Badge>
              <Badge variant={chgDir1hN > 0 ? 'default' : chgDir1hN < 0 ? 'destructive' : 'secondary'}>H {chgDir1hN > 0 ? 'LONG' : chgDir1hN < 0 ? 'SHORT' : '-'}</Badge>
              {riskBudgetTier !== '-' && <Badge variant={riskBudgetTier === 'risk_on' ? 'default' : riskBudgetTier === 'risk_off' ? 'destructive' : 'secondary'}>{riskBudgetTier}</Badge>}
              {crashSwitch ? <Badge variant="destructive">CrashSwitch ON</Badge> : null}
              {showStdShape && stdShapeTs > 0 && <Badge variant="outline">{stdShapeLabel} {_fmtDateTime(stdShapeTs)}</Badge>}
              <Badge variant="secondary">BTC {String(lastBtcTrend?.time_regime ?? '-')}</Badge>
              <Badge variant="secondary">ETH {String(lastEthTrend?.time_regime ?? '-')}</Badge>
              {cfgWriteMsg ? <Badge variant="outline">{cfgWriteMsg}</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-12 gap-4 text-sm">
              <div className="border rounded p-3 bg-white">
                <div className="text-slate-500">rs_btc_vs_mkt</div>
                <div className="text-lg font-semibold">{_fmt2(Number(rsBtc), 4)}</div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="text-slate-500">rs_eth_vs_mkt</div>
                <div className="text-lg font-semibold">{_fmt2(Number(rsEth), 4)}</div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="text-slate-500">rs_btc_vs_eth</div>
                <div className="text-lg font-semibold">{_fmt2(Number(rsBtcEth), 4)}</div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="text-slate-500">risk_baseline (BTC/ETH)</div>
                <div className="text-lg font-semibold">
                {_fmt2(Number(lastBtcEnergy?.risk_baseline), 3)} / {_fmt2(Number(lastEthEnergy?.risk_baseline), 3)}
                </div>
              </div>

              <div className="border rounded p-3 bg-white xl:col-span-2">
                <div className="font-semibold mb-1">周线层（战略净暴露）</div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant={trendDirW > 0 ? 'default' : trendDirW < 0 ? 'destructive' : 'secondary'}>DirW {trendDirW > 0 ? 'LONG' : trendDirW < 0 ? 'SHORT' : '-'}</Badge>
                  <Badge variant={chgDirW > 0 ? 'default' : chgDirW < 0 ? 'destructive' : 'secondary'}>ChgDirW {chgDirW > 0 ? '+1' : chgDirW < 0 ? '-1' : '0'}</Badge>
                </div>
                <div className="text-xs text-slate-500 mt-2">ChgSpeedW {Number.isFinite(chgSpeedW) ? _fmt2(chgSpeedW, 6) : '-'}</div>
                <div className="text-xs text-slate-500 mt-1">target_net_bias {Number.isFinite(triTargetNetBias) ? _fmt2(triTargetNetBias, 3) : '-'} · max_net_exposure {Number.isFinite(triMaxNetExposure) ? _fmt2(triMaxNetExposure, 3) : '-'}</div>
              </div>

              <div className="border rounded p-3 bg-white xl:col-span-2">
                <div className="font-semibold mb-1">日线层（战术风险预算）</div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant={trendDirD > 0 ? 'default' : trendDirD < 0 ? 'destructive' : 'secondary'}>DirD {trendDirD > 0 ? 'LONG' : trendDirD < 0 ? 'SHORT' : '-'}</Badge>
                  <Badge variant={chgDirD > 0 ? 'default' : chgDirD < 0 ? 'destructive' : 'secondary'}>ChgDirD {chgDirD > 0 ? '+1' : chgDirD < 0 ? '-1' : '0'}</Badge>
                  {riskBudgetTier !== '-' ? <Badge variant={riskBudgetTier === 'risk_on' ? 'default' : riskBudgetTier === 'risk_off' ? 'destructive' : 'secondary'}>{riskBudgetTier}</Badge> : null}
                </div>
                <div className="text-xs text-slate-500 mt-2">ChgSpeedD {Number.isFinite(chgSpeedD) ? _fmt2(chgSpeedD, 3) : '-'}</div>
                <div className="text-xs text-slate-500 mt-1">RiskD {Number.isFinite(riskD) ? _fmtPct(riskD, 1) : _fmtPct(dayRiskBtcView, 1)} · BTC risk/value {_fmtPct(dayRiskBtcView, 1)} / {_fmtPct(dayValueBtcView, 1)}</div>
              </div>

              <div className="border rounded p-3 bg-white xl:col-span-2">
                <div className="font-semibold mb-1">1H 层（熔断与节奏）</div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant={chgDir1hN > 0 ? 'default' : chgDir1hN < 0 ? 'destructive' : 'secondary'}>ChgDir1h×{String(triLayer?.short_n ?? 3)} {chgDir1hN > 0 ? 'LONG' : chgDir1hN < 0 ? 'SHORT' : '-'}</Badge>
                  <Badge variant={crashSwitch ? 'destructive' : 'secondary'}>CrashSwitch {crashSwitch ? 'ON' : 'OFF'}</Badge>
                </div>
                <div className="text-xs text-slate-500 mt-2">Risk1h {Number.isFinite(risk1h) ? _fmtPct(risk1h, 1) : _fmtPct(h1RiskBtcView, 1)} · ChgStrength1h {Number.isFinite(chgStrength1h) ? _fmt2(chgStrength1h, 3) : '-'}</div>
                <div className="text-xs text-slate-500 mt-1">BTC risk/value {_fmtPct(h1RiskBtcView, 1)} / {_fmtPct(h1ValueBtcView, 1)}</div>
              </div>

              <div className="border rounded p-3 bg-white xl:col-span-2">
                <div className="font-semibold mb-1">合成输出（对交易链路影响）</div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant={triAllowOpen ? 'outline' : 'destructive'}>allow_open {triAllowOpen ? 'yes' : 'no'}</Badge>
                  <Badge variant={triAllowAddon ? 'outline' : 'secondary'}>allow_addon {triAllowAddon ? 'yes' : 'no'}</Badge>
                </div>
                <div className="text-xs text-slate-500 mt-2">目标净暴露 {Number.isFinite(triTargetNetBias) ? _fmt2(triTargetNetBias, 3) : '-'} · 上限 {Number.isFinite(triMaxNetExposure) ? _fmt2(triMaxNetExposure, 3) : '-'}</div>
                <div className="text-xs text-slate-500 mt-1">宏观只限制新开仓/同向加仓，不阻止减仓/平仓</div>
              </div>

            </div>

            <details className="mt-4 border rounded bg-white p-3">
              <summary className="cursor-pointer text-sm text-slate-700 select-none">兼容层（std12h/std1h，默认禁用）</summary>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div className="border rounded p-2">
                  <div className="font-semibold">std12h</div>
                  <div className="text-slate-500">ts {std12hTs > 0 ? _fmtDateTime(std12hTs) : '-'}</div>
                  <div className="text-slate-500 mt-1">BTC dir {String(std12hBtcDir ?? '-')} · risk/value {_fmtPct(_toNum(std12hBtcRisk, Number.NaN), 1)} / {_fmtPct(_toNum(std12hBtcValue, Number.NaN), 1)}</div>
                  <div className="text-slate-500 mt-1">ETH risk/value {_fmtPct(_toNum(std12hEthRisk, Number.NaN), 1)} / {_fmtPct(_toNum(std12hEthValue, Number.NaN), 1)}</div>
                </div>
                <div className="border rounded p-2">
                  <div className="font-semibold">std1h</div>
                  <div className="text-slate-500">ts {std1hTs > 0 ? _fmtDateTime(std1hTs) : '-'}</div>
                  <div className="text-slate-500 mt-1">BTC dir {String(std1hBtcDir ?? '-')} · risk/value {_fmtPct(_toNum(std1hBtcRisk, Number.NaN), 1)} / {_fmtPct(_toNum(std1hBtcValue, Number.NaN), 1)}</div>
                  <div className="text-slate-500 mt-1">ETH risk/value {_fmtPct(_toNum(std1hEthRisk, Number.NaN), 1)} / {_fmtPct(_toNum(std1hEthValue, Number.NaN), 1)}</div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div className="border rounded p-3 bg-white">
                  <div className="text-slate-500 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span>Entry Hard Gate (std1h)</span>
                      {gateEnabled ? (
                        <span className="px-2 py-0.5 rounded text-xs font-semibold bg-green-100 text-green-800">HARD ON</span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-xs font-semibold bg-slate-100 text-slate-600">OFF</span>
                      )}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!d || cfgMutation.isPending}
                      onClick={() => cfgMutation.mutate({ entry_macro_btceth_hard_gate_enabled: !gateEnabled })}
                    >
                      {gateEnabled ? 'Disable' : 'Enable'}
                    </Button>
                  </div>
                  <div className="text-lg font-semibold">{gateEnabled ? (gateStd1hEffRec ?? gateStd1hRec ?? '-') : 'disabled'}</div>
                  <div className="text-xs text-slate-500">
                    {(gateEnabled ? 'enabled' : 'disabled')} · effective {(gateEnabled ? (gateStd1hEffRec ?? gateStd1hRec ?? '-') : 'disabled')} · fail_open {(gateCfg?.fail_open ? 'on' : 'off')} · data {(std1hValid ? 'valid' : 'invalid')} · ts {std1hTs ? _fmtDateTime(std1hTs) : '-'} · thr {_fmtPct(_toNum(gateStd1h?.risk_thr, Number.NaN), 1)} · align {gateStd1h?.only_with_alignment ? 'only' : 'any'} · min {_fmtPct(_toNum(gateStd1h?.min_risk, Number.NaN), 1)} · L {(gateEnabled ? (gateStd1h?.effective_long_ok ? 'ok' : 'block') : 'ok')} {String(gateStd1h?.long?.reason_code ?? gateStd1h?.long?.reason ?? '')} · S {(gateEnabled ? (gateStd1h?.effective_short_ok ? 'ok' : 'block') : 'ok')} {String(gateStd1h?.short?.reason_code ?? gateStd1h?.short?.reason ?? '')}
                  </div>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-slate-500 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span>Entry Shape ({stdShapeLabel})</span>
                      {macroShapeEnabled ? (
                        <span className="px-2 py-0.5 rounded text-xs font-semibold bg-green-100 text-green-800">ON</span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-xs font-semibold bg-slate-100 text-slate-600">OFF</span>
                      )}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!d || cfgMutation.isPending}
                      onClick={() => cfgMutation.mutate({ entry_macro_btceth_shape_enabled: !macroShapeEnabled })}
                    >
                      {macroShapeEnabled ? 'Disable' : 'Enable'}
                    </Button>
                  </div>
                  <div className="text-lg font-semibold">{macroShapeName ?? '-'}</div>
                  <div className="text-xs text-slate-500 space-y-0.5">
                    <div>
                      data {(macroShapeValid ? 'valid' : 'invalid')} · accepted buckets {(macroShapeRiskBucket ?? '-')}/{(macroShapeValueBucket ?? '-')}
                    </div>
                    <div>
                      now {(macroShapeNext ?? macroShapeName ?? '-')} · buckets {(macroShapeRiskBucketNext ?? '-')}/{(macroShapeValueBucketNext ?? '-')} · used {_fmtPct(_toNum(macroShape?.risk_used, Number.NaN), 1)}/{_fmtPct(_toNum(macroShape?.value_used, Number.NaN), 1)}
                      {macroShapePending ? ` · pending ${macroShapePending}` : ''}
                      {(macroShapeCand && macroShapePersistBars && macroShapePersistBars > 1) ? ` · persist ${String(macroShapeCandN ?? 0)}/${String(macroShapePersistBars)}` : ''}
                    </div>
                  </div>
                </div>
              </div>
            </details>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Exit Inference Summary</span>
            <div className="flex gap-2 items-center">
              <Badge variant="outline">asof {_fmtDate(_toNum((exitD as { ts?: number } | undefined)?.ts, 0))}</Badge>
              <Link to="/evaluation"><Button variant="outline" size="sm">Evaluation</Button></Link>
              <Link to="/exit"><Button variant="outline" size="sm">Exit</Button></Link>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className="px-2 py-1">pair</th>
                  <th className="px-2 py-1">side</th>
                  <th className="px-2 py-1">owner</th>
                  <th className="px-2 py-1">mrd_dir</th>
                  <th className="px-2 py-1">p_dir</th>
                  <th className="px-2 py-1">risk</th>
                  <th className="px-2 py-1">value</th>
                  <th className="px-2 py-1">action</th>
                  <th className="px-2 py-1">reason</th>
                </tr>
              </thead>
              <tbody>
                {exitRows.map((r) => (
                  <tr key={r.pair} className="border-t">
                    <td className="px-2 py-1">{r.pair}</td>
                    <td className="px-2 py-1">{r.side ?? '-'}</td>
                    <td className="px-2 py-1">{r.owner ?? '-'}</td>
                    <td className="px-2 py-1">{r.mrd_dir ?? '-'}</td>
                    <td className="px-2 py-1">{r.p_dir === null ? '-' : _fmtPct(r.p_dir, 1)}</td>
                    <td className="px-2 py-1">{r.hold_risk === null ? '-' : _fmtPct(r.hold_risk, 1)}</td>
                    <td className="px-2 py-1">{r.hold_value === null ? '-' : _fmtPct(r.hold_value, 1)}</td>
                    <td className="px-2 py-1">{r.action ?? '-'}</td>
                    <td className="px-2 py-1">{r.reason ?? ''}</td>
                  </tr>
                ))}
                {exitRows.length === 0 && (
                  <tr><td className="px-2 py-3 text-slate-500" colSpan={9}>No exit inference</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>BTC Time Dimension (trend_shape_5)</span>
              <Badge variant="secondary">{String(lastBtcTrend?.trend_shape_5 ?? '-')}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={btcTrend} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                  <YAxis domain={['auto', 'auto']} />
                  <Tooltip labelFormatter={(v) => _fmtDate(Number(v))} />
                  <Line type="monotone" dataKey="trend_w_slope" stroke="#2563eb" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="trend_d_slope" stroke="#f59e0b" dot={false} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th className="px-2 py-1">factor_id</th>
                    <th className="px-2 py-1">value_t</th>
                    <th className="px-2 py-1">value_t-1</th>
                    <th className="px-2 py-1">delta</th>
                    <th className="px-2 py-1">dir</th>
                    <th className="px-2 py-1">chg_dir</th>
                    <th className="px-2 py-1">speed</th>
                    <th className="px-2 py-1">bucket</th>
                  </tr>
                </thead>
                <tbody>
                  {btcTimeRows.map((r) => (
                    <tr key={r.factor} className="border-t">
                      <td className="px-2 py-1">{r.factor}</td>
                      <td className="px-2 py-1">{r.value_t}</td>
                      <td className="px-2 py-1">{r.value_t1}</td>
                      <td className="px-2 py-1">{r.delta}</td>
                      <td className="px-2 py-1">{r.direction}</td>
                      <td className="px-2 py-1">{r.change_direction}</td>
                      <td className="px-2 py-1">{r.speed}</td>
                      <td className="px-2 py-1">{r.bucket}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>ETH Time Dimension (trend_shape_5)</span>
              <Badge variant="secondary">{String(lastEthTrend?.trend_shape_5 ?? '-')}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={ethTrend} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                  <YAxis domain={['auto', 'auto']} />
                  <Tooltip labelFormatter={(v) => _fmtDate(Number(v))} />
                  <Line type="monotone" dataKey="trend_w_slope" stroke="#2563eb" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="trend_d_slope" stroke="#f59e0b" dot={false} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th className="px-2 py-1">factor_id</th>
                    <th className="px-2 py-1">value_t</th>
                    <th className="px-2 py-1">value_t-1</th>
                    <th className="px-2 py-1">delta</th>
                    <th className="px-2 py-1">dir</th>
                    <th className="px-2 py-1">chg_dir</th>
                    <th className="px-2 py-1">speed</th>
                    <th className="px-2 py-1">bucket</th>
                  </tr>
                </thead>
                <tbody>
                  {ethTimeRows.map((r) => (
                    <tr key={r.factor} className="border-t">
                      <td className="px-2 py-1">{r.factor}</td>
                      <td className="px-2 py-1">{r.value_t}</td>
                      <td className="px-2 py-1">{r.value_t1}</td>
                      <td className="px-2 py-1">{r.delta}</td>
                      <td className="px-2 py-1">{r.direction}</td>
                      <td className="px-2 py-1">{r.change_direction}</td>
                      <td className="px-2 py-1">{r.speed}</td>
                      <td className="px-2 py-1">{r.bucket}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>BTC Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={btcTrend} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                  <YAxis yAxisId="p" tickFormatter={(v) => String(Math.round(Number(v)))} />
                  <YAxis yAxisId="adx" orientation="right" domain={[0, 'auto']} />
                  <Tooltip labelFormatter={(v) => _fmtDate(Number(v))} />
                  <Line yAxisId="p" type="monotone" dataKey="close" stroke="#111827" dot={false} strokeWidth={2} />
                  <Line yAxisId="p" type="monotone" dataKey="ema_fast_w" stroke="#2563eb" dot={false} strokeWidth={1.5} />
                  <Line yAxisId="p" type="monotone" dataKey="ema_slow_w" stroke="#60a5fa" dot={false} strokeWidth={1.5} />
                  <Line yAxisId="adx" type="monotone" dataKey="adx_w" stroke="#f59e0b" dot={false} strokeWidth={1.2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>ETH Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={ethTrend} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                  <YAxis yAxisId="p" tickFormatter={(v) => String(Math.round(Number(v)))} />
                  <YAxis yAxisId="adx" orientation="right" domain={[0, 'auto']} />
                  <Tooltip labelFormatter={(v) => _fmtDate(Number(v))} />
                  <Line yAxisId="p" type="monotone" dataKey="close" stroke="#111827" dot={false} strokeWidth={2} />
                  <Line yAxisId="p" type="monotone" dataKey="ema_fast_w" stroke="#2563eb" dot={false} strokeWidth={1.5} />
                  <Line yAxisId="p" type="monotone" dataKey="ema_slow_w" stroke="#60a5fa" dot={false} strokeWidth={1.5} />
                  <Line yAxisId="adx" type="monotone" dataKey="adx_w" stroke="#f59e0b" dot={false} strokeWidth={1.2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>BTC Energy</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={btcEnergy} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                  <YAxis domain={['auto', 'auto']} />
                  <Tooltip labelFormatter={(v) => _fmtDate(Number(v))} />
                  <Line type="monotone" dataKey="kin_ma" stroke="#2563eb" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="vol_ma" stroke="#10b981" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="pot_ma" stroke="#f59e0b" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="risk_baseline" stroke="#ef4444" dot={false} strokeWidth={1.2} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th className="px-2 py-1">factor_id</th>
                    <th className="px-2 py-1">value_t</th>
                    <th className="px-2 py-1">value_t-1</th>
                    <th className="px-2 py-1">delta</th>
                    <th className="px-2 py-1">dir</th>
                    <th className="px-2 py-1">chg_dir</th>
                    <th className="px-2 py-1">speed</th>
                    <th className="px-2 py-1">bucket</th>
                  </tr>
                </thead>
                <tbody>
                  {btcEnergyRows.map((r) => (
                    <tr key={r.factor} className="border-t">
                      <td className="px-2 py-1">{r.factor}</td>
                      <td className="px-2 py-1">{r.value_t}</td>
                      <td className="px-2 py-1">{r.value_t1}</td>
                      <td className="px-2 py-1">{r.delta}</td>
                      <td className="px-2 py-1">{r.direction}</td>
                      <td className="px-2 py-1">{r.change_direction}</td>
                      <td className="px-2 py-1">{r.speed}</td>
                      <td className="px-2 py-1">{r.bucket}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>ETH Energy</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={ethEnergy} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                  <YAxis domain={['auto', 'auto']} />
                  <Tooltip labelFormatter={(v) => _fmtDate(Number(v))} />
                  <Line type="monotone" dataKey="kin_ma" stroke="#2563eb" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="vol_ma" stroke="#10b981" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="pot_ma" stroke="#f59e0b" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="risk_baseline" stroke="#ef4444" dot={false} strokeWidth={1.2} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th className="px-2 py-1">factor_id</th>
                    <th className="px-2 py-1">value_t</th>
                    <th className="px-2 py-1">value_t-1</th>
                    <th className="px-2 py-1">delta</th>
                    <th className="px-2 py-1">dir</th>
                    <th className="px-2 py-1">chg_dir</th>
                    <th className="px-2 py-1">speed</th>
                    <th className="px-2 py-1">bucket</th>
                  </tr>
                </thead>
                <tbody>
                  {ethEnergyRows.map((r) => (
                    <tr key={r.factor} className="border-t">
                      <td className="px-2 py-1">{r.factor}</td>
                      <td className="px-2 py-1">{r.value_t}</td>
                      <td className="px-2 py-1">{r.value_t1}</td>
                      <td className="px-2 py-1">{r.delta}</td>
                      <td className="px-2 py-1">{r.direction}</td>
                      <td className="px-2 py-1">{r.change_direction}</td>
                      <td className="px-2 py-1">{r.speed}</td>
                      <td className="px-2 py-1">{r.bucket}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Macro Flow (RS Proxies)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={flow} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={_fmtDate} />
                <YAxis tickFormatter={(v) => _fmtPct(Number(v), 2)} />
                <Tooltip labelFormatter={(v) => _fmtDate(Number(v))} formatter={(v: unknown) => _fmtPct(_toNum(v, 0), 2)} />
                <Line type="monotone" dataKey="rs_btc_vs_mkt" stroke="#111827" dot={false} strokeWidth={1.8} />
                <Line type="monotone" dataKey="rs_eth_vs_mkt" stroke="#2563eb" dot={false} strokeWidth={1.8} />
                <Line type="monotone" dataKey="rs_btc_vs_eth" stroke="#f59e0b" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className="px-2 py-1">factor_id</th>
                  <th className="px-2 py-1">value_t</th>
                  <th className="px-2 py-1">value_t-1</th>
                  <th className="px-2 py-1">delta</th>
                  <th className="px-2 py-1">dir</th>
                  <th className="px-2 py-1">chg_dir</th>
                  <th className="px-2 py-1">speed</th>
                  <th className="px-2 py-1">bucket</th>
                </tr>
              </thead>
              <tbody>
                {flowRows.map((r) => (
                  <tr key={r.factor} className="border-t">
                    <td className="px-2 py-1">{r.factor}</td>
                    <td className="px-2 py-1">{r.value_t}</td>
                    <td className="px-2 py-1">{r.value_t1}</td>
                    <td className="px-2 py-1">{r.delta}</td>
                    <td className="px-2 py-1">{r.direction}</td>
                    <td className="px-2 py-1">{r.change_direction}</td>
                    <td className="px-2 py-1">{r.speed}</td>
                    <td className="px-2 py-1">{r.bucket}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
