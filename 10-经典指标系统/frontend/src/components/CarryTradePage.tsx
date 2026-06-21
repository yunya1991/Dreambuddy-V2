import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import {
  fetchCarryAcceptance,
  fetchCarryCandidates,
  fetchCarryOrdersRecent,
  fetchCarryStatus,
  fetchCarryUniverse,
  fetchConfig,
  fetchFundingRates,
  fetchFundingSchedule,
  hyperliquidPing,
  updateCarryConfig,
  type CarryAcceptanceResponse,
  type CarryCandidatesResponse,
  type CarryStatusResponse,
  type CarryUniverseResponse,
  type Config,
  type FundingRatesResponse,
  type FundingScheduleResponse,
  type HyperliquidPingResponse,
} from '../lib/api';
import { filterOrdersForUi } from '../lib/ordersUi';
import { useOrdersUiPrefs } from '../lib/ordersUiPrefs';

function _toNum(v: unknown, d = 0): number {
  if (v === null || v === undefined) return d;
  if (typeof v === 'string' && v.trim() === '') return d;
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

function _fmtPct(x: number, digits = 2): string {
  if (!Number.isFinite(x)) return '-';
  return `${(x * 100).toFixed(digits)}%`;
}

function _fmtBps(x: number, digits = 1): string {
  if (!Number.isFinite(x)) return '-';
  return `${x.toFixed(digits)}bps`;
}

function _fmtTs(ms: number): string {
  const t = Number(ms);
  if (!Number.isFinite(t) || t <= 0) return '-';
  const d = new Date(t);
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(d);
  const m: Record<string, string> = {};
  for (const p of parts) m[p.type] = p.value;
  return `${m.year}-${m.month}-${m.day} ${m.hour}:${m.minute}:${m.second}`;
}

function _maskAddr(addr: unknown): string {
  const s = String(addr ?? '').trim();
  if (!s) return '-';
  if (s.length <= 12) return s;
  return `${s.slice(0, 6)}…${s.slice(-4)}`;
}

function _fmtPx(x: unknown): string {
  const v = Number(x);
  if (!Number.isFinite(v) || v <= 0) return '-';
  if (v >= 1000) return v.toFixed(2);
  if (v >= 1) return v.toFixed(4);
  return v.toFixed(6);
}

function _fmtUsd(x: unknown, digits = 2): string {
  const v = Number(x);
  if (!Number.isFinite(v)) return '-';
  const s = v.toFixed(digits);
  return v >= 0 ? `$${s}` : `-$${Math.abs(v).toFixed(digits)}`;
}

function _readBool(obj: unknown, key: string): boolean | null {
  if (!obj || typeof obj !== 'object') return null;
  const v = (obj as Record<string, unknown>)[key];
  return typeof v === 'boolean' ? v : null;
}

type CarryDraft = {
  carry_trade_enabled: boolean;
  carry_trade_live_enabled: boolean | null;
  carry_trade_hl_trading_enabled: boolean | null;
  carry_trade_mode: string;
  carry_trade_profile: string;
  carry_trade_venue: string;
  carry_trade_pre_funding_window_min: number;
  carry_trade_no_exit_pre_funding_min: number;
  carry_trade_post_funding_grace_min: number;
  carry_trade_post_funding_trailing_enabled: boolean;
  carry_trade_post_funding_trailing_max_hold_min: number;
  carry_trade_post_funding_trailing_arm_min_r: number;
  carry_trade_post_funding_trailing_dist_r: number;
  carry_trade_post_funding_require_basis_reversion: boolean;
  carry_trade_post_funding_basis_reversion_mult: number;
  carry_trade_min_abs_funding: number;
  carry_trade_cost_buffer_bps: number;
  carry_trade_cost_buffer_adaptive_enabled: boolean;
  carry_trade_cost_buffer_p95_mult: number;
  carry_trade_cost_buffer_p95_lookback_hours: number;
  carry_trade_cost_buffer_p95_lookback_n: number;
  carry_trade_cost_buffer_p95_min_samples: number;
  carry_trade_cost_buffer_min_bps: number;
  carry_trade_cost_buffer_max_bps: number;
  carry_trade_candidates_top_n: number;
  carry_trade_open_top_k: number;
  carry_trade_max_open_positions: number;
  carry_trade_max_spread_bps: number;
  carry_trade_max_atr_pct_5m: number;
  carry_trade_trend_veto_adx: number;
  carry_trade_use_1m_filter: boolean;
  carry_trade_1m_spike_atr_mult: number;
  carry_trade_emergency_stoploss_r: number;
  carry_trade_emergency_stoploss_dynamic_enabled: boolean;
  carry_trade_emergency_stoploss_atr_mult: number;
  carry_trade_emergency_stoploss_min_r: number;
  carry_trade_emergency_stoploss_max_r: number;
  carry_trade_soft_no_exit_reduce_enabled: boolean;
  carry_trade_soft_no_exit_reduce_frac: number;
  carry_trade_soft_no_exit_reduce_spike_required: boolean;
  carry_trade_soft_no_exit_reduce_spread_mult: number;
  carry_trade_soft_no_exit_reduce_cooldown_sec: number;
  carry_trade_cooldown_min: number;
  carry_trade_sandbox: boolean;

  carry_trade_hedge_rotate_enabled: boolean;
  carry_trade_hedge_rotate_edge_diff_min: number;
  carry_trade_hedge_rotate_require_net_profit: boolean;

  carry_trade_hedge_min_hold_min: number;
  carry_trade_hedge_min_hold_strict: boolean;

  carry_trade_hedge_unhedge_enabled: boolean;
  carry_trade_hedge_unhedge_trigger_score: number;
  carry_trade_hedge_best_timing_wait_min: number;
  carry_trade_hedge_unhedge_intent_max_min: number;
  carry_trade_hedge_unhedge_exit_score: number;
  carry_trade_hedge_unhedge_timeout_min: number;
  carry_trade_hedge_unhedge_cooldown_min: number;
  carry_trade_hedge_allow_pre_funding_unhedge: boolean;

  carry_trade_hedge_dyn_leverage_enabled: boolean;
  carry_trade_hedge_leverage_min: number;
  carry_trade_hedge_leverage_max: number;
  carry_trade_hedge_leverage_alt_max: number;
  carry_trade_hedge_leverage_target_move_r: number;
  carry_trade_hedge_leverage_atr_floor: number;
  carry_trade_hedge_leverage_spread_good_bps: number;
  carry_trade_hedge_leverage_spread_bad_bps: number;
  carry_trade_hedge_leverage_use_depth: boolean;
  carry_trade_hedge_leverage_depth_window_bps: number;
  carry_trade_hedge_leverage_depth_notional_mult: number;

  carry_trade_hedge_circuit_breaker_enabled: boolean;
  carry_trade_hedge_cb_ret_1m_min_r: number;
  carry_trade_hedge_cb_ret_5m_atr_mult: number;
  carry_trade_hedge_cb_spread_bps: number;
  carry_trade_hedge_cb_cooldown_min: number;

  carry_trade_hedge_rebalance_enabled: boolean;
  carry_trade_hedge_rebalance_mismatch_pct: number;
  carry_trade_hedge_rebalance_reduce_only: boolean;
  carry_trade_hedge_rebalance_skip_no_exit: boolean;
  carry_trade_hedge_rebalance_min_notional_usdc: number;
  carry_trade_hedge_rebalance_cooldown_sec: number;

  carry_universe_enabled: boolean;
  carry_universe_refresh_seconds: number;
  carry_universe_min_abs_funding: number;
  carry_universe_max_spread_bps: number;
  carry_universe_min_day_ntl: number;
  carry_universe_max_coins: number;
  carry_universe_allowlist_csv: string;
  carry_universe_denylist_csv: string;
};

const _defaultDraft: CarryDraft = {
  carry_trade_enabled: false,
  carry_trade_live_enabled: null,
  carry_trade_hl_trading_enabled: null,
  carry_trade_mode: 'perp',
  carry_trade_profile: 'carry_v1',
  carry_trade_venue: 'hyperliquid',
  carry_trade_pre_funding_window_min: 12,
  carry_trade_no_exit_pre_funding_min: 5,
  carry_trade_post_funding_grace_min: 1,
  carry_trade_post_funding_trailing_enabled: false,
  carry_trade_post_funding_trailing_max_hold_min: 3,
  carry_trade_post_funding_trailing_arm_min_r: 0.001,
  carry_trade_post_funding_trailing_dist_r: 0.003,
  carry_trade_post_funding_require_basis_reversion: true,
  carry_trade_post_funding_basis_reversion_mult: 0.85,
  carry_trade_min_abs_funding: 0.00005,
  carry_trade_cost_buffer_bps: 8,
  carry_trade_cost_buffer_adaptive_enabled: false,
  carry_trade_cost_buffer_p95_mult: 1.0,
  carry_trade_cost_buffer_p95_lookback_hours: 72,
  carry_trade_cost_buffer_p95_lookback_n: 300,
  carry_trade_cost_buffer_p95_min_samples: 20,
  carry_trade_cost_buffer_min_bps: 0,
  carry_trade_cost_buffer_max_bps: 200,
  carry_trade_candidates_top_n: 10,
  carry_trade_open_top_k: 1,
  carry_trade_max_open_positions: 1,
  carry_trade_max_spread_bps: 15,
  carry_trade_max_atr_pct_5m: 0.012,
  carry_trade_trend_veto_adx: 35,
  carry_trade_use_1m_filter: true,
  carry_trade_1m_spike_atr_mult: 2.5,
  carry_trade_emergency_stoploss_r: -0.015,
  carry_trade_emergency_stoploss_dynamic_enabled: true,
  carry_trade_emergency_stoploss_atr_mult: 2.0,
  carry_trade_emergency_stoploss_min_r: -0.08,
  carry_trade_emergency_stoploss_max_r: -0.008,
  carry_trade_soft_no_exit_reduce_enabled: false,
  carry_trade_soft_no_exit_reduce_frac: 0.5,
  carry_trade_soft_no_exit_reduce_spike_required: true,
  carry_trade_soft_no_exit_reduce_spread_mult: 1.2,
  carry_trade_soft_no_exit_reduce_cooldown_sec: 900,
  carry_trade_cooldown_min: 10,
  carry_trade_sandbox: true,

  carry_trade_hedge_rotate_enabled: true,
  carry_trade_hedge_rotate_edge_diff_min: 0.00003,
  carry_trade_hedge_rotate_require_net_profit: true,

  carry_trade_hedge_min_hold_min: 4320,
  carry_trade_hedge_min_hold_strict: true,

  carry_trade_hedge_unhedge_enabled: true,
  carry_trade_hedge_unhedge_trigger_score: 0.82,
  carry_trade_hedge_best_timing_wait_min: 6,
  carry_trade_hedge_unhedge_intent_max_min: 20,
  carry_trade_hedge_unhedge_exit_score: 0.7,
  carry_trade_hedge_unhedge_timeout_min: 45,
  carry_trade_hedge_unhedge_cooldown_min: 30,
  carry_trade_hedge_allow_pre_funding_unhedge: true,

  carry_trade_hedge_dyn_leverage_enabled: true,
  carry_trade_hedge_leverage_min: 3,
  carry_trade_hedge_leverage_max: 10,
  carry_trade_hedge_leverage_alt_max: 6,
  carry_trade_hedge_leverage_target_move_r: 0.06,
  carry_trade_hedge_leverage_atr_floor: 0.003,
  carry_trade_hedge_leverage_spread_good_bps: 8,
  carry_trade_hedge_leverage_spread_bad_bps: 30,
  carry_trade_hedge_leverage_use_depth: false,
  carry_trade_hedge_leverage_depth_window_bps: 10,
  carry_trade_hedge_leverage_depth_notional_mult: 3,

  carry_trade_hedge_circuit_breaker_enabled: true,
  carry_trade_hedge_cb_ret_1m_min_r: 0.015,
  carry_trade_hedge_cb_ret_5m_atr_mult: 2.5,
  carry_trade_hedge_cb_spread_bps: 35,
  carry_trade_hedge_cb_cooldown_min: 60,

  carry_trade_hedge_rebalance_enabled: true,
  carry_trade_hedge_rebalance_mismatch_pct: 0.03,
  carry_trade_hedge_rebalance_reduce_only: true,
  carry_trade_hedge_rebalance_skip_no_exit: true,
  carry_trade_hedge_rebalance_min_notional_usdc: 12,
  carry_trade_hedge_rebalance_cooldown_sec: 600,

  carry_universe_enabled: true,
  carry_universe_refresh_seconds: 3600,
  carry_universe_min_abs_funding: 0.00005,
  carry_universe_max_spread_bps: 15,
  carry_universe_min_day_ntl: 0,
  carry_universe_max_coins: 200,
  carry_universe_allowlist_csv: '',
  carry_universe_denylist_csv: '',
};

export const CarryTradePage: React.FC = () => {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<string>('candidates');
  const [topN, setTopN] = useState<number>(20);
  const [fundingLimit, setFundingLimit] = useState<number>(80);
  const [ordersLimit, setOrdersLimit] = useState<number>(50);
  const [ordersType, setOrdersType] = useState<'all' | 'spot' | 'perp'>('all');
  const { showShadow: ordersShowShadow, setShowShadow: setOrdersShowShadow, showSimulated: ordersShowSimulated, setShowSimulated: setOrdersShowSimulated } = useOrdersUiPrefs({ scope: 'carry_orders' });
  const [acceptanceLookbackDays, setAcceptanceLookbackDays] = useState<number>(90);
  const [liveConfirmText, setLiveConfirmText] = useState<string>('');

  const { data: cfg } = useQuery<Config>({ queryKey: ['config'], queryFn: () => fetchConfig(), refetchInterval: 15000 });
  const { data: status } = useQuery<CarryStatusResponse>({ queryKey: ['carryStatus'], queryFn: () => fetchCarryStatus(), refetchInterval: 5000 });

  const venueEffective = useMemo(() => {
    const s = (status ?? {}) as Record<string, unknown>;
    if (s.venue != null) return String(s.venue);
    const c = (cfg ?? {}) as Record<string, unknown>;
    return String(c.carry_trade_venue ?? _defaultDraft.carry_trade_venue);
  }, [cfg, status]);

  const { data: hlPing } = useQuery<HyperliquidPingResponse>({
    queryKey: ['hlPing'],
    queryFn: () => hyperliquidPing(),
    enabled: venueEffective === 'hyperliquid',
    refetchInterval: venueEffective === 'hyperliquid' ? 15000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const gateOk = useMemo(() => _readBool(status?.gate, 'ok'), [status?.gate]);

  const fundingIncome = useMemo(() => {
    const fi = (status?.funding_income ?? null) as unknown;
    return fi && typeof fi === 'object' ? (fi as Record<string, unknown>) : null;
  }, [status?.funding_income]);

  const detailEnabled = tab === 'positions' || tab === 'events';
  const { data: statusDetail, isFetching: statusDetailFetching } = useQuery<CarryStatusResponse>({
    queryKey: ['carryStatusDetail', venueEffective, tab],
    queryFn: () =>
      fetchCarryStatus({
        include_positions: tab === 'positions',
        include_events: tab === 'events',
        events_n: 80,
      }),
    enabled: detailEnabled,
    refetchInterval: detailEnabled ? 5000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: carryUniverse, isFetching: universeFetching } = useQuery<CarryUniverseResponse>({
    queryKey: ['carryUniverse', venueEffective],
    queryFn: () => fetchCarryUniverse({}),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const uniState = useMemo(() => {
    const st = (carryUniverse?.state ?? {}) as Record<string, unknown>;
    const coins = Array.isArray(st.coins) ? (st.coins as unknown[]).map((x) => String(x ?? '').trim()).filter(Boolean) : [];
    const meta = (st.metadata ?? {}) as Record<string, unknown>;
    return {
      ts: _toNum(st.ts, 0),
      venue: String(st.venue ?? carryUniverse?.venue ?? venueEffective ?? 'hyperliquid'),
      n: _toNum(st.n, coins.length),
      coins,
      metadata: meta && typeof meta === 'object' ? (meta as Record<string, unknown>) : {},
      last_error: (st.last_error ?? null) as unknown,
    };
  }, [carryUniverse, venueEffective]);

  const universeRows = useMemo(() => {
    const meta = uniState.metadata as Record<string, unknown>;
    return uniState.coins.map((coin) => {
      const m = meta[coin] as Record<string, unknown> | undefined;
      return {
        coin,
        funding_rate: _toNum(m?.funding_rate, NaN),
        spread_bps: m?.spread_bps === null || m?.spread_bps === undefined ? null : _toNum(m?.spread_bps, NaN),
        day_ntl: _toNum(m?.day_ntl, NaN),
        basis_bps: _toNum(m?.basis_bps, NaN),
      };
    });
  }, [uniState.coins, uniState.metadata]);

  const refreshUniverseMutation = useMutation({
    mutationFn: () => fetchCarryUniverse({ refresh: 1 }),
    onSuccess: async (data) => {
      queryClient.setQueryData(['carryUniverse', venueEffective], data);
      await queryClient.invalidateQueries({ queryKey: ['carryStatus'] });
    },
  });

  const { data: candidates, isFetching: candidatesFetching } = useQuery<CarryCandidatesResponse>({
    queryKey: ['carryCandidates', venueEffective, topN],
    queryFn: () => fetchCarryCandidates({ venue: venueEffective, n: topN }),
    refetchInterval: 5000,
  });

  const { data: acceptance, isFetching: acceptanceFetching } = useQuery<CarryAcceptanceResponse>({
    queryKey: ['carryAcceptance', venueEffective, acceptanceLookbackDays],
    queryFn: () => fetchCarryAcceptance({ venue: venueEffective, lookback_days: acceptanceLookbackDays }),
    enabled: tab === 'acceptance',
    refetchInterval: tab === 'acceptance' ? 15000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: fundingSchedule } = useQuery<FundingScheduleResponse>({
    queryKey: ['fundingSchedule', venueEffective],
    queryFn: () => fetchFundingSchedule({ venue: venueEffective, n: 8 }),
    refetchInterval: 60000,
  });

  const { data: fundingRates, isFetching: fundingFetching } = useQuery<FundingRatesResponse>({
    queryKey: ['fundingRates', venueEffective, fundingLimit],
    queryFn: () => fetchFundingRates({ venue: venueEffective, limit: fundingLimit }),
    refetchInterval: 10000,
  });

  const { data: carryOrders, isFetching: ordersFetching } = useQuery({
    queryKey: ['carryOrders', ordersLimit],
    queryFn: () => fetchCarryOrdersRecent({ limit: ordersLimit }),
    refetchInterval: 8000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const inferOrderType = (o: unknown): 'spot' | 'perp' | 'unknown' => {
    const r = o as Record<string, unknown>;
    const it0 = r.instrument_type;
    const it = typeof it0 === 'string' ? it0.trim().toLowerCase() : '';
    if (it === 'spot' || it === 'perp') return it;
    const pair = String(r.pair ?? '').trim().toLowerCase();
    if (pair.includes('-perp') || pair.endsWith('perp')) return 'perp';
    if (pair.includes('/')) return 'spot';
    const ex = (r.exec ?? {}) as Record<string, unknown>;
    const mkt = String(ex.market ?? '').trim().toLowerCase();
    if (mkt === 'spot') return 'spot';
    return 'unknown';
  };

  const filteredCarryOrders = useMemo(() => {
    const rows = Array.isArray(carryOrders) ? carryOrders : [];
    const byType = ordersType === 'all' ? rows : rows.filter((o) => inferOrderType(o) === ordersType);
    return filterOrdersForUi(byType, { showShadow: ordersShowShadow, showSimulated: ordersShowSimulated });
  }, [carryOrders, ordersType, ordersShowShadow, ordersShowSimulated]);

  const effective = useMemo<CarryDraft>(() => {
    const c = (cfg ?? {}) as Record<string, unknown>;
    const liveEnabled = _readBool(c, 'carry_trade_live_enabled');
    const hlTradingEnabled = _readBool(c, 'carry_trade_hl_trading_enabled');
    const toCsvCoins = (v: unknown): string => {
      if (Array.isArray(v)) return v.map((x) => String(x ?? '').trim()).filter(Boolean).join(',');
      return String(v ?? '').trim();
    };
    return {
      ..._defaultDraft,
      carry_trade_enabled: Boolean(c.carry_trade_enabled ?? _defaultDraft.carry_trade_enabled),
      carry_trade_live_enabled: liveEnabled === null ? _defaultDraft.carry_trade_live_enabled : liveEnabled,
      carry_trade_hl_trading_enabled: hlTradingEnabled === null ? _defaultDraft.carry_trade_hl_trading_enabled : hlTradingEnabled,
      carry_trade_mode: String(c.carry_trade_mode ?? _defaultDraft.carry_trade_mode),
      carry_trade_profile: String(c.carry_trade_profile ?? _defaultDraft.carry_trade_profile),
      carry_trade_venue: String(c.carry_trade_venue ?? _defaultDraft.carry_trade_venue),
      carry_trade_pre_funding_window_min: _toNum(c.carry_trade_pre_funding_window_min, _defaultDraft.carry_trade_pre_funding_window_min),
      carry_trade_no_exit_pre_funding_min: _toNum(c.carry_trade_no_exit_pre_funding_min, _defaultDraft.carry_trade_no_exit_pre_funding_min),
      carry_trade_post_funding_grace_min: _toNum(c.carry_trade_post_funding_grace_min, _defaultDraft.carry_trade_post_funding_grace_min),
      carry_trade_post_funding_trailing_enabled: Boolean(c.carry_trade_post_funding_trailing_enabled ?? _defaultDraft.carry_trade_post_funding_trailing_enabled),
      carry_trade_post_funding_trailing_max_hold_min: _toNum(c.carry_trade_post_funding_trailing_max_hold_min, _defaultDraft.carry_trade_post_funding_trailing_max_hold_min),
      carry_trade_post_funding_trailing_arm_min_r: _toNum(c.carry_trade_post_funding_trailing_arm_min_r, _defaultDraft.carry_trade_post_funding_trailing_arm_min_r),
      carry_trade_post_funding_trailing_dist_r: _toNum(c.carry_trade_post_funding_trailing_dist_r, _defaultDraft.carry_trade_post_funding_trailing_dist_r),
      carry_trade_post_funding_require_basis_reversion: Boolean(c.carry_trade_post_funding_require_basis_reversion ?? _defaultDraft.carry_trade_post_funding_require_basis_reversion),
      carry_trade_post_funding_basis_reversion_mult: _toNum(c.carry_trade_post_funding_basis_reversion_mult, _defaultDraft.carry_trade_post_funding_basis_reversion_mult),
      carry_trade_min_abs_funding: _toNum(c.carry_trade_min_abs_funding, _defaultDraft.carry_trade_min_abs_funding),
      carry_trade_cost_buffer_bps: _toNum(c.carry_trade_cost_buffer_bps, _defaultDraft.carry_trade_cost_buffer_bps),
      carry_trade_cost_buffer_adaptive_enabled: Boolean(c.carry_trade_cost_buffer_adaptive_enabled ?? _defaultDraft.carry_trade_cost_buffer_adaptive_enabled),
      carry_trade_cost_buffer_p95_mult: _toNum(c.carry_trade_cost_buffer_p95_mult, _defaultDraft.carry_trade_cost_buffer_p95_mult),
      carry_trade_cost_buffer_p95_lookback_hours: _toNum(c.carry_trade_cost_buffer_p95_lookback_hours, _defaultDraft.carry_trade_cost_buffer_p95_lookback_hours),
      carry_trade_cost_buffer_p95_lookback_n: _toNum(c.carry_trade_cost_buffer_p95_lookback_n, _defaultDraft.carry_trade_cost_buffer_p95_lookback_n),
      carry_trade_cost_buffer_p95_min_samples: _toNum(c.carry_trade_cost_buffer_p95_min_samples, _defaultDraft.carry_trade_cost_buffer_p95_min_samples),
      carry_trade_cost_buffer_min_bps: _toNum(c.carry_trade_cost_buffer_min_bps, _defaultDraft.carry_trade_cost_buffer_min_bps),
      carry_trade_cost_buffer_max_bps: _toNum(c.carry_trade_cost_buffer_max_bps, _defaultDraft.carry_trade_cost_buffer_max_bps),
      carry_trade_candidates_top_n: _toNum(c.carry_trade_candidates_top_n, _defaultDraft.carry_trade_candidates_top_n),
      carry_trade_open_top_k: _toNum(c.carry_trade_open_top_k, _defaultDraft.carry_trade_open_top_k),
      carry_trade_max_open_positions: _toNum(c.carry_trade_max_open_positions, _defaultDraft.carry_trade_max_open_positions),
      carry_trade_max_spread_bps: _toNum(c.carry_trade_max_spread_bps, _defaultDraft.carry_trade_max_spread_bps),
      carry_trade_max_atr_pct_5m: _toNum(c.carry_trade_max_atr_pct_5m, _defaultDraft.carry_trade_max_atr_pct_5m),
      carry_trade_trend_veto_adx: _toNum(c.carry_trade_trend_veto_adx, _defaultDraft.carry_trade_trend_veto_adx),
      carry_trade_use_1m_filter: Boolean(c.carry_trade_use_1m_filter ?? _defaultDraft.carry_trade_use_1m_filter),
      carry_trade_1m_spike_atr_mult: _toNum(c.carry_trade_1m_spike_atr_mult, _defaultDraft.carry_trade_1m_spike_atr_mult),
      carry_trade_emergency_stoploss_r: _toNum(c.carry_trade_emergency_stoploss_r, _defaultDraft.carry_trade_emergency_stoploss_r),
      carry_trade_emergency_stoploss_dynamic_enabled: Boolean(c.carry_trade_emergency_stoploss_dynamic_enabled ?? _defaultDraft.carry_trade_emergency_stoploss_dynamic_enabled),
      carry_trade_emergency_stoploss_atr_mult: _toNum(c.carry_trade_emergency_stoploss_atr_mult, _defaultDraft.carry_trade_emergency_stoploss_atr_mult),
      carry_trade_emergency_stoploss_min_r: _toNum(c.carry_trade_emergency_stoploss_min_r, _defaultDraft.carry_trade_emergency_stoploss_min_r),
      carry_trade_emergency_stoploss_max_r: _toNum(c.carry_trade_emergency_stoploss_max_r, _defaultDraft.carry_trade_emergency_stoploss_max_r),
      carry_trade_soft_no_exit_reduce_enabled: Boolean(c.carry_trade_soft_no_exit_reduce_enabled ?? _defaultDraft.carry_trade_soft_no_exit_reduce_enabled),
      carry_trade_soft_no_exit_reduce_frac: _toNum(c.carry_trade_soft_no_exit_reduce_frac, _defaultDraft.carry_trade_soft_no_exit_reduce_frac),
      carry_trade_soft_no_exit_reduce_spike_required: Boolean(c.carry_trade_soft_no_exit_reduce_spike_required ?? _defaultDraft.carry_trade_soft_no_exit_reduce_spike_required),
      carry_trade_soft_no_exit_reduce_spread_mult: _toNum(c.carry_trade_soft_no_exit_reduce_spread_mult, _defaultDraft.carry_trade_soft_no_exit_reduce_spread_mult),
      carry_trade_soft_no_exit_reduce_cooldown_sec: _toNum(c.carry_trade_soft_no_exit_reduce_cooldown_sec, _defaultDraft.carry_trade_soft_no_exit_reduce_cooldown_sec),
      carry_trade_cooldown_min: _toNum(c.carry_trade_cooldown_min, _defaultDraft.carry_trade_cooldown_min),
      carry_trade_sandbox: Boolean(c.carry_trade_sandbox ?? _defaultDraft.carry_trade_sandbox),

      carry_trade_hedge_rotate_enabled: Boolean(c.carry_trade_hedge_rotate_enabled ?? _defaultDraft.carry_trade_hedge_rotate_enabled),
      carry_trade_hedge_rotate_edge_diff_min: _toNum(c.carry_trade_hedge_rotate_edge_diff_min, _defaultDraft.carry_trade_hedge_rotate_edge_diff_min),
      carry_trade_hedge_rotate_require_net_profit: Boolean(c.carry_trade_hedge_rotate_require_net_profit ?? _defaultDraft.carry_trade_hedge_rotate_require_net_profit),

      carry_trade_hedge_min_hold_min: _toNum(c.carry_trade_hedge_min_hold_min, _defaultDraft.carry_trade_hedge_min_hold_min),
      carry_trade_hedge_min_hold_strict: Boolean(c.carry_trade_hedge_min_hold_strict ?? _defaultDraft.carry_trade_hedge_min_hold_strict),

      carry_trade_hedge_unhedge_enabled: Boolean(c.carry_trade_hedge_unhedge_enabled ?? _defaultDraft.carry_trade_hedge_unhedge_enabled),
      carry_trade_hedge_unhedge_trigger_score: _toNum(c.carry_trade_hedge_unhedge_trigger_score, _defaultDraft.carry_trade_hedge_unhedge_trigger_score),
      carry_trade_hedge_best_timing_wait_min: _toNum(c.carry_trade_hedge_best_timing_wait_min, _defaultDraft.carry_trade_hedge_best_timing_wait_min),
      carry_trade_hedge_unhedge_intent_max_min: _toNum(c.carry_trade_hedge_unhedge_intent_max_min, _defaultDraft.carry_trade_hedge_unhedge_intent_max_min),
      carry_trade_hedge_unhedge_exit_score: _toNum(c.carry_trade_hedge_unhedge_exit_score, _defaultDraft.carry_trade_hedge_unhedge_exit_score),
      carry_trade_hedge_unhedge_timeout_min: _toNum(c.carry_trade_hedge_unhedge_timeout_min, _defaultDraft.carry_trade_hedge_unhedge_timeout_min),
      carry_trade_hedge_unhedge_cooldown_min: _toNum(c.carry_trade_hedge_unhedge_cooldown_min, _defaultDraft.carry_trade_hedge_unhedge_cooldown_min),
      carry_trade_hedge_allow_pre_funding_unhedge: Boolean(c.carry_trade_hedge_allow_pre_funding_unhedge ?? _defaultDraft.carry_trade_hedge_allow_pre_funding_unhedge),

      carry_trade_hedge_dyn_leverage_enabled: Boolean(c.carry_trade_hedge_dyn_leverage_enabled ?? _defaultDraft.carry_trade_hedge_dyn_leverage_enabled),
      carry_trade_hedge_leverage_min: _toNum(c.carry_trade_hedge_leverage_min, _defaultDraft.carry_trade_hedge_leverage_min),
      carry_trade_hedge_leverage_max: _toNum(c.carry_trade_hedge_leverage_max, _defaultDraft.carry_trade_hedge_leverage_max),
      carry_trade_hedge_leverage_alt_max: _toNum(c.carry_trade_hedge_leverage_alt_max, _defaultDraft.carry_trade_hedge_leverage_alt_max),
      carry_trade_hedge_leverage_target_move_r: _toNum(c.carry_trade_hedge_leverage_target_move_r, _defaultDraft.carry_trade_hedge_leverage_target_move_r),
      carry_trade_hedge_leverage_atr_floor: _toNum(c.carry_trade_hedge_leverage_atr_floor, _defaultDraft.carry_trade_hedge_leverage_atr_floor),
      carry_trade_hedge_leverage_spread_good_bps: _toNum(c.carry_trade_hedge_leverage_spread_good_bps, _defaultDraft.carry_trade_hedge_leverage_spread_good_bps),
      carry_trade_hedge_leverage_spread_bad_bps: _toNum(c.carry_trade_hedge_leverage_spread_bad_bps, _defaultDraft.carry_trade_hedge_leverage_spread_bad_bps),
      carry_trade_hedge_leverage_use_depth: Boolean(c.carry_trade_hedge_leverage_use_depth ?? _defaultDraft.carry_trade_hedge_leverage_use_depth),
      carry_trade_hedge_leverage_depth_window_bps: _toNum(c.carry_trade_hedge_leverage_depth_window_bps, _defaultDraft.carry_trade_hedge_leverage_depth_window_bps),
      carry_trade_hedge_leverage_depth_notional_mult: _toNum(c.carry_trade_hedge_leverage_depth_notional_mult, _defaultDraft.carry_trade_hedge_leverage_depth_notional_mult),

      carry_trade_hedge_circuit_breaker_enabled: Boolean(c.carry_trade_hedge_circuit_breaker_enabled ?? _defaultDraft.carry_trade_hedge_circuit_breaker_enabled),
      carry_trade_hedge_cb_ret_1m_min_r: _toNum(c.carry_trade_hedge_cb_ret_1m_min_r, _defaultDraft.carry_trade_hedge_cb_ret_1m_min_r),
      carry_trade_hedge_cb_ret_5m_atr_mult: _toNum(c.carry_trade_hedge_cb_ret_5m_atr_mult, _defaultDraft.carry_trade_hedge_cb_ret_5m_atr_mult),
      carry_trade_hedge_cb_spread_bps: _toNum(c.carry_trade_hedge_cb_spread_bps, _defaultDraft.carry_trade_hedge_cb_spread_bps),
      carry_trade_hedge_cb_cooldown_min: _toNum(c.carry_trade_hedge_cb_cooldown_min, _defaultDraft.carry_trade_hedge_cb_cooldown_min),

      carry_trade_hedge_rebalance_enabled: Boolean(c.carry_trade_hedge_rebalance_enabled ?? _defaultDraft.carry_trade_hedge_rebalance_enabled),
      carry_trade_hedge_rebalance_mismatch_pct: _toNum(c.carry_trade_hedge_rebalance_mismatch_pct, _defaultDraft.carry_trade_hedge_rebalance_mismatch_pct),
      carry_trade_hedge_rebalance_reduce_only: Boolean(c.carry_trade_hedge_rebalance_reduce_only ?? _defaultDraft.carry_trade_hedge_rebalance_reduce_only),
      carry_trade_hedge_rebalance_skip_no_exit: Boolean(c.carry_trade_hedge_rebalance_skip_no_exit ?? _defaultDraft.carry_trade_hedge_rebalance_skip_no_exit),
      carry_trade_hedge_rebalance_min_notional_usdc: _toNum(c.carry_trade_hedge_rebalance_min_notional_usdc, _defaultDraft.carry_trade_hedge_rebalance_min_notional_usdc),
      carry_trade_hedge_rebalance_cooldown_sec: _toNum(c.carry_trade_hedge_rebalance_cooldown_sec, _defaultDraft.carry_trade_hedge_rebalance_cooldown_sec),

      carry_universe_enabled: Boolean(c.carry_universe_enabled ?? _defaultDraft.carry_universe_enabled),
      carry_universe_refresh_seconds: _toNum(c.carry_universe_refresh_seconds, _defaultDraft.carry_universe_refresh_seconds),
      carry_universe_min_abs_funding: _toNum(c.carry_universe_min_abs_funding, _defaultDraft.carry_universe_min_abs_funding),
      carry_universe_max_spread_bps: _toNum(c.carry_universe_max_spread_bps, _defaultDraft.carry_universe_max_spread_bps),
      carry_universe_min_day_ntl: _toNum(c.carry_universe_min_day_ntl, _defaultDraft.carry_universe_min_day_ntl),
      carry_universe_max_coins: _toNum(c.carry_universe_max_coins, _defaultDraft.carry_universe_max_coins),
      carry_universe_allowlist_csv: toCsvCoins(c.carry_universe_allowlist ?? _defaultDraft.carry_universe_allowlist_csv),
      carry_universe_denylist_csv: toCsvCoins(c.carry_universe_denylist ?? _defaultDraft.carry_universe_denylist_csv),
    } as CarryDraft;
  }, [cfg]);

  const [draft, setDraft] = useState<CarryDraft>(_defaultDraft);
  React.useEffect(() => setDraft(effective), [effective]);

  const liveConfirmOk = useMemo(() => liveConfirmText.trim().toUpperCase() === 'LIVE', [liveConfirmText]);
  const needsConfirmLive = useMemo(() => {
    const enablingSandboxOff = effective.carry_trade_sandbox && !draft.carry_trade_sandbox;
    const enablingLiveGate = (effective.carry_trade_live_enabled !== true) && (draft.carry_trade_live_enabled === true);
    const enablingHl = (effective.carry_trade_hl_trading_enabled !== true) && (draft.carry_trade_hl_trading_enabled === true);
    return enablingSandboxOff || enablingLiveGate || enablingHl;
  }, [draft, effective]);

  const saveMutation = useMutation({
    mutationFn: (next: CarryDraft) => {
      const csvToCoins = (v: unknown): string[] => {
        const s = String(v ?? '')
          .split(',')
          .map((x) => x.trim().toUpperCase())
          .filter(Boolean);
        return Array.from(new Set(s));
      };
      const { carry_universe_allowlist_csv, carry_universe_denylist_csv, ...rest } = next;
      const extra = (needsConfirmLive && liveConfirmOk) ? { confirm_live: true } : {};
      return updateCarryConfig({
        ...rest,
        ...extra,
        carry_universe_allowlist: csvToCoins(carry_universe_allowlist_csv),
        carry_universe_denylist: csvToCoins(carry_universe_denylist_csv),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['config'] });
      await queryClient.invalidateQueries({ queryKey: ['carryStatus'] });
      await queryClient.invalidateQueries({ queryKey: ['carryCandidates'] });
      await queryClient.invalidateQueries({ queryKey: ['carryUniverse'] });
    },
  });

  type NumericKeys<T> = {
    [K in keyof T]-?: T[K] extends number ? K : never;
  }[keyof T];

  const setDraftNumber = (k: NumericKeys<CarryDraft>) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setDraft((p) => {
      const current = p[k];
      const nextValue = v === '' ? current : Number(v);
      return { ...p, [k]: nextValue } as CarryDraft;
    });
  };

  const activePos = useMemo(() => {
    const ap = (status?.active_position ?? null) as unknown;
    return ap && typeof ap === 'object' ? (ap as Record<string, unknown>) : null;
  }, [status?.active_position]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span>Carry Trade（资金费率套利）</span>
              <Badge variant={status?.enabled_effective ? 'secondary' : 'outline'}>{status?.enabled_effective ? 'enabled' : 'disabled'}</Badge>
              <Badge variant={status?.sandbox ? 'outline' : 'secondary'}>{status?.sandbox ? 'sandbox' : 'live'}</Badge>
              <Badge variant={status?.execute_effective ? 'secondary' : 'outline'}>{status?.execute_effective ? 'execute' : 'paper'}</Badge>
              <Badge variant={gateOk ? 'outline' : 'destructive'}>{gateOk ? 'gate_ok' : 'gated'}</Badge>
              {venueEffective === 'hyperliquid' && hlPing?.pk_matches_account === false ? (
                <Badge variant="destructive">pk_mismatch</Badge>
              ) : null}
            </div>
            <div className="text-xs text-slate-500">
              profile: {String(status?.profile ?? '-')} · venue: {String(status?.venue ?? 'hyperliquid')}
              {venueEffective === 'hyperliquid' && hlPing?.account_address ? ` · hl_acct: ${_maskAddr(hlPing.account_address)}` : ''}
              {venueEffective === 'hyperliquid' && hlPing?.pk_wallet_address ? ` · hl_pk: ${_maskAddr(hlPing.pk_wallet_address)}` : ''}
              {venueEffective === 'hyperliquid' && hlPing?.vault_address ? ` · hl_vault: ${_maskAddr(hlPing.vault_address)}` : ''}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-7 gap-3 text-sm">
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">next_funding</div>
              <div className="font-semibold">{_fmtTs(_toNum(status?.next_funding_ts, 0))}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">minutes_to_funding</div>
              <div className="font-semibold">{Number.isFinite(Number(status?.minutes_to_funding)) ? Number(status?.minutes_to_funding).toFixed(2) : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">window</div>
              <div className="font-semibold">{String(status?.window_state ?? '-') }</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">candidates</div>
              <div className="font-semibold">{Array.isArray(candidates?.candidates) ? candidates?.candidates.length : '-'}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">engine</div>
              <div className="font-semibold">
                {String(status?.engine?.positions_count ?? '-') } · {String(status?.engine?.open_window?.reason ?? '-')}
              </div>
              <div className="text-xs text-slate-500">tick: {_fmtTs(_toNum(status?.engine?.tick_ts, 0))}</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">active_position</div>
              <div className="font-semibold">{activePos ? `${String(activePos.coin ?? '-') } · ${String(activePos.hedge_stage ?? '-')}` : '-'}</div>
              <div className="text-xs text-slate-500">
                {activePos ? `${String(activePos.pair ?? '-') } · ${String(activePos.status ?? '-')}` : '-'}
              </div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">pnl（est. next funding / unreal / costs）</div>
              <div className="font-semibold">
                {_fmtUsd(status?.funding_pnl)} · {_fmtUsd(status?.price_move_pnl)} · {_fmtUsd(status?.costs)}
              </div>
              <div className="text-xs text-slate-500">funding_income（progress / accrued / realized_24h / realized_total / est_next）</div>
              <div className="font-semibold">
                {_fmtPct(Number(fundingIncome?.progress ?? NaN), 1)} · {_fmtUsd(fundingIncome?.accrued_current_period_usdc_est)} · {_fmtUsd(fundingIncome?.realized_24h_usdc_est)} · {_fmtUsd(fundingIncome?.realized_total_usdc_est)} · {_fmtUsd(fundingIncome?.est_next_period_usdc_est)}
              </div>
            </div>
          </div>

          <div className="mt-3 border rounded bg-white overflow-auto">
            <div className="px-3 py-2 text-xs text-slate-500 border-b">funding_income.ledger_tail</div>
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-left p-2">funding_ts</th>
                  <th className="text-left p-2">coin</th>
                  <th className="text-left p-2">side</th>
                  <th className="text-right p-2">notional</th>
                  <th className="text-right p-2">funding</th>
                  <th className="text-right p-2">payment</th>
                </tr>
              </thead>
              <tbody>
                {(Array.isArray(fundingIncome?.ledger_tail) ? (fundingIncome?.ledger_tail as unknown[]) : []).slice(0, 20).map((raw, i) => {
                  const r = (raw ?? {}) as Record<string, unknown>;
                  const fts = _toNum(r.funding_ts, 0);
                  return (
                    <tr key={`${String(r.coin ?? '')}-${String(r.funding_ts ?? '')}-${i}`} className="border-t">
                      <td className="p-2">{_fmtTs(fts)}</td>
                      <td className="p-2 font-semibold">{String(r.coin ?? '-')}</td>
                      <td className="p-2">{String(r.side ?? '-')}</td>
                      <td className="p-2 text-right">{_fmtUsd(r.notional_usdc, 2)}</td>
                      <td className="p-2 text-right">{_fmtPct(Number(r.funding_rate ?? NaN), 4)}</td>
                      <td className="p-2 text-right">{_fmtUsd(r.payment_usdc_est, 4)}</td>
                    </tr>
                  );
                })}
                {!(Array.isArray(fundingIncome?.ledger_tail) && (fundingIncome?.ledger_tail as unknown[]).length > 0) && (
                  <tr>
                    <td className="p-2 text-slate-500" colSpan={6}>
                      -
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="candidates" onValueChange={(v) => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="candidates">Candidates</TabsTrigger>
          <TabsTrigger value="orders">Orders</TabsTrigger>
          <TabsTrigger value="positions">Positions</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="funding">Funding</TabsTrigger>
          <TabsTrigger value="acceptance">Acceptance</TabsTrigger>
          <TabsTrigger value="universe">Universe</TabsTrigger>
          <TabsTrigger value="config">Config</TabsTrigger>
        </TabsList>

        <TabsContent value="candidates">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>候选列表</span>
                <div className="flex items-center gap-2">
                  <div className="text-xs text-slate-500">TopN</div>
                  <Input type="number" className="w-24" value={topN} onChange={(e) => setTopN(_toNum(e.target.value, 20))} />
                  <Badge variant="outline">{candidatesFetching ? 'updating' : 'live'}</Badge>
                  <div className="text-xs text-slate-500">rec_k</div>
                  <Badge variant="outline">{String(candidates?.recommended_open_top_k ?? '-') }</Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-auto border rounded bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left p-2">coin</th>
                      <th className="text-right p-2">funding</th>
                      <th className="text-right p-2">basis</th>
                      <th className="text-left p-2">side</th>
                      <th className="text-right p-2">edge</th>
                      <th className="text-right p-2">atr5m</th>
                      <th className="text-right p-2">adx5m</th>
                      <th className="text-right p-2">corr</th>
                      <th className="text-right p-2">vol5m</th>
                      <th className="text-left p-2">gate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(candidates?.candidates ?? []).map((r) => {
                      const veto = Boolean(r.vetoed);
                      const coin = String(r.coin ?? '');
                      return (
                        <tr key={coin} className="border-t">
                          <td className="p-2 font-semibold">{coin}</td>
                          <td className="p-2 text-right">{_fmtPct(Number(r.funding_rate ?? 0), 4)}</td>
                          <td className="p-2 text-right">{_fmtBps(Number(r.basis_bps ?? 0), 1)}</td>
                          <td className="p-2">{String(r.carry_side ?? '-')}</td>
                          <td className="p-2 text-right">{_fmtPct(Number(r.expected_edge ?? 0), 4)}</td>
                          <td className="p-2 text-right">{_fmtPct(Number(r.atr_pct_5m ?? NaN), 2)}</td>
                          <td className="p-2 text-right">{Number.isFinite(Number(r.adx_5m)) ? Number(r.adx_5m).toFixed(1) : '-'}</td>
                          <td className="p-2 text-right">{Number.isFinite(Number(r.corr_max_abs)) ? Number(r.corr_max_abs).toFixed(2) : '-'}</td>
                          <td className="p-2 text-right">{Number.isFinite(Number(r.vol_usdc_5m)) ? _fmtUsd(r.vol_usdc_5m, 0) : '-'}</td>
                          <td className="p-2">
                            <Badge variant={veto ? 'destructive' : 'secondary'}>{veto ? String(r.veto_reason ?? 'veto') : 'ok'}</Badge>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="orders">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Recent Orders（Carry 专用）</span>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant={ordersType === 'all' ? 'secondary' : 'outline'} onClick={() => setOrdersType('all')}>
                    All
                  </Button>
                  <Button size="sm" variant={ordersType === 'spot' ? 'secondary' : 'outline'} onClick={() => setOrdersType('spot')}>
                    Spot
                  </Button>
                  <Button size="sm" variant={ordersType === 'perp' ? 'secondary' : 'outline'} onClick={() => setOrdersType('perp')}>
                    Perp
                  </Button>
                  <Button size="sm" variant={ordersShowShadow ? 'secondary' : 'outline'} onClick={() => setOrdersShowShadow((v) => !v)}>
                    {ordersShowShadow ? '含 shadow' : '不含 shadow'}
                  </Button>
                  <Button size="sm" variant={ordersShowSimulated ? 'secondary' : 'outline'} onClick={() => setOrdersShowSimulated((v) => !v)}>
                    {ordersShowSimulated ? '含模拟' : '不含模拟'}
                  </Button>
                  <div className="text-xs text-slate-500">Limit</div>
                  <Input type="number" className="w-24" value={ordersLimit} onChange={(e) => setOrdersLimit(_toNum(e.target.value, 50))} />
                  <Badge variant="outline">{ordersFetching ? 'updating' : 'live'}</Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-auto border rounded bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left p-2">time</th>
                      <th className="text-left p-2">type</th>
                      <th className="text-left p-2">pair</th>
                      <th className="text-left p-2">side</th>
                      <th className="text-left p-2">action</th>
                      <th className="text-left p-2">status</th>
                      <th className="text-left p-2">mode</th>
                      <th className="text-left p-2">exchange_oid</th>
                      <th className="text-left p-2">preflight</th>
                      <th className="text-left p-2">ab_owner</th>
                      <th className="text-left p-2">tag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCarryOrders.map((o) => {
                      const ts = _toNum((o as { ts?: unknown }).ts, 0);
                      const id = String((o as { id?: unknown }).id ?? '');
                      const type0 = inferOrderType(o);
                      const pair = String((o as { pair?: unknown }).pair ?? '-');
                      const side = String((o as { side?: unknown }).side ?? '-');
                      const action = String((o as { action?: unknown }).action ?? '-');
                      const status0 = String((o as { status?: unknown }).status ?? '-');
                      const mode = String((o as { mode?: unknown }).mode ?? '-');
                      const exchangeOid = String((o as { exchange_oid?: unknown }).exchange_oid ?? '-');
                      const exec = ((o as { exec?: unknown }).exec ?? null) as unknown;
                      const preflight =
                        exec && typeof exec === 'object' && 'preflight_error' in (exec as Record<string, unknown>)
                          ? String((exec as Record<string, unknown>).preflight_error ?? '')
                          : '';
                      const abOwner = String((o as { ab_owner?: unknown }).ab_owner ?? '-');
                      const tag = String((o as { tag?: unknown }).tag ?? '');
                      return (
                        <tr key={id} className="border-t">
                          <td className="p-2 font-mono text-xs">{_fmtTs(ts)}</td>
                          <td className="p-2">
                            <Badge variant="outline">{String(type0 || '-')}</Badge>
                          </td>
                          <td className="p-2 font-semibold">{pair}</td>
                          <td className="p-2">{side}</td>
                          <td className="p-2">{action}</td>
                          <td className="p-2">{status0}</td>
                          <td className="p-2">{mode}</td>
                          <td className="p-2 font-mono text-xs">{exchangeOid}</td>
                          <td className="p-2 font-mono text-xs">{preflight || '-'}</td>
                          <td className="p-2">{abOwner}</td>
                          <td className="p-2 font-mono text-xs">{tag}</td>
                        </tr>
                      );
                    })}
                    {filteredCarryOrders.length === 0 ? (
                      <tr>
                        <td className="p-6 text-center text-slate-500" colSpan={11}>
                          -
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="positions">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Active Positions</span>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{statusDetailFetching ? 'updating' : 'live'}</Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-auto border rounded bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left p-2">coin</th>
                      <th className="text-left p-2">pair</th>
                      <th className="text-left p-2">status</th>
                      <th className="text-left p-2">stage</th>
                      <th className="text-right p-2">macro</th>
                      <th className="text-right p-2">reversal</th>
                      <th className="text-right p-2">best</th>
                      <th className="text-right p-2">exit</th>
                      <th className="text-right p-2">net_pnl</th>
                      <th className="text-left p-2">deadline</th>
                    </tr>
                  </thead>
                  <tbody>
                    {((statusDetail?.positions?.items ?? []) as Record<string, unknown>[]).map((r) => {
                      const coin = String(r.coin ?? '-');
                      const pair = String(r.pair ?? '-');
                      const status0 = String(r.status ?? '-');
                      const stage = String(r.hedge_stage ?? '-');
                      const macroDir = Number(r.macro_dir ?? NaN);
                      const reversalDir = Number(r.reversal_dir ?? NaN);
                      const best = Number(r.best_timing_score ?? NaN);
                      const exit = Number(r.unhedge_exit_score ?? NaN);
                      const net = Number(r.net_pnl_usdc_est ?? NaN);
                      const deadlineTs = _toNum(r.unhedge_deadline_ts, 0);
                      return (
                        <tr key={`${coin}-${pair}`} className="border-t">
                          <td className="p-2 font-semibold">{coin}</td>
                          <td className="p-2 font-semibold">{pair}</td>
                          <td className="p-2">{status0}</td>
                          <td className="p-2">{stage}</td>
                          <td className="p-2 text-right">{Number.isFinite(macroDir) ? String(macroDir) : '-'}</td>
                          <td className="p-2 text-right">{Number.isFinite(reversalDir) ? String(reversalDir) : '-'}</td>
                          <td className="p-2 text-right">{Number.isFinite(best) ? best.toFixed(3) : '-'}</td>
                          <td className="p-2 text-right">{Number.isFinite(exit) ? exit.toFixed(3) : '-'}</td>
                          <td className="p-2 text-right">{Number.isFinite(net) ? _fmtUsd(net) : '-'}</td>
                          <td className="p-2 font-mono text-xs">{_fmtTs(deadlineTs)}</td>
                        </tr>
                      );
                    })}
                    {((statusDetail?.positions?.items ?? []) as unknown[]).length === 0 ? (
                      <tr>
                        <td className="p-6 text-center text-slate-500" colSpan={10}>
                          -
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="events">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Events</span>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{statusDetailFetching ? 'updating' : 'live'}</Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-auto border rounded bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left p-2">time</th>
                      <th className="text-left p-2">type</th>
                      <th className="text-left p-2">coin</th>
                      <th className="text-left p-2">msg</th>
                    </tr>
                  </thead>
                  <tbody>
                    {((statusDetail?.events?.items ?? []) as Record<string, unknown>[]).map((e, idx) => {
                      const ts = _toNum(e.ts, 0);
                      const type0 = String(e.type ?? e.event ?? '-');
                      const coin = String(e.coin ?? e.pair ?? '-');
                      const msg = String(e.msg ?? e.reason ?? JSON.stringify(e));
                      return (
                        <tr key={`${ts}-${idx}`} className="border-t">
                          <td className="p-2 font-mono text-xs">{_fmtTs(ts)}</td>
                          <td className="p-2">{type0}</td>
                          <td className="p-2 font-semibold">{coin}</td>
                          <td className="p-2 font-mono text-xs whitespace-pre-wrap break-words">{msg}</td>
                        </tr>
                      );
                    })}
                    {((statusDetail?.events?.items ?? []) as unknown[]).length === 0 ? (
                      <tr>
                        <td className="p-6 text-center text-slate-500" colSpan={4}>
                          -
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="funding">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Funding / Mark / Basis</span>
                <div className="flex items-center gap-2">
                  <div className="text-xs text-slate-500">Limit</div>
                  <Input type="number" className="w-24" value={fundingLimit} onChange={(e) => setFundingLimit(_toNum(e.target.value, 80))} />
                  <Badge variant="outline">{fundingFetching ? 'updating' : 'live'}</Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-2">schedule（next 8）</div>
                  <div className="space-y-1 text-sm">
                    {(fundingSchedule?.schedule ?? []).slice(0, 8).map((t) => (
                      <div key={t} className="flex items-center justify-between">
                        <div className="font-mono text-xs">{t}</div>
                        <div className="font-semibold">{_fmtTs(Number(t))}</div>
                      </div>
                    ))}
                    {Array.isArray(fundingSchedule?.schedule) && fundingSchedule?.schedule.length === 0 ? <div className="text-slate-500">-</div> : null}
                  </div>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-2">snapshot</div>
                  <div className="space-y-1 text-sm">
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">next_funding_ts</div>
                      <div className="font-semibold">{_fmtTs(_toNum(fundingRates?.next_funding_ts, 0))}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">minutes_to_funding</div>
                      <div className="font-semibold">{Number.isFinite(Number(fundingRates?.minutes_to_funding)) ? Number(fundingRates?.minutes_to_funding).toFixed(2) : '-'}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">venue</div>
                      <div className="font-semibold">{String(fundingRates?.venue ?? venueEffective)}</div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-4 overflow-auto border rounded bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left p-2">coin</th>
                      <th className="text-right p-2">funding</th>
                      <th className="text-right p-2">basis</th>
                      <th className="text-right p-2">mark</th>
                      <th className="text-right p-2">index</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries((fundingRates?.rates_by_coin ?? fundingRates?.rates) ?? {})
                      .sort(
                        (a, b) =>
                          Math.abs(Number(b[1]?.funding_rate_1h ?? b[1]?.funding_rate ?? 0)) - Math.abs(Number(a[1]?.funding_rate_1h ?? a[1]?.funding_rate ?? 0)),
                      )
                      .map(([coin, r]) => (
                        <tr key={coin} className="border-t">
                          <td className="p-2 font-semibold">{coin}</td>
                          <td className="p-2 text-right">{_fmtPct(Number(r?.funding_rate_1h ?? r?.funding_rate ?? 0), 4)}</td>
                          <td className="p-2 text-right">{_fmtBps(Number(r?.basis_bps ?? 0), 1)}</td>
                          <td className="p-2 text-right">{_fmtPx(r?.mark_price)}</td>
                          <td className="p-2 text-right">{_fmtPx(r?.index_price)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="acceptance">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>验收指标</span>
                <div className="flex items-center gap-2">
                  <div className="text-xs text-slate-500">Lookback(d)</div>
                  <Input type="number" className="w-24" value={acceptanceLookbackDays} onChange={(e) => setAcceptanceLookbackDays(_toNum(e.target.value, 90))} />
                  <Badge variant="outline">{acceptanceFetching ? 'updating' : 'cached'}</Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500">funding_pnl</div>
                  <div className="font-semibold">{_fmtUsd((acceptance?.pnl_split as Record<string, unknown> | undefined)?.funding_pnl_usdc_est, 2)}</div>
                  <div className="mt-2 text-xs text-slate-500">share(abs)</div>
                  <div className="font-semibold">{_fmtPct(_toNum((acceptance?.pnl_split as Record<string, unknown> | undefined)?.funding_share_of_abs, NaN), 2)}</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500">price_move_pnl</div>
                  <div className="font-semibold">{_fmtUsd((acceptance?.pnl_split as Record<string, unknown> | undefined)?.price_move_pnl_usdc_est, 2)}</div>
                  <div className="mt-2 text-xs text-slate-500">costs_est</div>
                  <div className="font-semibold">{_fmtUsd((acceptance?.pnl_split as Record<string, unknown> | undefined)?.costs_usdc_est, 2)}</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500">net_total</div>
                  <div className="font-semibold">{_fmtUsd((acceptance?.pnl_split as Record<string, unknown> | undefined)?.net_total_usdc_est, 2)}</div>
                  <div className="mt-2 text-xs text-slate-500">trades_n</div>
                  <div className="font-semibold">{String((acceptance?.pnl_split as Record<string, unknown> | undefined)?.trades_n ?? '-') }</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500">tail</div>
                  <div className="space-y-1 mt-1">
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">p95_dd</div>
                      <div className="font-semibold">{_fmtPct(_toNum((acceptance?.tail as Record<string, unknown> | undefined)?.p95_trade_drawdown_pct, NaN), 2)}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">p99_dd</div>
                      <div className="font-semibold">{_fmtPct(_toNum((acceptance?.tail as Record<string, unknown> | undefined)?.p99_trade_drawdown_pct, NaN), 2)}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">maxdd</div>
                      <div className="font-semibold">{_fmtPct(_toNum((acceptance?.tail as Record<string, unknown> | undefined)?.max_drawdown_pct, NaN), 2)}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">liq_warn</div>
                      <div className="font-semibold">{String((acceptance?.tail as Record<string, unknown> | undefined)?.liq_warn_total ?? '-') }</div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-2">turnover</div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">avg_hold_days</div>
                      <div className="font-semibold">{Number.isFinite(_toNum((acceptance?.turnover as Record<string, unknown> | undefined)?.avg_hold_days, NaN)) ? _toNum((acceptance?.turnover as Record<string, unknown> | undefined)?.avg_hold_days, NaN).toFixed(2) : '-'}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">median_hold_days</div>
                      <div className="font-semibold">{Number.isFinite(_toNum((acceptance?.turnover as Record<string, unknown> | undefined)?.median_hold_days, NaN)) ? _toNum((acceptance?.turnover as Record<string, unknown> | undefined)?.median_hold_days, NaN).toFixed(2) : '-'}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">weekly_opens_avg</div>
                      <div className="font-semibold">{Number.isFinite(_toNum((acceptance?.turnover as Record<string, unknown> | undefined)?.weekly_opens_avg, NaN)) ? _toNum((acceptance?.turnover as Record<string, unknown> | undefined)?.weekly_opens_avg, NaN).toFixed(2) : '-'}</div>
                    </div>
                  </div>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-2">cost_stress</div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">funding</div>
                      <div className="font-semibold">{_fmtUsd((acceptance?.cost_stress as Record<string, unknown> | undefined)?.funding_usdc, 2)}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">cost_base</div>
                      <div className="font-semibold">{_fmtUsd((acceptance?.cost_stress as Record<string, unknown> | undefined)?.cost_base_usdc, 2)}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">net(1.5x)</div>
                      <div className="font-semibold">{_fmtUsd((acceptance?.cost_stress as Record<string, unknown> | undefined)?.net_1_5x, 2)}</div>
                    </div>
                  </div>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-2">thresholds</div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">funding_share_ideal</div>
                      <div className="font-semibold">{_fmtPct(_toNum((acceptance?.thresholds as Record<string, unknown> | undefined)?.funding_share_ideal, NaN), 0)}</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">weekly_switch_max</div>
                      <div className="font-semibold">{String((acceptance?.thresholds as Record<string, unknown> | undefined)?.weekly_switch_max ?? '-') }</div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-slate-500">liq_warn_buffer_pct</div>
                      <div className="font-semibold">{_fmtPct(_toNum((acceptance?.thresholds as Record<string, unknown> | undefined)?.liq_warn_buffer_pct, NaN), 2)}</div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="overflow-auto border rounded bg-white">
                  <div className="px-3 py-2 text-xs text-slate-500">weekly funding stability</div>
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-slate-600">
                      <tr>
                        <th className="text-left p-2">week</th>
                        <th className="text-right p-2">payment</th>
                        <th className="text-right p-2">cost</th>
                        <th className="text-right p-2">net</th>
                        <th className="text-right p-2">coins</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(((acceptance?.stability as Record<string, unknown> | undefined)?.weekly as Record<string, unknown> | undefined)?.items as unknown[] | undefined)?.slice(-12).map((raw, i) => {
                        const r = (raw ?? {}) as Record<string, unknown>;
                        return (
                          <tr key={`${String(r.key ?? '')}-${i}`} className="border-t">
                            <td className="p-2 font-mono text-xs">{String(r.key ?? '-') }</td>
                            <td className="p-2 text-right">{_fmtUsd(r.payment_usdc, 2)}</td>
                            <td className="p-2 text-right">{_fmtUsd(r.cost_usdc, 2)}</td>
                            <td className="p-2 text-right">{_fmtUsd(r.net_usdc, 2)}</td>
                            <td className="p-2 text-right">{String(r.coins ?? '-') }</td>
                          </tr>
                        );
                      }) ?? (
                        <tr>
                          <td className="p-4 text-slate-500" colSpan={5}>
                            -
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="overflow-auto border rounded bg-white">
                  <div className="px-3 py-2 text-xs text-slate-500">by_coin (top 12)</div>
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-slate-600">
                      <tr>
                        <th className="text-left p-2">coin</th>
                        <th className="text-right p-2">payment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(((acceptance?.stability as Record<string, unknown> | undefined)?.by_coin as Record<string, unknown> | undefined)?.items as unknown[] | undefined)?.slice(0, 12).map((raw, i) => {
                        const r = (raw ?? {}) as Record<string, unknown>;
                        return (
                          <tr key={`${String(r.coin ?? '')}-${i}`} className="border-t">
                            <td className="p-2 font-semibold">{String(r.coin ?? '-') }</td>
                            <td className="p-2 text-right">{_fmtUsd(r.payment_usdc, 2)}</td>
                          </tr>
                        );
                      }) ?? (
                        <tr>
                          <td className="p-4 text-slate-500" colSpan={2}>
                            -
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="universe">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Carry Universe（专用币种池）</span>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">n={String(uniState.n)}</Badge>
                  <Badge variant="outline">ts={_fmtTs(uniState.ts)}</Badge>
                  <Badge variant="outline">{universeFetching ? 'updating' : 'cached'}</Badge>
                  <Button type="button" size="sm" variant="outline" onClick={() => refreshUniverseMutation.mutate()} disabled={refreshUniverseMutation.isPending}>
                    Refresh
                  </Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500">venue</div>
                  <div className="font-semibold">{String(uniState.venue || '-') }</div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500">last_error</div>
                  <div className="font-mono text-xs whitespace-pre-wrap break-words">
                    {uniState.last_error ? JSON.stringify(uniState.last_error) : '-'}
                  </div>
                </div>
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500">cfg_effective</div>
                  <div className="font-mono text-xs whitespace-pre-wrap break-words">
                    {carryUniverse?.cfg_effective ? JSON.stringify(carryUniverse.cfg_effective) : '-'}
                  </div>
                </div>
              </div>

              <div className="mt-4 overflow-auto border rounded bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="text-left p-2">coin</th>
                      <th className="text-right p-2">funding</th>
                      <th className="text-right p-2">spread</th>
                      <th className="text-right p-2">day_ntl</th>
                      <th className="text-right p-2">basis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {universeRows.map((r) => (
                      <tr key={r.coin} className="border-t">
                        <td className="p-2 font-semibold">{r.coin}</td>
                        <td className="p-2 text-right">{Number.isFinite(Number(r.funding_rate)) ? _fmtPct(Number(r.funding_rate), 4) : '-'}</td>
                        <td className="p-2 text-right">{r.spread_bps === null ? '-' : _fmtBps(Number(r.spread_bps), 1)}</td>
                        <td className="p-2 text-right">{Number.isFinite(Number(r.day_ntl)) ? _fmtUsd(Number(r.day_ntl), 0) : '-'}</td>
                        <td className="p-2 text-right">{Number.isFinite(Number(r.basis_bps)) ? _fmtBps(Number(r.basis_bps), 1) : '-'}</td>
                      </tr>
                    ))}
                    {universeRows.length === 0 ? (
                      <tr>
                        <td className="p-6 text-center text-slate-500" colSpan={5}>
                          -
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="config">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>参数配置（隔离：默认 sandbox + disabled）</span>
                <div className="flex items-center gap-2">
                  <Button type="button" variant="outline" onClick={() => setDraft(effective)} disabled={saveMutation.isPending}>
                    Reset
                  </Button>
                  <Button type="button" onClick={() => saveMutation.mutate(draft)} disabled={saveMutation.isPending || (needsConfirmLive && !liveConfirmOk)}>
                    Save
                  </Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="border rounded p-3 bg-white mb-4">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold">实盘开启</div>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          setDraft((p) => ({
                            ...p,
                            carry_trade_sandbox: true,
                            carry_trade_live_enabled: null,
                            carry_trade_hl_trading_enabled: null,
                          }))
                        }
                      >
                        Paper
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        onClick={() =>
                          setDraft((p) => ({
                            ...p,
                            carry_trade_enabled: true,
                            carry_trade_sandbox: false,
                            carry_trade_live_enabled: true,
                            carry_trade_hl_trading_enabled: true,
                          }))
                        }
                      >
                        Live
                      </Button>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="text-xs text-slate-500">输入 LIVE 以确认保存</div>
                    <Input className="w-32" value={liveConfirmText} onChange={(e) => setLiveConfirmText(e.target.value)} placeholder="LIVE" />
                    <Badge variant={needsConfirmLive ? (liveConfirmOk ? 'secondary' : 'destructive') : 'outline'}>
                      {needsConfirmLive ? (liveConfirmOk ? 'confirmed' : 'confirm_required') : 'no_confirm'}
                    </Badge>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_trade_enabled</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_enabled ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_enabled: e.target.value === '1' }))}>
                    <option value="0">false</option>
                    <option value="1">true</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_trade_live_enabled</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_live_enabled === null ? 'inherit' : (draft.carry_trade_live_enabled ? '1' : '0')}
                    onChange={(e) =>
                      setDraft((p) => ({
                        ...p,
                        carry_trade_live_enabled: e.target.value === 'inherit' ? null : e.target.value === '1',
                      }))
                    }
                  >
                    <option value="inherit">inherit</option>
                    <option value="0">false</option>
                    <option value="1">true</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_trade_hl_trading_enabled</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_hl_trading_enabled === null ? 'inherit' : (draft.carry_trade_hl_trading_enabled ? '1' : '0')}
                    onChange={(e) =>
                      setDraft((p) => ({
                        ...p,
                        carry_trade_hl_trading_enabled: e.target.value === 'inherit' ? null : e.target.value === '1',
                      }))
                    }
                  >
                    <option value="inherit">inherit</option>
                    <option value="0">false</option>
                    <option value="1">true</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_trade_sandbox</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_sandbox ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_sandbox: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_trade_profile</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_profile} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_profile: e.target.value }))}>
                    <option value="carry_v1">carry_v1</option>
                    <option value="carry_v2">carry_v2</option>
                    <option value="hedge_v1">hedge_v1</option>
                    <option value="hedge_v2">hedge_v2</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_trade_mode</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_mode} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_mode: e.target.value }))}>
                    <option value="perp">perp</option>
                    <option value="hedge">hedge</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_trade_venue</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_venue} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_venue: e.target.value }))}>
                    <option value="hyperliquid">hyperliquid</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">pre_funding_window_min</div>
                  <Input type="number" value={draft.carry_trade_pre_funding_window_min} onChange={setDraftNumber('carry_trade_pre_funding_window_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">no_exit_pre_funding_min</div>
                  <Input type="number" value={draft.carry_trade_no_exit_pre_funding_min} onChange={setDraftNumber('carry_trade_no_exit_pre_funding_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">post_funding_grace_min</div>
                  <Input type="number" value={draft.carry_trade_post_funding_grace_min} onChange={setDraftNumber('carry_trade_post_funding_grace_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">post_funding_trailing_enabled</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_post_funding_trailing_enabled ? '1' : '0'}
                    onChange={(e) => setDraft((p) => ({ ...p, carry_trade_post_funding_trailing_enabled: e.target.value === '1' }))}
                  >
                    <option value="0">false</option>
                    <option value="1">true</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">post_funding_trailing_max_hold_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_post_funding_trailing_max_hold_min} onChange={setDraftNumber('carry_trade_post_funding_trailing_max_hold_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">post_funding_trailing_arm_min_r</div>
                  <Input type="number" step="0.0005" value={draft.carry_trade_post_funding_trailing_arm_min_r} onChange={setDraftNumber('carry_trade_post_funding_trailing_arm_min_r')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">post_funding_trailing_dist_r</div>
                  <Input type="number" step="0.0005" value={draft.carry_trade_post_funding_trailing_dist_r} onChange={setDraftNumber('carry_trade_post_funding_trailing_dist_r')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">post_funding_require_basis_reversion</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_post_funding_require_basis_reversion ? '1' : '0'}
                    onChange={(e) => setDraft((p) => ({ ...p, carry_trade_post_funding_require_basis_reversion: e.target.value === '1' }))}
                  >
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">post_funding_basis_reversion_mult</div>
                  <Input type="number" step="0.05" value={draft.carry_trade_post_funding_basis_reversion_mult} onChange={setDraftNumber('carry_trade_post_funding_basis_reversion_mult')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">min_abs_funding</div>
                  <Input type="number" step="0.00001" value={draft.carry_trade_min_abs_funding} onChange={setDraftNumber('carry_trade_min_abs_funding')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_bps</div>
                  <Input type="number" step="0.5" value={draft.carry_trade_cost_buffer_bps} onChange={setDraftNumber('carry_trade_cost_buffer_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_adaptive_enabled</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_cost_buffer_adaptive_enabled ? '1' : '0'}
                    onChange={(e) => setDraft((p) => ({ ...p, carry_trade_cost_buffer_adaptive_enabled: e.target.value === '1' }))}
                  >
                    <option value="0">false</option>
                    <option value="1">true</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_p95_mult</div>
                  <Input type="number" step="0.1" value={draft.carry_trade_cost_buffer_p95_mult} onChange={setDraftNumber('carry_trade_cost_buffer_p95_mult')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_p95_lookback_hours</div>
                  <Input type="number" step="1" value={draft.carry_trade_cost_buffer_p95_lookback_hours} onChange={setDraftNumber('carry_trade_cost_buffer_p95_lookback_hours')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_p95_lookback_n</div>
                  <Input type="number" step="1" value={draft.carry_trade_cost_buffer_p95_lookback_n} onChange={setDraftNumber('carry_trade_cost_buffer_p95_lookback_n')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_p95_min_samples</div>
                  <Input type="number" step="1" value={draft.carry_trade_cost_buffer_p95_min_samples} onChange={setDraftNumber('carry_trade_cost_buffer_p95_min_samples')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_min_bps</div>
                  <Input type="number" step="1" value={draft.carry_trade_cost_buffer_min_bps} onChange={setDraftNumber('carry_trade_cost_buffer_min_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cost_buffer_max_bps</div>
                  <Input type="number" step="1" value={draft.carry_trade_cost_buffer_max_bps} onChange={setDraftNumber('carry_trade_cost_buffer_max_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">candidates_top_n</div>
                  <Input type="number" step="1" value={draft.carry_trade_candidates_top_n} onChange={setDraftNumber('carry_trade_candidates_top_n')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">open_top_k</div>
                  <Input type="number" step="1" value={draft.carry_trade_open_top_k} onChange={setDraftNumber('carry_trade_open_top_k')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">max_open_positions</div>
                  <Input type="number" step="1" value={draft.carry_trade_max_open_positions} onChange={setDraftNumber('carry_trade_max_open_positions')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">max_spread_bps</div>
                  <Input type="number" step="0.5" value={draft.carry_trade_max_spread_bps} onChange={setDraftNumber('carry_trade_max_spread_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">max_atr_pct_5m</div>
                  <Input type="number" step="0.001" value={draft.carry_trade_max_atr_pct_5m} onChange={setDraftNumber('carry_trade_max_atr_pct_5m')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">trend_veto_adx</div>
                  <Input type="number" step="1" value={draft.carry_trade_trend_veto_adx} onChange={setDraftNumber('carry_trade_trend_veto_adx')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">use_1m_filter</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_use_1m_filter ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_use_1m_filter: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">1m_spike_atr_mult</div>
                  <Input type="number" step="0.1" value={draft.carry_trade_1m_spike_atr_mult} onChange={setDraftNumber('carry_trade_1m_spike_atr_mult')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">emergency_stoploss_r</div>
                  <Input type="number" step="0.001" value={draft.carry_trade_emergency_stoploss_r} onChange={setDraftNumber('carry_trade_emergency_stoploss_r')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">emergency_stoploss_dynamic_enabled</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_emergency_stoploss_dynamic_enabled ? '1' : '0'}
                    onChange={(e) => setDraft((p) => ({ ...p, carry_trade_emergency_stoploss_dynamic_enabled: e.target.value === '1' }))}
                  >
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">emergency_stoploss_atr_mult</div>
                  <Input type="number" step="0.1" value={draft.carry_trade_emergency_stoploss_atr_mult} onChange={setDraftNumber('carry_trade_emergency_stoploss_atr_mult')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">emergency_stoploss_min_r</div>
                  <Input type="number" step="0.001" value={draft.carry_trade_emergency_stoploss_min_r} onChange={setDraftNumber('carry_trade_emergency_stoploss_min_r')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">emergency_stoploss_max_r</div>
                  <Input type="number" step="0.001" value={draft.carry_trade_emergency_stoploss_max_r} onChange={setDraftNumber('carry_trade_emergency_stoploss_max_r')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">soft_no_exit_reduce_enabled</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_soft_no_exit_reduce_enabled ? '1' : '0'}
                    onChange={(e) => setDraft((p) => ({ ...p, carry_trade_soft_no_exit_reduce_enabled: e.target.value === '1' }))}
                  >
                    <option value="0">false</option>
                    <option value="1">true</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">soft_no_exit_reduce_frac</div>
                  <Input type="number" step="0.05" value={draft.carry_trade_soft_no_exit_reduce_frac} onChange={setDraftNumber('carry_trade_soft_no_exit_reduce_frac')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">soft_no_exit_reduce_spike_required</div>
                  <select
                    className="w-full border rounded h-10 px-3 bg-white"
                    value={draft.carry_trade_soft_no_exit_reduce_spike_required ? '1' : '0'}
                    onChange={(e) => setDraft((p) => ({ ...p, carry_trade_soft_no_exit_reduce_spike_required: e.target.value === '1' }))}
                  >
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">soft_no_exit_reduce_spread_mult</div>
                  <Input type="number" step="0.1" value={draft.carry_trade_soft_no_exit_reduce_spread_mult} onChange={setDraftNumber('carry_trade_soft_no_exit_reduce_spread_mult')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">soft_no_exit_reduce_cooldown_sec</div>
                  <Input type="number" step="1" value={draft.carry_trade_soft_no_exit_reduce_cooldown_sec} onChange={setDraftNumber('carry_trade_soft_no_exit_reduce_cooldown_sec')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">cooldown_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_cooldown_min} onChange={setDraftNumber('carry_trade_cooldown_min')} />
                </div>

                <div className="md:col-span-3 pt-2 text-xs font-semibold text-slate-600">carry_trade_hedge_*</div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rotate_enabled</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_rotate_enabled ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_rotate_enabled: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rotate_edge_diff_min</div>
                  <Input type="number" step="0.00001" value={draft.carry_trade_hedge_rotate_edge_diff_min} onChange={setDraftNumber('carry_trade_hedge_rotate_edge_diff_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rotate_require_net_profit</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_rotate_require_net_profit ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_rotate_require_net_profit: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_min_hold_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_min_hold_min} onChange={setDraftNumber('carry_trade_hedge_min_hold_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_min_hold_strict</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_min_hold_strict ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_min_hold_strict: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_unhedge_enabled</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_unhedge_enabled ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_unhedge_enabled: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_unhedge_trigger_score</div>
                  <Input type="number" step="0.01" value={draft.carry_trade_hedge_unhedge_trigger_score} onChange={setDraftNumber('carry_trade_hedge_unhedge_trigger_score')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_best_timing_wait_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_best_timing_wait_min} onChange={setDraftNumber('carry_trade_hedge_best_timing_wait_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_unhedge_intent_max_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_unhedge_intent_max_min} onChange={setDraftNumber('carry_trade_hedge_unhedge_intent_max_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_unhedge_exit_score</div>
                  <Input type="number" step="0.01" value={draft.carry_trade_hedge_unhedge_exit_score} onChange={setDraftNumber('carry_trade_hedge_unhedge_exit_score')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_unhedge_timeout_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_unhedge_timeout_min} onChange={setDraftNumber('carry_trade_hedge_unhedge_timeout_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_unhedge_cooldown_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_unhedge_cooldown_min} onChange={setDraftNumber('carry_trade_hedge_unhedge_cooldown_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_allow_pre_funding_unhedge</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_allow_pre_funding_unhedge ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_allow_pre_funding_unhedge: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_dyn_leverage_enabled</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_dyn_leverage_enabled ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_dyn_leverage_enabled: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_leverage_min} onChange={setDraftNumber('carry_trade_hedge_leverage_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_max</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_leverage_max} onChange={setDraftNumber('carry_trade_hedge_leverage_max')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_alt_max</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_leverage_alt_max} onChange={setDraftNumber('carry_trade_hedge_leverage_alt_max')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_target_move_r</div>
                  <Input type="number" step="0.005" value={draft.carry_trade_hedge_leverage_target_move_r} onChange={setDraftNumber('carry_trade_hedge_leverage_target_move_r')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_atr_floor</div>
                  <Input type="number" step="0.0005" value={draft.carry_trade_hedge_leverage_atr_floor} onChange={setDraftNumber('carry_trade_hedge_leverage_atr_floor')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_spread_good_bps</div>
                  <Input type="number" step="0.5" value={draft.carry_trade_hedge_leverage_spread_good_bps} onChange={setDraftNumber('carry_trade_hedge_leverage_spread_good_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_spread_bad_bps</div>
                  <Input type="number" step="0.5" value={draft.carry_trade_hedge_leverage_spread_bad_bps} onChange={setDraftNumber('carry_trade_hedge_leverage_spread_bad_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_use_depth</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_leverage_use_depth ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_leverage_use_depth: e.target.value === '1' }))}>
                    <option value="0">false</option>
                    <option value="1">true</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_depth_window_bps</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_leverage_depth_window_bps} onChange={setDraftNumber('carry_trade_hedge_leverage_depth_window_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_leverage_depth_notional_mult</div>
                  <Input type="number" step="0.5" value={draft.carry_trade_hedge_leverage_depth_notional_mult} onChange={setDraftNumber('carry_trade_hedge_leverage_depth_notional_mult')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_circuit_breaker_enabled</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_circuit_breaker_enabled ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_circuit_breaker_enabled: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_cb_ret_1m_min_r</div>
                  <Input type="number" step="0.001" value={draft.carry_trade_hedge_cb_ret_1m_min_r} onChange={setDraftNumber('carry_trade_hedge_cb_ret_1m_min_r')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_cb_ret_5m_atr_mult</div>
                  <Input type="number" step="0.1" value={draft.carry_trade_hedge_cb_ret_5m_atr_mult} onChange={setDraftNumber('carry_trade_hedge_cb_ret_5m_atr_mult')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_cb_spread_bps</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_cb_spread_bps} onChange={setDraftNumber('carry_trade_hedge_cb_spread_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_cb_cooldown_min</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_cb_cooldown_min} onChange={setDraftNumber('carry_trade_hedge_cb_cooldown_min')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rebalance_enabled</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_rebalance_enabled ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_rebalance_enabled: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rebalance_mismatch_pct</div>
                  <Input type="number" step="0.005" value={draft.carry_trade_hedge_rebalance_mismatch_pct} onChange={setDraftNumber('carry_trade_hedge_rebalance_mismatch_pct')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rebalance_reduce_only</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_rebalance_reduce_only ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_rebalance_reduce_only: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rebalance_skip_no_exit</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_trade_hedge_rebalance_skip_no_exit ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_trade_hedge_rebalance_skip_no_exit: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rebalance_min_notional_usdc</div>
                  <Input type="number" step="1" value={draft.carry_trade_hedge_rebalance_min_notional_usdc} onChange={setDraftNumber('carry_trade_hedge_rebalance_min_notional_usdc')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">hedge_rebalance_cooldown_sec</div>
                  <Input type="number" step="10" value={draft.carry_trade_hedge_rebalance_cooldown_sec} onChange={setDraftNumber('carry_trade_hedge_rebalance_cooldown_sec')} />
                </div>

                <div className="md:col-span-3 pt-2 text-xs font-semibold text-slate-600">carry_universe_*</div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_enabled</div>
                  <select className="w-full border rounded h-10 px-3 bg-white" value={draft.carry_universe_enabled ? '1' : '0'} onChange={(e) => setDraft((p) => ({ ...p, carry_universe_enabled: e.target.value === '1' }))}>
                    <option value="1">true</option>
                    <option value="0">false</option>
                  </select>
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_refresh_seconds</div>
                  <Input type="number" step="60" value={draft.carry_universe_refresh_seconds} onChange={setDraftNumber('carry_universe_refresh_seconds')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_min_abs_funding</div>
                  <Input type="number" step="0.00001" value={draft.carry_universe_min_abs_funding} onChange={setDraftNumber('carry_universe_min_abs_funding')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_max_spread_bps</div>
                  <Input type="number" step="0.5" value={draft.carry_universe_max_spread_bps} onChange={setDraftNumber('carry_universe_max_spread_bps')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_min_day_ntl</div>
                  <Input type="number" step="100000" value={draft.carry_universe_min_day_ntl} onChange={setDraftNumber('carry_universe_min_day_ntl')} />
                </div>

                <div className="border rounded p-3 bg-white">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_max_coins</div>
                  <Input type="number" step="10" value={draft.carry_universe_max_coins} onChange={setDraftNumber('carry_universe_max_coins')} />
                </div>

                <div className="border rounded p-3 bg-white md:col-span-3">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_allowlist（CSV）</div>
                  <Input value={draft.carry_universe_allowlist_csv} onChange={(e) => setDraft((p) => ({ ...p, carry_universe_allowlist_csv: e.target.value }))} />
                </div>

                <div className="border rounded p-3 bg-white md:col-span-3">
                  <div className="text-xs text-slate-500 mb-1">carry_universe_denylist（CSV）</div>
                  <Input value={draft.carry_universe_denylist_csv} onChange={(e) => setDraft((p) => ({ ...p, carry_universe_denylist_csv: e.target.value }))} />
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};
