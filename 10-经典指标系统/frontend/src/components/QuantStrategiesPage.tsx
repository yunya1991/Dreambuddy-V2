import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  fetchConfig,
  fetchMacroBtcEthOverview,
  fetchQuantPairBtcAltBacktest,
  fetchQuantPairBtcAltCandidates,
  fetchQuantPairBtcAltPortfolioSimulate,
  fetchQuantPairBtcAltRecommend,
  fetchQuantPairBtcAltResearchCapacity,
  fetchQuantPairBtcAltResearchMarginStress,
  fetchQuantPairBtcAltResearchSplit,
  fetchQuantPairBtcAltStatus,
  fetchQuantAutoBtcEthLast,
  fetchQuantAutoBtcaltsLast,
  quantAutoBtcEthTick,
  quantAutoBtcaltsTick,
  fetchQuantPairBtcEthBacktest,
  fetchQuantPairBtcEthResearchCapacity,
  fetchQuantPairBtcEthResearchMarginStress,
  fetchQuantPairBtcEthResearchSplit,
  fetchQuantPairBtcEthStatus,
  fetchQuantComboSupervision,
  fetchTrackerStats,
  fetchUniversePairs,
  fetchUniverseStatus,
  fetchDiagnosticsGateState,
  api,
  livePreflight,
  livePlan,
  liveRiskCheck,
  pairsBtcAltMarketClose,
  pairsBtcAltMarketOpen,
  pairsBtcEthMarketClose,
  pairsBtcEthMarketOpen,
  updateConfig,
  updateQuantPairBtcEthConfig,
  updateQuantPairBtcAltConfig,
  getExecuteToken,
  hasOperatorToken,
  setExecuteToken,
  subscribeConfigToken,
  subscribeExecuteToken,
  subscribeMaintenanceToken,
} from '../lib/api';
import type {
  Config,
  ConfigPatch,
  MacroBtcEthOverviewResponse,
  QuantPairBtcAltBacktestResponse,
  QuantPairBtcAltScaleCurveItem,
  QuantPairBtcAltCandidatesResponse,
  QuantPairBtcAltConfig,
  QuantPairBtcAltPortfolioSimulateResponse,
  QuantPairBtcAltResearchCapacityItem,
  QuantPairBtcAltResearchCapacityResponse,
  QuantPairBtcAltResearchMarginStressResponse,
  QuantPairBtcAltResearchSplitResponse,
  QuantPairBtcAltRecommendResponse,
  QuantPairBtcAltStatusResponse,
  QuantAutoBtcEthLastResponse,
  QuantAutoBtcaltsLastResponse,
  QuantPairBtcEthBacktestResponse,
  QuantPairBtcEthScaleCurveItem,
  QuantPairBtcEthConfig,
  QuantPairBtcEthResearchCapacityItem,
  QuantPairBtcEthResearchCapacityResponse,
  QuantPairBtcEthResearchMarginStressResponse,
  QuantPairBtcEthResearchSplitResponse,
  QuantPairBtcEthStatusResponse,
  QuantMacroVeto,
  QuantComboSupervisionResponse,
  TrackerStats,
  UniversePairsResponse,
  UniverseState,
  LivePlanResponse,
  LiveRiskCheckResponse,
  DiagnosticsGateStateResponse,
} from '../lib/api';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { SignalsTable } from './SignalsTable';

function _toNum(v: unknown, d = 0): number {
  if (v === null || v === undefined) return d;
  if (typeof v === 'string' && v.trim() === '') return d;
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

function _fmtTs(ms: number): string {
  const t = Number(ms);
  if (!Number.isFinite(t) || t <= 0) return '';
  const d = new Date(t);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function _tfToMs(tf: string): number {
  const s = String(tf || '').trim().toLowerCase();
  if (s === '5m') return 5 * 60 * 1000;
  if (s === '15m') return 15 * 60 * 1000;
  if (s === '30m') return 30 * 60 * 1000;
  if (s === '1h' || s === '60m') return 60 * 60 * 1000;
  if (s === '4h') return 4 * 60 * 60 * 1000;
  if (s === '1d') return 24 * 60 * 60 * 1000;
  return 0;
}

function idemKey(scope: string, parts: Record<string, unknown>, bucketMs = 15000): string {
  const bucket = Math.floor(Date.now() / Math.max(1000, bucketMs));
  const items = Object.entries(parts)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => {
      const kk = String(k).trim();
      const vv = typeof v === 'string' ? v.trim() : String(v);
      return `${kk}=${vv.slice(0, 80)}`;
    })
    .sort();
  return `quant|${String(scope).trim()}|${bucket}|${items.join('|')}`.slice(0, 240);
}

type Std1hPoint = { ts: number; risk: number | null; value: number | null; dir: number | null };

type GateEvalRow = {
  ts: number;
  pass: boolean;
  adf_p: number | null;
  adf_p_adj: number | null;
  kpss_stat: number | null;
  beta_std: number | null;
  half_life_bars: number | null;
};

type SubportfolioMetaDraft = {
  init_equity_usdc: number;
  max_dd: number;
  max_daily_loss: number;
  max_weekly_loss: number;
  dd_cooldown_sec: number;
  daily_cooldown_sec: number;
  weekly_cooldown_sec: number;
  vol_target_atr_pct: number;
  vol_scale_min: number;
  vol_scale_max: number;
  max_trade_notional_usdc: number | null;
};

type QuantAutoBtcaltsDraft = {
  quant_auto_mode: 'off' | 'monitor' | 'paper' | 'live';
  quant_auto_enabled: boolean;
  quant_auto_btceth_enabled: boolean;
  quant_auto_btcalts_enabled: boolean;
  quant_auto_state_check_interval_sec: number;
  quant_auto_daily_loss_limit_pct: number;
  quant_auto_weekly_loss_limit_pct: number;
  quant_auto_net_btc_pct_max: number;
  quant_auto_pair_notional_usdc_max: number;
  quant_auto_max_open_pairs_total: number;

  quant_auto_btcalts_capacity_turnover_frac: number;
  quant_auto_btcalts_capacity_depth_frac: number;
  quant_pairs_btcalt_capacity_turnover_frac: number;
  quant_pairs_btcalt_capacity_depth_frac: number;

  quant_auto_btcalts_scan_n: number;
  quant_auto_btcalts_open_per_tick: number;
  quant_auto_btcalts_cooldown_bars: number;
  quant_auto_btcalts_max_open_pairs: number;
  quant_auto_btcalts_max_per_cluster: number;
  quant_auto_btcalts_macro_trend_required: boolean;
  quant_auto_btcalts_z_bias_min: number;
  quant_auto_btcalts_z_bias_weight: number;
  quant_auto_btcalts_notional_nontrend_mult: number;
  quant_auto_btcalts_open_per_tick_nontrend: number;
  quant_auto_btcalts_max_open_pairs_nontrend: number;
  quant_auto_btcalts_dynamic_hedge_enabled: boolean;
  quant_auto_btcalts_dynamic_hedge_step: number;
  quant_auto_btcalts_btc_hedge_frac: number;
};

function _loadStd1hSeq(storageKey: string): Std1hPoint[] {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return [];
    const obj = JSON.parse(raw) as unknown;
    if (!Array.isArray(obj)) return [];
    return obj
      .map((x) => {
        const r = x as Record<string, unknown>;
        const ts = Number(r.ts);
        const risk = r.risk === null || r.risk === undefined ? null : Number(r.risk);
        const value = r.value === null || r.value === undefined ? null : Number(r.value);
        const dir = r.dir === null || r.dir === undefined ? null : Number(r.dir);
        return {
          ts: Number.isFinite(ts) ? ts : 0,
          risk: Number.isFinite(risk) ? risk : null,
          value: Number.isFinite(value) ? value : null,
          dir: Number.isFinite(dir) ? dir : null,
        };
      })
      .filter((p) => p.ts > 0)
      .sort((a, b) => a.ts - b.ts);
  } catch {
    return [];
  }
}

function _saveStd1hSeq(storageKey: string, seq: Std1hPoint[]) {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(seq));
  } catch {
    void 0;
  }
}

function _pushStd1hSeq(prev: Std1hPoint[], p: Std1hPoint, n: number): Std1hPoint[] {
  const ts = Number(p.ts);
  if (!Number.isFinite(ts) || ts <= 0) return prev;
  const next = [...prev.filter((x) => Number(x.ts) !== ts), { ...p, ts }].sort((a, b) => a.ts - b.ts);
  const out = next.slice(Math.max(0, next.length - Math.max(1, Math.trunc(n || 3))));
  return out;
}

const _defaultDraft: QuantPairBtcEthConfig = {
  timeframe: '1h',
  window_ols: 240,
  window_z: 240,
  beta_std_max: 0.15,
  beta_abs_max: 3.0,
  entry_z: 2.0,
  entry_z_long: 2.0,
  entry_z_short: 2.0,
  exit_z: 0.5,
  z_exit_confirm_bars: 1,
  stop_z: 4.0,
  corr_min: 0.8,
  max_hold_bars: 240,
  z_cost_buffer_mult: 1.0,
  notional_usdc_per_leg: 200.0,
  pair_notional_usdc_max: 400.0,
  cooldown_bars_after_exit: 4,
  emergency_close_on_gate_violation: true,
  state_check_interval_sec: 60,
  exit_pnl_enabled: true,
  pnl_stop_loss_r: -0.01,
  pnl_take_profit_r: 0.008,
  pnl_trail_start_r: 0.006,
  pnl_trail_dd_r: 0.003,
  pnl_min_on_z_exit_r: 0.0,
  pnl_min_hold_bars: 0,
};

const _defaultBtcAltDraft: QuantPairBtcAltConfig = {
  timeframe: '30m',
  window_ols: 240,
  window_z: 240,
  entry_z: 2.0,
  entry_z_long: 2.0,
  entry_z_short: 2.0,
  exit_z: 0.5,
  z_exit_confirm_bars: 1,
  stop_z: 4.0,
  corr_min: 0.6,
  max_hold_bars: 240,
  z_cost_buffer_mult: 1.0,
  exit_pnl_enabled: true,
  pnl_stop_loss_r: -0.01,
  pnl_take_profit_r: 0.008,
  pnl_trail_start_r: 0.006,
  pnl_trail_dd_r: 0.003,
  pnl_min_on_z_exit_r: 0.0,
  pnl_min_hold_bars: 0,
  max_pairs_active: 5,
  cluster_max_active: 1,
  cluster_risk_budget_frac: 0.25,
  gross_notional_usdc: 400.0,
  pair_notional_usdc_max: 200.0,
  capacity_turnover_frac: 0.0,
  capacity_depth_frac: 0.0,
  risk_weight_mode: 'inv_resid_vol',
  net_btc_exposure_target: 0.0,
  net_btc_exposure_max: 0.1,
  universe_consistency_min_ari: 0.3,
  universe_consistency_min_nmi: 0.4,
  circuit_breaker_dd_day: 0.03,
  circuit_breaker_dd_week: 0.08,
};

const PairConfigPanel: React.FC<{
  initial: QuantPairBtcEthConfig;
  onSave: (cfg: QuantPairBtcEthConfig) => void;
  saving: boolean;
  saveState: 'idle' | 'ok' | 'error';
}> = ({ initial, onSave, saving, saveState }) => {
  const [draft, setDraft] = useState<QuantPairBtcEthConfig>(() => initial);

  const handleDraftNumber = (k: keyof QuantPairBtcEthConfig) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setDraft((prev) => ({ ...prev, [k]: v === '' ? prev[k] : Number(v) }));
  };

  const handleEntryZ = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setDraft((prev) => {
      if (v === '') return prev;
      const n = Number(v);
      if (!Number.isFinite(n)) return prev;
      return { ...prev, entry_z: n, entry_z_long: n, entry_z_short: n };
    });
  };

  const reset = () => setDraft(initial);

  return (
    <>
      <Tabs defaultValue="basic">
        <TabsList>
          <TabsTrigger value="basic">核心参数</TabsTrigger>
          <TabsTrigger value="advanced">高级参数</TabsTrigger>
        </TabsList>
        <TabsContent value="basic">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">Timeframe</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={draft.timeframe}
                onChange={(e) => setDraft((p) => ({ ...p, timeframe: e.target.value }))}
              >
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">window_ols</div>
              <Input type="number" value={draft.window_ols} onChange={handleDraftNumber('window_ols')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">window_z</div>
              <Input type="number" value={draft.window_z} onChange={handleDraftNumber('window_z')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">max_hold_bars</div>
              <Input type="number" value={draft.max_hold_bars} onChange={handleDraftNumber('max_hold_bars')} />
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">notional_usdc_per_leg</div>
              <Input type="number" step="1" value={draft.notional_usdc_per_leg} onChange={handleDraftNumber('notional_usdc_per_leg')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pair_notional_usdc_max</div>
              <Input type="number" step="1" value={draft.pair_notional_usdc_max} onChange={handleDraftNumber('pair_notional_usdc_max')} />
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">entry_z</div>
              <Input type="number" step="0.1" value={draft.entry_z} onChange={handleEntryZ} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">exit_z</div>
              <Input type="number" step="0.1" value={draft.exit_z} onChange={handleDraftNumber('exit_z')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">z_exit_confirm_bars</div>
              <Input type="number" step="1" value={draft.z_exit_confirm_bars} onChange={handleDraftNumber('z_exit_confirm_bars')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">stop_z</div>
              <Input type="number" step="0.1" value={draft.stop_z} onChange={handleDraftNumber('stop_z')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">corr_min</div>
              <Input type="number" step="0.01" value={draft.corr_min} onChange={handleDraftNumber('corr_min')} />
            </div>
          </div>
        </TabsContent>
        <TabsContent value="advanced">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">beta_std_max</div>
              <Input type="number" step="0.01" value={draft.beta_std_max} onChange={handleDraftNumber('beta_std_max')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">beta_abs_max</div>
              <Input type="number" step="0.1" value={draft.beta_abs_max} onChange={handleDraftNumber('beta_abs_max')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">cooldown_bars_after_exit</div>
              <Input type="number" value={draft.cooldown_bars_after_exit} onChange={handleDraftNumber('cooldown_bars_after_exit')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">state_check_interval_sec</div>
              <Input type="number" value={draft.state_check_interval_sec} onChange={handleDraftNumber('state_check_interval_sec')} />
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">entry_z_long</div>
              <Input type="number" step="0.1" value={draft.entry_z_long} onChange={handleDraftNumber('entry_z_long')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">entry_z_short</div>
              <Input type="number" step="0.1" value={draft.entry_z_short} onChange={handleDraftNumber('entry_z_short')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">z_cost_buffer_mult</div>
              <Input type="number" step="0.1" value={draft.z_cost_buffer_mult} onChange={handleDraftNumber('z_cost_buffer_mult')} />
            </div>

            <div className="flex items-end">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={Boolean(draft.emergency_close_on_gate_violation)}
                  onChange={(e) => setDraft((p) => ({ ...p, emergency_close_on_gate_violation: Boolean(e.target.checked) }))}
                />
                emergency_close_on_gate_violation
              </label>
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={Boolean(draft.exit_pnl_enabled)}
                  onChange={(e) => setDraft((p) => ({ ...p, exit_pnl_enabled: Boolean(e.target.checked) }))}
                />
                exit_pnl_enabled
              </label>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_stop_loss_r</div>
              <Input type="number" step="0.001" value={draft.pnl_stop_loss_r} onChange={handleDraftNumber('pnl_stop_loss_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_take_profit_r</div>
              <Input type="number" step="0.001" value={draft.pnl_take_profit_r} onChange={handleDraftNumber('pnl_take_profit_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_trail_start_r</div>
              <Input type="number" step="0.001" value={draft.pnl_trail_start_r} onChange={handleDraftNumber('pnl_trail_start_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_trail_dd_r</div>
              <Input type="number" step="0.001" value={draft.pnl_trail_dd_r} onChange={handleDraftNumber('pnl_trail_dd_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_min_on_z_exit_r</div>
              <Input type="number" step="0.001" value={draft.pnl_min_on_z_exit_r} onChange={handleDraftNumber('pnl_min_on_z_exit_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_min_hold_bars</div>
              <Input type="number" value={draft.pnl_min_hold_bars} onChange={handleDraftNumber('pnl_min_hold_bars')} />
            </div>
          </div>
        </TabsContent>
      </Tabs>

      <div className="mt-4 flex gap-2">
        <Button onClick={() => onSave(draft)} disabled={saving}>Save</Button>
        <Button variant="secondary" onClick={reset} disabled={saving}>Reset</Button>
        <div className="text-xs text-slate-500 flex items-center">
          {saving ? 'Saving…' : saveState === 'error' ? 'Save failed.' : saveState === 'ok' ? 'Saved.' : ''}
        </div>
      </div>
    </>
  );
};

const BtcAltConfigPanel: React.FC<{
  initial: QuantPairBtcAltConfig;
  onSave: (cfg: QuantPairBtcAltConfig & { sync_quant_auto?: boolean }) => void;
  saving: boolean;
  saveState: 'idle' | 'ok' | 'error';
}> = ({ initial, onSave, saving, saveState }) => {
  const [draft, setDraft] = useState<QuantPairBtcAltConfig>(() => initial);
  const [syncQuantAuto, setSyncQuantAuto] = useState<boolean>(true);

  const handleDraftNumber = (k: keyof QuantPairBtcAltConfig) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setDraft((prev) => ({ ...prev, [k]: v === '' ? prev[k] : Number(v) }));
  };

  const handleEntryZ = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setDraft((prev) => {
      if (v === '') return prev;
      const n = Number(v);
      if (!Number.isFinite(n)) return prev;
      return { ...prev, entry_z: n, entry_z_long: n, entry_z_short: n };
    });
  };

  const reset = () => setDraft(initial);
  const resetToDefaults = () => {
    setDraft(_defaultBtcAltDraft);
    onSave({ ..._defaultBtcAltDraft, sync_quant_auto: syncQuantAuto });
  };

  return (
    <>
      <Tabs defaultValue="basic">
        <TabsList>
          <TabsTrigger value="basic">核心参数</TabsTrigger>
          <TabsTrigger value="advanced">高级参数</TabsTrigger>
        </TabsList>
        <TabsContent value="basic">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">Timeframe</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={draft.timeframe}
                onChange={(e) => setDraft((p) => ({ ...p, timeframe: e.target.value }))}
              >
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">window_ols</div>
              <Input type="number" value={draft.window_ols} onChange={handleDraftNumber('window_ols')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">window_z</div>
              <Input type="number" value={draft.window_z} onChange={handleDraftNumber('window_z')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">max_hold_bars</div>
              <Input type="number" value={draft.max_hold_bars} onChange={handleDraftNumber('max_hold_bars')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">entry_z</div>
              <Input type="number" step="0.1" value={draft.entry_z} onChange={handleEntryZ} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">exit_z</div>
              <Input type="number" step="0.1" value={draft.exit_z} onChange={handleDraftNumber('exit_z')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">z_exit_confirm_bars</div>
              <Input type="number" step="1" value={draft.z_exit_confirm_bars} onChange={handleDraftNumber('z_exit_confirm_bars')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">stop_z</div>
              <Input type="number" step="0.1" value={draft.stop_z} onChange={handleDraftNumber('stop_z')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">corr_min</div>
              <Input type="number" step="0.01" value={draft.corr_min} onChange={handleDraftNumber('corr_min')} />
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">max_pairs_active</div>
              <Input type="number" value={draft.max_pairs_active} onChange={handleDraftNumber('max_pairs_active')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">gross_notional_usdc</div>
              <Input type="number" step="1" value={draft.gross_notional_usdc} onChange={handleDraftNumber('gross_notional_usdc')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pair_notional_usdc_max</div>
              <Input type="number" step="1" value={draft.pair_notional_usdc_max} onChange={handleDraftNumber('pair_notional_usdc_max')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">net_btc_exposure_max</div>
              <Input type="number" step="0.01" value={draft.net_btc_exposure_max} onChange={handleDraftNumber('net_btc_exposure_max')} />
            </div>
          </div>
        </TabsContent>
        <TabsContent value="advanced">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">entry_z_long</div>
              <Input type="number" step="0.1" value={draft.entry_z_long} onChange={handleDraftNumber('entry_z_long')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">entry_z_short</div>
              <Input type="number" step="0.1" value={draft.entry_z_short} onChange={handleDraftNumber('entry_z_short')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">z_cost_buffer_mult</div>
              <Input type="number" step="0.01" value={draft.z_cost_buffer_mult} onChange={handleDraftNumber('z_cost_buffer_mult')} />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={Boolean(draft.exit_pnl_enabled)}
                  onChange={(e) => setDraft((p) => ({ ...p, exit_pnl_enabled: Boolean(e.target.checked) }))}
                />
                exit_pnl_enabled
              </label>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_stop_loss_r</div>
              <Input type="number" step="0.001" value={draft.pnl_stop_loss_r} onChange={handleDraftNumber('pnl_stop_loss_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_take_profit_r</div>
              <Input type="number" step="0.001" value={draft.pnl_take_profit_r} onChange={handleDraftNumber('pnl_take_profit_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_trail_start_r</div>
              <Input type="number" step="0.001" value={draft.pnl_trail_start_r} onChange={handleDraftNumber('pnl_trail_start_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_trail_dd_r</div>
              <Input type="number" step="0.001" value={draft.pnl_trail_dd_r} onChange={handleDraftNumber('pnl_trail_dd_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_min_on_z_exit_r</div>
              <Input type="number" step="0.001" value={draft.pnl_min_on_z_exit_r} onChange={handleDraftNumber('pnl_min_on_z_exit_r')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pnl_min_hold_bars</div>
              <Input type="number" value={draft.pnl_min_hold_bars} onChange={handleDraftNumber('pnl_min_hold_bars')} />
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">cluster_max_active</div>
              <Input type="number" value={draft.cluster_max_active} onChange={handleDraftNumber('cluster_max_active')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">cluster_risk_budget_frac</div>
              <Input type="number" step="0.01" value={draft.cluster_risk_budget_frac} onChange={handleDraftNumber('cluster_risk_budget_frac')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">capacity_turnover_frac</div>
              <Input type="number" step="0.01" value={draft.capacity_turnover_frac} onChange={handleDraftNumber('capacity_turnover_frac')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">capacity_depth_frac</div>
              <Input type="number" step="0.01" value={draft.capacity_depth_frac} onChange={handleDraftNumber('capacity_depth_frac')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">risk_weight_mode</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={draft.risk_weight_mode}
                onChange={(e) => setDraft((p) => ({ ...p, risk_weight_mode: e.target.value }))}
              >
                <option value="inv_resid_vol">inv_resid_vol</option>
                <option value="inv_spread_sigma">inv_spread_sigma</option>
                <option value="equal">equal</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">net_btc_exposure_target</div>
              <Input type="number" step="0.01" value={draft.net_btc_exposure_target} onChange={handleDraftNumber('net_btc_exposure_target')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">universe_consistency_min_ari</div>
              <Input
                type="number"
                step="0.01"
                value={draft.universe_consistency_min_ari}
                onChange={handleDraftNumber('universe_consistency_min_ari')}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">universe_consistency_min_nmi</div>
              <Input
                type="number"
                step="0.01"
                value={draft.universe_consistency_min_nmi}
                onChange={handleDraftNumber('universe_consistency_min_nmi')}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">circuit_breaker_dd_day</div>
              <Input type="number" step="0.01" value={draft.circuit_breaker_dd_day} onChange={handleDraftNumber('circuit_breaker_dd_day')} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">circuit_breaker_dd_week</div>
              <Input type="number" step="0.01" value={draft.circuit_breaker_dd_week} onChange={handleDraftNumber('circuit_breaker_dd_week')} />
            </div>
          </div>
        </TabsContent>
      </Tabs>

      <div className="mt-4 flex gap-2">
        <Button onClick={() => onSave({ ...draft, sync_quant_auto: syncQuantAuto })} disabled={saving}>Save</Button>
        <Button variant="secondary" onClick={reset} disabled={saving}>Reset</Button>
        <Button variant="secondary" onClick={resetToDefaults} disabled={saving}>Reset to defaults</Button>
        <label className="text-xs text-slate-600 flex items-center gap-2 ml-2">
          <input type="checkbox" checked={syncQuantAuto} onChange={(e) => setSyncQuantAuto(e.target.checked)} disabled={saving} />
          <span>同步 quant_auto_*</span>
        </label>
        <div className="text-xs text-slate-500 flex items-center">
          {saving ? 'Saving…' : saveState === 'error' ? 'Save failed.' : saveState === 'ok' ? 'Saved.' : ''}
        </div>
      </div>
    </>
  );
};

const SubportfolioConfigPanel: React.FC<{
  enabled: boolean;
  hasOverride: boolean;
  base: SubportfolioMetaDraft;
  initial: SubportfolioMetaDraft;
  tracker: {
    equity: number;
    peak: number;
    dd: number;
    cooldownUntilMs: number;
  };
  live: {
    enabled: boolean;
    ok: boolean;
    dd: number;
    ddLimit: number;
    reason: string;
  };
  liveMode: boolean;
  saving: boolean;
  msg: string;
  onSave: (draft: SubportfolioMetaDraft, confirmLive: boolean) => void;
  onClearOverride: (confirmLive: boolean) => void;
}> = ({ enabled, hasOverride, base, initial, tracker, live, liveMode, saving, msg, onSave, onClearOverride }) => {
  const [draft, setDraft] = useState<SubportfolioMetaDraft>(() => initial);
  const [confirmLive, setConfirmLive] = useState<boolean>(false);

  const handleDraftNumber = (k: keyof SubportfolioMetaDraft) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setDraft((prev) => ({ ...prev, [k]: v === '' ? prev[k] : Number(v) }));
  };

  const handleMaxTrade = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    if (v.trim() === '') {
      setDraft((prev) => ({ ...prev, max_trade_notional_usdc: null }));
      return;
    }
    const n = Number(v);
    if (!Number.isFinite(n)) return;
    setDraft((prev) => ({ ...prev, max_trade_notional_usdc: n }));
  };

  const saveDisabled = saving || (liveMode && !confirmLive);

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4 text-sm">
        <div className="border rounded p-3 bg-white">
          <div className="font-semibold mb-1">Tracker</div>
          <div className="text-slate-700">equity {Number.isFinite(tracker.equity) ? `$${_fmt2(tracker.equity, 2)}` : '-'}</div>
          <div className="text-xs text-slate-500 mt-1">peak {Number.isFinite(tracker.peak) ? `$${_fmt2(tracker.peak, 2)}` : '-'}</div>
          <div className="text-xs text-slate-500 mt-1">dd {Number.isFinite(tracker.dd) ? _fmtPct(tracker.dd, 2) : '-'}</div>
          <div className="text-xs text-slate-500 mt-1">cooldown {tracker.cooldownUntilMs > 0 ? _fmtTs(tracker.cooldownUntilMs) : '-'}</div>
        </div>

        <div className="border rounded p-3 bg-white">
          <div className="font-semibold mb-1">Live risk</div>
          <div className="text-slate-700">{!live.enabled ? 'disabled' : live.ok ? 'ok' : 'blocked'}</div>
          <div className="text-xs text-slate-500 mt-1">dd {Number.isFinite(live.dd) ? _fmtPct(live.dd, 2) : '-'} / limit {Number.isFinite(live.ddLimit) ? _fmtPct(live.ddLimit, 2) : '-'}</div>
          {live.reason ? <div className="text-xs text-slate-500 mt-1">{live.reason}</div> : null}
        </div>

        <div className="border rounded p-3 bg-white">
          <div className="font-semibold mb-1">Defaults</div>
          <div className="text-slate-700">{enabled ? 'enabled' : 'disabled'} · {hasOverride ? 'override' : 'base'}</div>
          <div className="text-xs text-slate-500 mt-1">max_dd {_fmtPct(base.max_dd, 2)}</div>
          <div className="text-xs text-slate-500 mt-1">max_daily_loss {_fmtPct(base.max_daily_loss, 2)}</div>
          <div className="text-xs text-slate-500 mt-1">max_weekly_loss {_fmtPct(base.max_weekly_loss, 2)}</div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div>
          <div className="text-xs text-slate-500 mb-1">init_equity_usdc</div>
          <Input type="number" step="1" value={draft.init_equity_usdc} onChange={handleDraftNumber('init_equity_usdc')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">max_dd</div>
          <Input type="number" step="0.01" value={draft.max_dd} onChange={handleDraftNumber('max_dd')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">max_daily_loss</div>
          <Input type="number" step="0.01" value={draft.max_daily_loss} onChange={handleDraftNumber('max_daily_loss')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">max_weekly_loss</div>
          <Input type="number" step="0.01" value={draft.max_weekly_loss} onChange={handleDraftNumber('max_weekly_loss')} disabled={saving} />
        </div>

        <div>
          <div className="text-xs text-slate-500 mb-1">dd_cooldown_sec</div>
          <Input type="number" step="60" value={draft.dd_cooldown_sec} onChange={handleDraftNumber('dd_cooldown_sec')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">daily_cooldown_sec</div>
          <Input type="number" step="60" value={draft.daily_cooldown_sec} onChange={handleDraftNumber('daily_cooldown_sec')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">weekly_cooldown_sec</div>
          <Input type="number" step="60" value={draft.weekly_cooldown_sec} onChange={handleDraftNumber('weekly_cooldown_sec')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">vol_target_atr_pct</div>
          <Input type="number" step="0.005" value={draft.vol_target_atr_pct} onChange={handleDraftNumber('vol_target_atr_pct')} disabled={saving} />
        </div>

        <div>
          <div className="text-xs text-slate-500 mb-1">vol_scale_min</div>
          <Input type="number" step="0.05" value={draft.vol_scale_min} onChange={handleDraftNumber('vol_scale_min')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">vol_scale_max</div>
          <Input type="number" step="0.1" value={draft.vol_scale_max} onChange={handleDraftNumber('vol_scale_max')} disabled={saving} />
        </div>
        <div>
          <div className="text-xs text-slate-500 mb-1">max_trade_notional_usdc (空=继承)</div>
          <Input type="number" step="1" value={draft.max_trade_notional_usdc ?? ''} onChange={handleMaxTrade} disabled={saving} />
        </div>
      </div>

      <div className="mt-4 flex gap-2 items-center">
        <Button size="sm" onClick={() => onSave(draft, confirmLive)} disabled={saveDisabled}>Save</Button>
        <Button size="sm" variant="secondary" onClick={() => setDraft(initial)} disabled={saving}>Reset</Button>
        <Button size="sm" variant="secondary" onClick={() => onClearOverride(confirmLive)} disabled={(!hasOverride) || saveDisabled}>Clear override</Button>
        {liveMode ? (
          <label className="text-xs text-slate-600 flex items-center gap-2 ml-2">
            <input type="checkbox" checked={confirmLive} onChange={(e) => setConfirmLive(e.target.checked)} disabled={saving} />
            <span>confirm_live</span>
          </label>
        ) : null}
        <div className="text-xs text-slate-500 flex items-center">{saving ? 'Saving…' : msg}</div>
      </div>
    </>
  );
};

export const QuantStrategiesPage: React.FC = () => {
  const qc = useQueryClient();
  const [timeframe, setTimeframe] = useState<string>(_defaultDraft.timeframe);
  const [btcEthCollapsed, setBtcEthCollapsed] = useState<boolean>(false);
  const [btcAltsCollapsed, setBtcAltsCollapsed] = useState<boolean>(true);

  const [btcAlt, setBtcAlt] = useState<string>('ETH');
  const [btcAltTimeframe, setBtcAltTimeframe] = useState<string>(_defaultDraft.timeframe);

  const [execModeOverride, setExecModeOverride] = useState<'dry-run' | 'execute' | null>(null);
  const [execDirection, setExecDirection] = useState<'long_btc_short_eth' | 'short_btc_long_eth'>('long_btc_short_eth');
  const [execNotional, setExecNotional] = useState<number>(200);
  const [execMakerMode, setExecMakerMode] = useState<'off' | 'auto' | 'on'>('auto');

  const [executeToken, setExecuteTokenLocal] = useState<string>(() => getExecuteToken());
  const [operatorOk, setOperatorOk] = useState<boolean>(() => hasOperatorToken());
  const [tierMsg, setTierMsg] = useState<string>('');

  const [quantLiveConfirm, setQuantLiveConfirm] = useState<boolean>(false);
  const [quantLiveMsg, setQuantLiveMsg] = useState<string>('');

  const [autoCfgTouched, setAutoCfgTouched] = useState<boolean>(false);
  const [autoCfgMsg, setAutoCfgMsg] = useState<string>('');
  const [autoCfgDraft, setAutoCfgDraft] = useState<QuantAutoBtcaltsDraft>(() => ({
    quant_auto_mode: 'off',
    quant_auto_enabled: false,
    quant_auto_btceth_enabled: false,
    quant_auto_btcalts_enabled: false,
    quant_auto_state_check_interval_sec: 60,
    quant_auto_daily_loss_limit_pct: 0,
    quant_auto_weekly_loss_limit_pct: 0,
    quant_auto_net_btc_pct_max: 0,
    quant_auto_pair_notional_usdc_max: 0,
    quant_auto_max_open_pairs_total: 0,

    quant_auto_btcalts_capacity_turnover_frac: 0,
    quant_auto_btcalts_capacity_depth_frac: 0,
    quant_pairs_btcalt_capacity_turnover_frac: 0,
    quant_pairs_btcalt_capacity_depth_frac: 0,

    quant_auto_btcalts_scan_n: 12,
    quant_auto_btcalts_open_per_tick: 1,
    quant_auto_btcalts_cooldown_bars: 12,
    quant_auto_btcalts_max_open_pairs: 1,
    quant_auto_btcalts_max_per_cluster: 1,
    quant_auto_btcalts_macro_trend_required: false,
    quant_auto_btcalts_z_bias_min: 1.5,
    quant_auto_btcalts_z_bias_weight: 0.25,
    quant_auto_btcalts_notional_nontrend_mult: 1.0,
    quant_auto_btcalts_open_per_tick_nontrend: 1,
    quant_auto_btcalts_max_open_pairs_nontrend: 1,
    quant_auto_btcalts_dynamic_hedge_enabled: false,
    quant_auto_btcalts_dynamic_hedge_step: 0.1,
    quant_auto_btcalts_btc_hedge_frac: 0,
  }));
  const [autoTickMsg, setAutoTickMsg] = useState<string>('');

  useEffect(() => {
    const refresh = () => setOperatorOk(hasOperatorToken());
    const unsub = subscribeExecuteToken((t) => {
      setExecuteTokenLocal(String(t || ''));
      refresh();
    });
    const unsubConfig = subscribeConfigToken(() => refresh());
    const unsubMaintenance = subscribeMaintenanceToken(() => refresh());
    const onStorage = (e: StorageEvent) => {
      if (e.key !== 'execute_token' && e.key !== 'config_token' && e.key !== 'maintenance_token') return;
      setExecuteTokenLocal(getExecuteToken());
      refresh();
    };
    window.addEventListener('storage', onStorage);
    return () => {
      unsub();
      unsubConfig();
      unsubMaintenance();
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  const [confirmExecute, setConfirmExecute] = useState<boolean>(false);

  const [execBtcAltDirection, setExecBtcAltDirection] = useState<'long_alt_short_btc' | 'short_alt_long_btc'>('long_alt_short_btc');
  const [execBtcAltNotional, setExecBtcAltNotional] = useState<number>(200);

  const [btLimit, setBtLimit] = useState<number>(2000);
  const [btNotional, setBtNotional] = useState<number>(200);
  const [btApplyCost, setBtApplyCost] = useState<'on' | 'off'>('on');

  const [wfoTouched, setWfoTouched] = useState<boolean>(false);
  const [wfoEnabledDraft, setWfoEnabledDraft] = useState<boolean>(false);
  const [wfoApplyDraft, setWfoApplyDraft] = useState<boolean>(false);
  const [wfoRefreshSecDraft, setWfoRefreshSecDraft] = useState<number>(3600);
  const [wfoPlateauMinFracDraft, setWfoPlateauMinFracDraft] = useState<number>(0.6);
  const [wfoPlateauTolDraft, setWfoPlateauTolDraft] = useState<number>(0.1);
  const [wfoIsBarsDraft, setWfoIsBarsDraft] = useState<number>(480);
  const [wfoOosBarsDraft, setWfoOosBarsDraft] = useState<number>(240);
  const [wfoStepBarsDraft, setWfoStepBarsDraft] = useState<number>(240);
  const [wfoEmbargoBarsDraft, setWfoEmbargoBarsDraft] = useState<number>(0);
  const [wfoGridDraft, setWfoGridDraft] = useState<string>('');

  const [rsSubset, setRsSubset] = useState<'full' | 'bull' | 'bear' | 'sideways'>('full');
  const [rsSplitTouched, setRsSplitTouched] = useState<boolean>(false);
  const [rsSplitLimit, setRsSplitLimit] = useState<number>(0);
  const [rsGapBars, setRsGapBars] = useState<number>(3);
  const [rsPurgeBars, setRsPurgeBars] = useState<number>(_defaultDraft.max_hold_bars);
  const [rsEmbargoBars, setRsEmbargoBars] = useState<number>(_defaultDraft.max_hold_bars);
  const [rsSplitWindowOls, setRsSplitWindowOls] = useState<number>(_defaultDraft.window_ols);
  const [rsSplitWindowZ, setRsSplitWindowZ] = useState<number>(_defaultDraft.window_z);
  const [rsExport, setRsExport] = useState<boolean>(false);

  const [rsCapacityLimit, setRsCapacityLimit] = useState<number>(8000);
  const [rsCapacityNotionals, setRsCapacityNotionals] = useState<string>('100,300,1000');
  const [rsCapacityApplyWfo, setRsCapacityApplyWfo] = useState<boolean>(false);

  const [rsMarginLookback, setRsMarginLookback] = useState<number>(720);
  const [rsMarginPaths, setRsMarginPaths] = useState<number>(1000);
  const [rsMarginHorizonHours, setRsMarginHorizonHours] = useState<number>(1.0);
  const [rsMarginLeverage, setRsMarginLeverage] = useState<number>(5.0);
  const [rsMarginNotionalBtc, setRsMarginNotionalBtc] = useState<number>(200.0);
  const [rsMarginImr, setRsMarginImr] = useState<number>(0);
  const [rsMarginMmr, setRsMarginMmr] = useState<number>(0);
  const [rsMarginConf, setRsMarginConf] = useState<number>(0.99);
  const [rsMarginDfT, setRsMarginDfT] = useState<number>(0);
  const [rsMarginSeed, setRsMarginSeed] = useState<number>(7);
  const [rsMarginVolMultLevels, setRsMarginVolMultLevels] = useState<string>('1.0,1.5,2.0,2.5');

  const [btcAltBtLimit, setBtcAltBtLimit] = useState<number>(2000);
  const [btcAltBtNotional, setBtcAltBtNotional] = useState<number>(200);
  const [btcAltBtApplyCost, setBtcAltBtApplyCost] = useState<'on' | 'off'>('on');

  const [btcAltPfLimit, setBtcAltPfLimit] = useState<number>(2500);
  const [btcAltPfNotional, setBtcAltPfNotional] = useState<number>(400);
  const [btcAltPfApplyCost, setBtcAltPfApplyCost] = useState<'on' | 'off'>('on');
  const [btcAltPfAlts, setBtcAltPfAlts] = useState<string>('');
  const [btcAltPfMaxAlts, setBtcAltPfMaxAlts] = useState<number>(10);
  const [btcAltPfNotionalGrid, setBtcAltPfNotionalGrid] = useState<string>('');

  const q = useQuery({
    queryKey: ['quant', 'pairs', 'btceth', timeframe],
    queryFn: () => fetchQuantPairBtcEthStatus({ timeframe, limit: 800 }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qBacktest = useQuery({
    queryKey: ['quant', 'pairs', 'btceth', 'backtest', timeframe, btLimit, btNotional, btApplyCost],
    queryFn: () =>
      fetchQuantPairBtcEthBacktest({
        timeframe,
        limit: btLimit,
        notional_usdc: btNotional,
        apply_cost: btApplyCost === 'on',
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qResearchSplit = useQuery({
    queryKey: [
      'quant',
      'pairs',
      'btceth',
      'research',
      'split',
      timeframe,
      rsSubset,
      rsSplitLimit,
      rsGapBars,
      rsSplitTouched ? rsPurgeBars : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.max_hold_bars, rsPurgeBars),
      rsSplitTouched ? rsEmbargoBars : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.max_hold_bars, rsEmbargoBars),
      rsSplitTouched ? rsSplitWindowOls : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.window_ols, rsSplitWindowOls),
      rsSplitTouched ? rsSplitWindowZ : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.window_z, rsSplitWindowZ),
      rsExport,
    ],
    queryFn: () =>
      fetchQuantPairBtcEthResearchSplit({
        timeframe,
        subset: rsSubset,
        limit: rsSplitLimit,
        gap_bars: rsGapBars,
        purge_bars: rsSplitTouched ? rsPurgeBars : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.max_hold_bars, rsPurgeBars),
        embargo_bars: rsSplitTouched ? rsEmbargoBars : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.max_hold_bars, rsEmbargoBars),
        window_ols: rsSplitTouched ? rsSplitWindowOls : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.window_ols, rsSplitWindowOls),
        window_z: rsSplitTouched ? rsSplitWindowZ : _toNum((q.data as QuantPairBtcEthStatusResponse | undefined)?.params?.window_z, rsSplitWindowZ),
        export: rsExport,
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qResearchCapacity = useQuery({
    queryKey: ['quant', 'pairs', 'btceth', 'research', 'capacity', timeframe, rsSubset, rsCapacityLimit, rsCapacityNotionals, rsCapacityApplyWfo],
    queryFn: () =>
      fetchQuantPairBtcEthResearchCapacity({
        timeframe,
        subset: rsSubset,
        limit: rsCapacityLimit,
        notionals: rsCapacityNotionals.trim() ? rsCapacityNotionals.trim() : undefined,
        apply_wfo: rsCapacityApplyWfo,
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qResearchMargin = useQuery({
    queryKey: ['quant', 'pairs', 'btceth', 'research', 'margin', timeframe, rsMarginLookback, rsMarginPaths, rsMarginHorizonHours, rsMarginLeverage, rsMarginNotionalBtc, rsMarginImr, rsMarginMmr, rsMarginConf, rsMarginDfT, rsMarginSeed, rsMarginVolMultLevels],
    queryFn: () =>
      fetchQuantPairBtcEthResearchMarginStress({
        timeframe,
        lookback_bars: rsMarginLookback,
        paths: rsMarginPaths,
        horizon_hours: rsMarginHorizonHours,
        leverage: rsMarginLeverage,
        notional_btc_usdc: rsMarginNotionalBtc,
        imr: rsMarginImr > 0 ? rsMarginImr : undefined,
        mmr: rsMarginMmr > 0 ? rsMarginMmr : undefined,
        conf: rsMarginConf,
        df_t: rsMarginDfT,
        seed: rsMarginSeed,
        vol_mult_levels: rsMarginVolMultLevels.trim() ? rsMarginVolMultLevels.trim() : undefined,
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qConfig = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig,
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const cfg = qConfig.data as Config | undefined;
  const quantBtcAltStrategyMode = useMemo<'A' | 'B' | 'C'>(() => {
    const raw = String(cfg?.quant_auto_btcalts_strategy_mode ?? 'B').trim().toUpperCase();
    if (raw === 'A' || raw === 'B' || raw === 'C') return raw;
    return 'B';
  }, [cfg?.quant_auto_btcalts_strategy_mode]);

  const autoCfgFromConfig = useMemo<QuantAutoBtcaltsDraft>(() => {
    const rawMode = String(cfg?.quant_auto_mode ?? 'off').trim().toLowerCase();
    const mode = rawMode === 'monitor' || rawMode === 'paper' || rawMode === 'live' ? rawMode : 'off';
    const qDayRaw = _toNum(cfg?.quant_max_daily_loss, _toNum(cfg?.max_daily_loss, -0.05));
    const qWkRaw = _toNum(cfg?.quant_max_weekly_loss, _toNum(cfg?.max_weekly_loss, -0.12));
    return {
      quant_auto_mode: mode,
      quant_auto_enabled: Boolean(cfg?.quant_auto_enabled),
      quant_auto_btceth_enabled: Boolean(cfg?.quant_auto_btceth_enabled),
      quant_auto_btcalts_enabled: Boolean(cfg?.quant_auto_btcalts_enabled),
      quant_auto_state_check_interval_sec: Math.max(1, Math.trunc(_toNum(cfg?.quant_auto_state_check_interval_sec, 60))),
      quant_auto_daily_loss_limit_pct: Math.max(0, Math.abs(qDayRaw)),
      quant_auto_weekly_loss_limit_pct: Math.max(0, Math.abs(qWkRaw)),
      quant_auto_net_btc_pct_max: _toNum(cfg?.quant_auto_net_btc_pct_max, 0),
      quant_auto_pair_notional_usdc_max: _toNum(cfg?.quant_auto_pair_notional_usdc_max, 0),
      quant_auto_max_open_pairs_total: Math.max(0, Math.trunc(_toNum(cfg?.quant_auto_max_open_pairs_total, 0))),

      quant_auto_btcalts_capacity_turnover_frac: _toNum(cfg?.quant_auto_btcalts_capacity_turnover_frac, 0),
      quant_auto_btcalts_capacity_depth_frac: _toNum(cfg?.quant_auto_btcalts_capacity_depth_frac, 0),
      quant_pairs_btcalt_capacity_turnover_frac: _toNum(cfg?.quant_pairs_btcalt_capacity_turnover_frac, 0),
      quant_pairs_btcalt_capacity_depth_frac: _toNum(cfg?.quant_pairs_btcalt_capacity_depth_frac, 0),

      quant_auto_btcalts_scan_n: Math.max(1, Math.trunc(_toNum(cfg?.quant_auto_btcalts_scan_n, 12))),
      quant_auto_btcalts_open_per_tick: Math.max(0, Math.trunc(_toNum(cfg?.quant_auto_btcalts_open_per_tick, 1))),
      quant_auto_btcalts_cooldown_bars: Math.max(0, Math.trunc(_toNum(cfg?.quant_auto_btcalts_cooldown_bars, 12))),
      quant_auto_btcalts_max_open_pairs: Math.max(0, Math.trunc(_toNum(cfg?.quant_auto_btcalts_max_open_pairs, 1))),
      quant_auto_btcalts_max_per_cluster: Math.max(0, Math.trunc(_toNum(cfg?.quant_auto_btcalts_max_per_cluster, 1))),
      quant_auto_btcalts_macro_trend_required: Boolean(cfg?.quant_auto_btcalts_macro_trend_required),
      quant_auto_btcalts_z_bias_min: _toNum(cfg?.quant_auto_btcalts_z_bias_min, 1.5),
      quant_auto_btcalts_z_bias_weight: _toNum(cfg?.quant_auto_btcalts_z_bias_weight, 0.25),
      quant_auto_btcalts_notional_nontrend_mult: _toNum(cfg?.quant_auto_btcalts_notional_nontrend_mult, 1.0),
      quant_auto_btcalts_open_per_tick_nontrend: Math.max(0, Math.trunc(_toNum(cfg?.quant_auto_btcalts_open_per_tick_nontrend, 1))),
      quant_auto_btcalts_max_open_pairs_nontrend: Math.max(0, Math.trunc(_toNum(cfg?.quant_auto_btcalts_max_open_pairs_nontrend, 1))),
      quant_auto_btcalts_dynamic_hedge_enabled: Boolean(cfg?.quant_auto_btcalts_dynamic_hedge_enabled),
      quant_auto_btcalts_dynamic_hedge_step: _toNum(cfg?.quant_auto_btcalts_dynamic_hedge_step, 0.1),
      quant_auto_btcalts_btc_hedge_frac: _toNum(cfg?.quant_auto_btcalts_btc_hedge_frac, 0),
    };
  }, [
    cfg?.quant_auto_mode,
    cfg?.quant_auto_enabled,
    cfg?.quant_auto_btceth_enabled,
    cfg?.quant_auto_btcalts_enabled,
    cfg?.quant_auto_state_check_interval_sec,
    cfg?.quant_max_daily_loss,
    cfg?.quant_max_weekly_loss,
    cfg?.max_daily_loss,
    cfg?.max_weekly_loss,
    cfg?.quant_auto_net_btc_pct_max,
    cfg?.quant_auto_pair_notional_usdc_max,
    cfg?.quant_auto_max_open_pairs_total,
    cfg?.quant_auto_btcalts_capacity_turnover_frac,
    cfg?.quant_auto_btcalts_capacity_depth_frac,
    cfg?.quant_pairs_btcalt_capacity_turnover_frac,
    cfg?.quant_pairs_btcalt_capacity_depth_frac,
    cfg?.quant_auto_btcalts_scan_n,
    cfg?.quant_auto_btcalts_open_per_tick,
    cfg?.quant_auto_btcalts_cooldown_bars,
    cfg?.quant_auto_btcalts_max_open_pairs,
    cfg?.quant_auto_btcalts_max_per_cluster,
    cfg?.quant_auto_btcalts_macro_trend_required,
    cfg?.quant_auto_btcalts_z_bias_min,
    cfg?.quant_auto_btcalts_z_bias_weight,
    cfg?.quant_auto_btcalts_notional_nontrend_mult,
    cfg?.quant_auto_btcalts_open_per_tick_nontrend,
    cfg?.quant_auto_btcalts_max_open_pairs_nontrend,
    cfg?.quant_auto_btcalts_dynamic_hedge_enabled,
    cfg?.quant_auto_btcalts_dynamic_hedge_step,
    cfg?.quant_auto_btcalts_btc_hedge_frac,
  ]);

  const autoCfgEff = autoCfgTouched ? autoCfgDraft : autoCfgFromConfig;

  const qBtcAlt = useQuery({
    queryKey: ['quant', 'pairs', 'btcalt', btcAltTimeframe, btcAlt, quantBtcAltStrategyMode],
    queryFn: () => fetchQuantPairBtcAltStatus({ timeframe: btcAltTimeframe, alt: btcAlt, limit: 800, strategy_mode: quantBtcAltStrategyMode }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qBtcAltPortfolio = useQuery({
    queryKey: ['quant', 'pairs', 'btcalt', 'portfolio', btcAltTimeframe, btcAltPfLimit, btcAltPfNotional, btcAltPfApplyCost, btcAltPfAlts, btcAltPfMaxAlts, btcAltPfNotionalGrid],
    queryFn: () =>
      fetchQuantPairBtcAltPortfolioSimulate({
        timeframe: btcAltTimeframe,
        limit: btcAltPfLimit,
        gross_notional_usdc: btcAltPfNotional,
        apply_cost: btcAltPfApplyCost === 'on',
        alts: btcAltPfAlts.trim() ? btcAltPfAlts.trim() : undefined,
        max_alts: btcAltPfMaxAlts,
        notional_grid: btcAltPfNotionalGrid.trim() ? btcAltPfNotionalGrid.trim() : undefined,
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qBtcAltBacktest = useQuery({
    queryKey: ['quant', 'pairs', 'btcalt', 'backtest', btcAltTimeframe, btcAlt, btcAltBtLimit, btcAltBtNotional, btcAltBtApplyCost],
    queryFn: () =>
      fetchQuantPairBtcAltBacktest({
        timeframe: btcAltTimeframe,
        alt: btcAlt,
        limit: btcAltBtLimit,
        notional_usdc: btcAltBtNotional,
        apply_cost: btcAltBtApplyCost === 'on',
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qBtcAltResearchSplit = useQuery({
    queryKey: [
      'quant',
      'pairs',
      'btcalt',
      'research',
      'split',
      btcAltTimeframe,
      btcAlt,
      rsSubset,
      rsSplitLimit,
      rsGapBars,
      rsSplitTouched ? rsPurgeBars : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.max_hold_bars, rsPurgeBars),
      rsSplitTouched ? rsEmbargoBars : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.max_hold_bars, rsEmbargoBars),
      rsSplitTouched ? rsSplitWindowOls : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.window_ols, rsSplitWindowOls),
      rsSplitTouched ? rsSplitWindowZ : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.window_z, rsSplitWindowZ),
      rsExport,
    ],
    queryFn: () =>
      fetchQuantPairBtcAltResearchSplit({
        timeframe: btcAltTimeframe,
        alt: btcAlt,
        subset: rsSubset,
        limit: rsSplitLimit,
        gap_bars: rsGapBars,
        purge_bars: rsSplitTouched ? rsPurgeBars : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.max_hold_bars, rsPurgeBars),
        embargo_bars: rsSplitTouched ? rsEmbargoBars : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.max_hold_bars, rsEmbargoBars),
        window_ols: rsSplitTouched ? rsSplitWindowOls : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.window_ols, rsSplitWindowOls),
        window_z: rsSplitTouched ? rsSplitWindowZ : _toNum((qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined)?.params?.window_z, rsSplitWindowZ),
        export: rsExport,
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qBtcAltResearchCapacity = useQuery({
    queryKey: ['quant', 'pairs', 'btcalt', 'research', 'capacity', btcAltTimeframe, btcAlt, rsSubset, rsCapacityLimit, rsCapacityNotionals, rsCapacityApplyWfo],
    queryFn: () =>
      fetchQuantPairBtcAltResearchCapacity({
        timeframe: btcAltTimeframe,
        alt: btcAlt,
        subset: rsSubset,
        limit: rsCapacityLimit,
        notionals: rsCapacityNotionals.trim() ? rsCapacityNotionals.trim() : undefined,
        apply_wfo: rsCapacityApplyWfo,
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qBtcAltResearchMargin = useQuery({
    queryKey: ['quant', 'pairs', 'btcalt', 'research', 'margin', btcAltTimeframe, btcAlt, rsMarginLookback, rsMarginPaths, rsMarginHorizonHours, rsMarginLeverage, rsMarginNotionalBtc, rsMarginImr, rsMarginMmr, rsMarginConf, rsMarginDfT, rsMarginSeed, rsMarginVolMultLevels],
    queryFn: () =>
      fetchQuantPairBtcAltResearchMarginStress({
        timeframe: btcAltTimeframe,
        alt: btcAlt,
        lookback_bars: rsMarginLookback,
        paths: rsMarginPaths,
        horizon_hours: rsMarginHorizonHours,
        leverage: rsMarginLeverage,
        notional_btc_usdc: rsMarginNotionalBtc,
        imr: rsMarginImr > 0 ? rsMarginImr : undefined,
        mmr: rsMarginMmr > 0 ? rsMarginMmr : undefined,
        conf: rsMarginConf,
        df_t: rsMarginDfT,
        seed: rsMarginSeed,
        vol_mult_levels: rsMarginVolMultLevels.trim() ? rsMarginVolMultLevels.trim() : undefined,
      }),
    enabled: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qBtcAltCandidates = useQuery({
    queryKey: ['quant', 'pairs', 'btcalt', 'candidates', btcAltTimeframe, btcAltPfMaxAlts],
    queryFn: () => fetchQuantPairBtcAltCandidates({ timeframe: btcAltTimeframe, max_alts: btcAltPfMaxAlts, include_snap: true, cache_ttl_sec: 300 }),
    refetchInterval: 300000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const std1hN = 3;
  const macro1hStorageKey = 'quant_final_std1h_btc_seq_v1';
  const [macro1hSeq, setMacro1hSeq] = useState<Std1hPoint[]>(() => _loadStd1hSeq(macro1hStorageKey));

  const qMacro = useQuery({
    queryKey: ['macro', 'btceth', 'overview', 'quant'],
    queryFn: async (): Promise<MacroBtcEthOverviewResponse> => {
      const d = await fetchMacroBtcEthOverview({ lookback_days: 120, flow_lookback_days: 120 });
      const std1h = d?.std_1h;
      const ts = Number(std1h?.ts ?? 0);
      const risk = std1h?.btc?.risk_pct;
      const value = std1h?.btc?.value_pct;
      const dir = std1h?.btc?.dir;
      if (ts > 0) {
        const p: Std1hPoint = {
          ts,
          risk: typeof risk === 'number' && Number.isFinite(risk) ? risk : null,
          value: typeof value === 'number' && Number.isFinite(value) ? value : null,
          dir: typeof dir === 'number' && Number.isFinite(dir) ? dir : null,
        };
        setMacro1hSeq((prev) => {
          const next = _pushStd1hSeq(prev, p, std1hN);
          if (next.length !== prev.length || next[next.length - 1]?.ts !== prev[prev.length - 1]?.ts) {
            _saveStd1hSeq(macro1hStorageKey, next);
          }
          return next;
        });
      }
      return d;
    },
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qUniversePairs = useQuery({
    queryKey: ['universe', 'pairs', 'quant'],
    queryFn: () => fetchUniversePairs(),
    refetchInterval: 300000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qUniverseStatus = useQuery({
    queryKey: ['universe', 'status', 'quant'],
    queryFn: () => fetchUniverseStatus(),
    refetchInterval: 300000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qCombo = useQuery({
    queryKey: ['quant', 'pairs', 'combo', 'supervision'],
    queryFn: () => fetchQuantComboSupervision(),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qLive = useQuery({
    queryKey: ['live', 'preflight'],
    queryFn: () => livePreflight(),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qTracker = useQuery({
    queryKey: ['tracker', 'sync', false, 'ui'],
    queryFn: () => fetchTrackerStats({ sync: false, view: 'ui' }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qGateState = useQuery({
    queryKey: ['diagnostics', 'gate_state'],
    queryFn: () => fetchDiagnosticsGateState(),
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qRisk = useQuery({
    queryKey: ['live', 'risk', 'quant_pairs_btceth'],
    queryFn: () => liveRiskCheck({ strategy_id: 'quant_pairs_btceth' }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qAutoBtcEth = useQuery({
    queryKey: ['quant', 'auto', 'btceth', 'last'],
    queryFn: () => fetchQuantAutoBtcEthLast(),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const qAutoBtcalts = useQuery({
    queryKey: ['quant', 'auto', 'btcalts', 'last'],
    queryFn: () => fetchQuantAutoBtcaltsLast(),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });


  const data = q.data as QuantPairBtcEthStatusResponse | undefined;
  const backtest = qBacktest.data as QuantPairBtcEthBacktestResponse | undefined;
  const scaleCurve = (backtest?.scale_curve ?? null) as QuantPairBtcEthScaleCurveItem[] | null;
  const btFundingBtc = _toNum(backtest?.funding_mean_8h_btc, Number.NaN);
  const btFundingEth = _toNum(backtest?.funding_mean_8h_eth, Number.NaN);

  const autoBtcEth = qAutoBtcEth.data as QuantAutoBtcEthLastResponse | undefined;
  const autoBtcalts = qAutoBtcalts.data as QuantAutoBtcaltsLastResponse | undefined;

  const autoBtcEthOk = Boolean(autoBtcEth?.ok);
  const autoBtcEthTs = _toNum(autoBtcEth?.ts, 0);
  const autoBtcEthState = String(autoBtcEth?.state ?? '').trim();
  const autoBtcEthBadgeVariant = autoBtcEthState === 'EMERGENCY_EXITING' ? 'destructive' : autoBtcEthState === 'COOLDOWN' ? 'secondary' : 'outline';

  const autoBtcaltsOk = Boolean(autoBtcalts?.ok);
  const autoBtcaltsTs = _toNum(autoBtcalts?.ts, 0);
  const autoBtcaltsDecision = (autoBtcalts?.decision ?? null) as Record<string, unknown> | null;
  const autoBtcaltsAction = String((autoBtcaltsDecision as { action?: unknown } | null)?.action ?? '').trim();
  const autoBtcaltsBlocked = String((autoBtcalts as { blocked?: unknown } | undefined)?.blocked ?? '').trim();

  const autoBtcaltsRebalance = (autoBtcalts?.rebalance ?? null) as Record<string, unknown> | null;
  const autoBtcaltsRbEnabled = Boolean((autoBtcaltsRebalance as { enabled?: unknown } | null)?.enabled);
  const autoBtcaltsRbSkip = String((autoBtcaltsRebalance as { skip?: unknown } | null)?.skip ?? '').trim();
  const autoBtcaltsRbCombo = (autoBtcaltsRebalance as { combo?: unknown } | null)?.combo as Record<string, unknown> | null;
  const autoBtcaltsRbComboState = (autoBtcaltsRbCombo as { state?: unknown } | null)?.state as Record<string, unknown> | null;
  const autoBtcaltsRbNeeded = Boolean((autoBtcaltsRbComboState as { rebalance_needed?: unknown } | null)?.rebalance_needed);
  const autoBtcaltsRbDelta = _toNum((autoBtcaltsRbComboState as { rebalance_delta_btc_leg_usdc?: unknown } | null)?.rebalance_delta_btc_leg_usdc, Number.NaN);
  const autoBtcaltsRbDeltaSide = Number.isFinite(autoBtcaltsRbDelta) ? (autoBtcaltsRbDelta > 0 ? 'LONG BTC' : 'SHORT BTC') : '';
  const autoBtcaltsRbDeltaAbs = Number.isFinite(autoBtcaltsRbDelta) ? Math.abs(autoBtcaltsRbDelta) : Number.NaN;
  const autoBtcaltsRbExec = (autoBtcaltsRebalance as { exec?: unknown } | null)?.exec as Record<string, unknown> | null;
  const autoBtcaltsRbExecOk = Boolean((autoBtcaltsRbExec as { ok?: unknown } | null)?.ok);
  const autoBtcaltsRbExecErr = String((autoBtcaltsRbExec as { error?: unknown; err?: unknown } | null)?.error ?? (autoBtcaltsRbExec as { err?: unknown } | null)?.err ?? '').trim();
  const autoBtcaltsRbExecNotional = _toNum(
    (autoBtcaltsRbExec as { requested_notional_usdc?: unknown; notional_usdc?: unknown } | null)?.requested_notional_usdc ??
      (autoBtcaltsRbExec as { notional_usdc?: unknown } | null)?.notional_usdc,
    Number.NaN,
  );
  const autoBtcaltsRbExecOrderId = String((autoBtcaltsRbExec as { order_id?: unknown } | null)?.order_id ?? '').trim();
  const autoBtcaltsRbMinNotional = _toNum((autoBtcaltsRebalance as { min_notional_usdc?: unknown } | null)?.min_notional_usdc, Number.NaN);
  const autoBtcaltsRbMaxNotional = _toNum((autoBtcaltsRebalance as { max_notional_usdc?: unknown } | null)?.max_notional_usdc, Number.NaN);
  const autoBtcaltsRbCooldownSec = _toNum((autoBtcaltsRebalance as { cooldown_sec?: unknown } | null)?.cooldown_sec, Number.NaN);

  const btcAltData = qBtcAlt.data as QuantPairBtcAltStatusResponse | undefined;
  const btcAltPortfolio = qBtcAltPortfolio.data as QuantPairBtcAltPortfolioSimulateResponse | undefined;
  const btcAltBacktest = qBtcAltBacktest.data as QuantPairBtcAltBacktestResponse | undefined;
  const btcAltCandidates = qBtcAltCandidates.data as QuantPairBtcAltCandidatesResponse | undefined;

  const btcAltScaleCurve = (btcAltBacktest?.scale_curve ?? null) as QuantPairBtcAltScaleCurveItem[] | null;
  const btAltFundingBtc = _toNum(btcAltBacktest?.funding_mean_8h_btc, Number.NaN);
  const btAltFundingAlt = _toNum(btcAltBacktest?.funding_mean_8h_alt, Number.NaN);

  const macroOverview = qMacro.data as MacroBtcEthOverviewResponse | undefined;
  const universePairs = qUniversePairs.data as UniversePairsResponse | undefined;
  const universeStatus = qUniverseStatus.data as UniverseState | undefined;

  const execVenue = 'aster';

  const execMode = useMemo<'dry-run' | 'execute'>(() => {
    if (execModeOverride) return execModeOverride;
    const liveEnabled = Boolean(cfg?.live_trading_enabled) && cfg?.dry_run !== true;
    return liveEnabled ? 'execute' : 'dry-run';
  }, [cfg?.dry_run, cfg?.live_trading_enabled, execModeOverride]);

  const quantLiveOn = useMemo(() => {
    const globalExecute = Boolean(cfg?.live_trading_enabled) && cfg?.dry_run === false;
    const qaMode = String(cfg?.quant_auto_mode ?? '').trim().toLowerCase();
    return globalExecute && qaMode === 'live' && Boolean(cfg?.quant_auto_enabled);
  }, [cfg?.dry_run, cfg?.live_trading_enabled, cfg?.quant_auto_enabled, cfg?.quant_auto_mode]);
  const tracker = qTracker.data as TrackerStats | undefined;
  const strategyId = 'quant_pairs_btceth';
  const strategyPoolMeta = useMemo(() => {
    return (cfg?.strategy_pool_meta ?? {}) as Record<string, Record<string, unknown>>;
  }, [cfg]);
  const strategyMeta = useMemo(() => {
    return (strategyPoolMeta?.[strategyId] ?? {}) as Record<string, unknown>;
  }, [strategyPoolMeta, strategyId]);

  const liveRiskData = qRisk.data as LiveRiskCheckResponse | undefined;

  const gateState = qGateState.data as DiagnosticsGateStateResponse | undefined;
  const gateTs = _toNum(gateState?.ts, 0);
  const gateSummary = (gateState?.gate_summary ?? null) as Record<string, unknown> | null;
  const gateByOk = (gateSummary?.by_ok ?? null) as Record<string, unknown> | null;
  const gateOkN = _toNum(gateByOk?.ok, 0);
  const gateRejectN = _toNum(gateByOk?.reject, 0);
  const gateByReasonTop = useMemo(() => {
    const by = (gateSummary?.by_reason ?? null) as Record<string, unknown> | null;
    if (!by || typeof by !== 'object') return [] as Array<{ reason: string; n: number }>;
    return Object.entries(by)
      .map(([reason, n]) => ({ reason: String(reason || '(none)'), n: _toNum(n, 0) }))
      .filter((x) => x.n > 0)
      .sort((a, b) => b.n - a.n)
      .slice(0, 6);
  }, [gateSummary]);

  const gateRecent = useMemo(() => {
    const rows = Array.isArray(gateState?.gate_history) ? (gateState?.gate_history as Array<Record<string, unknown>>) : [];
    return rows
      .map((r) => {
        const ts = _toNum(r.ts, 0);
        const pair = String(r.pair ?? '');
        const side = String(r.side ?? '');
        const ok = Boolean(r.ok);
        const reason = String(r.reason ?? '');
        const systemId = String(r.system_id ?? '');
        const corr = _toNum(r.btc_corr_gate_corr, Number.NaN);
        const thrEnter = _toNum(r.btc_corr_gate_enter_thr, Number.NaN);
        const thrExit = _toNum(r.btc_corr_gate_exit_thr, Number.NaN);
        const cacheHit = r.btc_corr_gate_cache_hit == null ? null : Boolean(r.btc_corr_gate_cache_hit);
        return { ts, pair, side, ok, reason, systemId, corr, thrEnter, thrExit, cacheHit };
      })
      .filter((x) => x.ts > 0)
      .sort((a, b) => b.ts - a.ts)
      .slice(0, 20);
  }, [gateState?.gate_history]);

  const combo = qCombo.data as QuantComboSupervisionResponse | undefined;
  const comboOk = Boolean(combo?.ok);
  const comboTs = _toNum(combo?.ts, 0);
  const comboGross = _toNum(combo?.params?.gross_notional_usdc, Number.NaN);
  const comboTarget = _toNum(combo?.params?.net_btc_exposure_target, Number.NaN);
  const comboMax = _toNum(combo?.params?.net_btc_exposure_max, Number.NaN);
  const comboNetLeg = _toNum(combo?.state?.net_btc_leg_usdc, Number.NaN);
  const comboNetFrac = _toNum(combo?.state?.net_btc_exposure_frac, Number.NaN);
  const comboOpenPairs = _toNum(combo?.state?.open_pairs, 0);
  const comboPairsByCluster = (combo?.state?.open_pairs_by_cluster ?? {}) as Record<string, number>;
  const comboReasons = Array.isArray(combo?.reasons) ? combo?.reasons : [];
  const comboNetDeviation =
    Number.isFinite(comboNetFrac) && Number.isFinite(comboTarget) ? comboNetFrac - comboTarget : Number.NaN;
  const comboNetOver =
    Number.isFinite(comboNetDeviation) && Number.isFinite(comboMax) ? Math.abs(comboNetDeviation) > comboMax : false;

  const liveRiskTs = _toNum(liveRiskData?.ts, 0);
  const liveRiskSubp = (liveRiskData?.subportfolio ?? null) as Record<string, unknown> | null;
  const liveRiskOpen = (liveRiskData?.open_positions ?? null) as Record<string, unknown> | null;
  const liveRiskSubpEnabled = Boolean(liveRiskSubp?.enabled);
  const liveRiskSubpOk = Boolean(liveRiskSubp?.ok);
  const liveRiskSubpReason = String(liveRiskSubp?.reason ?? '');
  const liveRiskSubpDecision = String(liveRiskSubp?.decision ?? '');
  const liveRiskSubpWaitMs = _toNum(liveRiskSubp?.wait_ms, 0);
  const liveRiskSubpDd = _toNum(liveRiskSubp?.dd, Number.NaN);
  const liveRiskSubpEquity = _toNum(liveRiskSubp?.equity_usdc, Number.NaN);
  const liveRiskOpenN = _toNum(liveRiskOpen?.n, 0);
  const liveRiskOpenNotional = _toNum(liveRiskOpen?.notional_usdc, 0);

  const liveRiskDdLimit = _toNum(
    (liveRiskSubp as { max_dd?: unknown; dd_limit?: unknown } | null)?.max_dd ??
      (liveRiskSubp as { max_dd?: unknown; dd_limit?: unknown } | null)?.dd_limit,
    Number.NaN,
  );
  const liveRiskDdOver =
    Number.isFinite(liveRiskSubpDd) && Number.isFinite(liveRiskDdLimit) && liveRiskSubpDd >= liveRiskDdLimit;

  const trackerSubpAll = (tracker?.strategy_subportfolios ?? {}) as Record<string, Record<string, unknown>>;
  const trackerSubp = (trackerSubpAll?.[strategyId] ?? null) as Record<string, unknown> | null;
  const trackerSubpEquity = _toNum(trackerSubp?.equity_usdc, Number.NaN);
  const trackerSubpPeak = _toNum(trackerSubp?.peak_equity_usdc, Number.NaN);
  const trackerSubpDd = _toNum(trackerSubp?.dd, Number.NaN);
  const trackerSubpCooldownUntil = _toNum(trackerSubp?.cooldown_until_ms, 0);

  const baseSubpMeta = useMemo<SubportfolioMetaDraft>(() => {
    return {
      init_equity_usdc: _toNum(cfg?.strategy_subportfolio_init_equity_usdc, 100.0),
      max_dd: _toNum(cfg?.strategy_subportfolio_max_dd, 0.25),
      max_daily_loss: _toNum(cfg?.strategy_subportfolio_max_daily_loss, -0.05),
      max_weekly_loss: _toNum(cfg?.strategy_subportfolio_max_weekly_loss, -0.12),
      dd_cooldown_sec: _toNum(cfg?.strategy_subportfolio_dd_cooldown_sec, 21600),
      daily_cooldown_sec: _toNum(cfg?.strategy_subportfolio_daily_cooldown_sec, 10800),
      weekly_cooldown_sec: _toNum(cfg?.strategy_subportfolio_weekly_cooldown_sec, 86400),
      vol_target_atr_pct: _toNum(cfg?.strategy_subportfolio_vol_target_atr_pct, 0.03),
      vol_scale_min: _toNum(cfg?.strategy_subportfolio_vol_scale_min, 0.25),
      vol_scale_max: _toNum(cfg?.strategy_subportfolio_vol_scale_max, 4.0),
      max_trade_notional_usdc: null,
    };
  }, [cfg]);

  const effectiveSubpMeta = useMemo<SubportfolioMetaDraft>(() => {
    const initEq = _toNum(strategyMeta?.init_equity_usdc ?? strategyMeta?.initial_equity_usdc, baseSubpMeta.init_equity_usdc);
    const maxDd = _toNum(strategyMeta?.max_dd, baseSubpMeta.max_dd);
    const maxDay = _toNum(strategyMeta?.max_daily_loss, baseSubpMeta.max_daily_loss);
    const maxWk = _toNum(strategyMeta?.max_weekly_loss, baseSubpMeta.max_weekly_loss);
    const ddCd = _toNum(strategyMeta?.dd_cooldown_sec, baseSubpMeta.dd_cooldown_sec);
    const dayCd = _toNum(strategyMeta?.daily_cooldown_sec, baseSubpMeta.daily_cooldown_sec);
    const wkCd = _toNum(strategyMeta?.weekly_cooldown_sec, baseSubpMeta.weekly_cooldown_sec);
    const volTarget = _toNum(strategyMeta?.vol_target_atr_pct, baseSubpMeta.vol_target_atr_pct);
    const volMin = _toNum(strategyMeta?.vol_scale_min, baseSubpMeta.vol_scale_min);
    const volMax = _toNum(strategyMeta?.vol_scale_max, baseSubpMeta.vol_scale_max);
    const mt = strategyMeta?.max_trade_notional_usdc;
    const mtNum = mt === null || mt === undefined ? null : Number(mt);
    const maxTrade = typeof mtNum === 'number' && Number.isFinite(mtNum) ? mtNum : null;
    return {
      init_equity_usdc: initEq,
      max_dd: maxDd,
      max_daily_loss: maxDay,
      max_weekly_loss: maxWk,
      dd_cooldown_sec: ddCd,
      daily_cooldown_sec: dayCd,
      weekly_cooldown_sec: wkCd,
      vol_target_atr_pct: volTarget,
      vol_scale_min: volMin,
      vol_scale_max: volMax,
      max_trade_notional_usdc: maxTrade,
    };
  }, [baseSubpMeta, strategyMeta]);

  const [subpMsg, setSubpMsg] = useState<string>('');

  const subpEnabled = Boolean(cfg?.strategy_subportfolio_enabled);
  const subpHasOverride = Boolean(strategyPoolMeta && Object.prototype.hasOwnProperty.call(strategyPoolMeta, strategyId));
  const subpLiveMode = (!cfg?.dry_run) && (cfg?.live_trading_enabled ?? false);

  const subpPanelKey = useMemo(() => {
    const x = effectiveSubpMeta;
    return `subp:${strategyId}|o:${subpHasOverride ? 1 : 0}|init:${x.init_equity_usdc}|dd:${x.max_dd}|d:${x.max_daily_loss}|w:${x.max_weekly_loss}|ddcd:${x.dd_cooldown_sec}|dcd:${x.daily_cooldown_sec}|wcd:${x.weekly_cooldown_sec}|vt:${x.vol_target_atr_pct}|vmin:${x.vol_scale_min}|vmax:${x.vol_scale_max}|mt:${x.max_trade_notional_usdc ?? 'null'}`;
  }, [effectiveSubpMeta, strategyId, subpHasOverride]);

  const subpMutation = useMutation({
    mutationFn: (p: Record<string, unknown>) => updateConfig(p as unknown as Partial<Config>),
    onSuccess: () => {
      setSubpMsg('saved');
      qc.invalidateQueries({ queryKey: ['config'] });
      qc.invalidateQueries({ queryKey: ['tracker'] });
      qc.invalidateQueries({ queryKey: ['live', 'risk', 'quant_pairs_btceth'] });
    },
    onError: (e) => {
      setSubpMsg(`error: ${String(e)}`);
    },
  });

  const saveSubp = (draft: SubportfolioMetaDraft, confirmLive: boolean) => {
    if (!cfg) return;
    const nextPool = { ...(strategyPoolMeta ?? {}) } as Record<string, Record<string, unknown>>;
    const prevMeta = (nextPool[strategyId] ?? {}) as Record<string, unknown>;
    const metaPatch = { ...draft } as Record<string, unknown>;
    if (draft.max_trade_notional_usdc === null) delete metaPatch.max_trade_notional_usdc;
    nextPool[strategyId] = { ...prevMeta, ...metaPatch };
    const payload: Record<string, unknown> = { strategy_pool_meta: nextPool };
    if (subpLiveMode && confirmLive) payload.confirm_live = true;
    setSubpMsg('');
    subpMutation.mutate(payload);
  };

  const clearSubpOverride = (confirmLive: boolean) => {
    if (!cfg) return;
    const nextPool = { ...(strategyPoolMeta ?? {}) } as Record<string, Record<string, unknown>>;
    delete nextPool[strategyId];
    const payload: Record<string, unknown> = { strategy_pool_meta: nextPool };
    if (subpLiveMode && confirmLive) payload.confirm_live = true;
    setSubpMsg('');
    subpMutation.mutate(payload);
  };

  const tierMutation = useMutation({
    mutationFn: (tier: 'A' | 'B' | 'C') =>
      updateConfig({ quant_auto_btcalts_strategy_mode: tier } as unknown as Partial<Config>),
    onMutate: () => {
      setTierMsg('saving…');
    },
    onSuccess: (res) => {
      setTierMsg('saved');
      try {
        if (res && typeof res === 'object' && 'config' in res) {
          const nextCfg = (res as unknown as { config?: unknown })?.config;
          if (nextCfg && typeof nextCfg === 'object') {
            qc.setQueryData(['config'], nextCfg);
          }
        }
      } catch {
        void 0;
      }
      qc.invalidateQueries({ queryKey: ['config'] });
    },
    onError: (e) => {
      const err = e as unknown;
      const resp = typeof err === 'object' && err && 'response' in err ? (err as { response?: unknown }).response : undefined;
      const status = typeof resp === 'object' && resp && 'status' in resp ? (resp as { status?: unknown }).status : undefined;
      const data = typeof resp === 'object' && resp && 'data' in resp ? (resp as { data?: unknown }).data : undefined;
      const apiError = typeof data === 'object' && data && 'error' in data ? (data as { error?: unknown }).error : undefined;
      const message = typeof err === 'object' && err && 'message' in err ? (err as { message?: unknown }).message : undefined;
      const msg = String(apiError ?? message ?? err);
      if (String(status ?? '') === '403' || msg.toLowerCase().includes('forbidden')) {
        setTierMsg('forbidden: 需要 execute_token');
      } else {
        setTierMsg(`error: ${msg}`);
      }
    },
  });

  const quantLiveMutation = useMutation({
    mutationFn: (payload: ConfigPatch) => updateConfig(payload),
    onMutate: () => {
      setQuantLiveMsg('saving…');
    },
    onSuccess: (res) => {
      setQuantLiveMsg('saved');
      try {
        if (res && typeof res === 'object' && 'config' in res) {
          const nextCfg = (res as unknown as { config?: unknown })?.config;
          if (nextCfg && typeof nextCfg === 'object') {
            qc.setQueryData(['config'], nextCfg);
          }
        }
      } catch {
        void 0;
      }
      qc.invalidateQueries({ queryKey: ['config'] });
    },
    onError: (e) => {
      const err = e as unknown;
      const resp = typeof err === 'object' && err && 'response' in err ? (err as { response?: unknown }).response : undefined;
      const status = typeof resp === 'object' && resp && 'status' in resp ? (resp as { status?: unknown }).status : undefined;
      const data = typeof resp === 'object' && resp && 'data' in resp ? (resp as { data?: unknown }).data : undefined;
      const apiError = typeof data === 'object' && data && 'error' in data ? (data as { error?: unknown }).error : undefined;
      const message = typeof err === 'object' && err && 'message' in err ? (err as { message?: unknown }).message : undefined;
      const msg = String(apiError ?? message ?? err);
      if (String(status ?? '') === '403' || msg.toLowerCase().includes('forbidden')) {
        setQuantLiveMsg('forbidden: 需要写权限令牌');
      } else {
        setQuantLiveMsg(`error: ${msg}`);
      }
    },
  });

  const setQuantLive = (next: boolean) => {
    if (!operatorOk) {
      setQuantLiveMsg('forbidden: 需要写权限令牌');
      return;
    }
    if (next && !quantLiveConfirm) {
      setQuantLiveMsg('需要勾选 confirm_live');
      return;
    }

    if (next) {
      quantLiveMutation.mutate({
        dry_run: false,
        live_trading_enabled: true,
        quant_auto_mode: 'live',
        quant_auto_enabled: true,
        quant_auto_btceth_enabled: true,
        quant_auto_btcalts_enabled: true,
        confirm_live: true,
      });
      return;
    }

    quantLiveMutation.mutate({
      dry_run: true,
      live_trading_enabled: false,
      quant_auto_mode: 'paper',
      quant_auto_enabled: false,
    });
  };

  const autoCfgMutation = useMutation({
    mutationFn: (payload: Partial<Config>) => updateConfig(payload),
    onMutate: () => {
      setAutoCfgMsg('saving…');
    },
    onSuccess: (res) => {
      setAutoCfgMsg('saved');
      setAutoCfgTouched(false);
      try {
        if (res && typeof res === 'object' && 'config' in res) {
          const nextCfg = (res as unknown as { config?: unknown })?.config;
          if (nextCfg && typeof nextCfg === 'object') {
            qc.setQueryData(['config'], nextCfg);
          }
        }
      } catch {
        void 0;
      }
      qc.invalidateQueries({ queryKey: ['config'] });
    },
    onError: (e) => {
      const err = e as unknown;
      const resp = typeof err === 'object' && err && 'response' in err ? (err as { response?: unknown }).response : undefined;
      const status = typeof resp === 'object' && resp && 'status' in resp ? (resp as { status?: unknown }).status : undefined;
      const data = typeof resp === 'object' && resp && 'data' in resp ? (resp as { data?: unknown }).data : undefined;
      const apiError = typeof data === 'object' && data && 'error' in data ? (data as { error?: unknown }).error : undefined;
      const message = typeof err === 'object' && err && 'message' in err ? (err as { message?: unknown }).message : undefined;
      const msg = String(apiError ?? message ?? err);
      if (String(status ?? '') === '403' || msg.toLowerCase().includes('forbidden')) {
        setAutoCfgMsg('forbidden: 需要写权限令牌');
      } else {
        setAutoCfgMsg(`error: ${msg}`);
      }
    },
  });

  const btcethTickMutation = useMutation({
    mutationFn: () => quantAutoBtcEthTick({ now_ms: Date.now() }),
    onMutate: () => {
      setAutoTickMsg('ticking…');
    },
    onSuccess: (d) => {
      setAutoTickMsg('ok');
      qc.setQueryData(['quant', 'auto', 'btceth', 'last'], d);
      qc.invalidateQueries({ queryKey: ['quant', 'auto', 'btceth', 'last'] });
    },
    onError: (e) => {
      const err = e as unknown;
      const resp = typeof err === 'object' && err && 'response' in err ? (err as { response?: unknown }).response : undefined;
      const status = typeof resp === 'object' && resp && 'status' in resp ? (resp as { status?: unknown }).status : undefined;
      const data = typeof resp === 'object' && resp && 'data' in resp ? (resp as { data?: unknown }).data : undefined;
      const apiError = typeof data === 'object' && data && 'error' in data ? (data as { error?: unknown }).error : undefined;
      const message = typeof err === 'object' && err && 'message' in err ? (err as { message?: unknown }).message : undefined;
      const msg = String(apiError ?? message ?? err);
      if (String(status ?? '') === '403' || msg.toLowerCase().includes('forbidden')) {
        setAutoTickMsg('forbidden: 需要 execute_token');
      } else {
        setAutoTickMsg(`error: ${msg}`);
      }
    },
  });

  const btcaltsTickMutation = useMutation({
    mutationFn: () => quantAutoBtcaltsTick({ now_ms: Date.now() }),
    onMutate: () => {
      setAutoTickMsg('ticking…');
    },
    onSuccess: (d) => {
      setAutoTickMsg('ok');
      qc.setQueryData(['quant', 'auto', 'btcalts', 'last'], d);
      qc.invalidateQueries({ queryKey: ['quant', 'auto', 'btcalts', 'last'] });
    },
    onError: (e) => {
      const err = e as unknown;
      const resp = typeof err === 'object' && err && 'response' in err ? (err as { response?: unknown }).response : undefined;
      const status = typeof resp === 'object' && resp && 'status' in resp ? (resp as { status?: unknown }).status : undefined;
      const data = typeof resp === 'object' && resp && 'data' in resp ? (resp as { data?: unknown }).data : undefined;
      const apiError = typeof data === 'object' && data && 'error' in data ? (data as { error?: unknown }).error : undefined;
      const message = typeof err === 'object' && err && 'message' in err ? (err as { message?: unknown }).message : undefined;
      const msg = String(apiError ?? message ?? err);
      if (String(status ?? '') === '403' || msg.toLowerCase().includes('forbidden')) {
        setAutoTickMsg('forbidden: 需要 execute_token');
      } else {
        setAutoTickMsg(`error: ${msg}`);
      }
    },
  });

  const setAutoDraft = <K extends keyof QuantAutoBtcaltsDraft,>(k: K, v: QuantAutoBtcaltsDraft[K]) => {
    setAutoCfgTouched(true);
    setAutoCfgDraft((prev) => {
      const base = autoCfgTouched ? prev : autoCfgFromConfig;
      return { ...base, [k]: v };
    });
  };

  const handleAutoNumber = <K extends keyof QuantAutoBtcaltsDraft,>(k: K, d = 0) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setAutoCfgTouched(true);
    const v = _toNum(e.target.value, d);
    setAutoCfgDraft((prev) => {
      const base = autoCfgTouched ? prev : autoCfgFromConfig;
      return { ...base, [k]: v };
    });
  };

  const saveAutoCfg = () => {
    if (!operatorOk) {
      setAutoCfgMsg('forbidden: 需要写权限令牌');
      return;
    }
    const p = autoCfgEff;
    const qDay = Math.max(0, _toNum(p.quant_auto_daily_loss_limit_pct, 0));
    const qWk = Math.max(0, _toNum(p.quant_auto_weekly_loss_limit_pct, 0));
    const payload: Partial<Config> = {
      quant_auto_mode: p.quant_auto_mode,
      quant_auto_enabled: p.quant_auto_enabled,
      quant_auto_btceth_enabled: p.quant_auto_btceth_enabled,
      quant_auto_btcalts_enabled: p.quant_auto_btcalts_enabled,
      quant_auto_state_check_interval_sec: p.quant_auto_state_check_interval_sec,
      quant_max_daily_loss: qDay > 0 ? -qDay : 0,
      quant_max_weekly_loss: qWk > 0 ? -qWk : 0,
      quant_auto_net_btc_pct_max: p.quant_auto_net_btc_pct_max,
      quant_auto_pair_notional_usdc_max: p.quant_auto_pair_notional_usdc_max,
      quant_auto_max_open_pairs_total: p.quant_auto_max_open_pairs_total,

      quant_auto_btcalts_capacity_turnover_frac: p.quant_auto_btcalts_capacity_turnover_frac,
      quant_auto_btcalts_capacity_depth_frac: p.quant_auto_btcalts_capacity_depth_frac,
      quant_pairs_btcalt_capacity_turnover_frac: p.quant_pairs_btcalt_capacity_turnover_frac,
      quant_pairs_btcalt_capacity_depth_frac: p.quant_pairs_btcalt_capacity_depth_frac,

      quant_auto_btcalts_scan_n: p.quant_auto_btcalts_scan_n,
      quant_auto_btcalts_open_per_tick: p.quant_auto_btcalts_open_per_tick,
      quant_auto_btcalts_cooldown_bars: p.quant_auto_btcalts_cooldown_bars,
      quant_auto_btcalts_max_open_pairs: p.quant_auto_btcalts_max_open_pairs,
      quant_auto_btcalts_max_per_cluster: p.quant_auto_btcalts_max_per_cluster,
      quant_auto_btcalts_macro_trend_required: p.quant_auto_btcalts_macro_trend_required,
      quant_auto_btcalts_z_bias_min: p.quant_auto_btcalts_z_bias_min,
      quant_auto_btcalts_z_bias_weight: p.quant_auto_btcalts_z_bias_weight,
      quant_auto_btcalts_notional_nontrend_mult: p.quant_auto_btcalts_notional_nontrend_mult,
      quant_auto_btcalts_open_per_tick_nontrend: p.quant_auto_btcalts_open_per_tick_nontrend,
      quant_auto_btcalts_max_open_pairs_nontrend: p.quant_auto_btcalts_max_open_pairs_nontrend,
      quant_auto_btcalts_dynamic_hedge_enabled: p.quant_auto_btcalts_dynamic_hedge_enabled,
      quant_auto_btcalts_dynamic_hedge_step: p.quant_auto_btcalts_dynamic_hedge_step,
      quant_auto_btcalts_btc_hedge_frac: p.quant_auto_btcalts_btc_hedge_frac,
    };
    autoCfgMutation.mutate(payload);
  };

  const updateMutation = useMutation({
    mutationFn: updateQuantPairBtcEthConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btceth'] });
    },
  });

  const wfoRunMutation = useMutation({
    mutationFn: () => fetchQuantPairBtcEthStatus({ timeframe, limit: 800, wfo_run: true }),
    onSuccess: (d) => {
      qc.setQueryData(['quant', 'pairs', 'btceth', timeframe], d);
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btceth'] });
    },
  });

  const wfoSaveMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => updateQuantPairBtcEthConfig(payload as never),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btceth'] });
    },
  });

  const btcAltUpdateMutation = useMutation({
    mutationFn: updateQuantPairBtcAltConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btcalt'] });
    },
  });

  const openMutation = useMutation({
    mutationFn: pairsBtcEthMarketOpen,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btceth'] });
    },
  });

  const closeMutation = useMutation({
    mutationFn: pairsBtcEthMarketClose,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btceth'] });
    },
  });

  const planMutation = useMutation({
    mutationFn: livePlan,
  });

  const openBtcAltMutation = useMutation({
    mutationFn: pairsBtcAltMarketOpen,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btcalt'] });
    },
  });

  const closeBtcAltMutation = useMutation({
    mutationFn: pairsBtcAltMarketClose,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quant', 'pairs', 'btcalt'] });
    },
  });

  const recommendMutation = useMutation({
    mutationFn: (params: { timeframe?: string; limit?: number; days?: number; notional_usdc?: number; apply_cost?: boolean; max_alts?: number }) =>
      fetchQuantPairBtcAltRecommend(params),
    onSuccess: (d) => {
      if (d && d.ok && d.best) {
        setBtcAlt(String(d.best).trim().toUpperCase());
      }
    },
  });

  const btcAltRecommend = recommendMutation.data as QuantPairBtcAltRecommendResponse | undefined;

  const downloadBtcAltBacktestCsv = (fmt: 'trades_csv' | 'equity_csv') => {
    const base = String(api.defaults.baseURL || '/api');
    const url = new URL(base, window.location.origin);
    url.pathname = `${String(url.pathname || '').replace(/\/$/, '')}/quant/pairs/btcalt/backtest/export`;
    const params = new URLSearchParams();
    params.set('format', fmt);
    params.set('timeframe', btcAltTimeframe);
    params.set('alt', btcAlt);
    params.set('limit', String(btcAltBtLimit));
    params.set('notional_usdc', String(btcAltBtNotional));
    params.set('apply_cost', btcAltBtApplyCost === 'on' ? '1' : '0');
    url.search = params.toString();
    window.open(url.toString(), '_blank', 'noopener,noreferrer');
  };

  const latest = data?.latest ?? null;
  const action = String(data?.action ?? '-');
  const reason = String(data?.reason ?? '');

  const researchSplit = qResearchSplit.data as QuantPairBtcEthResearchSplitResponse | undefined;
  const researchCapacity = qResearchCapacity.data as QuantPairBtcEthResearchCapacityResponse | undefined;
  const researchMargin = qResearchMargin.data as QuantPairBtcEthResearchMarginStressResponse | undefined;

  const btcAltResearchSplit = qBtcAltResearchSplit.data as QuantPairBtcAltResearchSplitResponse | undefined;
  const btcAltResearchCapacity = qBtcAltResearchCapacity.data as QuantPairBtcAltResearchCapacityResponse | undefined;
  const btcAltResearchMargin = qBtcAltResearchMargin.data as QuantPairBtcAltResearchMarginStressResponse | undefined;

  const planData = planMutation.data as LivePlanResponse | undefined;
  const planLegs = Array.isArray(planData?.legs) ? planData.legs : [];
  const planTs = _toNum(planData?.ts, 0);
  const planRiskSubp = (planData?.risk?.subportfolio ?? null) as Record<string, unknown> | null;
  const planRiskOpen = (planData?.risk?.open_positions ?? null) as Record<string, unknown> | null;
  const planRiskSubpEnabled = Boolean(planRiskSubp?.enabled);
  const planRiskSubpOk = Boolean(planRiskSubp?.ok);
  const planRiskSubpReason = String(planRiskSubp?.reason ?? '');
  const planRiskOpenN = _toNum(planRiskOpen?.n, 0);
  const planRiskOpenNotional = _toNum(planRiskOpen?.notional_usdc, 0);

  const planNotionalEff = Number.isFinite(planData?.notional_usdc)
    ? _toNum(planData?.notional_usdc, execNotional)
    : execNotional;

  const position = (data?.position ?? null) as Record<string, unknown> | null;
  const posAny = Boolean(position?.any);
  const posPairOk = Boolean(position?.pair_ok);
  const posHoldBars = _toNum(position?.hold_bars, Number.NaN);
  const posEntryTs = _toNum(position?.entry_ts, 0);
  const posLegs = (position?.legs ?? null) as Record<string, unknown> | null;
  const posLegBtc = (posLegs?.btc ?? null) as Record<string, unknown> | null;
  const posLegEth = (posLegs?.eth ?? null) as Record<string, unknown> | null;

  const pnl = (data?.pnl ?? null) as Record<string, unknown> | null;
  const pnlOk = Boolean(pnl?.ok);
  const pnlNet = _toNum(pnl?.net_est_usdc, Number.NaN);
  const pnlGross = _toNum(pnl?.unrealized_gross_usdc, Number.NaN);
  const pnlFunding = _toNum(pnl?.funding_accrual_usdc, Number.NaN);
  const pnlCost = _toNum(pnl?.cost_est_usdc, Number.NaN);

  const gate = (data?.gate ?? null) as Record<string, unknown> | null;
  const gateEnabled = Boolean(gate?.enabled);
  const gatePass = Boolean(gate?.pass);
  const gateBlocked = Boolean(gate?.blocked);
  const gateBlockedReason = String(gate?.blocked_reason ?? '');
  const gateFailCount = _toNum(gate?.fail_count, 0);
  const gateKFail = _toNum(gate?.k_fail, 0);
  const gateHighVol = Boolean(gate?.high_vol);
  const gateFreqBars = _toNum(gate?.freq_bars, 0);

  const gateStruct = (gate?.struct ?? null) as Record<string, unknown> | null;
  const gateBetaStd = _toNum(gateStruct?.beta_std, Number.NaN);
  const gateHalfLifeBars = _toNum(gateStruct?.half_life_bars, Number.NaN);
  const gateStructReasons = Array.isArray(gateStruct?.reasons) ? (gateStruct?.reasons as unknown[]).map((x) => String(x)) : [];

  const gateFailRate = _toNum(gate?.fail_rate, Number.NaN);
  const gateLogTail = useMemo<GateEvalRow[]>(() => {
    const rows = Array.isArray(gate?.log_tail) ? (gate?.log_tail as unknown[]) : [];
    return rows
      .map((x) => {
        const r = x as Record<string, unknown>;
        const ts = _toNum(r.ts, 0);
        const pass = Boolean(r.pass);
        const adf_p = r.adf_p === null || r.adf_p === undefined ? null : _toNum(r.adf_p, Number.NaN);
        const adf_p_adj = r.adf_p_adj === null || r.adf_p_adj === undefined ? null : _toNum(r.adf_p_adj, Number.NaN);
        const kpss_stat = r.kpss_stat === null || r.kpss_stat === undefined ? null : _toNum(r.kpss_stat, Number.NaN);
        const beta_std = r.beta_std === null || r.beta_std === undefined ? null : _toNum(r.beta_std, Number.NaN);
        const half_life_bars = r.half_life_bars === null || r.half_life_bars === undefined ? null : _toNum(r.half_life_bars, Number.NaN);
        return {
          ts,
          pass,
          adf_p: Number.isFinite(adf_p) ? adf_p : null,
          adf_p_adj: Number.isFinite(adf_p_adj) ? adf_p_adj : null,
          kpss_stat: Number.isFinite(kpss_stat) ? kpss_stat : null,
          beta_std: Number.isFinite(beta_std) ? beta_std : null,
          half_life_bars: Number.isFinite(half_life_bars) ? half_life_bars : null,
        };
      })
      .filter((r) => r.ts > 0)
      .slice(-20);
  }, [gate]);

  const cost = (data?.cost ?? null) as Record<string, unknown> | null;
  const costNotional = _toNum(cost?.notional_usdc, Number.NaN);
  const costEstimate = (cost?.estimate ?? null) as Record<string, unknown> | null;
  const costOk = Boolean(costEstimate?.ok);
  const costMode = String(costEstimate?.mode ?? '-');
  const costFee = _toNum(costEstimate?.fee_rate, Number.NaN);
  const costSlip = _toNum(costEstimate?.slippage_rate, Number.NaN);
  const costTotal = Number.isFinite(costFee) && Number.isFinite(costSlip) ? costFee + costSlip : Number.NaN;

  const margin = (data?.margin ?? null) as Record<string, unknown> | null;
  const marginOk = Boolean(margin?.ok);
  const marginRec = String(margin?.recommend ?? '-');
  const marginLegs = (margin?.legs ?? null) as Record<string, unknown> | null;
  const marginBtc = (marginLegs?.BTC ?? null) as Record<string, unknown> | null;
  const marginEth = (marginLegs?.ETH ?? null) as Record<string, unknown> | null;
  const marginBtcPnl = _toNum(marginBtc?.pnl_pct, Number.NaN);
  const marginEthPnl = _toNum(marginEth?.pnl_pct, Number.NaN);

  const cojump = (data?.cojump ?? null) as Record<string, unknown> | null;
  const cojumpEnabled = Boolean(cojump?.enabled);
  const cojumpBlocked = Boolean(cojump?.blocked);
  const cojumpTriggered = Boolean(cojump?.triggered);
  const cojumpUntil = _toNum(cojump?.blocked_until_ms, 0);

  const opGate = (data?.op_gate ?? null) as Record<string, unknown> | null;
  const opGateEnabled = Boolean(opGate?.enabled);
  const opGateBlocked = Boolean(opGate?.blocked);
  const opGateReason = String(opGate?.blocked_reason ?? '');
  const opGateUntil = _toNum(opGate?.cooldown_until_ms, 0);

  const macroVeto = (data?.macro_veto ?? null) as QuantMacroVeto | null;
  const macroVetoBlocked = Boolean(macroVeto?.blocked);
  const macroVetoReason = String(macroVeto?.blocked_reason ?? '');
  const macroTrendDirW = _toNum(macroVeto?.TrendDirW, _toNum(macroVeto?.TrendDir12h, 0));
  const macroTrendDirD = _toNum(macroVeto?.TrendDirD, _toNum(macroVeto?.TrendDir12h, 0));
  const macroChgDir1hN = _toNum(macroVeto?.ChgDir1hN, 0);
  const macroChgStrength = _toNum(macroVeto?.ChgStrength, Number.NaN);
  const macroChgSpeedD = _toNum(macroVeto?.ChgSpeedD, Number.NaN);
  const macroRiskBudgetTier = String(macroVeto?.RiskBudgetTier ?? '-');
  const macroCrashSwitch = macroVeto?.CrashSwitch === true;
  const macroTargetNetBias = _toNum(macroVeto?.TargetNetBias, Number.NaN);
  const macroMaxNetExposure = _toNum(macroVeto?.MaxNetExposure, Number.NaN);
  const macroAllowOpen = macroVeto?.AllowOpen === true;
  const macroAllowAddon = macroVeto?.AllowAddon === true;
  const macroState = String(macroVeto?.MacroState ?? '-');
  const macroAligned = macroVeto?.aligned === true;
  const macroConflict = macroVeto?.conflict === true;

  const chartData = useMemo(() => {
    const rows = Array.isArray(data?.series) ? data?.series : [];
    return rows
      .map((r) => ({
        ts: _toNum((r as Record<string, unknown>).ts, Number.NaN),
        spread: _toNum((r as Record<string, unknown>).spread, Number.NaN),
        z: _toNum((r as Record<string, unknown>).z, Number.NaN),
      }))
      .filter((r) => Number.isFinite(r.ts));
  }, [data]);

  const latestTs = _toNum((latest as Record<string, unknown> | null)?.ts, 0);
  const latestSpread = _toNum((latest as Record<string, unknown> | null)?.spread, Number.NaN);
  const latestZ = _toNum((latest as Record<string, unknown> | null)?.z, Number.NaN);
  const latestBeta = _toNum((latest as Record<string, unknown> | null)?.beta, Number.NaN);
  const latestCorr = _toNum((latest as Record<string, unknown> | null)?.corr, Number.NaN);

  const staleness = useMemo(() => {
    if (!(latestTs > 0)) return { isStale: false, text: '' };
    const tfMs = _tfToMs(String(data?.timeframe ?? timeframe));
    if (!(tfMs > 0)) return { isStale: false, text: '' };
    const nowTs = _toNum((data as Record<string, unknown> | undefined)?.ts, 0);
    const delta = nowTs - latestTs;
    if (!(Number.isFinite(delta)) || delta <= 0) return { isStale: false, text: '' };
    const thr = tfMs * 3;
    if (delta <= thr) return { isStale: false, text: '' };
    const mins = Math.round(delta / 60000);
    return { isStale: true, text: `stale ${mins}m` };
  }, [data, timeframe, latestTs]);

  const effectiveParamsKey = useMemo(() => {
    const p = data?.params;
    if (!p) return `tf:${timeframe}|none`;
    return `tf:${data?.timeframe ?? timeframe}|ols:${p.window_ols}|z:${p.window_z}|e:${p.entry_z}|el:${String((p as { entry_z_long?: unknown }).entry_z_long)}|es:${String((p as { entry_z_short?: unknown }).entry_z_short)}|x:${p.exit_z}|s:${p.stop_z}|c:${p.corr_min}|h:${p.max_hold_bars}|zb:${p.z_cost_buffer_mult}|pnl:${String((p as { exit_pnl_enabled?: unknown }).exit_pnl_enabled)}|sl:${String((p as { pnl_stop_loss_r?: unknown }).pnl_stop_loss_r)}|tp:${String((p as { pnl_take_profit_r?: unknown }).pnl_take_profit_r)}|ts:${String((p as { pnl_trail_start_r?: unknown }).pnl_trail_start_r)}|tdd:${String((p as { pnl_trail_dd_r?: unknown }).pnl_trail_dd_r)}|mze:${String((p as { pnl_min_on_z_exit_r?: unknown }).pnl_min_on_z_exit_r)}|mh:${String((p as { pnl_min_hold_bars?: unknown }).pnl_min_hold_bars)}`;
  }, [data, timeframe]);

  const initialCfg = useMemo<QuantPairBtcEthConfig>(() => {
    const p = data?.params;
    const tf = String(data?.timeframe ?? timeframe ?? _defaultDraft.timeframe);
    if (!p) return { ..._defaultDraft, timeframe: tf };
    return {
      timeframe: tf,
      window_ols: _toNum(p.window_ols, _defaultDraft.window_ols),
      window_z: _toNum(p.window_z, _defaultDraft.window_z),
      beta_std_max: _toNum((p as { beta_std_max?: unknown }).beta_std_max, _defaultDraft.beta_std_max),
      beta_abs_max: _toNum((p as { beta_abs_max?: unknown }).beta_abs_max, _defaultDraft.beta_abs_max),
      entry_z: _toNum(p.entry_z, _defaultDraft.entry_z),
      entry_z_long: _toNum((p as { entry_z_long?: unknown }).entry_z_long, _defaultDraft.entry_z_long),
      entry_z_short: _toNum((p as { entry_z_short?: unknown }).entry_z_short, _defaultDraft.entry_z_short),
      exit_z: _toNum(p.exit_z, _defaultDraft.exit_z),
      z_exit_confirm_bars: _toNum((p as { z_exit_confirm_bars?: unknown }).z_exit_confirm_bars, _defaultDraft.z_exit_confirm_bars),
      stop_z: _toNum(p.stop_z, _defaultDraft.stop_z),
      corr_min: _toNum(p.corr_min, _defaultDraft.corr_min),
      max_hold_bars: _toNum(p.max_hold_bars, _defaultDraft.max_hold_bars),
      z_cost_buffer_mult: _toNum(p.z_cost_buffer_mult, _defaultDraft.z_cost_buffer_mult),
      notional_usdc_per_leg: _toNum((p as { notional_usdc_per_leg?: unknown }).notional_usdc_per_leg, _defaultDraft.notional_usdc_per_leg),
      pair_notional_usdc_max: _toNum((p as { pair_notional_usdc_max?: unknown }).pair_notional_usdc_max, _defaultDraft.pair_notional_usdc_max),
      cooldown_bars_after_exit: _toNum((p as { cooldown_bars_after_exit?: unknown }).cooldown_bars_after_exit, _defaultDraft.cooldown_bars_after_exit),
      emergency_close_on_gate_violation: Boolean(
        (p as { emergency_close_on_gate_violation?: unknown }).emergency_close_on_gate_violation ?? _defaultDraft.emergency_close_on_gate_violation,
      ),
      state_check_interval_sec: _toNum(
        (p as { state_check_interval_sec?: unknown }).state_check_interval_sec,
        _defaultDraft.state_check_interval_sec,
      ),
      exit_pnl_enabled: Boolean((p as { exit_pnl_enabled?: unknown }).exit_pnl_enabled ?? _defaultDraft.exit_pnl_enabled),
      pnl_stop_loss_r: _toNum((p as { pnl_stop_loss_r?: unknown }).pnl_stop_loss_r, _defaultDraft.pnl_stop_loss_r),
      pnl_take_profit_r: _toNum((p as { pnl_take_profit_r?: unknown }).pnl_take_profit_r, _defaultDraft.pnl_take_profit_r),
      pnl_trail_start_r: _toNum((p as { pnl_trail_start_r?: unknown }).pnl_trail_start_r, _defaultDraft.pnl_trail_start_r),
      pnl_trail_dd_r: _toNum((p as { pnl_trail_dd_r?: unknown }).pnl_trail_dd_r, _defaultDraft.pnl_trail_dd_r),
      pnl_min_on_z_exit_r: _toNum((p as { pnl_min_on_z_exit_r?: unknown }).pnl_min_on_z_exit_r, _defaultDraft.pnl_min_on_z_exit_r),
      pnl_min_hold_bars: _toNum((p as { pnl_min_hold_bars?: unknown }).pnl_min_hold_bars, _defaultDraft.pnl_min_hold_bars),
    };
  }, [data, timeframe]);

  const wfoConfig = useMemo(() => {
    const w = (data?.wfo ?? null) as Record<string, unknown> | null;
    const cfg0 = (w?.config ?? null) as Record<string, unknown> | null;
    return cfg0;
  }, [data?.wfo]);

  const wfoGridDefault = useMemo(() => {
    return wfoConfig?.grid && typeof wfoConfig.grid === 'object' ? JSON.stringify(wfoConfig.grid, null, 2) : '';
  }, [wfoConfig]);

  const wfoEnabledEff = wfoTouched ? wfoEnabledDraft : Boolean(wfoConfig?.enabled);
  const wfoApplyEff = wfoTouched ? wfoApplyDraft : Boolean(wfoConfig?.apply);
  const wfoRefreshSecEff = wfoTouched ? wfoRefreshSecDraft : _toNum(wfoConfig?.refresh_sec, 3600);
  const wfoPlateauMinFracEff = wfoTouched ? wfoPlateauMinFracDraft : _toNum(wfoConfig?.plateau_min_frac, 0.6);
  const wfoPlateauTolEff = wfoTouched ? wfoPlateauTolDraft : _toNum(wfoConfig?.plateau_tol, 0.1);
  const wfoIsBarsEff = wfoTouched ? wfoIsBarsDraft : _toNum(wfoConfig?.is_bars, 480);
  const wfoOosBarsEff = wfoTouched ? wfoOosBarsDraft : _toNum(wfoConfig?.oos_bars, 240);
  const wfoStepBarsEff = wfoTouched ? wfoStepBarsDraft : _toNum(wfoConfig?.step_bars, 240);
  const wfoEmbargoBarsEff = wfoTouched ? wfoEmbargoBarsDraft : _toNum(wfoConfig?.embargo_bars, 0);
  const wfoGridEff = wfoTouched ? wfoGridDraft : wfoGridDefault;

  const rsPurgeBarsEff = rsSplitTouched ? rsPurgeBars : _toNum((data?.params as { max_hold_bars?: unknown } | undefined)?.max_hold_bars, rsPurgeBars);
  const rsEmbargoBarsEff = rsSplitTouched ? rsEmbargoBars : _toNum((data?.params as { max_hold_bars?: unknown } | undefined)?.max_hold_bars, rsEmbargoBars);
  const rsSplitWindowOlsEff = rsSplitTouched ? rsSplitWindowOls : _toNum((data?.params as { window_ols?: unknown } | undefined)?.window_ols, rsSplitWindowOls);
  const rsSplitWindowZEff = rsSplitTouched ? rsSplitWindowZ : _toNum((data?.params as { window_z?: unknown } | undefined)?.window_z, rsSplitWindowZ);

  const saveState: 'idle' | 'ok' | 'error' = updateMutation.isPending
    ? 'idle'
    : updateMutation.isError
      ? 'error'
      : updateMutation.isSuccess
        ? 'ok'
        : 'idle';

  const btcAltSaveState: 'idle' | 'ok' | 'error' = btcAltUpdateMutation.isPending
    ? 'idle'
    : btcAltUpdateMutation.isError
      ? 'error'
      : btcAltUpdateMutation.isSuccess
        ? 'ok'
        : 'idle';

  const btcAltLatest = btcAltData?.latest ?? null;
  const btcAltLatestTs = _toNum((btcAltLatest as Record<string, unknown> | null)?.ts, 0);
  const btcAltLatestSpread = _toNum((btcAltLatest as Record<string, unknown> | null)?.spread, Number.NaN);
  const btcAltLatestZ = _toNum((btcAltLatest as Record<string, unknown> | null)?.z, Number.NaN);
  const btcAltLatestBeta = _toNum((btcAltLatest as Record<string, unknown> | null)?.beta, Number.NaN);
  const btcAltLatestCorr = _toNum((btcAltLatest as Record<string, unknown> | null)?.corr, Number.NaN);

  const btcAltAction = String(btcAltData?.action ?? '-');
  const btcAltReason = String(btcAltData?.reason ?? '');

  const guardEnabled = (qLive.data as { execute_guard?: { enabled?: unknown } } | undefined)?.execute_guard?.enabled;
  const guardTokenRequired = (qLive.data as { execute_guard?: { token_required?: unknown } } | undefined)?.execute_guard?.token_required;
  const tokenOk = guardTokenRequired === false ? true : operatorOk;
  const quantAsterOwner = (qLive.data as { aster?: { owners?: { quant?: { ready?: unknown; blockers?: unknown } } } } | undefined)?.aster
    ?.owners?.quant;
  const preflightReady = Boolean((quantAsterOwner?.ready as unknown) ?? (qLive.data as { ready?: unknown } | undefined)?.ready);
  const preflightBlockers = Array.isArray(quantAsterOwner?.blockers)
    ? ((quantAsterOwner?.blockers as unknown[]) || []).map((x) => String(x))
    : Array.isArray((qLive.data as { blockers?: unknown } | undefined)?.blockers)
      ? (((qLive.data as { blockers?: unknown } | undefined)?.blockers as unknown[]) || []).map((x) => String(x))
      : [];
  const preflightVenue = String((qLive.data as { config?: { execution_venue?: unknown } } | undefined)?.config?.execution_venue ?? '')
    .trim()
    .toLowerCase();
  const venueMatchesPreflight = Boolean(preflightVenue) && preflightVenue === execVenue;
  const venueReady = venueMatchesPreflight ? preflightReady : true;
  const liveReady =
    execMode === 'dry-run' || (guardEnabled === false ? true : (Boolean(tokenOk) && Boolean(confirmExecute) && Boolean(venueReady)));

  const btcAltGate = (btcAltData?.gate ?? null) as Record<string, unknown> | null;
  const btcAltGateEnabled = Boolean(btcAltGate?.enabled);
  const btcAltGatePass = Boolean(btcAltGate?.pass);
  const btcAltGateBlocked = Boolean(btcAltGate?.blocked);
  const btcAltGateBlockedReason = String(btcAltGate?.blocked_reason ?? '');

  const btcAltCorrGate = (btcAltData?.corr_gate ?? null) as Record<string, unknown> | null;
  const btcAltCorrGateEnabled = Boolean(btcAltCorrGate?.enabled);
  const btcAltCorrGateBlocked = Boolean(btcAltCorrGate?.blocked);

  const btcAltCojump = (btcAltData?.cojump ?? null) as Record<string, unknown> | null;
  const btcAltCojumpEnabled = Boolean(btcAltCojump?.enabled);
  const btcAltCojumpBlocked = Boolean(btcAltCojump?.blocked);

  const btcAltThresholds = (btcAltData?.thresholds ?? null) as Record<string, unknown> | null;
  const btcAltEntryZEff = _toNum(btcAltThresholds?.entry_z_eff, Number.NaN);
  const btcAltExitZEff = _toNum(btcAltThresholds?.exit_z_eff, Number.NaN);

  const btcAltParamsAny = (btcAltData as unknown as { params?: Record<string, unknown> | null } | undefined)?.params ?? null;
  const btcAltBaseParams = (btcAltData as unknown as { base_params?: Record<string, unknown> | null } | undefined)?.base_params ?? null;
  const btcAltPortfolioParams = (btcAltData as unknown as { portfolio_params?: Record<string, unknown> | null } | undefined)?.portfolio_params ?? null;
  const btcAltInitialCfg: QuantPairBtcAltConfig | null = btcAltBaseParams
    ? {
        timeframe: String(btcAltData?.timeframe ?? (btcAltTimeframe || _defaultDraft.timeframe)),
        window_ols: _toNum((btcAltBaseParams as Record<string, unknown>).window_ols, _defaultBtcAltDraft.window_ols),
        window_z: _toNum((btcAltBaseParams as Record<string, unknown>).window_z, _defaultBtcAltDraft.window_z),
        entry_z: _toNum((btcAltBaseParams as Record<string, unknown>).entry_z, _defaultBtcAltDraft.entry_z),
        entry_z_long: _toNum((btcAltBaseParams as Record<string, unknown>).entry_z_long, _defaultBtcAltDraft.entry_z_long ?? _defaultBtcAltDraft.entry_z),
        entry_z_short: _toNum((btcAltBaseParams as Record<string, unknown>).entry_z_short, _defaultBtcAltDraft.entry_z_short ?? _defaultBtcAltDraft.entry_z),
        exit_z: _toNum((btcAltBaseParams as Record<string, unknown>).exit_z, _defaultBtcAltDraft.exit_z),
        z_exit_confirm_bars: _toNum((btcAltBaseParams as Record<string, unknown>).z_exit_confirm_bars, _defaultBtcAltDraft.z_exit_confirm_bars),
        stop_z: _toNum((btcAltBaseParams as Record<string, unknown>).stop_z, _defaultBtcAltDraft.stop_z),
        corr_min: _toNum((btcAltBaseParams as Record<string, unknown>).corr_min, _defaultBtcAltDraft.corr_min),
        max_hold_bars: _toNum((btcAltBaseParams as Record<string, unknown>).max_hold_bars, _defaultBtcAltDraft.max_hold_bars),
        z_cost_buffer_mult: _toNum((btcAltBaseParams as Record<string, unknown>).z_cost_buffer_mult, _defaultBtcAltDraft.z_cost_buffer_mult),
        exit_pnl_enabled: Boolean((btcAltBaseParams as Record<string, unknown>).exit_pnl_enabled ?? _defaultBtcAltDraft.exit_pnl_enabled),
        pnl_stop_loss_r: _toNum((btcAltBaseParams as Record<string, unknown>).pnl_stop_loss_r, _defaultBtcAltDraft.pnl_stop_loss_r ?? -0.01),
        pnl_take_profit_r: _toNum((btcAltBaseParams as Record<string, unknown>).pnl_take_profit_r, _defaultBtcAltDraft.pnl_take_profit_r ?? 0.008),
        pnl_trail_start_r: _toNum((btcAltBaseParams as Record<string, unknown>).pnl_trail_start_r, _defaultBtcAltDraft.pnl_trail_start_r ?? 0.006),
        pnl_trail_dd_r: _toNum((btcAltBaseParams as Record<string, unknown>).pnl_trail_dd_r, _defaultBtcAltDraft.pnl_trail_dd_r ?? 0.003),
        pnl_min_on_z_exit_r: _toNum((btcAltBaseParams as Record<string, unknown>).pnl_min_on_z_exit_r, _defaultBtcAltDraft.pnl_min_on_z_exit_r ?? 0.0),
        pnl_min_hold_bars: _toNum((btcAltBaseParams as Record<string, unknown>).pnl_min_hold_bars, _defaultBtcAltDraft.pnl_min_hold_bars ?? 0),
        max_pairs_active: Math.max(1, Math.trunc(_toNum((btcAltPortfolioParams as Record<string, unknown> | null)?.max_pairs_active, _defaultBtcAltDraft.max_pairs_active))),
        cluster_max_active: Math.max(1, Math.trunc(_toNum((btcAltPortfolioParams as Record<string, unknown> | null)?.cluster_max_active, _defaultBtcAltDraft.cluster_max_active))),
        cluster_risk_budget_frac: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.cluster_risk_budget_frac,
          _defaultBtcAltDraft.cluster_risk_budget_frac,
        ),
        gross_notional_usdc: _toNum((btcAltPortfolioParams as Record<string, unknown> | null)?.gross_notional_usdc, _defaultBtcAltDraft.gross_notional_usdc),
        pair_notional_usdc_max: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.pair_notional_usdc_max,
          _defaultBtcAltDraft.pair_notional_usdc_max,
        ),
        capacity_turnover_frac: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.capacity_turnover_frac,
          _defaultBtcAltDraft.capacity_turnover_frac,
        ),
        capacity_depth_frac: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.capacity_depth_frac,
          _defaultBtcAltDraft.capacity_depth_frac,
        ),
        risk_weight_mode: String((btcAltPortfolioParams as Record<string, unknown> | null)?.risk_weight_mode ?? _defaultBtcAltDraft.risk_weight_mode),
        net_btc_exposure_target: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.net_btc_exposure_target,
          _defaultBtcAltDraft.net_btc_exposure_target,
        ),
        net_btc_exposure_max: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.net_btc_exposure_max,
          _defaultBtcAltDraft.net_btc_exposure_max,
        ),
        universe_consistency_min_ari: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.universe_consistency_min_ari,
          _defaultBtcAltDraft.universe_consistency_min_ari,
        ),
        universe_consistency_min_nmi: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.universe_consistency_min_nmi,
          _defaultBtcAltDraft.universe_consistency_min_nmi,
        ),
        circuit_breaker_dd_day: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.circuit_breaker_dd_day,
          _defaultBtcAltDraft.circuit_breaker_dd_day,
        ),
        circuit_breaker_dd_week: _toNum(
          (btcAltPortfolioParams as Record<string, unknown> | null)?.circuit_breaker_dd_week,
          _defaultBtcAltDraft.circuit_breaker_dd_week,
        ),
      }
    : null;

  const btcAltRegime = (btcAltData?.regime ?? null) as Record<string, unknown> | null;
  const btcAltRegimeLatest = (btcAltRegime?.latest ?? null) as Record<string, unknown> | null;
  const btcAltRegimeMode = String(btcAltRegimeLatest?.regime ?? '-');
  const btcAltRegimeProb = _toNum(btcAltRegimeLatest?.regime_prob, Number.NaN);

  const btcAltRs = (btcAltData?.rs ?? null) as Record<string, unknown> | null;
  const btcAltRsLatest = (btcAltRs?.latest ?? null) as Record<string, unknown> | null;
  const btcAltRsScore = _toNum(btcAltRsLatest?.rs_score, Number.NaN);

  const btcAltCost = (btcAltData?.cost ?? null) as Record<string, unknown> | null;
  const btcAltCostNotional = _toNum(btcAltCost?.notional_usdc, Number.NaN);
  const btcAltCostEstimate = (btcAltCost?.estimate ?? null) as Record<string, unknown> | null;
  const btcAltCostOk = Boolean(btcAltCostEstimate?.ok);
  const btcAltCostMode = String(btcAltCostEstimate?.mode ?? '-');
  const btcAltCostFee = _toNum(btcAltCostEstimate?.fee_rate, Number.NaN);
  const btcAltCostSlip = _toNum(btcAltCostEstimate?.slippage_rate, Number.NaN);
  const btcAltCostTotal = Number.isFinite(btcAltCostFee) && Number.isFinite(btcAltCostSlip) ? btcAltCostFee + btcAltCostSlip : Number.NaN;

  const btcAltPosition = (btcAltData?.position ?? null) as Record<string, unknown> | null;
  const btcAltPosAny = Boolean(btcAltPosition?.any);
  const btcAltPosPairOk = Boolean(btcAltPosition?.pair_ok);
  const btcAltPosHoldBars = _toNum(btcAltPosition?.hold_bars, Number.NaN);
  const btcAltPosEntryTs = _toNum(btcAltPosition?.entry_ts, 0);
  const btcAltPosLegs = (btcAltPosition?.legs ?? null) as Record<string, unknown> | null;
  const btcAltPosLegBtc = (btcAltPosLegs?.btc ?? null) as Record<string, unknown> | null;
  const btcAltPosLegAlt = (btcAltPosLegs?.alt ?? null) as Record<string, unknown> | null;

  const btcAltPnl = (btcAltData?.pnl ?? null) as Record<string, unknown> | null;
  const btcAltPnlOk = Boolean(btcAltPnl?.ok);
  const btcAltPnlNet = _toNum(btcAltPnl?.net_est_usdc, Number.NaN);
  const btcAltPnlGross = _toNum(btcAltPnl?.unrealized_gross_usdc, Number.NaN);
  const btcAltPnlFunding = _toNum(btcAltPnl?.funding_accrual_usdc, Number.NaN);
  const btcAltPnlCost = _toNum(btcAltPnl?.cost_est_usdc, Number.NaN);

  const btcAltChartData = useMemo(() => {
    const rows = Array.isArray(btcAltData?.series) ? btcAltData?.series : [];
    return rows
      .map((r) => ({
        ts: _toNum((r as Record<string, unknown>).ts, Number.NaN),
        spread: _toNum((r as Record<string, unknown>).spread, Number.NaN),
        z: _toNum((r as Record<string, unknown>).z, Number.NaN),
      }))
      .filter((r) => Number.isFinite(r.ts));
  }, [btcAltData]);

  const btcAltStaleness = useMemo(() => {
    if (!(btcAltLatestTs > 0)) return { isStale: false, text: '' };
    const tfMs = _tfToMs(String(btcAltData?.timeframe ?? btcAltTimeframe));
    if (!(tfMs > 0)) return { isStale: false, text: '' };
    const nowTs = _toNum((btcAltData as Record<string, unknown> | undefined)?.ts, 0);
    const delta = nowTs - btcAltLatestTs;
    if (!(Number.isFinite(delta)) || delta <= 0) return { isStale: false, text: '' };
    const thr = tfMs * 3;
    if (delta <= thr) return { isStale: false, text: '' };
    const mins = Math.round(delta / 60000);
    return { isStale: true, text: `stale ${mins}m` };
  }, [btcAltData, btcAltTimeframe, btcAltLatestTs]);

  const trendDirW = useMemo(() => {
    const d0 = macroVeto?.TrendDirW;
    const d1 = macroOverview?.macro_tri_layer?.dir_w;
    const d2 = macroOverview?.std_12h?.btc?.dir;
    const d3 = macroOverview?.macro_btceth_shape?.dir_12h;
    const x = typeof d0 === 'number' && Number.isFinite(d0)
      ? d0
      : typeof d1 === 'number' && Number.isFinite(d1)
        ? d1
        : typeof d2 === 'number' && Number.isFinite(d2)
          ? d2
          : typeof d3 === 'number' && Number.isFinite(d3)
            ? d3
            : 0;
    if (x >= 1) return 1;
    if (x <= -1) return -1;
    return 0;
  }, [macroOverview, macroVeto]);

  const trendDirD = useMemo(() => {
    const d0 = macroVeto?.TrendDirD;
    const d1 = macroOverview?.macro_tri_layer?.dir_d;
    const d2 = macroOverview?.std_1d?.btc?.dir;
    const d3 = macroOverview?.std_12h?.btc?.dir;
    const x = typeof d0 === 'number' && Number.isFinite(d0)
      ? d0
      : typeof d1 === 'number' && Number.isFinite(d1)
        ? d1
        : typeof d2 === 'number' && Number.isFinite(d2)
          ? d2
          : typeof d3 === 'number' && Number.isFinite(d3)
            ? d3
            : 0;
    if (x >= 1) return 1;
    if (x <= -1) return -1;
    return 0;
  }, [macroOverview, macroVeto]);

  const chgDir1hN = useMemo(() => {
    const d0 = macroVeto?.ChgDir1hN;
    if (typeof d0 === 'number' && Number.isFinite(d0)) {
      if (d0 >= 1) return 1;
      if (d0 <= -1) return -1;
      return 0;
    }
    const d1 = macroOverview?.macro_tri_layer?.dir_short;
    if (typeof d1 === 'number' && Number.isFinite(d1)) {
      if (d1 >= 1) return 1;
      if (d1 <= -1) return -1;
      return 0;
    }
    const dirs = macro1hSeq.map((p) => {
      const x = Number(p.dir ?? 0);
      if (!Number.isFinite(x)) return 0;
      if (x >= 1) return 1;
      if (x <= -1) return -1;
      return 0;
    });
    const pos = dirs.filter((x) => x === 1).length;
    const neg = dirs.filter((x) => x === -1).length;
    if (pos >= 2) return 1;
    if (neg >= 2) return -1;
    return 0;
  }, [macroOverview, macroVeto, macro1hSeq]);

  const isAligned = trendDirW !== 0 && trendDirD === trendDirW && chgDir1hN === trendDirW;

  const universePairsCoins = useMemo(() => {
    const xs = universePairs?.coins;
    if (!Array.isArray(xs)) return [];
    return xs.map((x) => String(x || '').trim().toUpperCase()).filter((x) => x);
  }, [universePairs]);

  const universeClusters = useMemo(() => {
    const clusters = (universeStatus?.metadata as { clusters?: unknown } | undefined)?.clusters;
    if (!clusters || typeof clusters !== 'object') return null;
    return clusters as Record<string, unknown>;
  }, [universeStatus]);

  const universeSelectionHints = useMemo(() => {
    const hints = (universeStatus?.metadata as { selection_hints?: unknown } | undefined)?.selection_hints;
    if (!hints || typeof hints !== 'object') return null;
    return hints as Record<string, unknown>;
  }, [universeStatus]);

  const coinClusterId = useMemo(() => {
    const clusters = universeClusters;
    if (!clusters) return new Map<string, string>();
    const m = new Map<string, string>();
    for (const [clusterId, v] of Object.entries(clusters)) {
      const members = (v as { members?: unknown } | null)?.members;
      if (!Array.isArray(members)) continue;
      for (const x of members) {
        const coin = String(x || '').trim().toUpperCase();
        if (coin) m.set(coin, String(clusterId));
      }
    }
    return m;
  }, [universeClusters]);

  const perClusterLimit = useMemo(() => {
    const k = _toNum(universeSelectionHints?.topk_per_cluster, Number.NaN);
    if (!Number.isFinite(k) || k <= 0) return null;
    return Math.max(1, Math.trunc(k));
  }, [universeSelectionHints]);

  const excludedClusters = useMemo(() => {
    const xs = (universeSelectionHints?.excluded_clusters ?? null) as unknown;
    if (!Array.isArray(xs)) return new Set<string>();
    return new Set(xs.map((x) => String(x || '').trim()).filter((x) => x));
  }, [universeSelectionHints]);

  const excludedCoins = useMemo(() => {
    const xs = (universeSelectionHints?.excluded_coins ?? null) as unknown;
    if (!Array.isArray(xs)) return new Set<string>();
    return new Set(xs.map((x) => String(x || '').trim().toUpperCase()).filter((x) => x));
  }, [universeSelectionHints]);

  const universeCandidateCoins = useMemo(() => {
    const xs = (universeStatus?.metadata as { candidates?: unknown } | undefined)?.candidates;
    if (!Array.isArray(xs) || xs.length === 0) return [];

    const rows = xs
      .map((x) => x as Record<string, unknown>)
      .map((x) => {
        const coin = String(x.coin ?? '').trim().toUpperCase();
        const rank = _toNum(x.rank, Number.NaN);
        const score = _toNum(x.score, Number.NaN);
        const clusterId = String((x.cluster as { cluster_id?: unknown } | null)?.cluster_id ?? '').trim();
        return { coin, rank, score, clusterId: clusterId || null };
      })
      .filter((r) => {
        if (!r.coin) return false;
        if (excludedCoins.has(r.coin)) return false;
        if (r.clusterId && excludedClusters.has(r.clusterId)) return false;
        return true;
      });

    const sorted = [...rows].sort((a, b) => {
      const ar = Number.isFinite(a.rank);
      const br = Number.isFinite(b.rank);
      if (ar && br && a.rank !== b.rank) return a.rank - b.rank;
      if (ar && !br) return -1;
      if (!ar && br) return 1;
      const as = Number.isFinite(a.score);
      const bs = Number.isFinite(b.score);
      if (as && bs && a.score !== b.score) return b.score - a.score;
      if (as && !bs) return -1;
      if (!as && bs) return 1;
      return 0;
    });

    if (!perClusterLimit) return sorted.map((r) => r.coin);

    const take: string[] = [];
    const cnt = new Map<string, number>();
    for (const r of sorted) {
      const cid = r.clusterId ?? r.coin;
      const c = cnt.get(cid) ?? 0;
      if (c >= perClusterLimit) continue;
      cnt.set(cid, c + 1);
      take.push(r.coin);
    }
    return take;
  }, [excludedClusters, excludedCoins, perClusterLimit, universeStatus]);

  const universeCoins = useMemo(() => {
    if (universeCandidateCoins.length > 0) return universeCandidateCoins;
    return universePairsCoins;
  }, [universeCandidateCoins, universePairsCoins]);

  const hardGate = useMemo(() => {
    const corrMin = _toNum(btcAltParamsAny?.corr_min, Number.NaN);
    const betaMax = _toNum(btcAltParamsAny?.beta_max ?? btcAltParamsAny?.beta_abs_max, Number.NaN);
    const betaStdMax = _toNum(btcAltParamsAny?.beta_std_max ?? btcAltParamsAny?.beta_sigma_max, Number.NaN);
    return {
      corrMin: Number.isFinite(corrMin) ? corrMin : null,
      betaMax: Number.isFinite(betaMax) ? betaMax : null,
      betaStdMax: Number.isFinite(betaStdMax) ? betaStdMax : null,
    };
  }, [btcAltParamsAny]);

  const topAlt = useMemo(() => {
    const snaps = btcAltCandidates?.snapshots;
    if (!Array.isArray(snaps)) return null;
    const universeSet = new Set(universeCoins);
    const rows = snaps
      .map((s) => s as Record<string, unknown>)
      .map((s) => {
        const ok = Boolean(s.ok);
        const alt = String(s.alt ?? '').trim().toUpperCase();
        const z = _toNum(s.z, Number.NaN);
        const corr = _toNum(s.corr, Number.NaN);
        const beta = _toNum(s.beta, Number.NaN);
        const betaStd = _toNum((s as Record<string, unknown>).beta_std ?? (s as Record<string, unknown>).beta_sigma ?? (s as Record<string, unknown>).beta_std_rolling, Number.NaN);
        const ts = _toNum(s.ts, 0);
        const clusterId = coinClusterId.get(alt) ?? null;
        return { ok, alt, z, corr, beta, betaStd, ts, clusterId };
      })
      .filter((r) => {
        if (!r.ok || !r.alt || !Number.isFinite(r.z)) return false;
        if (excludedCoins.has(r.alt)) return false;
        if (universeSet.size > 0 && !universeSet.has(r.alt)) return false;
        if (r.clusterId && excludedClusters.has(r.clusterId)) return false;

        if (hardGate.corrMin !== null) {
          if (!Number.isFinite(r.corr) || r.corr < hardGate.corrMin) return false;
        }
        if (hardGate.betaMax !== null) {
          if (!Number.isFinite(r.beta) || Math.abs(r.beta) > hardGate.betaMax) return false;
        }
        if (hardGate.betaStdMax !== null) {
          if (!Number.isFinite(r.betaStd) || r.betaStd > hardGate.betaStdMax) return false;
        }
        return true;
      });
    if (!rows.length) return null;
    const bestFirst = (a: { z: number; corr: number; beta: number; betaStd: number }, b: { z: number; corr: number; beta: number; betaStd: number }) => {
      if (trendDirW === 1) {
        const dz = a.z - b.z;
        if (dz !== 0) return dz;
      } else if (trendDirW === -1) {
        const dz = b.z - a.z;
        if (dz !== 0) return dz;
      } else {
        const da = Math.abs(a.z);
        const db = Math.abs(b.z);
        if (da !== db) return db - da;
      }
      if (Number.isFinite(a.corr) && Number.isFinite(b.corr) && a.corr !== b.corr) return b.corr - a.corr;
      if (Number.isFinite(a.beta) && Number.isFinite(b.beta) && a.beta !== b.beta) return Math.abs(a.beta) - Math.abs(b.beta);
      if (Number.isFinite(a.betaStd) && Number.isFinite(b.betaStd) && a.betaStd !== b.betaStd) return a.betaStd - b.betaStd;
      return 0;
    };

    const sorted = [...rows].sort(bestFirst);

    if (perClusterLimit && universeClusters) {
      const take: typeof sorted = [];
      const cnt = new Map<string, number>();
      for (const r of sorted) {
        const cid = r.clusterId ?? `__NOCLUSTER__`;
        const c = cnt.get(cid) ?? 0;
        if (c >= perClusterLimit) continue;
        cnt.set(cid, c + 1);
        take.push(r);
        if (take.length >= 1) break;
      }
      return take[0] ?? null;
    }

    return sorted[0] ?? null;
  }, [btcAltCandidates, coinClusterId, excludedClusters, excludedCoins, hardGate, perClusterLimit, trendDirW, universeClusters, universeCoins]);

  const finalSide = trendDirW === 1 ? 'long_alt_short_btc' : trendDirW === -1 ? 'short_alt_long_btc' : '-';

  const finalDecision = useMemo(() => {
    const entryZ = btcAltEntryZEff;
    const exitZ = btcAltExitZEff;
    const z = topAlt?.z;
    const haveZ = typeof z === 'number' && Number.isFinite(z);
    const haveEntry = typeof entryZ === 'number' && Number.isFinite(entryZ) && entryZ > 0;
    const passZ =
      trendDirW === 1
        ? haveZ && haveEntry && z <= -entryZ
        : trendDirW === -1
          ? haveZ && haveEntry && z >= entryZ
          : false;
    const action = isAligned && passZ && topAlt?.alt ? 'open' : isAligned ? 'wait' : 'hold';
    const reason = !isAligned ? 'macro_not_aligned' : !topAlt?.alt ? 'no_candidate' : !passZ ? 'z_not_reached' : 'ok';
    return { action, reason, entryZ, exitZ, passZ };
  }, [btcAltEntryZEff, btcAltExitZEff, isAligned, topAlt, trendDirW]);

  return (
    <Tabs defaultValue="core" className="w-full">
      <TabsList>
        <TabsTrigger value="core">核心</TabsTrigger>
        <TabsTrigger value="advanced">高级</TabsTrigger>
      </TabsList>

      <TabsContent value="core">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Quant 实盘开关</span>
                <div className="flex gap-2 items-center">
                  <Badge variant="secondary">{execMode}</Badge>
                  <Badge variant="secondary">{String(cfg?.quant_auto_mode ?? '-')}</Badge>
                  <Badge variant={quantLiveOn ? 'destructive' : 'outline'}>{quantLiveOn ? 'live' : 'not live'}</Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap items-center gap-4 text-sm">
                <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                  <input
                    type="checkbox"
                    checked={quantLiveOn}
                    onChange={(e) => setQuantLive(Boolean(e.target.checked))}
                    disabled={quantLiveMutation.isPending || qConfig.isLoading}
                  />
                  <span>实盘</span>
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                  <input
                    type="checkbox"
                    checked={quantLiveConfirm}
                    onChange={(e) => setQuantLiveConfirm(Boolean(e.target.checked))}
                    disabled={quantLiveMutation.isPending}
                  />
                  <span>confirm_live</span>
                </label>
                <div className="text-xs text-slate-500 flex items-center">{quantLiveMutation.isPending ? 'Saving…' : quantLiveMsg}</div>
                {!operatorOk ? <div className="text-xs text-amber-700">未设置写权限令牌</div> : null}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>BTC-ETH Pair Trading (Z-Score)</CardTitle>
            </CardHeader>
            <CardContent>
              {q.isLoading ? (
                <div className="text-sm text-slate-500">Loading…</div>
              ) : q.isError ? (
                <div className="text-sm text-red-600">Failed to load.</div>
              ) : data?.ok === false ? (
                <div className="text-sm text-amber-700">{String(data.error || 'no_data')}</div>
              ) : (
                <div className="h-[360px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="ts" tickFormatter={(v) => _fmtTs(Number(v)).slice(11)} minTickGap={24} />
                      <YAxis yAxisId="left" domain={['auto', 'auto']} />
                      <YAxis yAxisId="right" orientation="right" domain={['auto', 'auto']} />
                      <Tooltip
                        labelFormatter={(v) => _fmtTs(Number(v))}
                        formatter={(val, name) => {
                          const x = Number(val);
                          if (!Number.isFinite(x)) return ['-', String(name)];
                          if (name === 'spread') return [_fmt2(x, 6), 'spread'];
                          if (name === 'z') return [_fmt2(x, 3), 'z'];
                          return [_fmt2(x, 6), String(name)];
                        }}
                      />
                      <Line yAxisId="left" type="monotone" dataKey="spread" stroke="#2563eb" dot={false} isAnimationActive={false} />
                      <Line yAxisId="right" type="monotone" dataKey="z" stroke="#16a34a" dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              <div className="mt-4 border-t pt-4">
                <PairConfigPanel
                  key={effectiveParamsKey}
                  initial={initialCfg}
                  onSave={(cfg) => {
                    setTimeframe(String(cfg.timeframe || timeframe));
                    updateMutation.mutate({ ...cfg });
                  }}
                  saving={updateMutation.isPending}
                  saveState={saveState}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>BTC-ALT Pair Trading (Spread / Z)</span>
                <Badge variant="secondary">BTC-{String(btcAltData?.alt ?? btcAlt)}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {qBtcAlt.isLoading ? (
                <div className="text-sm text-slate-500">Loading…</div>
              ) : qBtcAlt.isError ? (
                <div className="text-sm text-red-600">Failed to load.</div>
              ) : btcAltData?.ok === false ? (
                <div className="text-sm text-amber-700">{String(btcAltData.error || 'no_data')}</div>
              ) : (
                <div className="h-[360px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={btcAltChartData} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="ts" tickFormatter={(v) => _fmtTs(Number(v)).slice(11)} minTickGap={24} />
                      <YAxis yAxisId="left" domain={['auto', 'auto']} />
                      <YAxis yAxisId="right" orientation="right" domain={['auto', 'auto']} />
                      <Tooltip
                        labelFormatter={(v) => _fmtTs(Number(v))}
                        formatter={(val, name) => {
                          const x = Number(val);
                          if (!Number.isFinite(x)) return ['-', String(name)];
                          if (name === 'spread') return [_fmt2(x, 6), 'spread'];
                          if (name === 'z') return [_fmt2(x, 3), 'z'];
                          return [_fmt2(x, 6), String(name)];
                        }}
                      />
                      <Line yAxisId="left" type="monotone" dataKey="spread" stroke="#2563eb" dot={false} isAnimationActive={false} />
                      <Line yAxisId="right" type="monotone" dataKey="z" stroke="#16a34a" dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {btcAltInitialCfg ? (
                <div className="mt-4 border-t pt-4">
                  <BtcAltConfigPanel
                    initial={btcAltInitialCfg}
                    onSave={(cfg) => {
                      setBtcAltTimeframe(String(cfg.timeframe || btcAltTimeframe));
                      btcAltUpdateMutation.mutate({ ...cfg });
                    }}
                    saving={btcAltUpdateMutation.isPending}
                    saveState={btcAltSaveState}
                  />
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Positions</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="border rounded p-3 bg-white">
                  <div className="flex items-center justify-between">
                    <div className="font-semibold">BTC-ETH</div>
                    <div className="flex items-center gap-2">
                      <Badge variant={posAny ? (posPairOk ? 'outline' : 'destructive') : 'secondary'}>{posAny ? (posPairOk ? 'in position' : 'one-leg') : 'flat'}</Badge>
                      {pnlOk ? <Badge variant={Number.isFinite(pnlNet) && pnlNet < 0 ? 'destructive' : 'outline'}>net {_fmt2(pnlNet, 2)}</Badge> : null}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                    <div>
                      <div className="text-xs text-slate-500">Entry time</div>
                      <div className="text-slate-700">{posEntryTs > 0 ? _fmtTs(posEntryTs) : '-'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">hold bars</div>
                      <div className="text-slate-700">{Number.isFinite(posHoldBars) ? String(Math.trunc(posHoldBars)) : '-'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Gross PnL</div>
                      <div className="text-slate-700">{pnlOk ? _fmt2(pnlGross, 2) : '-'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Funding</div>
                      <div className="text-slate-700">{pnlOk ? _fmt2(pnlFunding, 2) : '-'}</div>
                    </div>
                  </div>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="flex items-center justify-between">
                    <div className="font-semibold">BTC-{String(btcAltData?.alt ?? btcAlt)}</div>
                    <div className="flex items-center gap-2">
                      <Badge variant={btcAltPosAny ? (btcAltPosPairOk ? 'outline' : 'destructive') : 'secondary'}>
                        {btcAltPosAny ? (btcAltPosPairOk ? 'in position' : 'one-leg') : 'flat'}
                      </Badge>
                      {btcAltPnlOk ? <Badge variant={Number.isFinite(btcAltPnlNet) && btcAltPnlNet < 0 ? 'destructive' : 'outline'}>net {_fmt2(btcAltPnlNet, 2)}</Badge> : null}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                    <div>
                      <div className="text-xs text-slate-500">Entry time</div>
                      <div className="text-slate-700">{btcAltPosEntryTs > 0 ? _fmtTs(btcAltPosEntryTs) : '-'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">hold bars</div>
                      <div className="text-slate-700">{Number.isFinite(btcAltPosHoldBars) ? String(Math.trunc(btcAltPosHoldBars)) : '-'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Gross PnL</div>
                      <div className="text-slate-700">{btcAltPnlOk ? _fmt2(btcAltPnlGross, 2) : '-'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Funding</div>
                      <div className="text-slate-700">{btcAltPnlOk ? _fmt2(btcAltPnlFunding, 2) : '-'}</div>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </TabsContent>

      <TabsContent value="advanced">
        <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Auto Engine</span>
            <div className="flex gap-2 items-center">
              <Badge variant="secondary">{autoCfgEff.quant_auto_mode}</Badge>
              <Badge variant={autoCfgEff.quant_auto_enabled ? 'destructive' : 'outline'}>{autoCfgEff.quant_auto_enabled ? 'enabled' : 'disabled'}</Badge>
              {autoCfgTouched ? <Badge variant="secondary">dirty</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4 text-sm">
            <div>
              <div className="text-xs text-slate-500 mb-1">mode</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={autoCfgEff.quant_auto_mode}
                onChange={(e) => setAutoDraft('quant_auto_mode', e.target.value as QuantAutoBtcaltsDraft['quant_auto_mode'])}
                disabled={autoCfgMutation.isPending}
              >
                <option value="off">off</option>
                <option value="monitor">monitor</option>
                <option value="paper">paper</option>
                <option value="live">live</option>
              </select>
            </div>

            <div className="xl:col-span-2 flex items-end gap-4">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={autoCfgEff.quant_auto_enabled}
                  onChange={(e) => setAutoDraft('quant_auto_enabled', Boolean(e.target.checked))}
                  disabled={autoCfgMutation.isPending}
                />
                quant_auto_enabled
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={autoCfgEff.quant_auto_btceth_enabled}
                  onChange={(e) => setAutoDraft('quant_auto_btceth_enabled', Boolean(e.target.checked))}
                  disabled={autoCfgMutation.isPending}
                />
                btceth
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={autoCfgEff.quant_auto_btcalts_enabled}
                  onChange={(e) => setAutoDraft('quant_auto_btcalts_enabled', Boolean(e.target.checked))}
                  disabled={autoCfgMutation.isPending}
                />
                btcalts
              </label>
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">state_check_interval_sec</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_state_check_interval_sec}
                onChange={handleAutoNumber('quant_auto_state_check_interval_sec', 60)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">daily_loss_limit_pct (quant)</div>
              <Input
                type="number"
                step="0.001"
                value={autoCfgEff.quant_auto_daily_loss_limit_pct}
                onChange={handleAutoNumber('quant_auto_daily_loss_limit_pct', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">weekly_loss_limit_pct (quant)</div>
              <Input
                type="number"
                step="0.001"
                value={autoCfgEff.quant_auto_weekly_loss_limit_pct}
                onChange={handleAutoNumber('quant_auto_weekly_loss_limit_pct', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">net_btc_pct_max</div>
              <Input
                type="number"
                step="0.001"
                value={autoCfgEff.quant_auto_net_btc_pct_max}
                onChange={handleAutoNumber('quant_auto_net_btc_pct_max', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pair_notional_usdc_max</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_pair_notional_usdc_max}
                onChange={handleAutoNumber('quant_auto_pair_notional_usdc_max', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4 text-sm">
            <div>
              <div className="text-xs text-slate-500 mb-1">max_open_pairs_total</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_max_open_pairs_total}
                onChange={handleAutoNumber('quant_auto_max_open_pairs_total', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">btcalts_capacity_turnover_frac</div>
              <Input
                type="number"
                step="0.01"
                value={autoCfgEff.quant_auto_btcalts_capacity_turnover_frac}
                onChange={handleAutoNumber('quant_auto_btcalts_capacity_turnover_frac', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">btcalts_capacity_depth_frac</div>
              <Input
                type="number"
                step="0.01"
                value={autoCfgEff.quant_auto_btcalts_capacity_depth_frac}
                onChange={handleAutoNumber('quant_auto_btcalts_capacity_depth_frac', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pairs_btcalt_capacity_turnover_frac</div>
              <Input
                type="number"
                step="0.01"
                value={autoCfgEff.quant_pairs_btcalt_capacity_turnover_frac}
                onChange={handleAutoNumber('quant_pairs_btcalt_capacity_turnover_frac', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">pairs_btcalt_capacity_depth_frac</div>
              <Input
                type="number"
                step="0.01"
                value={autoCfgEff.quant_pairs_btcalt_capacity_depth_frac}
                onChange={handleAutoNumber('quant_pairs_btcalt_capacity_depth_frac', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">scan_n</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_btcalts_scan_n}
                onChange={handleAutoNumber('quant_auto_btcalts_scan_n', 12)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">open_per_tick</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_btcalts_open_per_tick}
                onChange={handleAutoNumber('quant_auto_btcalts_open_per_tick', 1)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">cooldown_bars</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_btcalts_cooldown_bars}
                onChange={handleAutoNumber('quant_auto_btcalts_cooldown_bars', 12)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">max_open_pairs</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_btcalts_max_open_pairs}
                onChange={handleAutoNumber('quant_auto_btcalts_max_open_pairs', 1)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">max_per_cluster</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_btcalts_max_per_cluster}
                onChange={handleAutoNumber('quant_auto_btcalts_max_per_cluster', 1)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div className="xl:col-span-2 flex items-end gap-4">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={autoCfgEff.quant_auto_btcalts_macro_trend_required}
                  onChange={(e) => setAutoDraft('quant_auto_btcalts_macro_trend_required', Boolean(e.target.checked))}
                  disabled={autoCfgMutation.isPending}
                />
                macro_trend_required
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={autoCfgEff.quant_auto_btcalts_dynamic_hedge_enabled}
                  onChange={(e) => setAutoDraft('quant_auto_btcalts_dynamic_hedge_enabled', Boolean(e.target.checked))}
                  disabled={autoCfgMutation.isPending}
                />
                dynamic_hedge
              </label>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4 text-sm">
            <div>
              <div className="text-xs text-slate-500 mb-1">z_bias_min</div>
              <Input
                type="number"
                step="0.1"
                value={autoCfgEff.quant_auto_btcalts_z_bias_min}
                onChange={handleAutoNumber('quant_auto_btcalts_z_bias_min', 1.5)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">z_bias_weight</div>
              <Input
                type="number"
                step="0.01"
                value={autoCfgEff.quant_auto_btcalts_z_bias_weight}
                onChange={handleAutoNumber('quant_auto_btcalts_z_bias_weight', 0.25)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">notional_nontrend_mult</div>
              <Input
                type="number"
                step="0.05"
                value={autoCfgEff.quant_auto_btcalts_notional_nontrend_mult}
                onChange={handleAutoNumber('quant_auto_btcalts_notional_nontrend_mult', 1.0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">open_per_tick_nontrend</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_btcalts_open_per_tick_nontrend}
                onChange={handleAutoNumber('quant_auto_btcalts_open_per_tick_nontrend', 1)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">max_open_pairs_nontrend</div>
              <Input
                type="number"
                value={autoCfgEff.quant_auto_btcalts_max_open_pairs_nontrend}
                onChange={handleAutoNumber('quant_auto_btcalts_max_open_pairs_nontrend', 1)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">dynamic_hedge_step</div>
              <Input
                type="number"
                step="0.01"
                value={autoCfgEff.quant_auto_btcalts_dynamic_hedge_step}
                onChange={handleAutoNumber('quant_auto_btcalts_dynamic_hedge_step', 0.1)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">btc_hedge_frac</div>
              <Input
                type="number"
                step="0.01"
                value={autoCfgEff.quant_auto_btcalts_btc_hedge_frac}
                onChange={handleAutoNumber('quant_auto_btcalts_btc_hedge_frac', 0)}
                disabled={autoCfgMutation.isPending}
              />
            </div>
            <div className="flex items-end gap-2">
              <Button size="sm" onClick={saveAutoCfg} disabled={autoCfgMutation.isPending || !autoCfgTouched || !operatorOk}>
                Save
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setAutoCfgTouched(false);
                  setAutoCfgDraft(autoCfgFromConfig);
                  setAutoCfgMsg('');
                }}
                disabled={autoCfgMutation.isPending || !autoCfgTouched}
              >
                Reset
              </Button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" onClick={() => btcethTickMutation.mutate()} disabled={btcethTickMutation.isPending || !operatorOk}>
              Tick BTC-ETH
            </Button>
            <Button size="sm" variant="secondary" onClick={() => btcaltsTickMutation.mutate()} disabled={btcaltsTickMutation.isPending || !operatorOk}>
              Tick BTC-ALTS
            </Button>
            <div className="text-xs text-slate-500">{autoTickMsg || autoCfgMsg}</div>
            {!operatorOk ? <div className="text-xs text-amber-700">未设置写权限令牌</div> : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>BTC-ETH</span>
            <Button type="button" variant="ghost" size="sm" className="h-7 px-2" onClick={() => setBtcEthCollapsed((v) => !v)}>
              {btcEthCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              <span className="ml-1 text-xs">{btcEthCollapsed ? '展开' : '折叠'}</span>
            </Button>
          </CardTitle>
        </CardHeader>
      </Card>

      {btcEthCollapsed ? null : (
        <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Quant Strategies</span>
            <div className="flex gap-2 items-center">
              <Badge variant="secondary">BTC-ETH Pairs</Badge>
              <Badge variant={action === 'pause' || action === 'stop' ? 'destructive' : 'outline'}>{action}</Badge>
              {reason && reason !== 'null' && reason !== 'undefined' ? <Badge variant="outline">{reason}</Badge> : null}
              {autoBtcEthOk && autoBtcEthState ? <Badge variant={autoBtcEthBadgeVariant}>{autoBtcEthState}</Badge> : null}
              {autoBtcEthOk && autoBtcEthTs > 0 ? <Badge variant="secondary">sm {_fmtTs(autoBtcEthTs).slice(11)}</Badge> : null}
              {gateEnabled ? (
                <Badge variant={gateBlocked ? 'destructive' : gatePass ? 'outline' : 'secondary'}>
                  gate {gateBlocked ? 'blocked' : gatePass ? 'pass' : 'fail'}
                </Badge>
              ) : null}
              {cojumpEnabled ? (
                <Badge variant={cojumpBlocked ? 'destructive' : cojumpTriggered ? 'secondary' : 'outline'}>
                  cojump {cojumpBlocked ? 'blocked' : cojumpTriggered ? 'triggered' : 'ok'}
                  {cojumpBlocked && cojumpUntil > 0 ? ` · ${_fmtTs(cojumpUntil).slice(11)}` : ''}
                </Badge>
              ) : null}
              {opGateEnabled ? (
                <Badge variant={opGateBlocked ? 'destructive' : 'outline'}>
                  op {opGateBlocked ? (opGateReason || 'blocked') : 'ok'}
                  {opGateBlocked && opGateUntil > 0 ? ` · ${_fmtTs(opGateUntil).slice(11)}` : ''}
                </Badge>
              ) : null}
              {macroVeto ? (
                <Badge variant={macroVetoBlocked ? 'destructive' : 'outline'}>
                  macro {macroVetoBlocked ? (macroVetoReason || 'blocked') : 'ok'}
                </Badge>
              ) : null}
              {macroRiskBudgetTier !== '-' ? (
                <Badge variant={macroRiskBudgetTier === 'risk_on' ? 'outline' : macroRiskBudgetTier === 'risk_off' ? 'destructive' : 'secondary'}>
                  {macroRiskBudgetTier}
                </Badge>
              ) : null}
              {macroCrashSwitch ? <Badge variant="destructive">CrashSwitch</Badge> : null}
            </div>
          </CardTitle>
          <CardDescription>
            模式说明：A-趋势跟随，B-强弱跟随，C-交易对均值回归
          </CardDescription>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <span>Quant 模式：</span>
            <select
              className="h-7 rounded border border-slate-200 bg-white px-2 text-xs"
              value={quantBtcAltStrategyMode}
              onChange={(e) => {
                const next = e.target.value as 'A' | 'B' | 'C';
                if (!executeToken) {
                  setTierMsg('forbidden: 需要 execute_token');
                  return;
                }
                setTierMsg('');
                tierMutation.mutate(next);
              }}
              disabled={tierMutation.isPending || !executeToken}
            >
              <option value="A">A · 趋势跟随</option>
              <option value="B">B · 强弱跟随</option>
              <option value="C">C · 交易对均值回归</option>
            </select>
            {tierMsg ? <span className="ml-2 text-xs text-slate-500">{tierMsg}</span> : null}
            {!executeToken ? <span className="ml-2 text-xs text-amber-700">未设置 execute_token</span> : null}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4 text-sm">
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Time</div>
              <div className="text-slate-700">{latestTs > 0 ? _fmtTs(latestTs) : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">timeframe {String(data?.timeframe ?? timeframe)}</div>
              {staleness.isStale ? <div className="text-xs text-amber-700 mt-1">{staleness.text}</div> : null}
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Spread</div>
              <div className="text-slate-700">{_fmt2(latestSpread, 6)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Z</div>
              <div className="text-slate-700">{_fmt2(latestZ, 3)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Beta</div>
              <div className="text-slate-700">{_fmt2(latestBeta, 4)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Corr</div>
              <div className="text-slate-700">{_fmt2(latestCorr, 4)}</div>
            </div>

            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Gate</div>
              <div className="text-slate-700">
                {!gateEnabled ? '-' : gateBlocked ? 'blocked' : gatePass ? 'pass' : 'fail'}
              </div>
              {gateEnabled ? (
                <div className="text-xs text-slate-500 mt-1">
                  fail {gateFailCount}/{gateKFail}{gateFreqBars > 0 ? ` · every ${gateFreqBars} bars` : ''}{gateHighVol ? ' · high-vol' : ''}
                  {gateBlockedReason ? ` · ${gateBlockedReason}` : ''}
                  {Number.isFinite(gateHalfLifeBars) ? ` · hl ${_fmt2(gateHalfLifeBars, 1)}b` : ''}
                  {Number.isFinite(gateBetaStd) ? ` · beta_std ${_fmt2(gateBetaStd, 4)}` : ''}
                  {Number.isFinite(gateFailRate) ? ` · fail_rate ${_fmtPct(gateFailRate, 1)}` : ''}
                  {gateStructReasons.length ? ` · struct ${gateStructReasons.join('+')}` : ''}
                </div>
              ) : null}

              {gateEnabled && gateLogTail.length ? (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-slate-600 select-none">log_tail ({gateLogTail.length})</summary>
                  <div className="mt-2 overflow-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-slate-500">
                          <th className="pr-3 py-1">ts</th>
                          <th className="pr-3 py-1">pass</th>
                          <th className="pr-3 py-1">adf_p</th>
                          <th className="pr-3 py-1">adf_p_adj</th>
                          <th className="pr-3 py-1">kpss_stat</th>
                          <th className="pr-3 py-1">beta_std</th>
                          <th className="pr-3 py-1">half_life</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gateLogTail
                          .slice()
                          .reverse()
                          .map((r) => (
                            <tr key={String(r.ts)} className={r.pass ? 'text-slate-700' : 'text-amber-700'}>
                              <td className="pr-3 py-1 whitespace-nowrap">{_fmtTs(r.ts).slice(11)}</td>
                              <td className="pr-3 py-1">{r.pass ? 'pass' : 'fail'}</td>
                              <td className="pr-3 py-1">{r.adf_p === null ? '-' : _fmt2(r.adf_p, 4)}</td>
                              <td className="pr-3 py-1">{r.adf_p_adj === null ? '-' : _fmt2(r.adf_p_adj, 4)}</td>
                              <td className="pr-3 py-1">{r.kpss_stat === null ? '-' : _fmt2(r.kpss_stat, 4)}</td>
                              <td className="pr-3 py-1">{r.beta_std === null ? '-' : _fmt2(r.beta_std, 4)}</td>
                              <td className="pr-3 py-1">{r.half_life_bars === null ? '-' : _fmt2(r.half_life_bars, 1)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              ) : null}
            </div>

            <div className="border rounded p-3 bg-white xl:col-span-2">
              <div className="font-semibold mb-1">Macro Veto (Tri-layer)</div>
              <div className="flex flex-wrap gap-2">
                <Badge variant={macroTrendDirW > 0 ? 'outline' : macroTrendDirW < 0 ? 'destructive' : 'secondary'}>
                  W {macroTrendDirW > 0 ? 'LONG' : macroTrendDirW < 0 ? 'SHORT' : '-'}
                </Badge>
                <Badge variant={macroTrendDirD > 0 ? 'outline' : macroTrendDirD < 0 ? 'destructive' : 'secondary'}>
                  D {macroTrendDirD > 0 ? 'LONG' : macroTrendDirD < 0 ? 'SHORT' : '-'}
                </Badge>
                <Badge variant={macroChgDir1hN > 0 ? 'outline' : macroChgDir1hN < 0 ? 'destructive' : 'secondary'}>
                  1H {macroChgDir1hN > 0 ? 'LONG' : macroChgDir1hN < 0 ? 'SHORT' : '-'}
                </Badge>
                <Badge variant={macroVetoBlocked ? 'destructive' : 'outline'}>
                  {macroVetoBlocked ? 'blocked' : 'pass'}
                </Badge>
              </div>
              <div className="text-xs text-slate-500 mt-2">
                state {macroState} · aligned {macroAligned ? 'yes' : 'no'} · conflict {macroConflict ? 'yes' : 'no'} · tier {macroRiskBudgetTier}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                ChgSpeedD {Number.isFinite(macroChgSpeedD) ? _fmt2(macroChgSpeedD, 3) : '-'} · ChgStrength {Number.isFinite(macroChgStrength) ? _fmt2(macroChgStrength, 3) : '-'} · CrashSwitch {macroCrashSwitch ? 'on' : 'off'}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                target_net_bias {Number.isFinite(macroTargetNetBias) ? _fmt2(macroTargetNetBias, 3) : '-'} · max_net_exposure {Number.isFinite(macroMaxNetExposure) ? _fmt2(macroMaxNetExposure, 3) : '-'} · allow_open {macroAllowOpen ? 'yes' : 'no'} · allow_addon {macroAllowAddon ? 'yes' : 'no'}
              </div>
              {macroVetoReason ? <div className="text-xs text-amber-700 mt-1">reason: {macroVetoReason}</div> : null}
            </div>

            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Cost</div>
              <div className="text-slate-700">{costOk ? _fmtPct(costTotal, 3) : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">
                {costOk ? `${costMode} · fee ${_fmtPct(costFee, 3)} · slip ${_fmtPct(costSlip, 3)}` : ''}
              </div>
              {Number.isFinite(costNotional) ? <div className="text-xs text-slate-500">notional ${_fmt2(costNotional, 2)}</div> : null}
            </div>

            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Margin</div>
              <div className="text-slate-700">{marginOk ? marginRec : '-'}</div>
              {marginOk ? (
                <div className="text-xs text-slate-500 mt-1">
                  BTC {Number.isFinite(marginBtcPnl) ? _fmtPct(marginBtcPnl, 2) : '-'} · ETH{' '}
                  {Number.isFinite(marginEthPnl) ? _fmtPct(marginEthPnl, 2) : '-'}
                </div>
              ) : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>组合风险状态</span>
            <div className="flex gap-2 items-center">
              {qCombo.isFetching ? <Badge variant="secondary">updating…</Badge> : null}
              {combo ? <Badge variant={comboOk ? 'outline' : 'destructive'}>{comboOk ? 'ok' : 'blocked'}</Badge> : null}
              {comboNetOver ? <Badge variant="destructive">net BTC exposure over</Badge> : null}
              {comboReasons.length ? <Badge variant="outline">{comboReasons.join(', ')}</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {qCombo.isLoading ? (
            <div className="text-sm text-slate-500">Loading…</div>
          ) : qCombo.isError ? (
            <div className="text-sm text-red-600">
              Failed to load{qCombo.error ? `: ${String(((qCombo.error as unknown as { message?: unknown })?.message ?? qCombo.error) as unknown)}` : ''}
            </div>
          ) : !combo ? (
            <div className="text-sm text-slate-500">No data.</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4 text-sm">
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Time</div>
                <div className="text-slate-700">{comboTs > 0 ? _fmtTs(comboTs) : '-'}</div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Gross</div>
                <div className="text-slate-700">{Number.isFinite(comboGross) ? `$${_fmt2(comboGross, 2)}` : '-'}</div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Net BTC leg</div>
                <div className="text-slate-700">{Number.isFinite(comboNetLeg) ? `$${_fmt2(comboNetLeg, 2)}` : '-'}</div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Net exposure</div>
                <div className={comboNetOver ? 'text-rose-700 font-semibold' : 'text-slate-700'}>
                  {Number.isFinite(comboNetFrac) ? _fmtPct(comboNetFrac, 2) : '-'}
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  target {Number.isFinite(comboTarget) ? _fmtPct(comboTarget, 2) : '-'} · max {Number.isFinite(comboMax) ? _fmtPct(comboMax, 2) : '-'}
                </div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Open pairs</div>
                <div className="text-slate-700">{comboOpenPairs}</div>
              </div>

              <div className="border rounded p-3 bg-white xl:col-span-3">
                <div className="font-semibold mb-1">By cluster</div>
                {Object.keys(comboPairsByCluster).length ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left">
                      <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                        <tr>
                          <th className="px-3 py-2">cluster</th>
                          <th className="px-3 py-2">n</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(comboPairsByCluster)
                          .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0) || String(a[0]).localeCompare(String(b[0])))
                          .map(([k, v]) => (
                            <tr key={String(k)} className="border-b last:border-0">
                              <td className="px-3 py-2 text-gray-700">{String(k)}</td>
                              <td className="px-3 py-2 text-gray-700">{String(v)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-xs text-slate-500">No clusters.</div>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Execution (BTC-ETH)</span>
            <div className="flex gap-2 items-center">
              <Badge variant={execMode === 'execute' ? 'destructive' : 'outline'}>{execMode}</Badge>
              {openMutation.isPending || closeMutation.isPending ? <Badge variant="secondary">working…</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">Venue</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={execVenue} disabled>
                <option value="aster">aster</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Mode</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={execMode} onChange={(e) => setExecModeOverride(e.target.value as 'dry-run' | 'execute')}>
                <option value="dry-run">dry-run</option>
                <option value="execute">execute</option>
              </select>
            </div>
            <div className="xl:col-span-2">
              <div className="text-xs text-slate-500 mb-1">execute_token</div>
              <Input
                type="password"
                value={executeToken}
                onChange={(e) => {
                  const v = String(e.target.value || '');
                  setExecuteToken(v);
                }}
                placeholder="WEBHOOK_EXECUTE_TOKEN"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={confirmExecute}
                  onChange={(e) => setConfirmExecute(Boolean(e.target.checked))}
                  disabled={execMode !== 'execute'}
                />
                confirm_execute
              </label>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Direction</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={execDirection}
                onChange={(e) => setExecDirection(e.target.value as 'long_btc_short_eth' | 'short_btc_long_eth')}
              >
                <option value="long_btc_short_eth">long BTC / short ETH</option>
                <option value="short_btc_long_eth">short BTC / long ETH</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Notional (BTC leg, USDC)</div>
              <Input type="number" value={execNotional} onChange={(e) => setExecNotional(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Maker</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={execMakerMode} onChange={(e) => setExecMakerMode(e.target.value as 'off' | 'auto' | 'on')}>
                <option value="off">off</option>
                <option value="auto">auto</option>
                <option value="on">on</option>
              </select>
            </div>
            <div className="flex items-end gap-2">
              <Button
                onClick={() =>
                  openMutation.mutate({
                    venue: execVenue,
                    direction: execDirection,
                    notional_usdc: execNotional,
                    execute: execMode === 'execute',
                    confirm_execute: confirmExecute,
                      idempotency_key:
                        execMode === 'execute'
                          ? idemKey('btceth_open', { venue: execVenue, direction: execDirection, notional_usdc: execNotional, timeframe })
                          : undefined,
                    maker: execMakerMode,
                    tag: 'quant_pairs_btceth',
                    strategy_id: 'quant_pairs_btceth',
                    timeframe,
                  })
                }
                disabled={openMutation.isPending || closeMutation.isPending || (execMode === 'execute' && !liveReady)}
              >
                Open
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  closeMutation.mutate({
                    venue: execVenue,
                    execute: execMode === 'execute',
                    confirm_execute: confirmExecute,
                      idempotency_key:
                        execMode === 'execute' ? idemKey('btceth_close', { venue: execVenue, timeframe }) : undefined,
                    tag: 'quant_pairs_btceth_close',
                  })
                }
                disabled={openMutation.isPending || closeMutation.isPending || (execMode === 'execute' && !liveReady)}
              >
                Close
              </Button>
            </div>
          </div>

          <div className="mt-3 border rounded p-3 bg-white">
            <div className="flex items-center justify-between">
              <div className="text-xs text-slate-500">Candidates (auto refresh 5m)</div>
              <div className="flex items-center gap-2">
                <Button variant="secondary" onClick={() => qBtcAltCandidates.refetch()} disabled={qBtcAltCandidates.isFetching}>
                  Refresh
                </Button>
                {qBtcAltCandidates.isFetching ? <Badge variant="secondary">loading…</Badge> : null}
              </div>
            </div>
            {btcAltCandidates?.ok && Array.isArray(btcAltCandidates.snapshots) && btcAltCandidates.snapshots.length > 0 ? (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                    <tr>
                      <th className="px-3 py-2">alt</th>
                      <th className="px-3 py-2">z</th>
                      <th className="px-3 py-2">corr</th>
                      <th className="px-3 py-2">beta</th>
                      <th className="px-3 py-2">ts</th>
                      <th className="px-3 py-2">status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {btcAltCandidates.snapshots
                      .slice(0, btcAltPfMaxAlts)
                      .map((s, idx) => (
                        <tr
                          key={`${String(s.alt || 'ALT')}_${idx}`}
                          className="border-b last:border-0 hover:bg-slate-50/50 cursor-pointer"
                          onClick={() => {
                            if (s && s.ok && s.alt) setBtcAlt(String(s.alt).trim().toUpperCase());
                          }}
                        >
                          <td className="px-3 py-2 text-gray-700 font-semibold">{String(s.alt || '-')}</td>
                          <td className="px-3 py-2 text-gray-700">{_fmt2(_toNum(s.z, Number.NaN), 3)}</td>
                          <td className="px-3 py-2 text-gray-700">{_fmt2(_toNum(s.corr, Number.NaN), 3)}</td>
                          <td className="px-3 py-2 text-gray-700">{_fmt2(_toNum(s.beta, Number.NaN), 3)}</td>
                          <td className="px-3 py-2 text-gray-500">{s.ts ? _fmtTs(Number(s.ts)).slice(5, 16) : '-'}</td>
                          <td className={s.ok ? 'px-3 py-2 text-emerald-700' : 'px-3 py-2 text-rose-700'}>{s.ok ? 'ok' : String(s.error || 'err')}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : btcAltCandidates && !btcAltCandidates.ok ? (
              <div className="mt-2 text-xs text-rose-700">{String(btcAltCandidates.error || 'failed')}</div>
            ) : qBtcAltCandidates.isLoading ? (
              <div className="mt-2 text-xs text-slate-500">Loading…</div>
            ) : (
              <div className="mt-2 text-xs text-slate-500">No data.</div>
            )}
          </div>

          {execMode === 'execute' && !liveReady ? (
            <div className="mt-3 text-xs text-amber-700">
              {!tokenOk || !confirmExecute ? <div>execute requires token + confirm_execute</div> : null}
              {venueMatchesPreflight && !preflightReady && preflightBlockers.length ? (
                <div>preflight blocked: {preflightBlockers.join(', ')}</div>
              ) : null}
            </div>
          ) : null}

          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Open result</div>
              <pre className="whitespace-pre-wrap break-words text-slate-700">{openMutation.data ? JSON.stringify(openMutation.data, null, 2) : ''}</pre>
              {openMutation.isError ? <div className="text-rose-700">open failed</div> : null}
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Close result</div>
              <pre className="whitespace-pre-wrap break-words text-slate-700">{closeMutation.data ? JSON.stringify(closeMutation.data, null, 2) : ''}</pre>
              {closeMutation.isError ? <div className="text-rose-700">close failed</div> : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>计划预览 (BTC-ETH)</span>
            <div className="flex gap-2 items-center">
              <Badge variant="outline">{execDirection}</Badge>
              <Badge variant="outline">notional {execNotional}</Badge>
              {planMutation.isPending ? <Badge variant="secondary">planning…</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
              <div>timeframe {String(planData?.timeframe ?? timeframe)}</div>
              <div>direction {String(planData?.direction ?? execDirection)}</div>
              <div>
                notional{' '}
                {Number.isFinite(planData?.notional_usdc ?? execNotional)
                  ? _fmt2(planData?.notional_usdc ?? execNotional, 2)
                  : '-'}
              </div>
              {planTs > 0 ? <div>ts {_fmtTs(planTs)}</div> : null}
            </div>
            {costOk && Number.isFinite(planNotionalEff) ? (
              <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
                <div>
                  预估成本{' '}
                  {Number.isFinite(costTotal) && Number.isFinite(planNotionalEff)
                    ? `${_fmtPct(costTotal, 3)} (~$${_fmt2(planNotionalEff * costTotal, 2)})`
                    : '-'}
                </div>
                <div>
                  手续费 {Number.isFinite(costFee) ? _fmtPct(costFee, 3) : '-'} · 滑点{' '}
                  {Number.isFinite(costSlip) ? _fmtPct(costSlip, 3) : '-'}
                </div>
                {Number.isFinite(costSlip) && Number.isFinite(planNotionalEff) ? (
                  <div>
                    滑点敏感：每增加 0.1% 滑点 ≈ ${_fmt2(planNotionalEff * 0.001, 2)} 成本
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={() =>
                  planMutation.mutate({
                    strategy_id: 'quant_pairs_btceth',
                    direction: execDirection,
                    notional_usdc: execNotional,
                    timeframe,
                  })
                }
                disabled={planMutation.isPending}
              >
                生成计划
              </Button>
              {planMutation.isError ? <div className="text-xs text-rose-700">plan failed</div> : null}
            </div>

            {planData ? (
              <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">Legs</div>
                  {planLegs.length ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs text-left">
                        <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                          <tr>
                            <th className="px-3 py-2">symbol</th>
                            <th className="px-3 py-2">side</th>
                            <th className="px-3 py-2">notional</th>
                          </tr>
                        </thead>
                        <tbody>
                          {planLegs.map((leg, idx) => (
                            <tr key={`${leg.symbol}_${idx}`} className="border-b last:border-0">
                              <td className="px-3 py-2 text-gray-700">{leg.symbol}</td>
                              <td className="px-3 py-2 text-gray-700">{leg.side}</td>
                              <td className="px-3 py-2 text-gray-700">{_fmt2(_toNum((leg as Record<string, unknown>).notional_usdc, Number.NaN), 2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500">No plan yet.</div>
                  )}
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">Risk snapshot</div>
                  {planData.risk ? (
                    <>
                      <div className="text-slate-700">
                        subportfolio {!planRiskSubpEnabled ? 'disabled' : planRiskSubpOk ? 'ok' : 'blocked'}
                      </div>
                      {planRiskSubpReason ? (
                        <div className="text-xs text-slate-500 mt-1">{planRiskSubpReason}</div>
                      ) : null}
                      <div className="text-xs text-slate-500 mt-1">
                        open_positions {planRiskOpenN} · notional{' '}
                        {planRiskOpenNotional ? `$${_fmt2(planRiskOpenNotional, 2)}` : '-'}
                      </div>
                    </>
                  ) : (
                    <div className="text-xs text-slate-500">No risk info.</div>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Strategy Status (BTC-ETH)</span>
            <div className="flex gap-2 items-center">
              {qRisk.isFetching ? <Badge variant="secondary">updating…</Badge> : null}
              {Number.isFinite(liveRiskSubpDd) && Number.isFinite(liveRiskDdLimit) ? (
                <Badge variant={liveRiskDdOver ? 'destructive' : 'outline'}>
                  DD {_fmtPct(liveRiskSubpDd, 1)} / limit {_fmtPct(liveRiskDdLimit, 1)}
                </Badge>
              ) : null}
              {liveRiskData?.ok ? <Badge variant="outline">ok</Badge> : liveRiskData ? <Badge variant="destructive">error</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {qRisk.isLoading ? (
            <div className="text-sm text-slate-500">Loading…</div>
          ) : qRisk.isError ? (
            <div className="text-sm text-red-600">Failed to load.</div>
          ) : !liveRiskData ? (
            <div className="text-sm text-slate-500">No data.</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4 text-sm">
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Time</div>
                <div className="text-slate-700">{liveRiskTs > 0 ? _fmtTs(liveRiskTs) : '-'}</div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Subportfolio</div>
                <div className="text-slate-700">
                  {!liveRiskSubpEnabled ? 'disabled' : liveRiskSubpOk ? 'ok' : 'blocked'}
                </div>
                {liveRiskSubpReason ? <div className="text-xs text-slate-500 mt-1">{liveRiskSubpReason}</div> : null}
                {liveRiskSubpDecision ? (
                  <div className="text-xs text-slate-500 mt-1">
                    decision {liveRiskSubpDecision}
                    {liveRiskSubpWaitMs > 0 ? ` · wait ${Math.round(liveRiskSubpWaitMs / 1000)}s` : ''}
                  </div>
                ) : null}
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Equity</div>
                <div className="text-slate-700">
                  {Number.isFinite(liveRiskSubpEquity) ? `$${_fmt2(liveRiskSubpEquity, 2)}` : '-'}
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  dd {Number.isFinite(liveRiskSubpDd) ? _fmtPct(liveRiskSubpDd, 2) : '-'}
                  {Number.isFinite(liveRiskDdLimit)
                    ? ` / limit ${_fmtPct(liveRiskDdLimit, 2)}${liveRiskDdOver ? ' · freeze' : ''}`
                    : ''}
                </div>
              </div>
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-1">Open positions</div>
                <div className="text-slate-700">{liveRiskOpenN}</div>
                <div className="text-xs text-slate-500 mt-1">
                  notional {liveRiskOpenNotional ? `$${_fmt2(liveRiskOpenNotional, 2)}` : '-'}
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Gate State</span>
            <div className="flex gap-2 items-center">
              {qGateState.isFetching ? <Badge variant="secondary">updating…</Badge> : null}
              {gateState?.ok ? <Badge variant="outline">ok</Badge> : gateState ? <Badge variant="destructive">error</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {qGateState.isLoading ? (
            <div className="text-sm text-slate-500">Loading…</div>
          ) : qGateState.isError ? (
            <div className="text-sm text-red-600">Failed to load.</div>
          ) : !gateState ? (
            <div className="text-sm text-slate-500">No data.</div>
          ) : (
            <div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4 text-sm">
                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">Time</div>
                  <div className="text-slate-700">{gateTs > 0 ? _fmtTs(gateTs) : '-'}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    venue {String(gateState?.execution_venue ?? '-')}
                    {gateState?.live ? ' · live' : ' · dry-run'}
                  </div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">Summary</div>
                  <div className="text-slate-700">
                    ok {gateOkN} · reject {gateRejectN}
                  </div>
                  {gateByReasonTop.length > 0 ? (
                    <div className="text-xs text-slate-500 mt-1">
                      {gateByReasonTop
                        .map((x) => `${x.reason}:${x.n}`)
                        .join(' · ')}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 mt-1">(no recent samples)</div>
                  )}
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">Config</div>
                  <div className="text-slate-700">pair_cd {String(gateState?.cooldown_sec ?? '-')}s</div>
                  <div className="text-xs text-slate-500 mt-1">coin_cd {String(gateState?.coin_cooldown_sec ?? '-')}s</div>
                  <div className="text-xs text-slate-500 mt-1">post_close {String(gateState?.post_close_hours ?? '-')}h</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">Active</div>
                  <div className="text-slate-700">pair {Object.keys((gateState?.cooldowns ?? {}) as Record<string, unknown>).length}</div>
                  <div className="text-xs text-slate-500 mt-1">coin {Object.keys((gateState?.coin_cooldowns ?? {}) as Record<string, unknown>).length}</div>
                  <div className="text-xs text-slate-500 mt-1">post_close {Object.keys((gateState?.post_close_cooldowns ?? {}) as Record<string, unknown>).length}</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">In-flight</div>
                  <div className="text-slate-700">{Object.keys((gateState?.entry_inflight ?? {}) as Record<string, unknown>).length}</div>
                  <div className="text-xs text-slate-500 mt-1">ttl {String(gateState?.entry_inflight_cooldown_sec ?? '-')}s</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="font-semibold mb-1">Rate limit</div>
                  <div className="text-slate-700">{String(gateState?.max_orders_per_minute ?? '-')} / min</div>
                  <div className="text-xs text-slate-500 mt-1">window {String(gateState?.order_rate_window_sec ?? '-')}s</div>
                </div>
              </div>

              <div className="mt-4 border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Recent decisions</div>
                {gateRecent.length === 0 ? (
                  <div className="text-xs text-slate-500">(empty)</div>
                ) : (
                  <div className="overflow-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-slate-500">
                          <th className="py-1 pr-2">time</th>
                          <th className="py-1 pr-2">system</th>
                          <th className="py-1 pr-2">pair</th>
                          <th className="py-1 pr-2">side</th>
                          <th className="py-1 pr-2">ok</th>
                          <th className="py-1 pr-2">reason</th>
                          <th className="py-1 pr-2">corr</th>
                          <th className="py-1 pr-2">thr</th>
                          <th className="py-1 pr-2">cache</th>
                        </tr>
                      </thead>
                      <tbody>
                        {gateRecent.map((r) => (
                          <tr key={`${r.ts}|${r.pair}|${r.side}|${r.reason}`} className="border-t">
                            <td className="py-1 pr-2 text-slate-700">{_fmtTs(r.ts).slice(11)}</td>
                            <td className="py-1 pr-2 text-slate-700">{r.systemId || '-'}</td>
                            <td className="py-1 pr-2 text-slate-700">{r.pair || '-'}</td>
                            <td className="py-1 pr-2 text-slate-700">{r.side || '-'}</td>
                            <td className="py-1 pr-2">
                              <span className={r.ok ? 'text-emerald-700' : 'text-red-700'}>{r.ok ? 'ok' : 'reject'}</span>
                            </td>
                            <td className="py-1 pr-2 text-slate-700">{r.reason || '-'}</td>
                            <td className="py-1 pr-2 text-slate-700">{_fmt2(r.corr, 4)}</td>
                            <td className="py-1 pr-2 text-slate-700">
                              {Number.isFinite(r.thrEnter) ? _fmt2(r.thrEnter, 2) : '-'}
                              {Number.isFinite(r.thrExit) ? `/${_fmt2(r.thrExit, 2)}` : ''}
                            </td>
                            <td className="py-1 pr-2 text-slate-700">{r.cacheHit == null ? '-' : r.cacheHit ? 'hit' : 'miss'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>子组合风控 (quant_pairs_btceth)</span>
            <div className="flex gap-2 items-center">
              {qRisk.isFetching ? <Badge variant="secondary">updating…</Badge> : null}
              <Badge variant={subpEnabled ? 'outline' : 'secondary'}>{subpEnabled ? 'enabled' : 'disabled'}</Badge>
              <Badge variant={subpHasOverride ? 'outline' : 'secondary'}>{subpHasOverride ? 'override' : 'base'}</Badge>
              {subpLiveMode ? <Badge variant="destructive">live</Badge> : <Badge variant="outline">dry-run</Badge>}
              {liveRiskSubpEnabled ? (
                <Badge variant={liveRiskSubpOk ? 'outline' : 'destructive'}>{liveRiskSubpOk ? 'ok' : 'blocked'}</Badge>
              ) : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <SubportfolioConfigPanel
            key={subpPanelKey}
            enabled={subpEnabled}
            hasOverride={subpHasOverride}
            base={baseSubpMeta}
            initial={effectiveSubpMeta}
            tracker={{
              equity: trackerSubpEquity,
              peak: trackerSubpPeak,
              dd: trackerSubpDd,
              cooldownUntilMs: trackerSubpCooldownUntil,
            }}
            live={{
              enabled: liveRiskSubpEnabled,
              ok: liveRiskSubpOk,
              dd: liveRiskSubpDd,
              ddLimit: liveRiskDdLimit,
              reason: liveRiskSubpReason || liveRiskSubpDecision,
            }}
            liveMode={subpLiveMode}
            saving={subpMutation.isPending}
            msg={subpMsg}
            onSave={saveSubp}
            onClearOverride={clearSubpOverride}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Position (BTC-ETH)</span>
            <div className="flex gap-2 items-center">
              <Badge variant={posAny ? (posPairOk ? 'outline' : 'destructive') : 'secondary'}>{posAny ? (posPairOk ? 'in position' : 'one-leg') : 'flat'}</Badge>
              {pnlOk ? <Badge variant={Number.isFinite(pnlNet) && pnlNet < 0 ? 'destructive' : 'outline'}>net {_fmt2(pnlNet, 2)}</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4 text-sm">
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Entry time</div>
              <div className="text-slate-700">{posEntryTs > 0 ? _fmtTs(posEntryTs) : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">hold bars {Number.isFinite(posHoldBars) ? String(Math.trunc(posHoldBars)) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Gross PnL</div>
              <div className="text-slate-700">{pnlOk ? _fmt2(pnlGross, 2) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Funding</div>
              <div className="text-slate-700">{pnlOk ? _fmt2(pnlFunding, 2) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Cost (est)</div>
              <div className="text-slate-700">{pnlOk ? _fmt2(pnlCost, 2) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">BTC leg</div>
              <div className="text-slate-700">
                {posLegBtc ? `${String(posLegBtc.side ?? '-')}` : '-'}
              </div>
              <div className="text-xs text-slate-500 mt-1">notional {_fmt2(_toNum(posLegBtc?.notional_usdc, Number.NaN), 2)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">ETH leg</div>
              <div className="text-slate-700">
                {posLegEth ? `${String(posLegEth.side ?? '-')}` : '-'}
              </div>
              <div className="text-xs text-slate-500 mt-1">notional {_fmt2(_toNum(posLegEth?.notional_usdc, Number.NaN), 2)}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Backtest (BTC-ETH)</span>
            <div className="flex gap-2 items-center">
              <Button onClick={() => qBacktest.refetch()} disabled={qBacktest.isFetching}>Run</Button>
              {qBacktest.isFetching ? <Badge variant="secondary">running…</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">limit</div>
              <Input type="number" value={btLimit} onChange={(e) => setBtLimit(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">notional_usdc</div>
              <Input type="number" value={btNotional} onChange={(e) => setBtNotional(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">apply_cost</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={btApplyCost} onChange={(e) => setBtApplyCost(e.target.value as 'on' | 'off')}>
                <option value="on">on</option>
                <option value="off">off</option>
              </select>
            </div>
            <div className="xl:col-span-3 border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">metrics</div>
              <div className="text-sm text-slate-700">
                {backtest?.sim?.metrics
                  ? `trades ${String(backtest.sim.metrics.trades)} · net ${_fmt2(backtest.sim.metrics.net_pnl, 2)} · sharpe ${_fmt2(backtest.sim.metrics.net_sharpe, 3)} · win ${_fmtPct(backtest.sim.metrics.win_rate, 2)} · maxdd ${_fmt2(backtest.sim.metrics.max_drawdown, 2)}`
                  : backtest?.error
                    ? String(backtest.error)
                    : backtest?.sim?.error
                      ? String(backtest.sim.error)
                      : ''}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {Number.isFinite(btFundingBtc) || Number.isFinite(btFundingEth)
                  ? `funding(8h mean) BTC ${Number.isFinite(btFundingBtc) ? _fmtPct(btFundingBtc, 4) : '-'} · ETH ${Number.isFinite(btFundingEth) ? _fmtPct(btFundingEth, 4) : '-'}`
                  : ''}
              </div>
            </div>
          </div>

          {Array.isArray(scaleCurve) && scaleCurve.length >= 3 ? (
            <div className="mt-4 border rounded p-3 bg-white text-xs">
              <div className="font-semibold mb-1">capacity (scale_curve)</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                    <tr>
                      <th className="px-3 py-2">notional</th>
                      <th className="px-3 py-2">trades</th>
                      <th className="px-3 py-2">net</th>
                      <th className="px-3 py-2">sharpe</th>
                      <th className="px-3 py-2">maxdd</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scaleCurve
                      .slice()
                      .sort((a, b) => Number(a.gross_notional_usdc) - Number(b.gross_notional_usdc))
                      .map((r) => {
                        const m = r.metrics ?? null;
                        return (
                          <tr key={String(r.gross_notional_usdc)} className="border-b last:border-0 hover:bg-slate-50/50">
                            <td className="px-3 py-2 text-gray-700">{_fmt2(Number(r.gross_notional_usdc), 2)}</td>
                            <td className="px-3 py-2 text-gray-500">{m ? String(m.trades) : '-'}</td>
                            <td className={m && Number(m.net_pnl) >= 0 ? 'px-3 py-2 text-emerald-700 font-semibold' : 'px-3 py-2 text-rose-700 font-semibold'}>
                              {m ? _fmt2(Number(m.net_pnl), 2) : '-'}
                            </td>
                            <td className="px-3 py-2 text-gray-500">{m ? _fmt2(Number(m.net_sharpe), 3) : '-'}</td>
                            <td className="px-3 py-2 text-gray-500">{m ? _fmt2(Number(m.max_drawdown), 2) : '-'}</td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="mt-4">
            {Array.isArray(backtest?.sim?.equity_curve) && backtest!.sim!.equity_curve!.length > 1 ? (
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={backtest!.sim!.equity_curve} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="t" tickFormatter={(v) => _fmtTs(Number(v)).slice(5, 16)} minTickGap={24} />
                    <YAxis domain={['auto', 'auto']} />
                    <Tooltip labelFormatter={(v) => _fmtTs(Number(v))} formatter={(val) => [_fmt2(Number(val), 2), 'cum']} />
                    <Line type="monotone" dataKey="cum" stroke="#0f766e" dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : null}
          </div>

          <div className="mt-4 border rounded p-3 bg-white text-xs">
            <div className="font-semibold mb-1">trades (latest 30)</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                  <tr>
                    <th className="px-3 py-2">t0</th>
                    <th className="px-3 py-2">t1</th>
                    <th className="px-3 py-2">dir</th>
                    <th className="px-3 py-2">hold</th>
                    <th className="px-3 py-2">pnl</th>
                    <th className="px-3 py-2">reason</th>
                  </tr>
                </thead>
                <tbody>
                  {Array.isArray(backtest?.sim?.trades) && backtest!.sim!.trades!.length > 0 ? (
                    backtest!.sim!.trades!
                      .slice(-30)
                      .reverse()
                      .map((t, idx) => (
                        <tr key={`${String(t.t0)}_${idx}`} className="border-b last:border-0 hover:bg-slate-50/50">
                          <td className="px-3 py-2 text-gray-500">{_fmtTs(Number(t.t0)).slice(5, 16)}</td>
                          <td className="px-3 py-2 text-gray-500">{_fmtTs(Number(t.t1)).slice(5, 16)}</td>
                          <td className="px-3 py-2 text-gray-700">{String(t.dir)}</td>
                          <td className="px-3 py-2 text-gray-500">{String(t.hold_bars)}</td>
                          <td className={Number(t.pnl_net) >= 0 ? 'px-3 py-2 text-emerald-700 font-semibold' : 'px-3 py-2 text-rose-700 font-semibold'}>
                            {_fmt2(Number(t.pnl_net), 2)}
                          </td>
                          <td className="px-3 py-2 text-gray-500">{String(t.reason)}</td>
                        </tr>
                      ))
                  ) : (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-center text-gray-500">
                        No trades.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>BTC-ETH Pair Trading (Z-Score)</CardTitle>
        </CardHeader>
        <CardContent>
          {q.isLoading ? (
            <div className="text-sm text-slate-500">Loading…</div>
          ) : q.isError ? (
            <div className="text-sm text-red-600">Failed to load.</div>
          ) : data?.ok === false ? (
            <div className="text-sm text-amber-700">{String(data.error || 'no_data')}</div>
          ) : (
            <div className="h-[360px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" tickFormatter={(v) => _fmtTs(Number(v)).slice(11)} minTickGap={24} />
                  <YAxis yAxisId="left" domain={['auto', 'auto']} />
                  <YAxis yAxisId="right" orientation="right" domain={['auto', 'auto']} />
                  <Tooltip
                    labelFormatter={(v) => _fmtTs(Number(v))}
                    formatter={(val, name) => {
                      const x = Number(val);
                      if (!Number.isFinite(x)) return ['-', String(name)];
                      if (name === 'spread') return [_fmt2(x, 6), 'spread'];
                      if (name === 'z') return [_fmt2(x, 3), 'z'];
                      return [_fmt2(x, 6), String(name)];
                    }}
                  />
                  <Line yAxisId="left" type="monotone" dataKey="spread" stroke="#2563eb" dot={false} isAnimationActive={false} />
                  <Line yAxisId="right" type="monotone" dataKey="z" stroke="#16a34a" dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="mt-4 border-t pt-4">
            <PairConfigPanel
              key={effectiveParamsKey}
              initial={initialCfg}
              onSave={(cfg) => {
                setTimeframe(String(cfg.timeframe || timeframe));
                updateMutation.mutate({ ...cfg });
              }}
              saving={updateMutation.isPending}
              saveState={saveState}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>WFO (BTC-ETH)</span>
            <div className="flex gap-2 items-center">
              <Button onClick={() => wfoRunMutation.mutate()} disabled={wfoRunMutation.isPending || q.isFetching}>Run now</Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setWfoTouched(false);
                  if (wfoConfig) {
                    setWfoEnabledDraft(Boolean(wfoConfig.enabled));
                    setWfoApplyDraft(Boolean(wfoConfig.apply));
                    setWfoRefreshSecDraft(_toNum(wfoConfig.refresh_sec, 3600));
                    setWfoPlateauMinFracDraft(_toNum(wfoConfig.plateau_min_frac, 0.6));
                    setWfoPlateauTolDraft(_toNum(wfoConfig.plateau_tol, 0.1));
                    setWfoIsBarsDraft(_toNum(wfoConfig.is_bars, 480));
                    setWfoOosBarsDraft(_toNum(wfoConfig.oos_bars, 240));
                    setWfoStepBarsDraft(_toNum(wfoConfig.step_bars, 240));
                    setWfoEmbargoBarsDraft(_toNum(wfoConfig.embargo_bars, 0));
                    const grid = wfoConfig.grid && typeof wfoConfig.grid === 'object' ? JSON.stringify(wfoConfig.grid, null, 2) : '';
                    setWfoGridDraft(grid);
                  }
                }}
                disabled={wfoSaveMutation.isPending || wfoRunMutation.isPending}
              >
                Reset
              </Button>
              <Button
                onClick={() => {
                  setWfoTouched(true);
                  wfoSaveMutation.mutate({
                    wfo_enabled: wfoEnabledEff,
                    wfo_apply: wfoApplyEff,
                    wfo_refresh_sec: wfoRefreshSecEff,
                    wfo_plateau_min_frac: wfoPlateauMinFracEff,
                    wfo_plateau_tol: wfoPlateauTolEff,
                    wfo_is_bars: wfoIsBarsEff,
                    wfo_oos_bars: wfoOosBarsEff,
                    wfo_step_bars: wfoStepBarsEff,
                    wfo_embargo_bars: wfoEmbargoBarsEff,
                    wfo_grid: wfoGridEff.trim() ? wfoGridEff.trim() : null,
                  });
                }}
                disabled={wfoSaveMutation.isPending || wfoRunMutation.isPending}
              >
                Save
              </Button>
              {wfoRunMutation.isPending ? <Badge variant="secondary">running…</Badge> : null}
              {wfoSaveMutation.isPending ? <Badge variant="secondary">saving…</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4">
            <div className="xl:col-span-2">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={wfoEnabledEff}
                  onChange={(e) => {
                    setWfoTouched(true);
                    setWfoEnabledDraft(Boolean(e.target.checked));
                  }}
                />
                wfo_enabled
              </label>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={wfoApplyEff}
                  onChange={(e) => {
                    setWfoTouched(true);
                    setWfoApplyDraft(Boolean(e.target.checked));
                  }}
                />
                wfo_apply
              </label>
              <div className="text-xs text-slate-500 mt-3">refresh_sec</div>
              <Input
                type="number"
                value={wfoRefreshSecEff}
                onChange={(e) => {
                  setWfoTouched(true);
                  setWfoRefreshSecDraft(Number(e.target.value));
                }}
              />
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">is_bars</div>
              <Input type="number" value={wfoIsBarsEff} onChange={(e) => {
                setWfoTouched(true);
                setWfoIsBarsDraft(Number(e.target.value));
              }} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">oos_bars</div>
              <Input type="number" value={wfoOosBarsEff} onChange={(e) => {
                setWfoTouched(true);
                setWfoOosBarsDraft(Number(e.target.value));
              }} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">step_bars</div>
              <Input type="number" value={wfoStepBarsEff} onChange={(e) => {
                setWfoTouched(true);
                setWfoStepBarsDraft(Number(e.target.value));
              }} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">embargo_bars</div>
              <Input type="number" value={wfoEmbargoBarsEff} onChange={(e) => {
                setWfoTouched(true);
                setWfoEmbargoBarsDraft(Number(e.target.value));
              }} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">plateau_min_frac</div>
              <Input type="number" step="0.01" value={wfoPlateauMinFracEff} onChange={(e) => {
                setWfoTouched(true);
                setWfoPlateauMinFracDraft(Number(e.target.value));
              }} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">plateau_tol</div>
              <Input type="number" step="0.01" value={wfoPlateauTolEff} onChange={(e) => {
                setWfoTouched(true);
                setWfoPlateauTolDraft(Number(e.target.value));
              }} />
            </div>
          </div>

          <div className="mt-4 border rounded p-3 bg-white">
            <div className="text-xs text-slate-500 mb-2">wfo_grid (JSON)</div>
            <textarea
              className="w-full min-h-[140px] border rounded px-3 py-2 font-mono text-xs"
              value={wfoGridEff}
              onChange={(e) => {
                setWfoTouched(true);
                setWfoGridDraft(e.target.value);
              }}
              placeholder='{"entry_z":{"values":[1.5,2.0,2.5]}}'
            />
          </div>

          <div className="mt-3 text-xs text-slate-600">
            {(() => {
              const w = (data?.wfo ?? null) as Record<string, unknown> | null;
              if (!w) return null;
              const ok = Boolean(w.ok);
              const enabled = Boolean(w.enabled);
              const cached = Boolean(w.cached);
              const applied = Boolean(w.applied);
              const err = String(w.error ?? '');
              const sel = (w.selected_params ?? null) as Record<string, unknown> | null;
              const top = sel ? Object.entries(sel).map(([k, v]) => `${k}=${String(v)}`).slice(0, 12).join(' · ') : '';
              return (
                <div>
                  <span className={ok ? 'text-emerald-700 font-semibold' : 'text-rose-700 font-semibold'}>{ok ? 'ok' : 'fail'}</span>
                  <span className="ml-2">enabled {enabled ? 'on' : 'off'} · cached {cached ? 'yes' : 'no'} · applied {applied ? 'yes' : 'no'}</span>
                  {top ? <span className="ml-2">· {top}</span> : null}
                  {err ? <div className="mt-1 text-rose-700">{err}</div> : null}
                </div>
              );
            })()}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Research (BTC-ETH)</span>
            <div className="flex gap-2 items-center">
              <Badge variant="outline">subset {rsSubset}</Badge>
              {qResearchSplit.isFetching || qResearchCapacity.isFetching || qResearchMargin.isFetching ? <Badge variant="secondary">running…</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">subset</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={rsSubset} onChange={(e) => setRsSubset(e.target.value as 'full' | 'bull' | 'bear' | 'sideways')}>
                <option value="full">full</option>
                <option value="bull">bull(2020-2021)</option>
                <option value="bear">bear(2022)</option>
                <option value="sideways">sideways(2023)</option>
              </select>
            </div>

            <div className="xl:col-span-2 border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Split (Purged)</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">limit</div>
                  <Input type="number" value={rsSplitLimit} onChange={(e) => setRsSplitLimit(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">gap_bars</div>
                  <Input type="number" value={rsGapBars} onChange={(e) => setRsGapBars(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">purge_bars</div>
                  <Input type="number" value={rsPurgeBarsEff} onChange={(e) => {
                    setRsSplitTouched(true);
                    setRsPurgeBars(Number(e.target.value));
                  }} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">embargo_bars</div>
                  <Input type="number" value={rsEmbargoBarsEff} onChange={(e) => {
                    setRsSplitTouched(true);
                    setRsEmbargoBars(Number(e.target.value));
                  }} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">window_ols</div>
                  <Input type="number" value={rsSplitWindowOlsEff} onChange={(e) => {
                    setRsSplitTouched(true);
                    setRsSplitWindowOls(Number(e.target.value));
                  }} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">window_z</div>
                  <Input type="number" value={rsSplitWindowZEff} onChange={(e) => {
                    setRsSplitTouched(true);
                    setRsSplitWindowZ(Number(e.target.value));
                  }} />
                </div>
              </div>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-600 select-none">
                <input type="checkbox" checked={rsExport} onChange={(e) => setRsExport(Boolean(e.target.checked))} />
                export csv
              </label>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => qResearchSplit.refetch()} disabled={qResearchSplit.isFetching}>Run</Button>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                {researchSplit?.ok ? (
                  <div>
                    <div>all {String(researchSplit.counts?.all ?? '-')} · train {String(researchSplit.counts?.train ?? '-')} · val {String(researchSplit.counts?.val ?? '-')} · test {String(researchSplit.counts?.test ?? '-')}</div>
                    <div className="text-slate-500">train {_fmtTs(Number(researchSplit.ranges?.train?.ts0 ?? 0)) || '-'} → {_fmtTs(Number(researchSplit.ranges?.train?.ts1 ?? 0)) || '-'}</div>
                    <div className="text-slate-500">val {_fmtTs(Number(researchSplit.ranges?.val?.ts0 ?? 0)) || '-'} → {_fmtTs(Number(researchSplit.ranges?.val?.ts1 ?? 0)) || '-'}</div>
                    <div className="text-slate-500">test {_fmtTs(Number(researchSplit.ranges?.test?.ts0 ?? 0)) || '-'} → {_fmtTs(Number(researchSplit.ranges?.test?.ts1 ?? 0)) || '-'}</div>
                    {researchSplit.exported && researchSplit.files?.dir ? <div className="text-slate-500 mt-1">exported {String(researchSplit.files.dir)}</div> : null}
                  </div>
                ) : qResearchSplit.isError ? (
                  <div className="text-rose-700">failed</div>
                ) : null}
              </div>
            </div>

            <div className="xl:col-span-3 border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Capacity</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">limit</div>
                  <Input type="number" value={rsCapacityLimit} onChange={(e) => setRsCapacityLimit(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">notionals</div>
                  <Input value={rsCapacityNotionals} onChange={(e) => setRsCapacityNotionals(String(e.target.value))} placeholder="100,300,1000" />
                </div>
              </div>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-600 select-none">
                <input type="checkbox" checked={rsCapacityApplyWfo} onChange={(e) => setRsCapacityApplyWfo(Boolean(e.target.checked))} />
                apply_wfo
              </label>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => qResearchCapacity.refetch()} disabled={qResearchCapacity.isFetching}>Run</Button>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                {researchCapacity?.ok && Array.isArray(researchCapacity.items) ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left">
                      <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                        <tr>
                          <th className="px-3 py-2">notional</th>
                          <th className="px-3 py-2">trades</th>
                          <th className="px-3 py-2">net</th>
                          <th className="px-3 py-2">sharpe</th>
                          <th className="px-3 py-2">win</th>
                          <th className="px-3 py-2">maxdd</th>
                        </tr>
                      </thead>
                      <tbody>
                        {researchCapacity.items.map((it: QuantPairBtcEthResearchCapacityItem) => {
                          const met = (it.metrics ?? null) as Record<string, unknown> | null;
                          return (
                            <tr key={String(it.notional_btc_usdc)} className="border-b last:border-0 hover:bg-slate-50/50">
                              <td className="px-3 py-2 text-gray-700">{_fmt2(Number(it.notional_btc_usdc), 2)}</td>
                              <td className="px-3 py-2 text-gray-500">{String(met?.trades ?? '-')}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.net_pnl === 'number' ? _fmt2(Number(met.net_pnl), 2) : '-'}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.net_sharpe === 'number' ? _fmt2(Number(met.net_sharpe), 3) : '-'}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.win_rate === 'number' ? _fmtPct(Number(met.win_rate), 2) : '-'}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.max_drawdown === 'number' ? _fmt2(Number(met.max_drawdown), 2) : '-'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : qResearchCapacity.isError ? (
                  <div className="text-rose-700">failed</div>
                ) : null}
              </div>
            </div>

            <div className="xl:col-span-2 border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Margin stress (MC)</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">lookback_bars</div>
                  <Input type="number" value={rsMarginLookback} onChange={(e) => setRsMarginLookback(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">paths</div>
                  <Input type="number" value={rsMarginPaths} onChange={(e) => setRsMarginPaths(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">horizon_hours</div>
                  <Input type="number" step="0.1" value={rsMarginHorizonHours} onChange={(e) => setRsMarginHorizonHours(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">leverage</div>
                  <Input type="number" step="0.1" value={rsMarginLeverage} onChange={(e) => setRsMarginLeverage(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">notional_btc_usdc</div>
                  <Input type="number" step="1" value={rsMarginNotionalBtc} onChange={(e) => setRsMarginNotionalBtc(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">conf</div>
                  <Input type="number" step="0.001" value={rsMarginConf} onChange={(e) => setRsMarginConf(Number(e.target.value))} />
                </div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">imr (0=auto)</div>
                  <Input type="number" step="0.001" value={rsMarginImr} onChange={(e) => setRsMarginImr(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">mmr (0=auto)</div>
                  <Input type="number" step="0.001" value={rsMarginMmr} onChange={(e) => setRsMarginMmr(Number(e.target.value))} />
                </div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">df_t</div>
                  <Input type="number" value={rsMarginDfT} onChange={(e) => setRsMarginDfT(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">seed</div>
                  <Input type="number" value={rsMarginSeed} onChange={(e) => setRsMarginSeed(Number(e.target.value))} />
                </div>
              </div>
              <div className="mt-2">
                <div className="text-xs text-slate-500 mb-1">vol_mult_levels</div>
                <Input value={rsMarginVolMultLevels} onChange={(e) => setRsMarginVolMultLevels(String(e.target.value))} />
              </div>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => qResearchMargin.refetch()} disabled={qResearchMargin.isFetching}>Run</Button>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                {researchMargin?.ok && Array.isArray(researchMargin.buffer_curve) ? (
                  <div>
                    <div className="text-slate-500">beta_abs {typeof researchMargin.beta_abs === 'number' ? _fmt2(Number(researchMargin.beta_abs), 4) : '-'}</div>
                    <div className="mt-1 overflow-x-auto">
                      <table className="w-full text-xs text-left">
                        <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                          <tr>
                            <th className="px-3 py-2">vol_mult</th>
                            <th className="px-3 py-2">liq_prob</th>
                            <th className="px-3 py-2">buffer_req</th>
                          </tr>
                        </thead>
                        <tbody>
                          {researchMargin.buffer_curve.map((row: NonNullable<QuantPairBtcEthResearchMarginStressResponse['buffer_curve']>[number], idx: number) => {
                            const worst = (row.worst ?? null) as Record<string, unknown> | null;
                            const res = (worst?.results ?? null) as Record<string, unknown> | null;
                            return (
                              <tr key={`${String(row.vol_mult)}_${idx}`} className="border-b last:border-0 hover:bg-slate-50/50">
                                <td className="px-3 py-2 text-gray-700">{typeof row.vol_mult === 'number' ? _fmt2(Number(row.vol_mult), 2) : '-'}</td>
                                <td className="px-3 py-2 text-gray-500">{typeof res?.liq_prob === 'number' ? _fmtPct(Number(res.liq_prob), 3) : '-'}</td>
                                <td className="px-3 py-2 text-gray-500">{typeof res?.buffer_req === 'number' ? _fmtPct(Number(res.buffer_req), 2) : '-'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : qResearchMargin.isError ? (
                  <div className="text-rose-700">failed</div>
                ) : null}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>BTC-ALTS</span>
            <Button type="button" variant="ghost" size="sm" className="h-7 px-2" onClick={() => setBtcAltsCollapsed((v) => !v)}>
              {btcAltsCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              <span className="ml-1 text-xs">{btcAltsCollapsed ? '展开' : '折叠'}</span>
            </Button>
          </CardTitle>
        </CardHeader>
      </Card>

      {btcAltsCollapsed ? null : (
        <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Research (BTC-ALT)</span>
            <div className="flex gap-2 items-center">
              <Badge variant="secondary">BTC-{String(btcAltData?.alt ?? btcAlt)}</Badge>
              <Badge variant="outline">tf {btcAltTimeframe}</Badge>
              <Badge variant="outline">subset {rsSubset}</Badge>
              {qBtcAltResearchSplit.isFetching || qBtcAltResearchCapacity.isFetching || qBtcAltResearchMargin.isFetching ? (
                <Badge variant="secondary">running…</Badge>
              ) : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">subset</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={rsSubset} onChange={(e) => setRsSubset(e.target.value as 'full' | 'bull' | 'bear' | 'sideways')}>
                <option value="full">full</option>
                <option value="bull">bull(2020-2021)</option>
                <option value="bear">bear(2022)</option>
                <option value="sideways">sideways(2023)</option>
              </select>
            </div>

            <div className="xl:col-span-2 border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Split (Purged)</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">limit</div>
                  <Input type="number" value={rsSplitLimit} onChange={(e) => setRsSplitLimit(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">gap_bars</div>
                  <Input type="number" value={rsGapBars} onChange={(e) => setRsGapBars(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">purge_bars</div>
                  <Input
                    type="number"
                    value={rsSplitTouched ? rsPurgeBars : _toNum((btcAltData as QuantPairBtcAltStatusResponse | undefined)?.params?.max_hold_bars, rsPurgeBars)}
                    onChange={(e) => {
                      setRsSplitTouched(true);
                      setRsPurgeBars(Number(e.target.value));
                    }}
                  />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">embargo_bars</div>
                  <Input
                    type="number"
                    value={rsSplitTouched ? rsEmbargoBars : _toNum((btcAltData as QuantPairBtcAltStatusResponse | undefined)?.params?.max_hold_bars, rsEmbargoBars)}
                    onChange={(e) => {
                      setRsSplitTouched(true);
                      setRsEmbargoBars(Number(e.target.value));
                    }}
                  />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">window_ols</div>
                  <Input
                    type="number"
                    value={rsSplitTouched ? rsSplitWindowOls : _toNum((btcAltData as QuantPairBtcAltStatusResponse | undefined)?.params?.window_ols, rsSplitWindowOls)}
                    onChange={(e) => {
                      setRsSplitTouched(true);
                      setRsSplitWindowOls(Number(e.target.value));
                    }}
                  />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">window_z</div>
                  <Input
                    type="number"
                    value={rsSplitTouched ? rsSplitWindowZ : _toNum((btcAltData as QuantPairBtcAltStatusResponse | undefined)?.params?.window_z, rsSplitWindowZ)}
                    onChange={(e) => {
                      setRsSplitTouched(true);
                      setRsSplitWindowZ(Number(e.target.value));
                    }}
                  />
                </div>
              </div>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-600 select-none">
                <input type="checkbox" checked={rsExport} onChange={(e) => setRsExport(Boolean(e.target.checked))} />
                export csv
              </label>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => qBtcAltResearchSplit.refetch()} disabled={qBtcAltResearchSplit.isFetching}>
                  Run
                </Button>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                {btcAltResearchSplit?.ok ? (
                  <div>
                    <div>
                      all {String(btcAltResearchSplit.counts?.all ?? '-')} · train {String(btcAltResearchSplit.counts?.train ?? '-')} · val{' '}
                      {String(btcAltResearchSplit.counts?.val ?? '-')} · test {String(btcAltResearchSplit.counts?.test ?? '-')}
                    </div>
                    <div className="text-slate-500">
                      train {_fmtTs(Number(btcAltResearchSplit.ranges?.train?.ts0 ?? 0)) || '-'} → {_fmtTs(Number(btcAltResearchSplit.ranges?.train?.ts1 ?? 0)) || '-'}
                    </div>
                    <div className="text-slate-500">
                      val {_fmtTs(Number(btcAltResearchSplit.ranges?.val?.ts0 ?? 0)) || '-'} → {_fmtTs(Number(btcAltResearchSplit.ranges?.val?.ts1 ?? 0)) || '-'}
                    </div>
                    <div className="text-slate-500">
                      test {_fmtTs(Number(btcAltResearchSplit.ranges?.test?.ts0 ?? 0)) || '-'} → {_fmtTs(Number(btcAltResearchSplit.ranges?.test?.ts1 ?? 0)) || '-'}
                    </div>
                    {btcAltResearchSplit.exported && btcAltResearchSplit.files?.dir ? <div className="text-slate-500 mt-1">exported {String(btcAltResearchSplit.files.dir)}</div> : null}
                  </div>
                ) : qBtcAltResearchSplit.isError ? (
                  <div className="text-rose-700">failed</div>
                ) : null}
              </div>
            </div>

            <div className="xl:col-span-3 border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Capacity</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">limit</div>
                  <Input type="number" value={rsCapacityLimit} onChange={(e) => setRsCapacityLimit(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">notionals</div>
                  <Input value={rsCapacityNotionals} onChange={(e) => setRsCapacityNotionals(String(e.target.value))} placeholder="100,300,1000" />
                </div>
              </div>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-600 select-none">
                <input type="checkbox" checked={rsCapacityApplyWfo} onChange={(e) => setRsCapacityApplyWfo(Boolean(e.target.checked))} />
                apply_wfo
              </label>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => qBtcAltResearchCapacity.refetch()} disabled={qBtcAltResearchCapacity.isFetching}>
                  Run
                </Button>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                {btcAltResearchCapacity?.ok && Array.isArray(btcAltResearchCapacity.items) ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left">
                      <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                        <tr>
                          <th className="px-3 py-2">notional</th>
                          <th className="px-3 py-2">trades</th>
                          <th className="px-3 py-2">net</th>
                          <th className="px-3 py-2">sharpe</th>
                          <th className="px-3 py-2">win</th>
                          <th className="px-3 py-2">maxdd</th>
                        </tr>
                      </thead>
                      <tbody>
                        {btcAltResearchCapacity.items.map((it: QuantPairBtcAltResearchCapacityItem) => {
                          const met = (it.metrics ?? null) as Record<string, unknown> | null;
                          return (
                            <tr key={String(it.notional_alt_usdc)} className="border-b last:border-0 hover:bg-slate-50/50">
                              <td className="px-3 py-2 text-gray-700">{_fmt2(Number(it.notional_alt_usdc), 2)}</td>
                              <td className="px-3 py-2 text-gray-500">{String(met?.trades ?? '-')}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.net_pnl === 'number' ? _fmt2(Number(met.net_pnl), 2) : '-'}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.net_sharpe === 'number' ? _fmt2(Number(met.net_sharpe), 3) : '-'}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.win_rate === 'number' ? _fmtPct(Number(met.win_rate), 2) : '-'}</td>
                              <td className="px-3 py-2 text-gray-500">{typeof met?.max_drawdown === 'number' ? _fmt2(Number(met.max_drawdown), 2) : '-'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : qBtcAltResearchCapacity.isError ? (
                  <div className="text-rose-700">failed</div>
                ) : null}
              </div>
            </div>

            <div className="xl:col-span-2 border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Margin stress (MC)</div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">lookback_bars</div>
                  <Input type="number" value={rsMarginLookback} onChange={(e) => setRsMarginLookback(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">paths</div>
                  <Input type="number" value={rsMarginPaths} onChange={(e) => setRsMarginPaths(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">horizon_hours</div>
                  <Input type="number" step="0.1" value={rsMarginHorizonHours} onChange={(e) => setRsMarginHorizonHours(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">leverage</div>
                  <Input type="number" step="0.1" value={rsMarginLeverage} onChange={(e) => setRsMarginLeverage(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">notional_btc_usdc</div>
                  <Input type="number" step="1" value={rsMarginNotionalBtc} onChange={(e) => setRsMarginNotionalBtc(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">conf</div>
                  <Input type="number" step="0.001" value={rsMarginConf} onChange={(e) => setRsMarginConf(Number(e.target.value))} />
                </div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">imr (0=auto)</div>
                  <Input type="number" step="0.001" value={rsMarginImr} onChange={(e) => setRsMarginImr(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">mmr (0=auto)</div>
                  <Input type="number" step="0.001" value={rsMarginMmr} onChange={(e) => setRsMarginMmr(Number(e.target.value))} />
                </div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">df_t</div>
                  <Input type="number" value={rsMarginDfT} onChange={(e) => setRsMarginDfT(Number(e.target.value))} />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">seed</div>
                  <Input type="number" value={rsMarginSeed} onChange={(e) => setRsMarginSeed(Number(e.target.value))} />
                </div>
              </div>
              <div className="mt-2">
                <div className="text-xs text-slate-500 mb-1">vol_mult_levels</div>
                <Input value={rsMarginVolMultLevels} onChange={(e) => setRsMarginVolMultLevels(String(e.target.value))} />
              </div>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => qBtcAltResearchMargin.refetch()} disabled={qBtcAltResearchMargin.isFetching}>
                  Run
                </Button>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                {btcAltResearchMargin?.ok && Array.isArray(btcAltResearchMargin.buffer_curve) ? (
                  <div>
                    <div className="text-slate-500">beta_abs {typeof btcAltResearchMargin.beta_abs === 'number' ? _fmt2(Number(btcAltResearchMargin.beta_abs), 4) : '-'}</div>
                    <div className="mt-1 overflow-x-auto">
                      <table className="w-full text-xs text-left">
                        <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                          <tr>
                            <th className="px-3 py-2">vol_mult</th>
                            <th className="px-3 py-2">liq_prob</th>
                            <th className="px-3 py-2">buffer_req</th>
                          </tr>
                        </thead>
                        <tbody>
                          {btcAltResearchMargin.buffer_curve.map((row: NonNullable<QuantPairBtcAltResearchMarginStressResponse['buffer_curve']>[number], idx: number) => {
                            const worst = (row.worst ?? null) as Record<string, unknown> | null;
                            const res = (worst?.results ?? null) as Record<string, unknown> | null;
                            return (
                              <tr key={`${String(row.vol_mult)}_${idx}`} className="border-b last:border-0 hover:bg-slate-50/50">
                                <td className="px-3 py-2 text-gray-700">{typeof row.vol_mult === 'number' ? _fmt2(Number(row.vol_mult), 2) : '-'}</td>
                                <td className="px-3 py-2 text-gray-500">{typeof res?.liq_prob === 'number' ? _fmtPct(Number(res.liq_prob), 3) : '-'}</td>
                                <td className="px-3 py-2 text-gray-500">{typeof res?.buffer_req === 'number' ? _fmtPct(Number(res.buffer_req), 2) : '-'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : qBtcAltResearchMargin.isError ? (
                  <div className="text-rose-700">failed</div>
                ) : null}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Final Recommend</span>
            <div className="flex gap-2 items-center">
              <Badge variant={trendDirW === 1 ? 'outline' : trendDirW === -1 ? 'secondary' : 'secondary'}>
                TrendDirW {trendDirW === 1 ? 'LONG' : trendDirW === -1 ? 'SHORT' : '-'}
              </Badge>
              <Badge variant={trendDirD === 1 ? 'outline' : trendDirD === -1 ? 'secondary' : 'secondary'}>
                TrendDirD {trendDirD === 1 ? 'LONG' : trendDirD === -1 ? 'SHORT' : '-'}
              </Badge>
              <Badge
                variant={chgDir1hN === 1 ? 'outline' : chgDir1hN === -1 ? 'secondary' : 'secondary'}
              >
                ChgDir1h×{std1hN} {chgDir1hN === 1 ? 'LONG' : chgDir1hN === -1 ? 'SHORT' : '-'}
              </Badge>
              <Badge variant={isAligned ? 'outline' : 'secondary'}>aligned {isAligned ? 'yes' : 'no'}</Badge>
              <Badge variant={finalDecision.action === 'open' ? 'outline' : finalDecision.action === 'wait' ? 'secondary' : 'secondary'}>
                {finalDecision.action}
              </Badge>
              <Badge variant="outline">{finalDecision.reason}</Badge>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4 text-sm">
            <div className="border rounded p-3 bg-white xl:col-span-2">
              <div className="font-semibold mb-1">Macro</div>
              <div className="text-slate-700">tier {String(macroVeto?.RiskBudgetTier ?? macroOverview?.macro_tri_layer?.risk_budget_tier ?? '-')}</div>
              <div className="text-xs text-slate-500 mt-1">
                target_net_bias {_fmt2(_toNum(macroVeto?.TargetNetBias, _toNum(macroOverview?.macro_tri_layer?.target_net_bias, Number.NaN)), 3)} · max_net_exposure {_fmt2(_toNum(macroVeto?.MaxNetExposure, _toNum(macroOverview?.macro_tri_layer?.max_net_exposure, Number.NaN)), 3)}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                allow_open {(macroVeto?.AllowOpen ?? macroOverview?.macro_tri_layer?.allow_open) ? 'yes' : 'no'} · allow_addon {(macroVeto?.AllowAddon ?? macroOverview?.macro_tri_layer?.allow_addon) ? 'yes' : 'no'} · crash {(macroVeto?.CrashSwitch ?? macroOverview?.macro_tri_layer?.crash_switch) ? 'on' : 'off'}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                ChgSpeedD {_fmt2(_toNum(macroVeto?.ChgSpeedD, _toNum(macroOverview?.macro_tri_layer?.chg_speed_d, Number.NaN)), 3)} · ChgStrength1h {_fmt2(_toNum(macroVeto?.ChgStrength, _toNum(macroOverview?.macro_tri_layer?.chg_strength, Number.NaN)), 3)}
              </div>
            </div>

            <div className="border rounded p-3 bg-white xl:col-span-3">
              <div className="font-semibold mb-1">Pool</div>
              <div className="text-slate-700">universe {universeCoins.length || 0} · candidates {Array.isArray(btcAltCandidates?.candidates) ? btcAltCandidates?.candidates?.length : 0}</div>
              <div className="text-xs text-slate-500 mt-1 break-words">{universeCoins.slice(0, 14).join(', ') || '-'}</div>
            </div>

            <div className="border rounded p-3 bg-white xl:col-span-3">
              <div className="font-semibold mb-1">Top alt</div>
              <div className="text-slate-700">{topAlt?.alt ? `BTC-${topAlt.alt}` : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">
                z {_fmt2(_toNum(topAlt?.z, Number.NaN), 3)} · corr {_fmt2(_toNum(topAlt?.corr, Number.NaN), 3)} · beta {_fmt2(_toNum(topAlt?.beta, Number.NaN), 3)} · cluster {String(topAlt?.clusterId ?? '-')}
              </div>
              <div className="text-xs text-slate-500 mt-1">side {finalSide} · entry_z {_fmt2(_toNum(finalDecision.entryZ, Number.NaN), 2)} · exit_z {_fmt2(_toNum(finalDecision.exitZ, Number.NaN), 2)}</div>
              <div className="text-xs text-slate-500 mt-1">exit_rules max_hold_bars {String(Math.trunc(_toNum(btcAltParamsAny?.max_hold_bars, Number.NaN)) || '-')} · stop_z {_fmt2(_toNum(btcAltParamsAny?.stop_z, Number.NaN), 2)}</div>
              <div className="text-xs text-slate-500 mt-1">
                hardgate corr_min {_fmt2(_toNum(hardGate.corrMin, Number.NaN), 3)} · beta_max {_fmt2(_toNum(hardGate.betaMax, Number.NaN), 3)} · beta_std_max {_fmt2(_toNum(hardGate.betaStdMax, Number.NaN), 3)} · per_cluster {perClusterLimit === null ? '-' : String(perClusterLimit)}
              </div>
            </div>
          </div>

          <div className="mt-4 border rounded bg-white overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-500 uppercase bg-gray-50/50">
                <tr>
                  <th className="px-4 py-2">std1h ts</th>
                  <th className="px-4 py-2">dir</th>
                  <th className="px-4 py-2">risk</th>
                  <th className="px-4 py-2">value</th>
                </tr>
              </thead>
              <tbody>
                {macro1hSeq.length ? (
                  macro1hSeq
                    .slice()
                    .reverse()
                    .map((p) => (
                      <tr key={String(p.ts)} className="border-b last:border-0">
                        <td className="px-4 py-2 text-gray-500">{_fmtTs(p.ts) || '-'}</td>
                        <td className="px-4 py-2 text-gray-900">{p.dir === 1 ? 'LONG' : p.dir === -1 ? 'SHORT' : '-'}</td>
                        <td className="px-4 py-2 text-gray-500">{_fmtPct(_toNum(p.risk, Number.NaN), 1)}</td>
                        <td className="px-4 py-2 text-gray-500">{_fmtPct(_toNum(p.value, Number.NaN), 1)}</td>
                      </tr>
                    ))
                ) : (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-gray-500">
                      std1h buffer empty
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>BTC-ALTS Pairs</span>
            <div className="flex gap-2 items-center">
              <Badge variant="secondary">BTC-{String(btcAltData?.alt ?? btcAlt)}</Badge>
              <Badge variant={btcAltAction === 'pause' || btcAltAction === 'stop' ? 'destructive' : 'outline'}>{btcAltAction}</Badge>
              {btcAltReason && btcAltReason !== 'null' && btcAltReason !== 'undefined' ? <Badge variant="outline">{btcAltReason}</Badge> : null}
              {autoBtcaltsOk && autoBtcaltsAction ? <Badge variant={autoBtcaltsAction === 'open' ? 'destructive' : 'outline'}>auto {autoBtcaltsAction}</Badge> : null}
              {autoBtcaltsOk && autoBtcaltsBlocked ? <Badge variant="secondary">{autoBtcaltsBlocked}</Badge> : null}
              {autoBtcaltsOk && autoBtcaltsTs > 0 ? <Badge variant="secondary">auto {_fmtTs(autoBtcaltsTs).slice(11)}</Badge> : null}
              {btcAltGateEnabled ? (
                <Badge variant={btcAltGateBlocked ? 'destructive' : btcAltGatePass ? 'outline' : 'secondary'}>
                  gate {btcAltGateBlocked ? 'blocked' : btcAltGatePass ? 'pass' : 'fail'}
                </Badge>
              ) : null}
              {btcAltCojumpEnabled ? <Badge variant={btcAltCojumpBlocked ? 'destructive' : 'outline'}>cojump {btcAltCojumpBlocked ? 'blocked' : 'ok'}</Badge> : null}
              {btcAltCorrGateEnabled ? <Badge variant={btcAltCorrGateBlocked ? 'destructive' : 'outline'}>corr {btcAltCorrGateBlocked ? 'blocked' : 'ok'}</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {btcAltInitialCfg ? (
            <div className="mb-6 border rounded bg-white p-3">
              <div className="font-semibold">Params (BTC-ALT)</div>
              <BtcAltConfigPanel
                initial={btcAltInitialCfg}
                onSave={(cfg) => {
                  setBtcAltTimeframe(String(cfg.timeframe || btcAltTimeframe));
                  btcAltUpdateMutation.mutate({ ...cfg });
                }}
                saving={btcAltUpdateMutation.isPending}
                saveState={btcAltSaveState}
              />
            </div>
          ) : null}

          {autoBtcaltsOk ? (
            <div className="mb-6 border rounded bg-white p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold">Auto Rebalance (Net BTC)</div>
                <div className="flex gap-2 items-center flex-wrap">
                  <Badge variant={autoBtcaltsRbEnabled ? 'outline' : 'secondary'}>enabled {autoBtcaltsRbEnabled ? 'on' : 'off'}</Badge>
                  <Badge variant={autoBtcaltsRbNeeded ? 'destructive' : 'secondary'}>{autoBtcaltsRbNeeded ? 'need' : 'no'}</Badge>
                  {autoBtcaltsRbSkip ? <Badge variant="secondary">skip {autoBtcaltsRbSkip}</Badge> : null}
                  {autoBtcaltsRbExec ? <Badge variant={autoBtcaltsRbExecOk ? 'outline' : 'destructive'}>exec {autoBtcaltsRbExecOk ? 'ok' : 'fail'}</Badge> : null}
                </div>
              </div>

              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 text-sm">
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">Suggested</div>
                  <div className="text-slate-800">{Number.isFinite(autoBtcaltsRbDeltaAbs) ? `${autoBtcaltsRbDeltaSide}  $${_fmt2(autoBtcaltsRbDeltaAbs, 2)}` : '-'}</div>
                  <div className="text-xs text-slate-500 mt-1">delta_btc_leg_usdc</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">Policy</div>
                  <div className="text-slate-800">min {Number.isFinite(autoBtcaltsRbMinNotional) ? `$${_fmt2(autoBtcaltsRbMinNotional, 2)}` : '-'}</div>
                  <div className="text-slate-800">cd {Number.isFinite(autoBtcaltsRbCooldownSec) ? `${_fmt2(autoBtcaltsRbCooldownSec, 0)}s` : '-'}</div>
                  <div className="text-slate-800">max {Number.isFinite(autoBtcaltsRbMaxNotional) && autoBtcaltsRbMaxNotional > 0 ? `$${_fmt2(autoBtcaltsRbMaxNotional, 2)}` : '-'}</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">Combo State</div>
                  <div className="text-slate-800">net_leg ${_fmt2(_toNum((autoBtcaltsRbComboState as { net_btc_leg_usdc?: unknown } | null)?.net_btc_leg_usdc, Number.NaN), 2)}</div>
                  <div className="text-slate-800">net_frac {_fmtPct(_toNum((autoBtcaltsRbComboState as { net_btc_exposure_frac?: unknown } | null)?.net_btc_exposure_frac, Number.NaN), 2)}</div>
                  <div className="text-slate-800">open_pairs {_toNum((autoBtcaltsRbComboState as { open_pairs?: unknown } | null)?.open_pairs, 0)}</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">Execution Receipt</div>
                  <div className="text-slate-800">{autoBtcaltsRbExec ? (Number.isFinite(autoBtcaltsRbExecNotional) ? `$${_fmt2(autoBtcaltsRbExecNotional, 2)}` : 'sent') : '-'}</div>
                  {autoBtcaltsRbExecOrderId ? <div className="text-xs text-slate-500 mt-1 break-all">order {autoBtcaltsRbExecOrderId}</div> : null}
                  {autoBtcaltsRbExecErr ? <div className="text-xs text-rose-700 mt-1 break-words">{autoBtcaltsRbExecErr}</div> : null}
                </div>
              </div>

              <details className="mt-3">
                <summary className="text-xs text-slate-600 cursor-pointer select-none">raw rebalance payload</summary>
                <pre className="mt-2 text-xs bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(autoBtcaltsRebalance ?? null, null, 2)}</pre>
              </details>
            </div>
          ) : null}

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">Alt</div>
              <Input
                value={btcAlt}
                onChange={(e) => setBtcAlt(String(e.target.value || '').trim().toUpperCase())}
                onBlur={(e) => setBtcAlt(String(e.target.value || '').trim().toUpperCase() || 'ETH')}
              />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Timeframe</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={btcAltTimeframe} onChange={(e) => setBtcAltTimeframe(e.target.value)}>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>
            <div className="flex items-end gap-2">
              <Button
                variant="secondary"
                onClick={() =>
                  recommendMutation.mutate({
                    timeframe: btcAltTimeframe,
                    limit: btcAltBtLimit,
                    notional_usdc: btcAltBtNotional,
                    apply_cost: btcAltBtApplyCost === 'on',
                    max_alts: btcAltPfMaxAlts,
                  })
                }
                disabled={recommendMutation.isPending}
              >
                Recommend
              </Button>
              {recommendMutation.isPending ? <Badge variant="secondary">running…</Badge> : null}
            </div>
          </div>

          {btcAltRecommend?.ok && (btcAltRecommend.best || (btcAltRecommend.ranked && btcAltRecommend.ranked.length > 0)) ? (
            <div className="mt-3 text-xs text-slate-600">
              {btcAltRecommend.best ? <div>best {String(btcAltRecommend.best)}{btcAltRecommend.cached ? ' (cached)' : ''}</div> : null}
              {btcAltRecommend.ranked && btcAltRecommend.ranked.length > 0 ? <div className="break-words">ranked {btcAltRecommend.ranked.join(', ')}</div> : null}
            </div>
          ) : recommendMutation.data && !btcAltRecommend?.ok ? (
            <div className="mt-3 text-xs text-rose-700">recommend failed: {String(btcAltRecommend?.error || 'unknown')}</div>
          ) : null}

          {btcAltData?.ok === false ? (
            <div className="mt-3 text-xs text-amber-700">status: {String(btcAltData.error || 'no_data')}</div>
          ) : null}

          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4 text-sm">
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Time</div>
              <div className="text-slate-700">{btcAltLatestTs > 0 ? _fmtTs(btcAltLatestTs) : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">timeframe {String(btcAltData?.timeframe ?? btcAltTimeframe)}</div>
              {btcAltStaleness.isStale ? <div className="text-xs text-amber-700 mt-1">{btcAltStaleness.text}</div> : null}
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Spread</div>
              <div className="text-slate-700">{_fmt2(btcAltLatestSpread, 6)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Z</div>
              <div className="text-slate-700">{_fmt2(btcAltLatestZ, 3)}</div>
              <div className="text-xs text-slate-500 mt-1">entry {_fmt2(btcAltEntryZEff, 2)} · exit {_fmt2(btcAltExitZEff, 2)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Beta</div>
              <div className="text-slate-700">{_fmt2(btcAltLatestBeta, 4)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Corr</div>
              <div className="text-slate-700">{_fmt2(btcAltLatestCorr, 4)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Regime</div>
              <div className="text-slate-700">{btcAltRegimeMode || '-'}</div>
              <div className="text-xs text-slate-500 mt-1">p {_fmt2(btcAltRegimeProb, 3)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">RS</div>
              <div className="text-slate-700">{_fmt2(btcAltRsScore, 3)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Cost</div>
              <div className="text-slate-700">{btcAltCostOk ? _fmtPct(btcAltCostTotal, 3) : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">{btcAltCostOk ? `${btcAltCostMode} · fee ${_fmtPct(btcAltCostFee, 3)} · slip ${_fmtPct(btcAltCostSlip, 3)}` : ''}</div>
              {Number.isFinite(btcAltCostNotional) ? <div className="text-xs text-slate-500">notional ${_fmt2(btcAltCostNotional, 2)}</div> : null}
            </div>
          </div>

          {qBtcAlt.isLoading ? <div className="mt-4 text-sm text-slate-500">Loading…</div> : qBtcAlt.isError ? <div className="mt-4 text-sm text-red-600">Failed to load.</div> : null}
          {btcAltGateEnabled && btcAltGateBlocked && btcAltGateBlockedReason ? (
            <div className="mt-3 text-xs text-amber-700">gate blocked: {btcAltGateBlockedReason}</div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Execution (BTC-ALTS)</span>
            <div className="flex gap-2 items-center">
              <Badge variant="secondary">BTC-{String(btcAltData?.alt ?? btcAlt)}</Badge>
              <Badge variant={execMode === 'execute' ? 'destructive' : 'outline'}>{execMode}</Badge>
              {openBtcAltMutation.isPending || closeBtcAltMutation.isPending ? <Badge variant="secondary">working…</Badge> : null}
            </div>
          </CardTitle>
          <CardDescription>
            策略模式（全局）：
            <span className="ml-1 font-medium">{quantBtcAltStrategyMode}</span>
            <span className="ml-2 text-[11px] text-slate-500">A-趋势跟随 · B-强弱跟随 · C-均值回归</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">Venue</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={execVenue} disabled>
                <option value="aster">aster</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Mode</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={execMode} onChange={(e) => setExecModeOverride(e.target.value as 'dry-run' | 'execute')}>
                <option value="dry-run">dry-run</option>
                <option value="execute">execute</option>
              </select>
            </div>
            <div className="xl:col-span-2">
              <div className="text-xs text-slate-500 mb-1">execute_token</div>
              <Input
                type="password"
                value={executeToken}
                onChange={(e) => {
                  const v = String(e.target.value || '');
                  setExecuteToken(v);
                }}
                placeholder="WEBHOOK_EXECUTE_TOKEN"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={confirmExecute}
                  onChange={(e) => setConfirmExecute(Boolean(e.target.checked))}
                  disabled={execMode !== 'execute'}
                />
                confirm_execute
              </label>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Direction</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={execBtcAltDirection}
                onChange={(e) => setExecBtcAltDirection(e.target.value as 'long_alt_short_btc' | 'short_alt_long_btc')}
              >
                <option value="long_alt_short_btc">long ALT / short BTC</option>
                <option value="short_alt_long_btc">short ALT / long BTC</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Notional (ALT leg, USDC)</div>
              <Input type="number" value={execBtcAltNotional} onChange={(e) => setExecBtcAltNotional(Number(e.target.value))} />
            </div>
            <div className="flex items-end gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  if (btcAltAction === 'long_alt_short_btc' || btcAltAction === 'short_alt_long_btc') {
                    setExecBtcAltDirection(btcAltAction as 'long_alt_short_btc' | 'short_alt_long_btc');
                  }
                }}
                disabled={openBtcAltMutation.isPending || closeBtcAltMutation.isPending}
              >
                Use action
              </Button>
              <Button
                onClick={() =>
                  openBtcAltMutation.mutate({
                    venue: execVenue,
                    alt: btcAlt,
                    direction: execBtcAltDirection,
                    notional_usdc: execBtcAltNotional,
                    execute: execMode === 'execute',
                    confirm_execute: confirmExecute,
                      idempotency_key:
                        execMode === 'execute'
                          ? idemKey('btcalt_open', {
                              venue: execVenue,
                              alt: btcAlt,
                              direction: execBtcAltDirection,
                              notional_usdc: execBtcAltNotional,
                              timeframe: btcAltTimeframe,
                              strategy_mode: quantBtcAltStrategyMode,
                            })
                          : undefined,
                    maker: execMakerMode,
                    tag: 'quant_pairs_btcalt',
                    strategy_id: 'quant_pairs_btcalt',
                    timeframe: btcAltTimeframe,
                    strategy_mode: quantBtcAltStrategyMode,
                  })
                }
                disabled={openBtcAltMutation.isPending || closeBtcAltMutation.isPending || (execMode === 'execute' && !liveReady)}
              >
                Open
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  closeBtcAltMutation.mutate({
                    venue: execVenue,
                    alt: btcAlt,
                    execute: execMode === 'execute',
                    confirm_execute: confirmExecute,
                      idempotency_key:
                        execMode === 'execute' ? idemKey('btcalt_close', { venue: execVenue, alt: btcAlt }) : undefined,
                    tag: 'quant_pairs_btcalt_close',
                  })
                }
                disabled={openBtcAltMutation.isPending || closeBtcAltMutation.isPending || (execMode === 'execute' && !liveReady)}
              >
                Close
              </Button>
            </div>
          </div>

          {execMode === 'execute' && !liveReady ? (
            <div className="mt-3 text-xs text-amber-700">
              {!tokenOk || !confirmExecute ? <div>execute requires token + confirm_execute</div> : null}
              {venueMatchesPreflight && !preflightReady && preflightBlockers.length ? (
                <div>preflight blocked: {preflightBlockers.join(', ')}</div>
              ) : null}
            </div>
          ) : null}

          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Open result</div>
              <pre className="whitespace-pre-wrap break-words text-slate-700">{openBtcAltMutation.data ? JSON.stringify(openBtcAltMutation.data, null, 2) : ''}</pre>
              {openBtcAltMutation.isError ? <div className="text-rose-700">open failed</div> : null}
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Close result</div>
              <pre className="whitespace-pre-wrap break-words text-slate-700">{closeBtcAltMutation.data ? JSON.stringify(closeBtcAltMutation.data, null, 2) : ''}</pre>
              {closeBtcAltMutation.isError ? <div className="text-rose-700">close failed</div> : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Position (BTC-{String(btcAltData?.alt ?? btcAlt)})</span>
            <div className="flex gap-2 items-center">
              <Badge variant={btcAltPosAny ? (btcAltPosPairOk ? 'outline' : 'destructive') : 'secondary'}>
                {btcAltPosAny ? (btcAltPosPairOk ? 'in position' : 'one-leg') : 'flat'}
              </Badge>
              {btcAltPnlOk ? <Badge variant={Number.isFinite(btcAltPnlNet) && btcAltPnlNet < 0 ? 'destructive' : 'outline'}>net {_fmt2(btcAltPnlNet, 2)}</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4 text-sm">
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Entry time</div>
              <div className="text-slate-700">{btcAltPosEntryTs > 0 ? _fmtTs(btcAltPosEntryTs) : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">hold bars {Number.isFinite(btcAltPosHoldBars) ? String(Math.trunc(btcAltPosHoldBars)) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Gross PnL</div>
              <div className="text-slate-700">{btcAltPnlOk ? _fmt2(btcAltPnlGross, 2) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Funding</div>
              <div className="text-slate-700">{btcAltPnlOk ? _fmt2(btcAltPnlFunding, 2) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">Cost (est)</div>
              <div className="text-slate-700">{btcAltPnlOk ? _fmt2(btcAltPnlCost, 2) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">BTC leg</div>
              <div className="text-slate-700">{btcAltPosLegBtc ? `${String(btcAltPosLegBtc.side ?? '-')}` : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">notional {_fmt2(_toNum(btcAltPosLegBtc?.notional_usdc, Number.NaN), 2)}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="font-semibold mb-1">ALT leg</div>
              <div className="text-slate-700">{btcAltPosLegAlt ? `${String(btcAltPosLegAlt.side ?? '-')}` : '-'}</div>
              <div className="text-xs text-slate-500 mt-1">notional {_fmt2(_toNum(btcAltPosLegAlt?.notional_usdc, Number.NaN), 2)}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Backtest (BTC-{String(btcAltData?.alt ?? btcAlt)})</span>
            <div className="flex gap-2 items-center">
              <Button onClick={() => qBtcAltBacktest.refetch()} disabled={qBtcAltBacktest.isFetching}>Run</Button>
              <Button variant="secondary" onClick={() => downloadBtcAltBacktestCsv('trades_csv')}>Trades CSV</Button>
              <Button variant="secondary" onClick={() => downloadBtcAltBacktestCsv('equity_csv')}>Equity CSV</Button>
              {qBtcAltBacktest.isFetching ? <Badge variant="secondary">running…</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">timeframe</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={btcAltTimeframe} onChange={(e) => setBtcAltTimeframe(e.target.value)}>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">limit</div>
              <Input type="number" value={btcAltBtLimit} onChange={(e) => setBtcAltBtLimit(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">notional_usdc</div>
              <Input type="number" value={btcAltBtNotional} onChange={(e) => setBtcAltBtNotional(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">apply_cost</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={btcAltBtApplyCost} onChange={(e) => setBtcAltBtApplyCost(e.target.value as 'on' | 'off')}>
                <option value="on">on</option>
                <option value="off">off</option>
              </select>
            </div>
            <div className="xl:col-span-2 border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">metrics</div>
              <div className="text-sm text-slate-700">
                {btcAltBacktest?.sim?.metrics
                  ? `trades ${String(btcAltBacktest.sim.metrics.trades)} · net ${_fmt2(btcAltBacktest.sim.metrics.net_pnl, 2)} · sharpe ${_fmt2(btcAltBacktest.sim.metrics.net_sharpe, 3)} · win ${_fmtPct(btcAltBacktest.sim.metrics.win_rate, 2)} · maxdd ${_fmt2(btcAltBacktest.sim.metrics.max_drawdown, 2)}`
                  : btcAltBacktest?.error
                    ? String(btcAltBacktest.error)
                    : btcAltBacktest?.sim?.error
                      ? String(btcAltBacktest.sim.error)
                      : ''}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {Number.isFinite(btAltFundingBtc) || Number.isFinite(btAltFundingAlt)
                  ? `funding(8h mean) BTC ${Number.isFinite(btAltFundingBtc) ? _fmtPct(btAltFundingBtc, 4) : '-'} · ALT ${Number.isFinite(btAltFundingAlt) ? _fmtPct(btAltFundingAlt, 4) : '-'}`
                  : ''}
              </div>
            </div>
          </div>

          {Array.isArray(btcAltScaleCurve) && btcAltScaleCurve.length >= 3 ? (
            <div className="mt-4 border rounded p-3 bg-white text-xs">
              <div className="font-semibold mb-1">capacity (scale_curve)</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                    <tr>
                      <th className="px-3 py-2">notional</th>
                      <th className="px-3 py-2">trades</th>
                      <th className="px-3 py-2">net</th>
                      <th className="px-3 py-2">sharpe</th>
                      <th className="px-3 py-2">maxdd</th>
                    </tr>
                  </thead>
                  <tbody>
                    {btcAltScaleCurve
                      .slice()
                      .sort((a, b) => Number(a.gross_notional_usdc) - Number(b.gross_notional_usdc))
                      .map((r) => {
                        const m = r.metrics ?? null;
                        return (
                          <tr key={String(r.gross_notional_usdc)} className="border-b last:border-0 hover:bg-slate-50/50">
                            <td className="px-3 py-2 text-gray-700">{_fmt2(Number(r.gross_notional_usdc), 2)}</td>
                            <td className="px-3 py-2 text-gray-500">{m ? String(m.trades) : '-'}</td>
                            <td className={m && Number(m.net_pnl) >= 0 ? 'px-3 py-2 text-emerald-700 font-semibold' : 'px-3 py-2 text-rose-700 font-semibold'}>
                              {m ? _fmt2(Number(m.net_pnl), 2) : '-'}
                            </td>
                            <td className="px-3 py-2 text-gray-500">{m ? _fmt2(Number(m.net_sharpe), 3) : '-'}</td>
                            <td className="px-3 py-2 text-gray-500">{m ? _fmt2(Number(m.max_drawdown), 2) : '-'}</td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="mt-4">
            {Array.isArray(btcAltBacktest?.sim?.equity_curve) && btcAltBacktest!.sim!.equity_curve!.length > 1 ? (
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={btcAltBacktest!.sim!.equity_curve} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="t" tickFormatter={(v) => _fmtTs(Number(v)).slice(5, 16)} minTickGap={24} />
                    <YAxis domain={['auto', 'auto']} />
                    <Tooltip labelFormatter={(v) => _fmtTs(Number(v))} formatter={(val) => [_fmt2(Number(val), 2), 'cum']} />
                    <Line type="monotone" dataKey="cum" stroke="#0f766e" dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : null}
          </div>

          <div className="mt-4 border rounded p-3 bg-white text-xs">
            <div className="font-semibold mb-1">trades (latest 30)</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                  <tr>
                    <th className="px-3 py-2">t0</th>
                    <th className="px-3 py-2">t1</th>
                    <th className="px-3 py-2">dir</th>
                    <th className="px-3 py-2">hold</th>
                    <th className="px-3 py-2">pnl</th>
                    <th className="px-3 py-2">reason</th>
                  </tr>
                </thead>
                <tbody>
                  {Array.isArray(btcAltBacktest?.sim?.trades) && btcAltBacktest!.sim!.trades!.length > 0 ? (
                    btcAltBacktest!.sim!.trades!
                      .slice(-30)
                      .reverse()
                      .map((t, idx) => (
                        <tr key={`${String(t.t0)}_${idx}`} className="border-b last:border-0 hover:bg-slate-50/50">
                          <td className="px-3 py-2 text-gray-500">{_fmtTs(Number(t.t0)).slice(5, 16)}</td>
                          <td className="px-3 py-2 text-gray-500">{_fmtTs(Number(t.t1)).slice(5, 16)}</td>
                          <td className="px-3 py-2 text-gray-700">{String(t.dir)}</td>
                          <td className="px-3 py-2 text-gray-500">{String(t.hold_bars)}</td>
                          <td className={Number(t.pnl_net) >= 0 ? 'px-3 py-2 text-emerald-700 font-semibold' : 'px-3 py-2 text-rose-700 font-semibold'}>
                            {_fmt2(Number(t.pnl_net), 2)}
                          </td>
                          <td className="px-3 py-2 text-gray-500">{String(t.reason)}</td>
                        </tr>
                      ))
                  ) : (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-center text-gray-500">
                        No trades.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Portfolio Sim (BTC-ALTS)</span>
            <div className="flex gap-2 items-center">
              <Button onClick={() => qBtcAltPortfolio.refetch()} disabled={qBtcAltPortfolio.isFetching}>Run</Button>
              {qBtcAltPortfolio.isFetching ? <Badge variant="secondary">running…</Badge> : null}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-8 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">timeframe</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={btcAltTimeframe} onChange={(e) => setBtcAltTimeframe(e.target.value)}>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">limit</div>
              <Input type="number" value={btcAltPfLimit} onChange={(e) => setBtcAltPfLimit(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">gross_notional_usdc</div>
              <Input type="number" value={btcAltPfNotional} onChange={(e) => setBtcAltPfNotional(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">apply_cost</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={btcAltPfApplyCost} onChange={(e) => setBtcAltPfApplyCost(e.target.value as 'on' | 'off')}>
                <option value="on">on</option>
                <option value="off">off</option>
              </select>
            </div>
            <div className="xl:col-span-2">
              <div className="text-xs text-slate-500 mb-1">alts (csv, empty=auto)</div>
              <Input value={btcAltPfAlts} onChange={(e) => setBtcAltPfAlts(e.target.value)} placeholder="ETH,SOL" />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">max_alts</div>
              <Input type="number" value={btcAltPfMaxAlts} onChange={(e) => setBtcAltPfMaxAlts(Number(e.target.value))} />
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">notional_grid (csv)</div>
              <Input value={btcAltPfNotionalGrid} onChange={(e) => setBtcAltPfNotionalGrid(e.target.value)} placeholder="200,400,800" />
            </div>
          </div>

          <div className="mt-4 border rounded p-3 bg-white">
            <div className="text-xs text-slate-500">metrics</div>
            <div className="text-sm text-slate-700">
              {btcAltPortfolio?.sim?.metrics
                ? `trades ${String(btcAltPortfolio.sim.metrics.trades)} · equity_end ${_fmt2(btcAltPortfolio.sim.metrics.equity_end, 2)} · realized ${_fmt2(btcAltPortfolio.sim.metrics.realized_pnl, 2)} · sharpe ${_fmt2(btcAltPortfolio.sim.metrics.sharpe_bar, 3)} · maxdd ${_fmt2(btcAltPortfolio.sim.metrics.max_drawdown_usdc, 2)} (${_fmtPct(btcAltPortfolio.sim.metrics.max_drawdown_frac, 2)})`
                : btcAltPortfolio?.error
                  ? String(btcAltPortfolio.error)
                  : btcAltPortfolio?.sim?.error
                    ? String(btcAltPortfolio.sim.error)
                    : ''}
            </div>
          </div>

          <div className="mt-4">
            {Array.isArray(btcAltPortfolio?.sim?.equity_curve) && btcAltPortfolio!.sim!.equity_curve!.length > 1 ? (
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={btcAltPortfolio!.sim!.equity_curve} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="t" tickFormatter={(v) => _fmtTs(Number(v)).slice(5, 16)} minTickGap={24} />
                    <YAxis domain={['auto', 'auto']} />
                    <Tooltip labelFormatter={(v) => _fmtTs(Number(v))} formatter={(val) => [_fmt2(Number(val), 2), 'equity']} />
                    <Line type="monotone" dataKey="equity" stroke="#0f766e" dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : null}
          </div>

          <div className="mt-4 border rounded p-3 bg-white text-xs">
            <div className="font-semibold mb-1">trades (latest 30)</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                  <tr>
                    <th className="px-3 py-2">t0</th>
                    <th className="px-3 py-2">t1</th>
                    <th className="px-3 py-2">coin</th>
                    <th className="px-3 py-2">mode</th>
                    <th className="px-3 py-2">dir</th>
                    <th className="px-3 py-2">hold</th>
                    <th className="px-3 py-2">pnl</th>
                    <th className="px-3 py-2">reason</th>
                  </tr>
                </thead>
                <tbody>
                  {Array.isArray(btcAltPortfolio?.sim?.trades) && btcAltPortfolio!.sim!.trades!.length > 0 ? (
                    btcAltPortfolio!.sim!.trades!
                      .slice(-30)
                      .reverse()
                      .map((t, idx) => (
                        <tr key={`${String(t.t0)}_${idx}`} className="border-b last:border-0 hover:bg-slate-50/50">
                          <td className="px-3 py-2 text-gray-500">{_fmtTs(Number(t.t0)).slice(5, 16)}</td>
                          <td className="px-3 py-2 text-gray-500">{_fmtTs(Number(t.t1)).slice(5, 16)}</td>
                          <td className="px-3 py-2 text-gray-700">{String(t.coin)}</td>
                          <td className="px-3 py-2 text-gray-500">{String(t.mode)}</td>
                          <td className="px-3 py-2 text-gray-500">{String(t.dir)}</td>
                          <td className="px-3 py-2 text-gray-500">{String(t.hold_bars)}</td>
                          <td className={Number(t.pnl_net) >= 0 ? 'px-3 py-2 text-emerald-700 font-semibold' : 'px-3 py-2 text-rose-700 font-semibold'}>
                            {_fmt2(Number(t.pnl_net), 2)}
                          </td>
                          <td className="px-3 py-2 text-gray-500">{String(t.reason)}</td>
                        </tr>
                      ))
                  ) : (
                    <tr>
                      <td colSpan={8} className="px-3 py-6 text-center text-gray-500">
                        No trades.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>BTC-ALT Pair Trading (Spread / Z)</CardTitle>
        </CardHeader>
        <CardContent>
          {qBtcAlt.isLoading ? (
            <div className="text-sm text-slate-500">Loading…</div>
          ) : qBtcAlt.isError ? (
            <div className="text-sm text-red-600">Failed to load.</div>
          ) : btcAltData?.ok === false ? (
            <div className="text-sm text-amber-700">{String(btcAltData.error || 'no_data')}</div>
          ) : (
            <div className="h-[360px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={btcAltChartData} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ts" tickFormatter={(v) => _fmtTs(Number(v)).slice(11)} minTickGap={24} />
                  <YAxis yAxisId="left" domain={['auto', 'auto']} />
                  <YAxis yAxisId="right" orientation="right" domain={['auto', 'auto']} />
                  <Tooltip
                    labelFormatter={(v) => _fmtTs(Number(v))}
                    formatter={(val, name) => {
                      const x = Number(val);
                      if (!Number.isFinite(x)) return ['-', String(name)];
                      if (name === 'spread') return [_fmt2(x, 6), 'spread'];
                      if (name === 'z') return [_fmt2(x, 3), 'z'];
                      return [_fmt2(x, 6), String(name)];
                    }}
                  />
                  <Line yAxisId="left" type="monotone" dataKey="spread" stroke="#2563eb" dot={false} isAnimationActive={false} />
                  <Line yAxisId="right" type="monotone" dataKey="z" stroke="#16a34a" dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
        </>
      )}

      <SignalsTable abOwner="quant" title="Quant Signals" />
        </div>
      </TabsContent>
    </Tabs>
  );
};
