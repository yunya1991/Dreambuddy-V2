
import axios, { AxiosHeaders } from 'axios';

const EXECUTE_TOKEN_STORAGE_KEY = 'execute_token';
const CONFIG_TOKEN_STORAGE_KEY = 'config_token';
const MAINTENANCE_TOKEN_STORAGE_KEY = 'maintenance_token';

const _getCookie = (name: string): string => {
  try {
    if (typeof document === 'undefined') return '';
    const all = String(document.cookie ?? '');
    if (!all) return '';
    const parts = all.split(';');
    for (const raw of parts) {
      const s = raw.trim();
      if (!s) continue;
      const i = s.indexOf('=');
      if (i <= 0) continue;
      const k = s.slice(0, i).trim();
      if (k !== name) continue;
      return decodeURIComponent(s.slice(i + 1));
    }
    return '';
  } catch {
    return '';
  }
};

export type UiEnv = 'prod' | 'explore' | 'pilot';

export const getUiEnv = (): UiEnv => {
  try {
    if (typeof window === 'undefined') return 'prod';
    const port = Number(String(window.location?.port ?? '').trim() || NaN);
    if (port === 3002) return 'explore';
    if (port === 3003) return 'pilot';
    return 'prod';
  } catch {
    return 'prod';
  }
};

export const getCsrfToken = (): string => {
  try {
    const env = getUiEnv();
    const v = String(_getCookie(`${env}_ml_csrf`) ?? '').trim();
    if (v) return v;
  } catch {
    void 0;
  }
  return String(_getCookie('ml_csrf') ?? '').trim();
};

export const getExecuteToken = (): string => {
  try {
    if (typeof window === 'undefined') return '';
    return String(window.localStorage.getItem(EXECUTE_TOKEN_STORAGE_KEY) ?? '').trim();
  } catch {
    return '';
  }
};

export const setExecuteToken = (token: string): void => {
  try {
    if (typeof window === 'undefined') return;
    const next = String(token ?? '').trim();
    if (next) {
      window.localStorage.setItem(EXECUTE_TOKEN_STORAGE_KEY, next);
    } else {
      window.localStorage.removeItem(EXECUTE_TOKEN_STORAGE_KEY);
    }
  } catch {
    void 0;
  } finally {
    try {
      const v = getExecuteToken();
      for (const fn of _executeTokenListeners) fn(v);
    } catch {
      void 0;
    }
  }
};

const _executeTokenListeners = new Set<(token: string) => void>();

export const subscribeExecuteToken = (listener: (token: string) => void): (() => void) => {
  _executeTokenListeners.add(listener);
  return () => {
    _executeTokenListeners.delete(listener);
  };
};

export const getConfigToken = (): string => {
  try {
    if (typeof window === 'undefined') return '';
    return String(window.localStorage.getItem(CONFIG_TOKEN_STORAGE_KEY) ?? '').trim();
  } catch {
    return '';
  }
};

export const setConfigToken = (token: string): void => {
  try {
    if (typeof window === 'undefined') return;
    const next = String(token ?? '').trim();
    if (next) {
      window.localStorage.setItem(CONFIG_TOKEN_STORAGE_KEY, next);
    } else {
      window.localStorage.removeItem(CONFIG_TOKEN_STORAGE_KEY);
    }
  } catch {
    void 0;
  } finally {
    try {
      const v = getConfigToken();
      for (const fn of _configTokenListeners) fn(v);
    } catch {
      void 0;
    }
  }
};

const _configTokenListeners = new Set<(token: string) => void>();

export const subscribeConfigToken = (listener: (token: string) => void): (() => void) => {
  _configTokenListeners.add(listener);
  return () => {
    _configTokenListeners.delete(listener);
  };
};

export const getMaintenanceToken = (): string => {
  try {
    if (typeof window === 'undefined') return '';
    return String(window.localStorage.getItem(MAINTENANCE_TOKEN_STORAGE_KEY) ?? '').trim();
  } catch {
    return '';
  }
};

export const setMaintenanceToken = (token: string): void => {
  try {
    if (typeof window === 'undefined') return;
    const next = String(token ?? '').trim();
    if (next) {
      window.localStorage.setItem(MAINTENANCE_TOKEN_STORAGE_KEY, next);
    } else {
      window.localStorage.removeItem(MAINTENANCE_TOKEN_STORAGE_KEY);
    }
  } catch {
    void 0;
  } finally {
    try {
      const v = getMaintenanceToken();
      for (const fn of _maintenanceTokenListeners) fn(v);
    } catch {
      void 0;
    }
  }
};

const _maintenanceTokenListeners = new Set<(token: string) => void>();

export const subscribeMaintenanceToken = (listener: (token: string) => void): (() => void) => {
  _maintenanceTokenListeners.add(listener);
  return () => {
    _maintenanceTokenListeners.delete(listener);
  };
};

export const getOperatorToken = (): string => {
  const executeToken = getExecuteToken();
  if (executeToken) return executeToken;
  const configToken = getConfigToken();
  if (configToken) return configToken;
  return getMaintenanceToken();
};

export const hasOperatorToken = (): boolean => {
  return Boolean(getOperatorToken().trim());
};

const EXPLICIT_API_BASE = import.meta.env.VITE_API_BASE;
const HAS_EXPLICIT_API_BASE = typeof EXPLICIT_API_BASE === 'string' && Boolean(EXPLICIT_API_BASE.trim());

const API_BASE = (() => {
  const base = EXPLICIT_API_BASE;
  if (typeof base === 'string' && base.trim()) {
    return base.trim();
  }
  if (import.meta.env.DEV) {
    return '/api';
  }
  if (typeof window === 'undefined') {
    return '';
  }

  const { hostname, port } = window.location;
  const isLocalhost = hostname === '127.0.0.1' || hostname === 'localhost';

  if (!port) {
    return '';
  }
  if (port === '8092') {
    return '';
  }
  if (isLocalhost) {
    return '/api';
  }
  return '';
})();

const SHOULD_PROBE_API_PROXY =
  import.meta.env.DEV &&
  !HAS_EXPLICIT_API_BASE &&
  typeof window !== 'undefined' &&
  (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost');

const SHOULD_GUARD_EXPLICIT_LOCAL_API_BASE =
  HAS_EXPLICIT_API_BASE &&
  typeof window !== 'undefined' &&
  (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost');

const SHOULD_PROBE_LOCAL_BACKEND =
  !import.meta.env.DEV &&
  !HAS_EXPLICIT_API_BASE &&
  typeof window !== 'undefined' &&
  (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') &&
  (
    String(import.meta.env.VITE_ENABLE_LOCAL_BACKEND_FALLBACK ?? '').trim().toLowerCase() === '1' ||
    String(import.meta.env.VITE_ENABLE_LOCAL_BACKEND_FALLBACK ?? '').trim().toLowerCase() === 'true' ||
    String(import.meta.env.VITE_ENABLE_LOCAL_BACKEND_FALLBACK ?? '').trim().toLowerCase() === 'yes' ||
    String(import.meta.env.VITE_ENABLE_LOCAL_BACKEND_FALLBACK ?? '').trim().toLowerCase() === 'on' ||
    String(import.meta.env.VITE_ENABLE_LOCAL_BACKEND_FALLBACK ?? '').trim() === ''
  );

let _resolvedLocalBackendBase: string | null = null;
let _resolveLocalBackendBasePromise: Promise<string> | null = null;

const _probeBackend = async (port: number, timeoutMs: number = 250): Promise<boolean> => {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/health`, {
      signal: ctrl.signal,
      headers: {
        accept: 'application/json',
      },
    });
    if (!res.ok) return false;
    const json = (await res.json()) as { ok?: unknown };
    return json?.ok === true;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
};

let _explicitLocalBaseOk: boolean | null = null;
let _explicitLocalBaseProbePromise: Promise<boolean> | null = null;
let _explicitLocalBaseKey: string | null = null;
let _explicitLocalBaseTs: number = 0;

const _probeExplicitLocalBaseUrl = async (baseURL: string, timeoutMs: number = 250): Promise<boolean> => {
  const raw = String(baseURL ?? '').trim();
  if (!raw) return false;
  const now = Date.now();
  if (_explicitLocalBaseKey === raw && _explicitLocalBaseOk != null && now - _explicitLocalBaseTs < 5000) return _explicitLocalBaseOk;
  if (_explicitLocalBaseKey === raw && _explicitLocalBaseProbePromise) return _explicitLocalBaseProbePromise;

  _explicitLocalBaseKey = raw;
  _explicitLocalBaseProbePromise = (async () => {
    let u: URL;
    try {
      u = new URL(raw);
    } catch {
      _explicitLocalBaseOk = false;
      _explicitLocalBaseTs = Date.now();
      return _explicitLocalBaseOk;
    }
    const host = String(u.hostname ?? '').trim().toLowerCase();
    if (host !== '127.0.0.1' && host !== 'localhost') {
      _explicitLocalBaseOk = false;
      _explicitLocalBaseTs = Date.now();
      return _explicitLocalBaseOk;
    }
    const p = Number(String(u.port ?? '').trim() || NaN);
    if (!Number.isFinite(p) || p <= 0) {
      _explicitLocalBaseOk = false;
      _explicitLocalBaseTs = Date.now();
      return _explicitLocalBaseOk;
    }
    if (p !== 8092) {
      _explicitLocalBaseOk = false;
      _explicitLocalBaseTs = Date.now();
      return _explicitLocalBaseOk;
    }
    _explicitLocalBaseOk = await _probeBackend(p, timeoutMs);
    _explicitLocalBaseTs = Date.now();
    return _explicitLocalBaseOk;
  })();
  return _explicitLocalBaseProbePromise;
};

let _apiProxyOk: boolean | null = null;
let _apiProxyProbePromise: Promise<boolean> | null = null;

const _probeApiProxy = async (timeoutMs: number = 1500): Promise<boolean> => {
  if (_apiProxyOk != null) return _apiProxyOk;
  if (_apiProxyProbePromise) return _apiProxyProbePromise;
  _apiProxyProbePromise = (async () => {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch('/api/health', {
        signal: ctrl.signal,
        headers: {
          accept: 'application/json',
        },
      });
      if (!res.ok) {
        _apiProxyOk = false;
        return _apiProxyOk;
      }
      const json = (await res.json()) as { ok?: unknown };
      _apiProxyOk = json?.ok === true;
      return _apiProxyOk;
    } catch {
      _apiProxyOk = false;
      return _apiProxyOk;
    } finally {
      clearTimeout(t);
    }
  })();
  return _apiProxyProbePromise;
};

const _resolveLocalBackendBase = async (): Promise<string> => {
  if (_resolvedLocalBackendBase) return _resolvedLocalBackendBase;
  if (_resolveLocalBackendBasePromise) return _resolveLocalBackendBasePromise;
  _resolveLocalBackendBasePromise = (async () => {
    _resolvedLocalBackendBase = 'http://127.0.0.1:8092';
    return _resolvedLocalBackendBase;
  })();
  return _resolveLocalBackendBasePromise;
};

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  return (async () => {
    if (SHOULD_GUARD_EXPLICIT_LOCAL_API_BASE) {
      const isRelativeUrl = typeof config.url === 'string' && !/^https?:\/\//i.test(config.url);
      const baseURL = typeof config.baseURL === 'string' ? config.baseURL : '';
      if (isRelativeUrl && baseURL) {
        const explicitOk = await _probeExplicitLocalBaseUrl(baseURL, 250);
        if (!explicitOk) {
          config.baseURL = '/api';
          const proxyOk = await _probeApiProxy(400);
          if (!proxyOk) {
            config.baseURL = await _resolveLocalBackendBase();
          }
        }
      }
    }

    if (SHOULD_PROBE_API_PROXY) {
      const isRelativeUrl = typeof config.url === 'string' && !/^https?:\/\//i.test(config.url);
      const baseURL = typeof config.baseURL === 'string' ? config.baseURL : '';
      if (isRelativeUrl && baseURL === '/api') {
        await _probeApiProxy();
      }
    }

    if (SHOULD_PROBE_LOCAL_BACKEND) {
      const isRelativeUrl = typeof config.url === 'string' && !/^https?:\/\//i.test(config.url);
      if (isRelativeUrl) {
        const baseURL = typeof config.baseURL === 'string' ? config.baseURL : '';
        if (baseURL === '/api') {
          const proxyOk = await _probeApiProxy(400);
          if (!proxyOk) {
            config.baseURL = await _resolveLocalBackendBase();
          }
        } else if (!baseURL || baseURL === 'http://127.0.0.1:8092') {
          config.baseURL = await _resolveLocalBackendBase();
        }
      }
    }

    const executeToken = getExecuteToken();
    const configToken = getConfigToken();
    const maintenanceToken = getMaintenanceToken();
    if (executeToken || configToken || maintenanceToken) {
      const headers = config.headers instanceof AxiosHeaders ? config.headers : AxiosHeaders.from(config.headers);
      if (executeToken) {
        if (!headers.has('X-Webhook-Token')) headers.set('X-Webhook-Token', executeToken);
        if (!headers.has('X-Execute-Token')) headers.set('X-Execute-Token', executeToken);
      }
      const effectiveConfigToken = configToken || executeToken;
      if (effectiveConfigToken && !headers.has('X-Config-Token')) headers.set('X-Config-Token', effectiveConfigToken);
      const effectiveMaintenanceToken = maintenanceToken || executeToken;
      if (effectiveMaintenanceToken && !headers.has('X-Maintenance-Token')) headers.set('X-Maintenance-Token', effectiveMaintenanceToken);
      config.headers = headers;
    }

    try {
      const m = String(config.method ?? 'get').toUpperCase();
      if (m !== 'GET' && m !== 'HEAD' && m !== 'OPTIONS') {
        const csrf = getCsrfToken();
        if (csrf) {
          const headers = config.headers instanceof AxiosHeaders ? config.headers : AxiosHeaders.from(config.headers);
          if (!headers.has('X-CSRF-Token')) {
            headers.set('X-CSRF-Token', csrf);
          }
          config.headers = headers;
        }
      }
    } catch {
      void 0;
    }
    return config;
  })();
});

api.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    try {
      const cfg = (error as { config?: Record<string, unknown> } | null | undefined)?.config;
      if (!cfg || typeof cfg !== 'object') throw error;
      if (cfg.__local_backend_retry_done) throw error;
      const url = String(cfg.url ?? '');
      const isRelativeUrl = !!url && !/^https?:\/\//i.test(url);
      const baseURL = String(cfg.baseURL ?? '');
      if (SHOULD_PROBE_LOCAL_BACKEND && isRelativeUrl && baseURL === '/api') {
        cfg.__local_backend_retry_done = true;
        cfg.baseURL = await _resolveLocalBackendBase();
        return api.request(cfg);
      }
    } catch {
      throw error;
    }
    throw error;
  },
);

export type AuthMeResponse = { ok: boolean; ts?: number; actor?: string; role?: string; csrf_token?: string };
export type AuthLoginResponse = { ok: boolean; ts?: number; actor?: string; role?: string; csrf_token?: string; error?: string };
export type AuthLogoutResponse = { ok: boolean; ts?: number };

export type DocSnippetResponse = {
  ok: boolean;
  doc_path?: string;
  section?: string;
  title?: string;
  start_line?: number;
  end_line?: number;
  text?: string;
  error?: string;
};

export const fetchDocSnippet = async (params: { doc?: string; section?: string; start_line?: number; end_line?: number; max_chars?: number } | undefined) => {
  const doc = String(params?.doc ?? '技术文档.md').trim() || '技术文档.md';
  const section = String(params?.section ?? '').trim();
  const start_line = Number.isFinite(Number(params?.start_line)) ? Math.max(1, Math.trunc(Number(params?.start_line))) : undefined;
  const end_line = Number.isFinite(Number(params?.end_line)) ? Math.max(1, Math.trunc(Number(params?.end_line))) : undefined;
  const max_chars = Number.isFinite(Number(params?.max_chars)) ? Number(params?.max_chars) : 20000;
  return (await api.get<DocSnippetResponse>('/doc/snippet', { params: { doc, section, start_line, end_line, max_chars } })).data;
};

export const authMe = async (): Promise<AuthMeResponse> => {
  const { data } = await api.get<AuthMeResponse>('/auth/me');
  return data;
};

export const authLogin = async (payload: { username: string; password: string }): Promise<AuthLoginResponse> => {
  const { data } = await api.post<AuthLoginResponse>('/auth/login', payload);
  return data;
};

export const authLogout = async (): Promise<AuthLogoutResponse> => {
  const { data } = await api.post<AuthLogoutResponse>('/auth/logout', {});
  return data;
};

export interface Metrics {
  signals: number;
  orders: number;
  orders_total?: number;
  orders_live?: number;
  orders_live_exchange?: number;
  orders_live_filled?: number;
  orders_shadow?: number;
  orders_execute?: number;
  orders_execute_exchange?: number;
  orders_execute_filled?: number;
  orders_observed?: number;
  orders_simulated?: number;
  ts: number;
  active_model?: string;
}

export interface SignalRejectStats {
  ok: boolean;
  limit: number;
  total_events: number;
  with_decision: number;
  by_decision: Record<string, number>;
  by_reason: Record<string, number>;
}

export interface ModelInfo {
  ok: boolean;
  models: string[];
  active?: string;
}

export type EngineeringIndexResponse = {
  ok: boolean;
  ts: number;
  docs?: { path?: string; section?: string };
  backend?: { entry?: string; routes?: string[]; functions?: string[] };
  frontend?: { app?: string; pages?: Record<string, string> };
  state_files?: Record<string, string>;
  faq?: Record<string, string>;
};

export type ModelArtifact = {
  name: string;
  path?: string;
  ext?: string;
  kind?: string;
  size_bytes?: number;
  mtime_ms?: number;
  loaded?: boolean;
  active?: boolean;
};

export type ModelArtifactsResponse = {
  ok: boolean;
  active?: string;
  loaded?: string[];
  models_dir?: string;
  dirs?: string[];
  artifacts?: ModelArtifact[];
};

export interface Order {
  id: string;
  pair: string;
  side: 'long' | 'short' | 'close' | string;
  action?: 'open' | 'close' | 'reduce' | string;
  size: number;
  mode: string;
  tag: string;
  ts: number;
  status: string;
  p: number;
  pc: number;
  sl?: number;
  tp?: number;
  regime?: string;
  model?: string;
  strategy_id?: string | null;
  strategy_version?: string | null;
  group_id?: string | null;
  system_id?: string | null;
  book_id?: string | null;
  exchange?: string;
  exchange_oid?: string | number | null;
  exec?: Record<string, unknown>;
  features?: Record<string, unknown>;
  committee?: Record<string, { p: number; pc: number; vote: string }>;
  event_id?: string | null;
  arena_shadow?: unknown;
  entry_type?: 'open' | 'addon';
  base_order_id?: string | null;
  pos_notional_usdc?: number;
  pos_prev_notional_usdc?: number;
  pos_entry_count?: number;
  gate?: Record<string, unknown>;
  pos_snapshot?: Record<string, unknown> | null;
  ab_owner?: string | null;
  instrument_type?: string | null;
  owner_contrib?: Record<string, number> | null;
  ab_settlement?: {
    pnl_by_owner?: Record<string, number>;
    notional_by_owner?: Record<string, number>;
    last_ts?: number;
  } | null;
}

export interface Signal {
  id: string;
  event_id?: string | null;
  signal_schema_version?: number;
  pair: string;
  side: 'long' | 'short';
  tag: string;
  ts: number;
  ts_emit_ms?: number;
  ingested_ms?: number;
  action?: 'open' | 'close' | 'observe' | string;
  timeframe?: string;
  bar_open_ms?: number;
  bar_close_ms?: number;
  bar_closed?: boolean;
  source?: string;
  features: Record<string, unknown>;
  strategy_id?: string | null;
  strategy_version?: string | null;
  group_id?: string | null;
  feature_set_id?: string | null;
  confidence?: number;
  decision_info?: {
    ts_ms?: number;
    decision?: string;
    decision_code?: number;
    reason?: string | null;
    p?: number | null;
    pc?: number | null;
    threshold?: number | null;
    regime?: string | null;
    arena?: {
      agg?: {
        threshold?: number | null;
        regime?: string | null;
        chosen?: string | null;
        explore?: boolean;
        n_models?: number;
        n_eligible?: number;
        n_take?: number;
        pc_mean?: number | null;
        pc_weighted?: number | null;
      };
      ref?: unknown;
    };
    committee?: unknown;
    out?: unknown;
  };
  arena?: {
    pair: string;
    side: string;
    tag?: unknown;
    ts: number;
    regime?: string;
    threshold?: number;
    chosen?: string | null;
    explore?: boolean;
    models?: Record<string, {
      p?: number;
      pc?: number;
      take?: boolean;
      weight?: number;
      capital_u?: number;
      eligible?: boolean;
    }>;
  };
  ab_owner?: string | null;
  owner_contrib?: Record<string, number> | null;
}

export interface Config {
  threshold_trend: number;
  threshold_chop: number;
  regime_method?: string;
  min_trade_size: number;
  max_trade_size: number;
  dry_run: boolean;
  signals_auto_decision?: boolean;
  signals_v1_restrict_trigger_non_feeder?: boolean;

  execution_venue?: string;
  live_trading_enabled?: boolean;
  strategy_live_trading_enabled?: boolean | null;
  three_screen_live_trading_enabled?: boolean | null;
  quant_live_trading_enabled?: boolean | null;
  pilot_canary_max_notional_usdc?: number;
  strategy_tier_trading_enabled?: boolean;
  strategy_tier_default?: string;

  quant_auto_mode?: string;
  quant_auto_enabled?: boolean;
  quant_auto_btceth_enabled?: boolean;
  quant_auto_btcalts_enabled?: boolean;
  quant_auto_state_check_interval_sec?: number;
  quant_auto_daily_loss_limit_pct?: number;
  quant_auto_weekly_loss_limit_pct?: number;
  quant_auto_net_btc_pct_max?: number;
  quant_auto_pair_notional_usdc_max?: number;
  quant_auto_max_open_pairs_total?: number;

  quant_auto_btcalts_strategy_mode?: string;

  quant_auto_btcalts_capacity_turnover_frac?: number;
  quant_auto_btcalts_capacity_depth_frac?: number;
  quant_pairs_btcalt_capacity_turnover_frac?: number;
  quant_pairs_btcalt_capacity_depth_frac?: number;

  quant_auto_btcalts_scan_n?: number;
  quant_auto_btcalts_open_per_tick?: number;
  quant_auto_btcalts_cooldown_bars?: number;
  quant_auto_btcalts_max_open_pairs?: number;
  quant_auto_btcalts_max_per_cluster?: number;
  quant_auto_btcalts_macro_trend_required?: boolean;
  quant_auto_btcalts_z_bias_min?: number;
  quant_auto_btcalts_z_bias_weight?: number;
  quant_auto_btcalts_notional_nontrend_mult?: number;
  quant_auto_btcalts_open_per_tick_nontrend?: number;
  quant_auto_btcalts_max_open_pairs_nontrend?: number;
  quant_auto_btcalts_dynamic_hedge_enabled?: boolean;
  quant_auto_btcalts_dynamic_hedge_step?: number;
  quant_auto_btcalts_btc_hedge_frac?: number;

  strategy_exit_enabled?: boolean;
  loss_gate_enabled?: boolean;
  exit_shadow_mode?: boolean;
  quant_pairs_btceth_exit_pnl_enabled?: boolean;
  quant_pairs_btcalt_exit_pnl_enabled?: boolean;
  carry_trade_soft_no_exit_reduce_enabled?: boolean;
  hl_trading_enabled?: boolean;
  aster_trading_enabled?: boolean;
  live_execute_allow_remote?: boolean;
  entry_fixed_notional_enabled?: boolean;
  entry_fixed_notional_usdc?: number;
  entry_min_notional_usdc?: number;
  entry_max_notional_usdc?: number;
  aster_min_notional_usdc?: number;
  aster_max_notional_usdc?: number;
  aster_adjust_to_min?: boolean;
  aster_max_bump_ratio?: number;

  hl_min_notional_usdc?: number;
  hl_max_notional_usdc?: number;

  hl_default_leverage?: number;
  aster_default_leverage?: number;

  leverage_dynamic_enabled?: boolean;
  leverage_dynamic_min?: number;
  leverage_dynamic_max?: number;
  serving_shadow_mode?: boolean;
  serving_canary_enabled?: boolean;
  serving_canary_size_frac?: number;
  serving_canary_pairs?: string[];

  trade_whitelist_enabled?: boolean;
  trade_whitelist_enforcement?: string;
  trade_whitelist?: string[];

  whitelist_gate_enabled?: boolean;
  whitelist_gate_dynamic_enabled?: boolean;
  whitelist_gate_vote_rule_base?: string;
  whitelist_gate_vote_rule_relax?: string;
  whitelist_gate_eval_window_hours?: number;
  whitelist_gate_target_entries_per_day?: number;
  whitelist_gate_resume_entries_per_day?: number;
  whitelist_gate_pnl_window_days?: number;
  whitelist_gate_pnl_floor?: number;
  whitelist_gate_dd_ceiling?: number;
  whitelist_gate_min_switch_interval_hours?: number;

  max_daily_loss?: number;
  max_weekly_loss?: number;
  strategy_max_daily_loss?: number;
  strategy_max_weekly_loss?: number;
  quant_max_daily_loss?: number;
  quant_max_weekly_loss?: number;
  carry_max_daily_loss?: number;
  carry_max_weekly_loss?: number;
  account_loss_gate_enabled?: boolean;
  account_max_daily_loss?: number;
  account_max_weekly_loss?: number;
  max_open_trades?: number;

  max_orders_per_minute?: number;
  order_rate_window_sec?: number;

  signals_dedup_ttl_sec?: number;
  signals_dedup_bucket_sec?: number;
  signals_pair_side_cooldown_sec?: number;
  signals_coin_side_cooldown_sec?: number;
  entry_inflight_cooldown_sec?: number;
  coin_freeze_post_close_hours?: number;

  pc_hysteresis_delta?: number;

  signals_v1_confirm_enabled?: boolean;
  signals_v1_confirm_n?: number;
  signals_v1_confirm_m?: number;

  correlation_threshold?: number;
  correlation_lookback_hours?: number;
  correlation_cache_ttl_sec?: number;
  correlation_cache_bucket_sec?: number;

  label_horizon_hours?: number;
  label_mode?: string;
  return_clip_abs?: number;
  auto_train_min_samples?: number;
  online_train_min_new_samples?: number;
  online_label_max_per_run?: number;
  eval_import_hard_scan_multiplier?: number;
  eval_import_time_budget_sec?: number;
  eval_history_max?: number;

  weight_time_decay?: number;
  weight_target_atr_pct?: number;

  stake_target_atr_pct?: number;
  stake_atr_scale_min?: number;
  stake_atr_scale_max?: number;
  kelly_multiplier?: number;
  kelly_lookback_samples?: number;
  kelly_min_samples?: number;
  kelly_default_b?: number;
  kelly_by_pair?: boolean;

  scaler_type?: string;
  online_scaler_window?: number;

  threshold_grid_step?: number;
  threshold_fit_window?: number;
  threshold_grid_lo?: number;
  threshold_grid_hi?: number;
  threshold_min_trades?: number;
  threshold_ttl_minutes?: number;

  calibration_min_samples_per_regime?: number;
  platt_l2?: number;
  platt_lr?: number;
  platt_steps?: number;

  strategy_meta?: Record<string, Record<string, unknown>>;
  strategy_pool_meta?: Record<string, Record<string, unknown>>;
  three_screen_use_ml_vote?: boolean;
  signal_group_meta?: Record<string, { pc_threshold_min?: number; [key: string]: unknown }>;
  signal_strategy_threshold?: Record<string, number | null>;

  strategy_subportfolio_enabled?: boolean;
  strategy_subportfolio_init_equity_usdc?: number;
  strategy_subportfolio_max_dd?: number;
  strategy_subportfolio_max_daily_loss?: number;
  strategy_subportfolio_max_weekly_loss?: number;
  strategy_subportfolio_dd_cooldown_sec?: number;
  strategy_subportfolio_daily_cooldown_sec?: number;
  strategy_subportfolio_weekly_cooldown_sec?: number;
  strategy_subportfolio_vol_target_atr_pct?: number;
  strategy_subportfolio_vol_scale_min?: number;
  strategy_subportfolio_vol_scale_max?: number;

  strategy_reward_enabled?: boolean;
  strategy_reward_window?: number;
  strategy_reward_pf_up?: number;
  strategy_reward_pf_down?: number;
  strategy_reward_maxdd_up?: number;
  strategy_reward_maxdd_down?: number;
  strategy_reward_step_up?: number;
  strategy_reward_step_down?: number;
  strategy_weight_floor?: number;
  strategy_weight_cap?: number;

  arena_enabled?: boolean;

  arena_entry_min_votes?: number;
  arena_entry_min_weight_sum?: number;
  arena_entry_weight_sum_floor_votes?: number;
  arena_entry_vote_eligible_only?: boolean;
  arena_entry_relax_quorum?: boolean;

  elastic_gating_enabled?: boolean;
  elastic_vote_rule?: string;

  entry_risk_gate_enabled?: boolean;
  entry_risk_gate_long_max?: number;
  entry_risk_gate_short_max?: number;

  exit_risk_gate_enabled?: boolean;
  exit_risk_gate_long_thr?: number;
  exit_risk_gate_short_thr?: number;
  exit_risk_gate_cooldown_min?: number;

  exit_apply_leverage_to_thresholds?: boolean;
  exit_l0_max_hold_sec?: number;
  exit_l0_max_unrealized_loss_pct?: number;
  exit_l0_liq_buffer_pct?: number;
  exit_l1_enabled?: boolean;
  exit_l1_mode?: string;
  exit_l1_hysteresis_n?: number;
  exit_l1_action_cooldown_sec?: number;
  exit_l1_hold_risk_reduce_threshold?: number;
  exit_l1_hold_risk_close_threshold?: number;
  exit_l1_reduce_min_profit_pct?: number;
  exit_l1_reduce_base_frac?: number;
  exit_l1_reduce_max_frac?: number;
  exit_tb_enabled?: boolean;
  exit_tb_sl_atr_mult?: number;
  exit_tb_tp_atr_mult?: number;
  exit_tb_time_barrier_sec?: number;
  exit_tb_take_reduce_frac?: number;
  exit_tb_time_reduce_frac?: number;
  exit_tstp_enabled?: boolean;
  exit_l2_reduce_frac?: number;
  exit_l2_take_profit_pct?: number;
  exit_l2_trailing_retrace_pct?: number;

  addon_entry_enabled?: boolean;
  addon_entry_max_count?: number;
  addon_entry_min_interval_sec?: number;

  entry_macro_addon_block_counter?: boolean;
  entry_macro_gate_extreme_risk?: boolean;
  entry_macro_gate_extreme_risk_allow_notional_usdc?: number;
  entry_macro_btceth_hard_gate_enabled?: boolean;
  entry_macro_btceth_hard_gate_mode?: string;
  entry_macro_btceth_hard_gate_auto_period_seconds?: number;
  entry_macro_btceth_hard_gate_auto_unlock_cooldown_hours?: number;
  entry_macro_btceth_hard_gate_allow_notional_usdc?: number;
  entry_macro_btceth_hard_gate_risk_pct_max?: number;
  entry_macro_btceth_hard_gate_only_with_macro_alignment?: boolean;
  entry_macro_btceth_hard_gate_fail_open?: boolean;
  entry_macro_btceth_hard_gate_apply_to_addon?: boolean;
  entry_btc_tv_hard_gate_apply_to_addon?: boolean;

  strategy_btc_corr_gate_enabled?: boolean;
  strategy_btc_corr_threshold?: number;
  strategy_btc_corr_hysteresis_delta?: number;

  carry_trade_enabled?: boolean;
  carry_trade_live_enabled?: boolean | null;
  carry_trade_sandbox?: boolean;
  carry_trade_venue?: string;
  carry_trade_pre_funding_window_min?: number;
  carry_trade_no_exit_pre_funding_min?: number;
  carry_trade_post_funding_grace_min?: number;
  carry_trade_min_abs_funding?: number;
  carry_trade_cost_buffer_bps?: number;
  carry_trade_candidates_top_n?: number;
  carry_trade_open_top_k?: number;
  carry_trade_max_open_positions?: number;
  carry_trade_max_spread_bps?: number;
  carry_trade_max_atr_pct_5m?: number;
  carry_trade_trend_veto_adx?: number;
  carry_trade_use_1m_filter?: boolean;
  carry_trade_1m_spike_atr_mult?: number;
  carry_trade_emergency_stoploss_r?: number;
  carry_trade_cooldown_min?: number;

  quant_pairs_btceth_exit_z?: number;
  quant_pairs_btceth_stop_z?: number;
  quant_pairs_btceth_z_exit_confirm_bars?: number;
  quant_pairs_btceth_pnl_stop_loss_r?: number;
  quant_pairs_btceth_pnl_take_profit_r?: number;
  quant_pairs_btceth_pnl_min_on_z_exit_r?: number;
  quant_pairs_btceth_cooldown_bars_after_exit?: number;
  quant_pairs_btceth_emergency_close_on_gate_violation?: boolean;

  quant_pairs_btcalt_exit_z?: number;
  quant_pairs_btcalt_stop_z?: number;
  quant_pairs_btcalt_z_exit_confirm_bars?: number;
  quant_pairs_btcalt_pnl_stop_loss_r?: number;
  quant_pairs_btcalt_pnl_take_profit_r?: number;
  quant_pairs_btcalt_pnl_min_on_z_exit_r?: number;

  paramopt_portfolio_u_r_min?: number;
  paramopt_portfolio_dd_guard?: number;
  paramopt_portfolio_tail_guard?: number;
  paramopt_portfolio_order_fail_delta_guard?: number;
  paramopt_portfolio_rollback_consecutive_gate_fail_k?: number;
}

export type ConfigPatch = Partial<Config> & {
  confirm_live?: boolean;
};

export type Health = {
  ok?: boolean;
  ts?: number;
  [key: string]: unknown;
};

export const fetchMetrics = async () => (await api.get<Metrics>('/metrics')).data;
export const fetchHealth = async () => (await api.get<Health>('/health')).data;
export const fetchModels = async () => (await api.get<ModelInfo>('/models')).data;
export const fetchModelArtifacts = async () => (await api.get<ModelArtifactsResponse>('/models/artifacts')).data;
export const fetchConfig = async () => (await api.get<Config>('/config/get')).data;
export const fetchEngineeringIndex = async () => (await api.get<EngineeringIndexResponse>('/engineering/index')).data;
export const updateConfig = async (cfg: ConfigPatch) => {
  const env = getUiEnv();
  const next: ConfigPatch = { ...cfg };
  if (env === 'explore') {
    if (next.dry_run === false) next.dry_run = true;
    if (next.live_trading_enabled === true) next.live_trading_enabled = false;
    if (next.strategy_live_trading_enabled === true) next.strategy_live_trading_enabled = false;
    if (next.three_screen_live_trading_enabled === true) next.three_screen_live_trading_enabled = false;
    if (next.quant_live_trading_enabled === true) next.quant_live_trading_enabled = false;
    if (next.hl_trading_enabled === true) next.hl_trading_enabled = false;
    if (next.aster_trading_enabled === true) next.aster_trading_enabled = false;
  } else if (env === 'pilot') {
    if (next.serving_canary_enabled === false) next.serving_canary_enabled = true;
    if (next.trade_whitelist_enabled === false) next.trade_whitelist_enabled = true;
    if (typeof next.trade_whitelist_enforcement === 'string' && next.trade_whitelist_enforcement.toLowerCase() !== 'hard') {
      next.trade_whitelist_enforcement = 'hard';
    }
    if (typeof (next as Record<string, unknown>)?.pilot_canary_max_notional_usdc === 'number') {
      const v = Number((next as Record<string, unknown>)?.pilot_canary_max_notional_usdc);
      if (Number.isFinite(v) && v > 200) (next as Record<string, unknown>).pilot_canary_max_notional_usdc = 200;
    }
  }
  return (
    await api.post<{ ok: boolean; config: Config; runtime_config_version?: string | null; applied_keys?: string[] }>(
      '/config/set',
      next,
      { timeout: 120000 },
    )
  ).data;
};

export const postConfigLiveEnable = async (payload: { confirm_live: boolean; confirm_execute?: boolean; trace_id?: string }) =>
  (await api.post<{ ok: boolean; ts: number; applied?: Record<string, unknown>; runtime_config_version?: string | null; execution_venue?: string | null; error?: string }>('/config/live/enable', payload)).data;

export const postConfigLiveDisable = async (payload: { confirm_live: boolean; confirm_execute?: boolean; trace_id?: string }) =>
  (await api.post<{ ok: boolean; ts: number; applied?: Record<string, unknown>; runtime_config_version?: string | null; error?: string }>('/config/live/disable', payload)).data;

export type ThreeScreenWeeklyStatus = {
  ok: boolean;
  ts_ms: number;
  timeframe?: '1w';
  pair?: string;
  group_id?: string | null;
  exists?: boolean;
  event_id?: string | null;
  bar_open_ms?: number;
  bar_close_ms?: number;
  bar_closed?: boolean;
  asof_week?: string | null;
  weekly_trend_dir?: 'long' | 'short' | 'neutral' | string | null;
  weekly_trend_strength?: number | null;
  weekly_trend_dir_a?: 'long' | 'short' | 'neutral' | string | null;
  weekly_trend_strength_a?: number | null;
  weekly_trend_dir_b?: 'long' | 'short' | 'neutral' | string | null;
  weekly_trend_strength_b?: number | null;
  weekly_ab_b_enabled?: boolean | null;
  weekly_ab_b_neutral_strength_mult?: number | null;
  weekly_ab_b_veto_opposite?: boolean | null;
  weekly_ab_b_dampened?: boolean | null;
  weekly_ab_b_vetoed?: boolean | null;
  weekly_ab_b_score_long?: number | null;
  weekly_ab_b_score_short?: number | null;
  weekly_reason_codes?: string[] | null;
  weekly_reason_codes_a?: string[] | null;
  weekly_reason_codes_b?: string[] | null;
  weekly_regime?: string | null;
  ttl_ms?: number;
  data_age_ms?: number | null;
  stale?: boolean;
  trend?: {
    dir?: 'long' | 'short' | 'neutral' | string;
    strength?: number | null;
    asof_week?: string | null;
    reason?: string | null;
  } | null;
  components?: Record<string, unknown> | null;
  reason_codes?: string[] | null;
  weekly_components?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type ThreeScreenDailySignal = {
  ok: boolean;
  ts_ms: number;
  timeframe?: '1d';
  pair?: string;
  group_id?: string | null;
  exists?: boolean;
  event_id?: string | null;
  bar_open_ms?: number;
  bar_close_ms?: number;
  bar_closed?: boolean;
  valid_from_ms?: number | null;
  valid_until_ms?: number | null;
  valid_days?: number | null;
  daily_setup?: Record<string, unknown> | null;
  daily_scenarios?: Record<string, unknown> | null;
  daily_setups?: Record<string, unknown> | null;
  ttl_ms?: number;
  data_age_ms?: number | null;
  stale?: boolean;
  signal?: {
    dir?: 'long' | 'short' | 'neutral' | string;
    confidence?: number | null;
    selection_mode?: string | null;
    topk_k?: number;
    topk?: Array<{ indicator_id?: string; weight?: number; oos_score?: number; [key: string]: unknown }> | null;
    best_indicator_id?: string | null;
    valid_until_ms?: number | null;
    valid_now?: boolean | null;
    valid_days?: number | null;
    daily_setup?: Record<string, unknown> | null;
    daily_scenarios?: Record<string, unknown> | null;
    daily_setups?: Record<string, unknown> | null;
    align_with_weekly?: boolean;
    weekly_dir?: string | null;
    align_detail_ok?: boolean;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
};

export type ThreeScreenDailyWfoSummary = {
  ok: boolean;
  ts_ms: number;
  pair?: string;
  group_id?: string | null;
  exists?: boolean;
  event_id?: string | null;
  bar_close_ms?: number;
  summary?: {
    daily_topk_k?: number;
    daily_topk_n?: number;
    daily_topk?: Array<{ indicator_id?: string; weight?: number; oos_score?: number; [key: string]: unknown }>;
    best_indicator_id?: string | null;
    scoring?: { a?: number; b?: number; c?: number };
    stability?: { min_trades?: number; pf_min?: number; max_dd_max?: number; turnover_max?: number | null };
    meta?: { selection_mode?: string | null; valid_until_ms?: number | null };
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
};

export type ThreeScreen5mSignal = {
  ok: boolean;
  ts_ms: number;
  timeframe?: string;
  pair?: string;
  group_id?: string | null;
  exists?: boolean;
  event_id?: string | null;
  bar_open_ms?: number;
  bar_close_ms?: number;
  bar_closed?: boolean | null;
  side?: string | null;
  action?: string | null;
  tag?: string | null;
  ttl_ms?: number;
  data_age_ms?: number | null;
  stale?: boolean;
  signal?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type ThreeScreenDailyTalibRank = {
  ok: boolean;
  ts_ms: number;
  pair?: string;
  group_id?: string | null;
  cached?: boolean;
  cache_ttl_sec?: number;
  talib_available?: boolean;
  source?: string;
  error?: string;
  rows?: Array<{
    indicator_id?: string;
    family?: string;
    params?: Record<string, unknown> | null;
    stats_oos?: Record<string, unknown> | null;
    stats_folds?: Array<Record<string, unknown>> | null;
    score?: number;
    stability_pass?: boolean;
    notes?: string | null;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
};

const _threeScreenAutoComputeEnabled = (params?: Record<string, unknown>): boolean => {
  if (!params || !Object.prototype.hasOwnProperty.call(params, 'auto_compute')) return true;
  const raw = params.auto_compute;
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'number') return raw !== 0;
  const s = String(raw ?? '').trim().toLowerCase();
  return s === '1' || s === 'true' || s === 'yes' || s === 'y' || s === 'on';
};

const _threeScreenShouldFallback = (error: unknown): boolean => {
  if (!axios.isAxiosError(error)) return false;
  const status = error.response?.status;
  const code = String(error.code ?? '').trim().toUpperCase();
  if (!status) return true;
  if (status >= 500) return true;
  if (code === 'ECONNABORTED' || code === 'ERR_NETWORK') return true;
  return false;
};

const _fetchThreeScreenWithFallback = async <T>(path: string, params?: Record<string, unknown>): Promise<T> => {
  try {
    return (await api.get<T>(path, { params })).data;
  } catch (error) {
    if (!_threeScreenAutoComputeEnabled(params) || !_threeScreenShouldFallback(error)) throw error;
    const fallbackParams: Record<string, unknown> = { ...(params ?? {}), auto_compute: 0 };
    return (await api.get<T>(path, { params: fallbackParams, timeout: 45_000 })).data;
  }
};

export const fetchThreeScreenWeeklyStatus = async (params?: { pair?: string; group_id?: string; require_bar_closed?: number | boolean; auto_compute?: number | boolean }) =>
  _fetchThreeScreenWithFallback<ThreeScreenWeeklyStatus>('/three_screen/weekly/status', params as Record<string, unknown> | undefined);

export type ThreeScreenBackfillResponse = {
  ok: boolean;
  ts_ms: number;
  job_id?: string;
  status?: string;
  coin?: string;
  group_id?: string;
  lookback_days?: number;
  timeout_sec?: number;
  backfill?: Record<string, unknown> | null;
  weekly_emit?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export const postThreeScreenBackfill = async (payload: { coin?: string; pair?: string; group_id?: string; lookback_days?: number; timeout_sec?: number; sync?: boolean }) =>
  (await api.post<ThreeScreenBackfillResponse>('/three_screen/backfill', payload)).data;

export const fetchThreeScreenBackfillStatus = async (params: { job_id: string }) =>
  (await api.get<{ ok: boolean; ts_ms: number; job?: Record<string, unknown> | null; error?: string; job_id?: string }>('/three_screen/backfill/status', { params })).data;

export type ThreeScreenWeeklyDiagnostics = {
  ok: boolean;
  ts_ms: number;
  coin?: string;
  n_rows?: number;
  lookback_weeks?: number;
  lookback_days?: number;
  bins?: number;
  range_approx?: { from?: string | null; to?: string | null } | null;
  raw?: {
    features?: string[];
    corr_top?: Array<{ a?: string; b?: string; corr?: number }>;
    mi_top?: Array<{ a?: string; b?: string; mi?: number }>;
    vif?: Record<string, unknown>;
    pca?: Record<string, unknown> | null;
  };
  strength?: {
    features?: string[];
    corr_top?: Array<{ a?: string; b?: string; corr?: number }>;
    mi_top?: Array<{ a?: string; b?: string; mi?: number }>;
    vif?: Record<string, unknown>;
    pca?: Record<string, unknown> | null;
  };
  error?: string;
  detail?: string;
  [key: string]: unknown;
};

export const fetchThreeScreenWeeklyDiagnostics = async (params?: { pair?: string; coin?: string; lookback_weeks?: number; lookback_days?: number; bins?: number }) =>
  (await api.get<ThreeScreenWeeklyDiagnostics>('/three_screen/weekly/diagnostics', { params })).data;

export const fetchThreeScreenDailySignal = async (params?: { pair?: string; group_id?: string; require_bar_closed?: number | boolean; auto_compute?: number | boolean }) =>
  _fetchThreeScreenWithFallback<ThreeScreenDailySignal>('/three_screen/daily/signal', params as Record<string, unknown> | undefined);

export const fetchThreeScreenDailyWfoSummary = async (params?: { pair?: string; group_id?: string; auto_compute?: number | boolean }) =>
  _fetchThreeScreenWithFallback<ThreeScreenDailyWfoSummary>('/three_screen/daily/wfo_summary', params as Record<string, unknown> | undefined);

export const fetchThreeScreenDailyTalibRank = async (params?: { pair?: string; group_id?: string; lookback_days?: number; train_days?: number; test_days?: number; folds?: number; gap_days?: number; cost_bps?: number; topn?: number; cache_ttl_sec?: number }) =>
  (await api.get<ThreeScreenDailyTalibRank>('/three_screen/daily/talib_rank', { params })).data;

export const fetchThreeScreen5mSignal = async (params?: { pair?: string; group_id?: string; require_bar_closed?: number | boolean; auto_compute?: number | boolean; trigger_decision?: number | boolean }) =>
  _fetchThreeScreenWithFallback<ThreeScreen5mSignal>('/three_screen/5m/signal', params as Record<string, unknown> | undefined);

export type ThreeScreen5mResearch = {
  ok: boolean;
  ts_ms: number;
  pair?: string;
  group_id?: string;
  bar?: {
    bar_open_ms?: number;
    bar_close_ms?: number;
    bar_closed?: boolean | null;
    bar_age_ms?: number;
    bar_stale?: boolean;
    px?: number | null;
    high?: number | null;
    low?: number | null;
    vol?: number | null;
    [key: string]: unknown;
  };
  mtf?: {
    weekly_trend_dir?: string | null;
    daily_signal_dir?: string | null;
    align_with_weekly?: boolean;
    allowed_side?: string | null;
    weekly_bar_close_ms?: number | null;
    daily_bar_close_ms?: number | null;
    daily_valid_until_ms?: number | null;
    setup_valid?: boolean;
    [key: string]: unknown;
  };
  touch?: { [key: string]: unknown } | null;
  touch_eval?: { [key: string]: unknown } | null;
  confirm?: { [key: string]: unknown } | null;
  window?: { [key: string]: unknown } | null;
  arena?: { [key: string]: unknown } | null;
  decision?: { [key: string]: unknown } | null;
  [key: string]: unknown;
};

export const fetchThreeScreen5mResearch = async (params?: { pair?: string; group_id?: string; require_bar_closed?: number | boolean; auto_compute?: number | boolean; trigger_decision?: number | boolean }) =>
  _fetchThreeScreenWithFallback<ThreeScreen5mResearch>('/three_screen/5m/research', params as Record<string, unknown> | undefined);

export type MaintenanceRunResponse = {
  ok: boolean;
  ts?: number;
  duration_ms?: number;
  [key: string]: unknown;
};

export type MaintenanceNanoclawStartResponse = MaintenanceRunResponse & {
  launchd_label?: string;
  launchd_target?: string;
  cwd?: string;
  bootstrap?: {
    ok: boolean;
    code?: number;
    stdout?: string;
    stderr?: string;
  };
  kickstart?: {
    ok: boolean;
    code?: number;
    stdout?: string;
    stderr?: string;
  };
};

export type MaintenanceCleanupNightlyStatusResponse = MaintenanceRunResponse & {
  label?: string;
  target?: string;
  platform?: string;
  script_exists?: boolean;
  plist_exists?: boolean;
  loaded?: boolean;
  meta?: Record<string, unknown>;
  paths?: Record<string, string>;
  launchctl?: {
    ok?: boolean;
    code?: number;
    stdout?: string;
    stderr?: string;
  };
};

export const runMaintenanceJanitor = async (): Promise<MaintenanceRunResponse> => {
  const token = getExecuteToken();
  const headers: Record<string, string> = {};
  if (token) headers['X-Maintenance-Token'] = token;
  return (await api.post<MaintenanceRunResponse>('/maintenance/janitor/run', {}, { headers, timeout: 120000 })).data;
};

export const runMaintenanceRetention = async (params?: { dry_run?: boolean }): Promise<MaintenanceRunResponse> => {
  const token = getExecuteToken();
  const headers: Record<string, string> = {};
  if (token) headers['X-Maintenance-Token'] = token;
  const dry_run = params?.dry_run == null ? undefined : (params.dry_run ? 1 : 0);
  return (await api.post<MaintenanceRunResponse>('/maintenance/retention/run', {}, { params: { dry_run }, headers, timeout: 300000 })).data;
};

export const runMaintenanceNanoclawStart = async (): Promise<MaintenanceNanoclawStartResponse> => {
  const token = getExecuteToken();
  const headers: Record<string, string> = {};
  if (token) headers['X-Maintenance-Token'] = token;
  return (await api.post<MaintenanceNanoclawStartResponse>('/maintenance/nanoclaw/start', {}, { headers, timeout: 30000 })).data;
};

export const fetchMaintenanceCleanupNightlyStatus = async (): Promise<MaintenanceCleanupNightlyStatusResponse> => {
  const token = getExecuteToken();
  const headers: Record<string, string> = {};
  if (token) headers['X-Maintenance-Token'] = token;
  return (await api.get<MaintenanceCleanupNightlyStatusResponse>('/maintenance/cleanup/nightly/status', { headers, timeout: 15000 })).data;
};

export const installMaintenanceCleanupNightly = async (payload?: {
  hour?: number;
  minute?: number;
  include_janitor?: boolean;
  include_retention?: boolean;
  base_url?: string;
}): Promise<MaintenanceRunResponse> => {
  const token = getExecuteToken();
  const headers: Record<string, string> = {};
  if (token) headers['X-Maintenance-Token'] = token;
  return (await api.post<MaintenanceRunResponse>('/maintenance/cleanup/nightly/install', payload ?? {}, { headers, timeout: 30000 })).data;
};

export const uninstallMaintenanceCleanupNightly = async (): Promise<MaintenanceRunResponse> => {
  const token = getExecuteToken();
  const headers: Record<string, string> = {};
  if (token) headers['X-Maintenance-Token'] = token;
  return (await api.post<MaintenanceRunResponse>('/maintenance/cleanup/nightly/uninstall', {}, { headers, timeout: 30000 })).data;
};

export type CarryStatusResponse = {
  ok: boolean;
  ts?: number;
  venue?: string;
  enabled?: boolean;
  enabled_effective?: boolean;
  sandbox?: boolean;
  execute_allowed?: boolean;
  execute_effective?: boolean;
  next_funding_ts?: number;
  minutes_to_funding?: number;
  window_state?: string;
  base_ts?: number;
  minutes_to_base?: number;
  funding_pnl?: number | null;
  price_move_pnl?: number | null;
  costs?: number | null;
  pnl?: Record<string, unknown>;
  funding_income?: Record<string, unknown>;
  profile?: string;
  profiles?: Record<string, unknown>;
  regime?: Record<string, unknown>;
  gate?: Record<string, unknown>;
  cfg_base?: Record<string, unknown>;
  cfg_effective?: Record<string, unknown>;
  cfg?: Record<string, unknown>;
  carry_universe?: Record<string, unknown> | null;
  active_position?: Record<string, unknown> | null;
  positions?: {
    ok?: boolean;
    ts?: number;
    n?: number;
    items?: Record<string, unknown>[];
    [key: string]: unknown;
  };
  events?: {
    ok?: boolean;
    ts?: number;
    n?: number;
    items?: Record<string, unknown>[];
    [key: string]: unknown;
  };
  engine?: {
    tick_ts?: number | null;
    pool_ts?: number | null;
    pool_n?: number | null;
    positions_count?: number | null;
    open_window?: Record<string, unknown> | null;
  };
};

export type CarryCandidate = {
  coin: string;
  funding_rate?: number;
  basis_bps?: number;
  carry_side?: string;
  expected_edge?: number;
  atr_pct_5m?: number | null;
  adx_5m?: number | null;
  vetoed?: boolean;
  veto_reason?: string | null;
  [key: string]: unknown;
};

export type CarryCandidatesResponse = {
  ok: boolean;
  ts?: number;
  venue?: string;
  n?: number;
  next_funding_ts?: number;
  minutes_to_funding?: number;
  window_state?: string;
  profile?: string;
  regime?: Record<string, unknown>;
  gate?: Record<string, unknown>;
  cfg_effective?: Record<string, unknown>;
  recommended_open_top_k?: number | null;
  candidates?: CarryCandidate[];
  [key: string]: unknown;
};

export type FundingRateItem = {
  coin?: string;
  pair?: string;
  funding_rate?: number;
  funding_period_ms?: number | null;
  funding_rate_1h?: number | null;
  funding_rate_apr?: number | null;
  next_funding_ts?: number | null;
  minutes_to_funding?: number;
  mark_price?: number | null;
  index_price?: number | null;
  basis_bps?: number;
  ts?: number;
  [key: string]: unknown;
};

export type FundingRatesResponse = {
  ok: boolean;
  ts?: number;
  venue?: string;
  period_ms?: number | null;
  next_funding_ts?: number | null;
  minutes_to_funding?: number;
  key_mode?: string;
  rates?: Record<string, FundingRateItem>;
  rates_by_coin?: Record<string, FundingRateItem>;
  rates_by_pair?: Record<string, FundingRateItem>;
  [key: string]: unknown;
};

export type FundingScheduleResponse = {
  ok: boolean;
  ts?: number;
  venue?: string;
  period_ms?: number;
  schedule?: number[];
  [key: string]: unknown;
};

export type CarryUniverseResponse = {
  ok: boolean;
  ts?: number;
  venue?: string;
  state?: {
    ts?: number;
    venue?: string;
    n?: number;
    coins?: string[];
    metadata?: Record<string, unknown>;
    last_error?: Record<string, unknown> | null;
    [key: string]: unknown;
  };
  cfg_effective?: Record<string, unknown>;
  refresh?: Record<string, unknown>;
  [key: string]: unknown;
};

export type CarryAcceptanceResponse = {
  ok: boolean;
  ts?: number;
  venue?: string;
  lookback_days?: number;
  thresholds?: Record<string, unknown>;
  pnl_split?: Record<string, unknown>;
  stability?: Record<string, unknown>;
  cost_stress?: Record<string, unknown>;
  turnover?: Record<string, unknown>;
  tail?: Record<string, unknown>;
  [key: string]: unknown;
};

export const fetchCarryStatus = async (params?: { include_positions?: boolean; include_events?: boolean; events_n?: number }) =>
  (await api.get<CarryStatusResponse>('/carry/status', { params: { ...(params ?? {}) } })).data;

export const fetchCarryCandidates = async (params?: { venue?: string; n?: number }) =>
  (await api.get<CarryCandidatesResponse>('/carry/candidates', { params: { ...(params ?? {}) }, timeout: 60000 })).data;

export const fetchCarryAcceptance = async (params?: { venue?: string; lookback_days?: number }) =>
  (await api.get<CarryAcceptanceResponse>('/carry/acceptance', { params: { ...(params ?? {}) } })).data;

export const updateCarryConfig = async (cfg: Record<string, unknown> & { confirm_live?: boolean }) =>
  (await api.post<{ ok: boolean; changed?: Record<string, unknown>; config?: Record<string, unknown> }>('/carry/config', cfg)).data;

export const fetchFundingRates = async (params?: { venue?: string; limit?: number }) =>
  (await api.get<FundingRatesResponse>('/funding/rates', { params: { ...(params ?? {}) }, timeout: 60000 })).data;

export const fetchFundingSchedule = async (params?: { venue?: string; n?: number }) =>
  (await api.get<FundingScheduleResponse>('/funding/schedule', { params: { ...(params ?? {}) } })).data;

export const fetchCarryUniverse = async (params?: { refresh?: number | boolean }) =>
  (await api.get<CarryUniverseResponse>('/carry/universe', { params: { ...(params ?? {}) }, timeout: 60000 })).data;
export const reloadModels = async () => (await api.post<{ok:boolean}>('/models/reload')).data;
export const selectModel = async (name: string) => (await api.post<{ok:boolean, active: string}>('/models/select', {name})).data;

export type FetchRecentOrdersParams = {
  limit?: number;
  sort?: 'ts' | 'ingest' | string;
  include_shadow?: number | boolean;
  allow_book_id_missing?: number | boolean;
  no_default_filter?: number | boolean;
  no_event_backfill?: number | boolean;
  strategy_id?: string;
  ab_owner?: string;
  book_id?: string;
  group_id?: string;
  pair?: string;
};

export const fetchRecentOrdersWithParams = async (params?: FetchRecentOrdersParams) =>
  (await api.get<Order[]>('/orders/recent', { params: { limit: 200, sort: 'ingest', include_shadow: 1, ...(params ?? {}) }, timeout: 60000 })).data;

export const fetchRecentOrders = async () => fetchRecentOrdersWithParams();

export const fetchCarryOrdersRecent = async (params?: { limit?: number; sort?: 'ts' | 'ingest'; include_shadow?: number | boolean }) =>
  (await api.get<Order[]>('/orders/recent', { params: { limit: 50, sort: 'ingest', include_shadow: 1, strategy_id: 'CarryTrade', ab_owner: 'carry', ...(params ?? {}) } })).data;

export type BacktestResultItem = {
  name: string;
  size_bytes: number;
  mtime_ms: number;
};

export type BacktestResultsResponse = {
  ok: boolean;
  ts: number;
  latest?: string | null;
  results: BacktestResultItem[];
};

export type FreqtradeBacktestStrategyRow = {
  key: string;
  trades?: number;
  wins?: number;
  losses?: number;
  draws?: number;
  winrate?: number;
  profit_total_abs?: number;
  profit_total_pct?: number;
  profit_mean_pct?: number;
  profit_factor?: number;
  sharpe?: number;
  sortino?: number;
  calmar?: number;
  sqn?: number;
  cagr?: number;
  expectancy?: number;
  expectancy_ratio?: number;
  max_drawdown_account?: number;
  max_drawdown_abs?: number;
  timeframe?: string;
  timeframe_detail?: string;
  timerange?: string;
  backtest_start_ts?: number;
  backtest_end_ts?: number;
  backtest_days?: number;
  final_balance?: number;
  starting_balance?: number;
  stake_currency?: string;
  max_open_trades?: number;
};

export type FreqtradeBacktestZipMetrics = {
  zip: string;
  strategies: FreqtradeBacktestStrategyRow[];
};

export type BacktestReportResponse = {
  ok: boolean;
  ts?: number;
  kind?: string;
  zip?: string;
  strategy?: string | null;
  metrics_summary?: FreqtradeBacktestStrategyRow | null;
  metrics?: FreqtradeBacktestZipMetrics | null;
  aligned_metrics?: {
    ok?: boolean;
    schema_version?: number;
    assumptions?: Record<string, unknown>;
    base_equity_u?: number | null;
    total?: number;
    total_pct?: number | null;
    maxdd?: number;
    maxdd_pct?: number | null;
    calmar?: number | null;
    sharpe?: number | null;
    sortino?: number | null;
    dd_recovery_ms_max?: number | null;
    trades?: number;
    wins?: number;
    losses?: number;
    winrate?: number | null;
    fees_u?: number;
    funding_u?: number;
    max_daily_loss_u?: number | null;
    max_weekly_loss_u?: number | null;
    max_daily_loss_pct?: number | null;
    max_weekly_loss_pct?: number | null;
    leverage_avg?: number | null;
    leverage_max?: number | null;
  } | null;
  eval?: {
    ok?: boolean;
    score?: number;
    objective?: string;
    hard_fails?: string[];
    policy?: Record<string, unknown>;
    metrics?: Record<string, unknown>;
  } | null;
  source?: Record<string, unknown>;
  error?: string;
};

export const fetchBacktestResults = async (params?: { limit?: number }) =>
  (await api.get<BacktestResultsResponse>('/backtest/results', { params })).data;

export const fetchBacktestReportLatest = async (params?: { strategy?: string }) =>
  (await api.get<BacktestReportResponse>('/backtest/report/latest', { params })).data;

export const fetchBacktestReportByZip = async (params: { zip: string; strategy?: string }) =>
  (await api.get<BacktestReportResponse>('/backtest/report', { params })).data;

export const backtestResultsDownloadUrl = (zip: string): string => `${API_BASE}/backtest/results/download?zip=${encodeURIComponent(zip)}`;

export type BacktestRobustnessResponse = {
  ok: boolean;
  ts?: number;
  zip?: string;
  strategy?: string | null;
  assumptions?: Record<string, unknown>;
  base_equity_u?: number | null;
  base?: Record<string, unknown>;
  eval?: { score?: number; hard_fails?: string[]; policy?: Record<string, unknown>; metrics?: Record<string, unknown> } | null;
  time_slices?: Array<{ i: number; from_ts: number; to_ts: number; n: number; metrics: Record<string, unknown> }>;
  walk_forward?: {
    n_folds?: number;
    summary?: Record<string, unknown>;
    folds?: unknown[];
  } | null;
  market_state_slices?: Record<string, { n: number; metrics: Record<string, unknown> }>;
  bootstrap?: Record<string, unknown> | null;
  shuffle?: Record<string, unknown> | null;
  sensitivity?: {
    x?: { key?: string; values?: number[] };
    y?: { key?: string; values?: number[] };
    metric?: string;
    grid?: Array<Array<number | null>>;
  } | null;
  error?: string;
};

export const fetchBacktestRobustness = async (payload: {
  zip?: string;
  strategy?: string;
  assumptions?: Record<string, unknown>;
  sensitivity?: Record<string, unknown>;
  seed?: number;
  n_slices?: number;
  n_bootstrap?: number;
  n_shuffle?: number;
  vol_ratio_thr?: number;
  trend_dist_thr?: number;
}) => (await api.post<BacktestRobustnessResponse>('/backtest/robustness', payload)).data;

export type StrategyRegistryEntry = {
  strategy_id: string;
  source_zip: string;
  family: string;
  stage: string;
  tags: string[];
  robustness?: string;
  econ_driver?: string;
  eval_policy_ref?: string;
  owner?: string;
  approved_by?: string;
  approved_at?: string;
  tier?: string;
  tier_reason?: string;
  baseline_ref?: string;
  bundle_id?: string;
  signal_density?: number | null;
  metrics_summary?: Record<string, unknown>;
  aligned_metrics?: Record<string, unknown>;
  oos_summary?: Record<string, unknown>;
  gate_result?: Record<string, unknown>;
  rollout?: Record<string, unknown>;
  rollback?: Record<string, unknown>;
  lifecycle_state?: string;
  deprecated_reason?: string;
  replacement_candidates?: string[];
  features?: Record<string, unknown>;
  timeframe?: string;
  pair_universe?: string[];
  leverage_mode?: string;
  source?: Record<string, unknown>;
  backtest_spec?: Record<string, unknown>;
  updated_at?: string;
};

export type StrategyRegistryResponse = {
  ok: boolean;
  ts?: number;
  entries?: StrategyRegistryEntry[];
  error?: string;
};

export type StrategySearchResponse = {
  ok: boolean;
  ts?: number;
  q?: string;
  family?: string;
  stage?: string;
  tier?: string;
  zip?: string;
  bundle_id?: string;
  cost_profile_id?: string;
  sort?: string;
  limit?: number;
  offset?: number;
  total?: number;
  rows?: StrategyRegistryEntry[];
  error?: string;
};

export const fetchStrategyRegistry = async () => (await api.get<StrategyRegistryResponse>('/strategy/registry')).data;

export const fetchStrategySearch = async (params?: {
  q?: string;
  family?: string;
  stage?: string;
  tier?: string;
  zip?: string;
  source_zip?: string;
  bundle_id?: string;
  cost_profile_id?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}) => (await api.get<StrategySearchResponse>('/search', { params })).data;

export const upsertStrategyRegistry = async (items: StrategyRegistryEntry[]) =>
  (await api.post<{ ok: boolean; saved?: number; ts?: number; error?: string }>('/strategy/registry/upsert', { items })).data;

export type StrategyRegistryImportActiveResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  approval_id?: string;
  source_zip?: string;
  saved?: number;
  error?: string;
};

export const importActiveStrategiesToRegistry = async (payload?: { source_zip?: string; stage?: string; trace_id?: string }) =>
  (await api.post<StrategyRegistryImportActiveResponse>('/strategy/registry/import_active', payload ?? {})).data;

export type StrategyRegistrySyncResponse = {
  ok: boolean;
  ts?: number;
  entry?: StrategyRegistryEntry;
  error?: string;
};

export const syncStrategyRegistryFromZip = async (payload: {
  zip: string;
  strategy_id: string;
  family?: string;
  stage?: string;
  tags?: string[];
  robustness?: string;
  econ_driver?: string;
  eval_policy_ref?: string;
  owner?: string;
  n_slices?: number;
  n_bootstrap?: number;
  n_shuffle?: number;
}) => (await api.post<StrategyRegistrySyncResponse>('/strategy/registry/sync_from_zip', payload)).data;

export type StrategyRegistryRunAndSyncResponse = {
  ok: boolean;
  ts?: number;
  backtest?: Record<string, unknown>;
  sync?: StrategyRegistrySyncResponse;
  error?: string;
};

export const runAndSyncStrategyRegistry = async (payload: {
  strategy_id: string;
  family?: string;
  stage?: string;
  tags?: string[];
  robustness?: string;
  econ_driver?: string;
  eval_policy_ref?: string;
  owner?: string;
  config?: string;
  timerange?: string;
  timeout_sec?: number;
  deep_robustness?: boolean;
  n_slices?: number;
  n_bootstrap?: number;
  n_shuffle?: number;
}) => (await api.post<StrategyRegistryRunAndSyncResponse>('/strategy/registry/run_and_sync', payload)).data;

export type StrategyRegistryImportFromGithubResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  repo?: Record<string, unknown>;
  inject?: Record<string, unknown>;
  backtest?: Record<string, unknown>;
  sync?: Record<string, unknown>;
  error?: string;
  candidates?: string[];
};

export const importStrategyRegistryFromGithub = async (payload: {
  trace_id?: string;
  approval_id?: string;
  confirm_live?: boolean;
  url: string;
  repo_url?: string;
  branch?: string;
  commit?: string;
  path?: string;
  strategy_name?: string;
  family?: string;
  stage?: string;
  tags?: string[];
  robustness?: string;
  econ_driver?: string;
  eval_policy_ref?: string;
  owner?: string;
  config?: string;
  timerange?: string;
  timeout_sec?: number;
}) => (await api.post<StrategyRegistryImportFromGithubResponse>('/strategy/registry/import_from_github', payload)).data;

export type StrategyRegistryEvent = {
  id?: string;
  ts?: number;
  trace_id?: string | null;
  actor?: string | null;
  kind: 'rollout' | 'rollback' | 'tier_change' | 'deprecate' | 'note' | string;
  strategy_id: string;
  source_zip: string;
  note?: string | null;
  payload?: Record<string, unknown>;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
};

export const appendStrategyRegistryEvent = async (payload: {
  strategy_id: string;
  source_zip: string;
  kind: StrategyRegistryEvent['kind'];
  trace_id?: string;
  actor?: string;
  note?: string;
  payload?: Record<string, unknown>;
}) =>
  (await api.post<{ ok: boolean; ts?: number; event?: StrategyRegistryEvent; entry?: StrategyRegistryEntry; error?: string }>('/strategy/registry/event', payload)).data;

export const fetchStrategyRegistryEvents = async (params: { strategy_id: string; source_zip: string; limit?: number }) =>
  (await api.get<{ ok: boolean; ts?: number; events?: StrategyRegistryEvent[]; error?: string }>('/strategy/registry/events', { params })).data;

export type StrategyLibrarySnapshotRow = {
  strategy_id: string;
  family: string;
  stage: string;
  tags: string[];
  robustness: string;
  tier: string;
  tier_reason?: string;
  signal_density_p50?: number | null;
  metrics?: {
    profit_factor?: number | null;
    max_drawdown_pct?: number | null;
    winrate?: number | null;
    trades?: number | null;
    backtest_days?: number | null;
  };
  extras?: {
    avg_win_loss_ratio?: number | null;
    tail_loss_ratio?: number | null;
    max_consecutive_losses?: number | null;
    signal_density?: number | null;
    gross_profit_abs?: number | null;
  };
};

export type StrategyLibrarySnapshotResponse = {
  ok: boolean;
  ts?: number;
  zip?: string;
  rows?: StrategyLibrarySnapshotRow[];
  error?: string;
};

export const fetchStrategyLibrarySnapshot = async (params?: { zip?: string }) =>
  (await api.get<StrategyLibrarySnapshotResponse>('/strategy/library/snapshot', { params })).data;

export type StrategyBundleBuildResponse = {
  ok: boolean;
  ts?: number;
  bundle_id?: string;
  bundle?: string;
  download_url?: string;
  manifest?: Record<string, unknown>;
  tier?: string;
  tier_reason?: string;
  error?: string;
};

export const buildStrategyBundle = async (payload: {
  zip?: string;
  strategy_id: string;
  family?: string;
  stage?: string;
  tags?: string[];
  eval_policy_ref?: string;
}) => (await api.post<StrategyBundleBuildResponse>('/strategy/bundle/build', payload)).data;

export const strategyBundleDownloadUrl = (name: string): string => `${API_BASE}/strategy/bundle/download?name=${encodeURIComponent(name)}`;

export const fetchStrategyBundles = async (params?: { limit?: number }) =>
  (await api.get<{ ok: boolean; ts?: number; bundles?: Array<{ name: string; size_bytes?: number; mtime_ms?: number }>; error?: string }>('/strategy/bundles', { params })).data;

export type RepoFetchStrategyResponse = {
  ok: boolean;
  repo_id?: string;
  repo_url?: string;
  commit?: string;
  files?: string[];
  diff_summary?: { added?: number; removed?: number; modified?: number } | null;
  sandbox_path?: string;
  strategy_name_effective?: string;
  rename_map?: Array<{ from_file?: string; to_file?: string; from_class?: string; to_class?: string }>;
  trace_id?: string;
  approval_id?: string | null;
  error?: string;
  detail?: string;
};

export type RepoWhitelistListResponse = {
  ok: boolean;
  enabled?: boolean;
  count?: number;
  items?: string[];
  ts: number;
  error?: string;
};

export const fetchRepoWhitelistList = async () => (await api.get<RepoWhitelistListResponse>('/repo/whitelist/list')).data;

export type RepoWhitelistUpdateResponse = {
  ok: boolean;
  enabled?: boolean;
  count?: number;
  items?: string[];
  ts: number;
  error?: string;
};

export const updateRepoWhitelist = async (payload: { enabled?: boolean; items?: string[]; add?: string[]; remove?: string[] }) =>
  (await api.post<RepoWhitelistUpdateResponse>('/repo/whitelist/update', payload)).data;

export const repoFetchStrategyStub = async (payload: {
  repo_url: string;
  branch?: string;
  commit?: string;
  path?: string;
  strategy_name?: string;
  trace_id?: string;
  approval_id?: string;
}) => (await api.post<RepoFetchStrategyResponse>('/repo/fetch_strategy', payload)).data;

export type AuditDataQualityResponse = {
  ok: boolean;
  ts?: number;
  pair?: string;
  file?: string;
  range?: {
    start_ts?: number;
    end_ts?: number;
    n_rows?: number;
    expected_step_ms?: number;
    expected_rows?: number;
    missing_rows?: number;
    missing_rate?: number;
    gaps?: number;
    max_gap_ms?: number;
    missing_bars_est?: number;
    data_start_ts?: number;
    data_end_ts?: number;
    last_bar_age_ms?: number | null;
  };
  invalid?: Record<string, number>;
  returns?: {
    n?: number;
    mean?: number;
    std?: number;
    p01?: number;
    p50?: number;
    p99?: number;
    abs_p99?: number;
    outlier_abs_thr?: number;
    outlier_n?: number;
  };
  volume?: {
    n?: number;
    p50?: number;
    p95?: number;
    p99?: number;
    zeros?: number;
  };
  alignment?: {
    hourly?: {
      n?: number;
      negative_offsets?: number;
      min_offset_ms?: number;
      p50_offset_ms?: number;
      p95_offset_ms?: number;
    };
    daily?: {
      n?: number;
      negative_offsets?: number;
      min_offset_ms?: number;
      p50_offset_ms?: number;
      p95_offset_ms?: number;
    };
    di_shifted?: boolean;
  };
  lookahead_risk?: {
    flags?: string[];
  };
  bar_closed?: {
    n?: number;
    closed_true?: number;
    closed_false?: number;
    missing?: number;
    rate_true?: number;
    by_strategy?: Record<string, { n?: number; closed_false?: number; missing?: number }>;
  };
  error?: string;
};

export type AuditExecutionQualityResponse = {
  ok: boolean;
  ts?: number;
  pair?: string | null;
  strategy_id?: string | null;
  range?: {
    start_ts?: number;
    end_ts?: number;
    lookback_ms?: number;
  };
  n_orders?: number;
  order_success_rate?: number | null;
  order_fail_rate?: number | null;
  status?: Record<string, number>;
  side?: Record<string, number>;
  action?: Record<string, number>;
  latency?: {
    n?: number;
    mean_ms?: number;
    p50_ms?: number;
    p95_ms?: number;
    p99_ms?: number;
  };
  submit_to_fill_latency?: {
    n?: number;
    mean_ms?: number;
    p50_ms?: number;
    p95_ms?: number;
    p99_ms?: number;
  };
  slippage?: {
    n?: number;
    mean_bps?: number;
    p50_bps?: number;
    p95_bps?: number;
    p99_bps?: number;
  };
  cancel?: {
    n?: number;
    fail_rate?: number | null;
    status?: Record<string, number>;
  };
  by_strategy?: Record<string, {
    n?: number;
    status?: Record<string, number>;
    side?: Record<string, number>;
    action?: Record<string, number>;
    latency?: {
      n?: number;
      mean_ms?: number;
      p50_ms?: number;
      p95_ms?: number;
      p99_ms?: number;
    };
  }>;
  error?: string;
};

export type ChangePackageGenerateRequest = {
  base_version: string;
  target_version: string;
  doc_section?: string;
  doc_change_summary?: string;
  pf?: number;
  dd?: number;
  trades?: number;
  win?: number;
  rollout?: { mode?: string; scope?: string; duration?: string };
  config_overrides?: Record<string, unknown>;
  doc_refs?: { doc_path: string; section: string; rule: string }[];
  rollback_trigger?: string;
  strategy?: string;
  exec_lookback_days?: number;
};

export type ChangePackageGenerateResponse = {
  ok: boolean;
  package?: Record<string, unknown>;
  error?: string;
};

export type AuditAlertsEvaluateResponse = {
  ok: boolean;
  ts?: number;
  pair?: string | null;
  lookback_days?: number;
  dq_ok?: boolean;
  eq_ok?: boolean;
  alerts?: { id: string; severity: string; value?: number; threshold?: number }[];
  dq?: AuditDataQualityResponse | null;
  eq?: AuditExecutionQualityResponse | null;
  error?: string;
};

export const fetchAuditDataQuality = async (params: {
  pair: string;
  start_ts?: number;
  end_ts?: number;
  lookback_days?: number;
  max_points?: number;
  ret_abs_thr?: number;
  include_events?: number | boolean;
  events_limit?: number;
}) => (await api.get<AuditDataQualityResponse>('/audit/data-quality', { params })).data;

export const fetchAuditExecutionQuality = async (params: {
  pair?: string;
  strategy_id?: string;
  start_ts?: number;
  end_ts?: number;
  lookback_days?: number;
  max_points?: number;
  include_shadow?: number | boolean;
}) => (await api.get<AuditExecutionQualityResponse>('/audit/execution-quality', { params })).data;

export const generateChangePackage = async (payload: ChangePackageGenerateRequest) => (await api.post<ChangePackageGenerateResponse>('/change/package/generate', payload)).data;

export const fetchAuditAlertsEvaluate = async (params: {
  pair?: string;
  lookback_days?: number;
}) => (await api.get<AuditAlertsEvaluateResponse>('/audit/alerts/evaluate', { params })).data;

export type AgentPushConfig = {
  im_webhook?: string;
  email?: string;
  sms_provider?: string;
  twitter_enabled?: boolean;
  twitter_outbox_worker_enabled?: boolean;
  twitter_max_per_hour?: number;
  twitter_rate_window_sec?: number;
  twitter_min_interval_sec?: number;
  twitter_llm_provider?: string;
  twitter_llm_model?: string;
  twitter_llm_note_timeout_sec?: number;
  twitter_llm_assess_timeout_sec?: number;
  twitter_llm_compose_prompt?: string;
  twitter_llm_assess_enabled?: boolean;
  twitter_llm_confidence_threshold?: number;
  twitter_llm_fail_policy?: string;
};
export const getAgentPushConfig = async () => (await api.get<{ok:boolean;config:AgentPushConfig;ts:number}>('/agent/push/config')).data;
export const saveAgentPushConfig = async (payload: AgentPushConfig) => (await api.post<{ok:boolean;config:AgentPushConfig;ts:number}>('/agent/push/config', payload)).data;
export type BinanceSpotSkillConfig = {
  enabled?: boolean;
  testnet?: boolean;
  base_url?: string;
  recv_window_ms?: number;
  timeout_sec?: number;
  api_key?: string;
  api_secret?: string;
  has_api_key?: boolean;
  has_secret?: boolean;
  api_key_masked?: string;
};
export const getBinanceSpotSkillConfig = async () => (await api.get<{ok:boolean;config:BinanceSpotSkillConfig;ts:number}>('/agent/skills/binance_spot/config')).data;
export const saveBinanceSpotSkillConfig = async (payload: BinanceSpotSkillConfig) => (await api.post<{ok:boolean;config:BinanceSpotSkillConfig;ts:number}>('/agent/skills/binance_spot/config', payload)).data;
export const recordAgentAuditActions = async (payload: { items?: { name: string; ts: number; payload?: Record<string, unknown> }[]; name?: string; ts?: number; payload?: Record<string, unknown> }) => (await api.post<{ok:boolean;saved:number;ts:number}>('/agent/audit/actions', payload)).data;
export const sendAgentPush = async (payload: { channel: 'im' | 'email' | 'sms' | 'twitter' | string; message: string; severity?: string; extras?: Record<string, unknown> }) => (await api.post<{ok:boolean;channel:string;ts:number}>('/agent/push/send', payload)).data;

export type AgentTwitterComposeResponse = {
  ok: boolean;
  trace_id?: string;
  event_id?: string | null;
  order_id?: string | null;
  text?: string;
  meta?: Record<string, unknown>;
  error?: string;
  ts?: number;
};

export const composeAgentTwitterTrade = async (payload: {
  event_id?: string;
  order_id?: string;
  include_order?: boolean;
  include_disclaimer?: boolean;
}) => (await api.post<AgentTwitterComposeResponse>('/agent/twitter/compose', payload)).data;

export type AgentTwitterSendResponse = {
  ok: boolean;
  id?: string;
  trace_id?: string;
  tweet_id?: string | null;
  result?: Record<string, unknown>;
  error?: string;
  ts?: number;
};

export const sendAgentTwitterTweet = async (payload: {
  text: string;
  trace_id?: string;
  idempotency_key?: string;
  dry_run?: boolean;
}) => (await api.post<AgentTwitterSendResponse>('/agent/twitter/send', payload)).data;

export type AgentTwitterAuthStatusResponse = {
  ok: boolean;
  twitter_enabled?: boolean;
  worker_enabled?: boolean;
  worker_source?: string;
  worker_env_value?: string | null;
  worker_config_value?: boolean | null;
  auth_mode?: string;
  has_bearer?: boolean;
  has_oauth1?: boolean;
  missing_env?: string[];
  required_bearer_env?: string[];
  required_oauth1_env?: string[];
  error?: string;
  ts?: number;
};

export const fetchAgentTwitterAuthStatus = async () => (await api.get<AgentTwitterAuthStatusResponse>('/agent/twitter/auth/status')).data;

export type AgentTwitterMetricsResponse = {
  ok: boolean;
  window_sec?: number;
  since_ms?: number;
  ts?: number;
  requests?: number;
  receipts_ok?: number;
  receipts_fail?: number;
  pending?: number;
  oldest_pending_age_sec?: number | null;
  last_receipt?: {
    ok?: boolean;
    ts?: number;
    status_code?: number | null;
    error?: string | null;
    provider_msg_id?: string | null;
    id?: string | null;
    idempotency_key?: string | null;
  } | null;
  files?: Record<string, { name?: string; size?: number; mtime_ms?: number }>;
  error?: string;
};

export const fetchAgentTwitterMetrics = async (params?: { window_sec?: number; tail_bytes?: number }) =>
  (await api.get<AgentTwitterMetricsResponse>('/agent/twitter/metrics', { params })).data;

export type AgentObservabilityDailyRow = {
  day: string;
  bugfix_ok: number;
  bugfix_fail: number;
  paramopt_runs: number;
  paramopt_runs_strategy?: number;
  paramopt_runs_system?: number;
  paramopt_suggestions: number;
  paramopt_suggestions_strategy?: number;
  paramopt_suggestions_system?: number;
  strategy_imports: number;
  shadow_candidates: number;
  rollbacks: number;
  approvals: number;
  approvals_strategy?: number;
  approvals_system?: number;
  chain_supply: number;
  chain_shadow: number;
  chain_paramopt: number;
  closure_rate?: number;
  timeout_rate?: number;
  paramopt_timeouts?: number;
  mttr_minutes?: number;
  system_gate_kpi_block_count?: number;
  system_gate_plan_block_count?: number;
  top_reason_codes?: Array<{ reason_code: string; count: number }>;
};

export type AgentObservabilityDailyResponse = {
  ok: boolean;
  ts: number;
  days: number;
  window?: { start_ms: number; end_ms: number };
  last_24h?: {
    bugfix_ok: number;
    bugfix_fail: number;
    paramopt_runs: number;
    paramopt_runs_strategy?: number;
    paramopt_runs_system?: number;
    paramopt_suggestions: number;
    paramopt_suggestions_strategy?: number;
    paramopt_suggestions_system?: number;
    strategy_imports: number;
    shadow_candidates: number;
    rollbacks: number;
    approvals: number;
    approvals_strategy?: number;
    approvals_system?: number;
    closure_rate?: number;
    timeout_rate?: number;
    paramopt_timeouts?: number;
    mttr_minutes?: number;
    system_gate_kpi_block_count?: number;
    system_gate_plan_block_count?: number;
    top_reason_codes?: Array<{ reason_code: string; count: number }>;
  };
  rows: AgentObservabilityDailyRow[];
  error?: string;
};

export const fetchAgentObservabilityDaily = async (params?: { days?: number }) =>
  (await api.get<AgentObservabilityDailyResponse>('/agent/observability/daily', { params })).data;

export type AgentObservabilityParamoptRecentItem = {
  trace_id: string;
  ts: number;
  opt_class?: string | null;
  strategy_id?: string | null;
  plan_id?: string | null;
  step_id?: string | null;
  step_seq?: number | null;
  reason_code?: string | null;
  failed_stage?: string | null;
  has_run?: boolean | null;
  has_suggestion?: boolean | null;
  mode?: string;
  preset?: string | null;
  family?: string | null;
  eval_mode?: string | null;
  folds?: number | null;
  n_init?: number | null;
  n_iter?: number | null;
  keys?: string[] | null;
  requested_keys_n?: number | null;
  ok?: boolean | null;
  gate_pass?: boolean | null;
  gate_fails_n?: number | null;
  selected_keys_n?: number | null;
  selected_rank?: number | null;
  selected_patch_n?: number | null;
  selected_patch_keys?: string[] | null;
  selected_config_patch_n?: number | null;
  selected_config_suggest_n?: number | null;
  apply_ok?: boolean | null;
  apply_mode?: string | null;
  apply_draft_id?: string | null;
  apply_approval_id?: string | null;
  optimizer_engine?: string | null;
  optimizer_error?: string | null;
  optimizer_fallback?: boolean | null;
  draft_id?: string | null;
  approval_id?: string | null;
};

export type AgentObservabilityParamoptRecentResponse = {
  ok: boolean;
  ts: number;
  days: number;
  limit: number;
  items: AgentObservabilityParamoptRecentItem[];
  error?: string;
};

export const fetchAgentObservabilityParamoptRecent = async (params?: { limit?: number; days?: number }) =>
  (await api.get<AgentObservabilityParamoptRecentResponse>('/agent/observability/paramopt/recent', { params })).data;

export type AgentOverviewSummaryResponse = {
  ok: boolean;
  ts?: number;
  twitter_config?: {
    twitter_enabled?: boolean | null;
    twitter_max_per_hour?: number | null;
    twitter_rate_window_sec?: number | null;
    twitter_min_interval_sec?: number | null;
  };
  twitter?: AgentTwitterMetricsResponse;
  trade_monitor_today?: {
    ok: boolean;
    day?: string;
    window?: { start_ms?: number; end_ms?: number };
    updated_ms?: number;
    summary?: {
      trades?: number;
      wins?: number;
      losses?: number;
      winrate?: number;
      pnl_net_u?: number;
      fees_u?: number;
      funding_u?: number;
      max_drawdown_u?: number;
    } | null;
    analysis?: { template_version?: number; text?: string } | null;
    input_evidence?: { method?: string; endpoint?: string }[] | null;
    error?: string;
    ts?: number;
  };
  error?: string;
};

export const fetchAgentOverviewSummary = async (params?: { window_sec?: number }) =>
  (await api.get<AgentOverviewSummaryResponse>('/agent/overview/summary', { params })).data;

export type AgentOutboxFileItem = {
  name: string;
  size?: number;
  mtime_ms?: number;
};

export type AgentOutboxFilesResponse = {
  ok: boolean;
  dir?: string;
  items: AgentOutboxFileItem[];
  count?: number;
  ts: number;
};

export const fetchAgentOutboxFiles = async () => (await api.get<AgentOutboxFilesResponse>('/agent/outbox/files')).data;

export type AgentOutboxReadResponse = {
  ok: boolean;
  name: string;
  offset: number;
  next_offset: number;
  items: { offset: number; item: unknown }[];
  count: number;
  reset?: boolean;
  ts: number;
};

export const fetchAgentOutboxRead = async (params: { name: string; offset?: number; limit?: number; compact?: boolean; tail?: boolean; tail_bytes?: number }) =>
  (await api.get<AgentOutboxReadResponse>('/agent/outbox/read', { params })).data;


export type FundamentalNewsBriefResponse = {
  ok: boolean;
  ts: number;
  path?: string;
  name?: string;
  generated_at?: string;
  content?: string;
  content_chars?: number;
  content_truncated?: boolean;
  max_chars?: number;
  quality?: string;
  coverage?: number | null;
  missing_data?: string[];
  turning_point_state?: string;
  trigger_reasons?: string[];
  confirm_bars?: number;
  turning_point_detail?: { level?: number | null; slope?: number | null; stress?: string } | null;
  execution_gate?: string;
  monitoring_clocks?: { update_frequency_sec?: number; max_tolerated_delay_sec?: number; backfill_freeze_window_sec?: number } | null;
  template_guard?: Record<string, unknown> | null;
  error?: string;
};

export const fetchFundamentalNewsBriefLatest = async (params?: { name?: string; max_chars?: number }) =>
  (await api.get<FundamentalNewsBriefResponse>('/fundamental/news/brief/latest', { params })).data;

export type FundamentalNewsEventLedgerItem = {
  _idx?: number;
  event_id?: string;
  timestamp?: string;
  title?: string;
  event_type?: string;
  window_range?: string;
  expectation_bucket?: string;
  risk_action_proposal?: string;
  credibility?: string;
  source_url?: string;
  published_at?: string;
  [k: string]: unknown;
};

export type FundamentalNewsEventLedgerResponse = {
  ok: boolean;
  ts: number;
  path?: string;
  name?: string;
  items?: FundamentalNewsEventLedgerItem[];
  count?: number;
  limit?: number;
  error?: string;
};

export const fetchFundamentalNewsEventLedgerLatest = async (params?: { name?: string; limit?: number }) =>
  (await api.get<FundamentalNewsEventLedgerResponse>('/fundamental/news/event_ledger/latest', { params })).data;

export type FundamentalNewsRiskActionItem = {
  _idx?: number;
  event_id?: string;
  ts?: string;
  title?: string;
  event_type?: string;
  event_window_range?: string;
  expectation_bucket?: string;
  risk_action_proposal?: string;
  execution_gate?: string;
  evidence_grade?: string;
  source_quality_score?: number;
  source_url?: string;
  published_at?: string;
  risk_flags?: string[];
  [k: string]: unknown;
};

export type FundamentalNewsRiskActionResponse = {
  ok: boolean;
  ts: number;
  path?: string;
  name?: string;
  items?: FundamentalNewsRiskActionItem[];
  count?: number;
  limit?: number;
  error?: string;
};

export const fetchFundamentalNewsRiskActionEventsLatest = async (params?: { name?: string; limit?: number }) =>
  (await api.get<FundamentalNewsRiskActionResponse>('/fundamental/news/risk_action_events/latest', { params })).data;

export type FundamentalNewsAnchorDeltaViewResponse = {
  ok: boolean;
  ts: number;
  path?: string;
  name?: string;
  record?: Record<string, unknown>;
  error?: string;
};

export const fetchFundamentalNewsAnchorDeltaViewLatest = async (params?: { name?: string }) =>
  (await api.get<FundamentalNewsAnchorDeltaViewResponse>('/fundamental/news/anchor_delta_view/latest', { params })).data;

export type FundamentalNewsEvaluationHistoryRow = {
  stamp?: string;
  ts_ms?: number;
  asof?: string;
  coverage_report_name?: string;
  risk_action_events_name?: string;
  generated_at?: string;
  quality?: string;
  coverage?: number;
  missing_data?: string[];
  turning_point_state?: string;
  dominant_action?: string;
  action_total?: number;
  action_counts?: Record<string, number>;
  [k: string]: unknown;
};

export type FundamentalNewsEvaluationHistoryResponse = {
  ok: boolean;
  ts: number;
  anchor_hour?: number;
  rows?: FundamentalNewsEvaluationHistoryRow[];
  anchor_run?: FundamentalNewsEvaluationHistoryRow | null;
  latest_run?: FundamentalNewsEvaluationHistoryRow | null;
  delta?: Record<string, unknown>;
  error?: string;
};

export const fetchFundamentalNewsEvaluationHistory = async (params?: { limit?: number; anchor_hour?: number }) =>
  (await api.get<FundamentalNewsEvaluationHistoryResponse>('/fundamental/news/evaluation/history', { params })).data;

export type FundamentalNewsAutomationStateResponse = {
  ok: boolean;
  ts: number;
  enabled?: boolean;
  period_hours?: number;
  period_sec?: number;
  window_hours?: number;
  state?: Record<string, unknown>;
  latest?: Record<string, unknown>;
  error?: string;
};

export const fetchFundamentalNewsAutomationState = async () =>
  (await api.get<FundamentalNewsAutomationStateResponse>('/fundamental/news/automation')).data;

export type FundamentalNewsAutomationConfigResponse = {
  ok: boolean;
  ts: number;
  enabled?: boolean;
  period_hours?: number;
  period_sec?: number;
  window_hours?: number;
  state?: Record<string, unknown>;
  error?: string;
};

export const setFundamentalNewsAutomationConfig = async (payload: { enabled?: boolean; period_hours?: number; window_hours?: number }) =>
  (await api.post<FundamentalNewsAutomationConfigResponse>('/fundamental/news/automation/config', payload)).data;

export type FundamentalNewsAutomationRunResponse = {
  ok: boolean;
  queued?: boolean;
  ts: number;
  hours?: number;
  source?: string;
  trigger_event?: string;
  state?: Record<string, unknown>;
  error?: string;
};

export const runFundamentalNewsAutomationNow = async (payload?: { hours?: number; trigger_event?: string }) =>
  (await api.post<FundamentalNewsAutomationRunResponse>('/fundamental/news/automation/run', payload ?? {})).data;

export type AgentLlmHealthResponse = {
  ok: boolean;
  healthy?: boolean;
  provider?: string;
  model?: string;
  chat_url?: string;
  base_url?: string;
  reachable?: boolean;
  version_ok?: boolean;
  version?: string | null;
  version_error?: string | null;
  tags_ok?: boolean;
  tags_error?: string | null;
  models?: string[];
  model_in_tags?: boolean;
  show_ok?: boolean;
  show_error?: string | null;
  model_available?: boolean;
  hint_pull?: string;
  error?: string;
  ts?: number;
};

export const fetchAgentLlmHealth = async (params?: { provider?: string; model?: string }) =>
  (await api.get<AgentLlmHealthResponse>('/agent/llm/health', { params })).data;

export type AgentParamoptSearchSpaceItem = {
  key: string;
  label?: string;
  desc?: string;
  scope?: string;
  type?: 'int' | 'float' | 'bool' | string;
  default?: unknown;
  range?: { min?: number; max?: number; step?: number } | null;
  apply_mode?: 'auto' | 'auto-tighten-only' | 'suggest-only' | string;
  tags?: string[];
  group?: string;
  unit?: string;
  severity_min?: string;
  severity_max?: string;
};

export type AgentParamoptSearchSpaceResponse = {
  ok: boolean;
  trace_id?: string;
  ts?: number;
  severity?: string;
  opt_class?: 'strategy' | 'system' | string;
  strategy_id?: string | null;
  group_id?: string | null;
  space?: {
    version?: string;
    source?: string;
    items?: AgentParamoptSearchSpaceItem[];
  };
  selection?: {
    selected_keys?: string[];
    selected_n?: number;
    ignored_n?: number;
  };
  allowlist?: Record<string, unknown>;
  error?: string;
};

export const fetchAgentParamoptSearchSpace = async (payload: {
  trace_id?: string;
  opt_class?: 'strategy' | 'system';
  strategy_id?: string;
  context?: Record<string, unknown>;
  scope?: string;
  scopes?: string[];
  include_modes?: string[];
  include_suggest_only?: boolean;
}) => (await api.post<AgentParamoptSearchSpaceResponse>('/agent/paramopt/search_space', payload)).data;

export type AgentParamoptTemplatesResponse = {
  ok: boolean;
  ts?: number;
  version?: string;
  updated_at?: string;
  kind?: 'base' | 'daily' | 'approval' | string;
  template?: string;
  templates?: {
    base?: string;
    daily?: string;
    approval?: string;
  };
  error?: string;
};

export const fetchAgentParamoptTemplates = async (params?: { kind?: 'base' | 'daily' | 'approval' }) =>
  (await api.get<AgentParamoptTemplatesResponse>('/agent/paramopt/templates', { params })).data;

export type AgentParamoptRunResponse = {
  ok: boolean;
  trace_id?: string;
  ts?: number;
  mode?: string;
  severity?: string;
  eval_mode?: string;
  family?: string;
  folds?: number;
  keys?: string[];
  requested_keys?: string[];
  ignored_keys?: string[];
  optimizer_error?: string | null;
  baseline?: Record<string, unknown> | null;
  selected?: Record<string, unknown> | null;
  topk?: Record<string, unknown> | null;
  gate?: Record<string, unknown> | null;
  history?: Array<Record<string, unknown>>;
  apply?: Record<string, unknown> | null;
  rollback_point?: Record<string, unknown> | null;
  portfolio_gate_config?: Record<string, unknown> | null;
  draft_id?: string | null;
  approval_id?: string | null;
  error?: string;
};

export const runAgentParamopt = async (payload: {
  trace_id?: string;
  mode?: 'suggest' | 'sandbox' | 'apply';
  preset?: string;
  opt_kind?: string;
  opt_class?: string;
  strategy_id?: string;
  plan_id?: string;
  step_id?: string;
  step_seq?: number;
  plan?: {
    plan_id?: string;
    step_id?: string;
    step_seq?: number;
    current_step_idx?: number;
    created_by?: string;
    created_at?: number;
  };
  context?: Record<string, unknown>;
  scope?: string;
  scopes?: string[];
  include_modes?: string[];
  include_suggest_only?: boolean;
  keys?: string[];
  family?: string;
  eval_mode?: 'rolling' | 'backtest';
  folds?: number;
  n_init?: number;
  n_iter?: number;
  topk?: number;
  skip_robustness?: boolean;
  embargo_days?: number;
  is_frac?: number;
  robust_n_slices?: number;
  robust_n_bootstrap?: number;
  robust_n_shuffle?: number;
  fallback_backtest?: boolean;
  bootstrap_samples?: boolean;
  backtest_config?: string;
  backtest_timerange?: string | null;
  backtest_strategy?: string | null;
  backtest_timeout_sec?: number;
  order_fail_rate_days?: number;
  order_fail_rate_delta?: number;
  portfolio_u_r_min?: number;
  portfolio_dd_guard?: number;
  portfolio_tail_guard?: number;
  portfolio_order_fail_delta_guard?: number;
  portfolio_rollback_consecutive_gate_fail_k?: number;
  confirm_apply?: boolean;
}) => (await api.post<AgentParamoptRunResponse>('/agent/paramopt/run', payload)).data;

export type AgentChatCommandResponse = {
  ok: boolean;
  queued?: boolean;
  id?: string;
  trace_id?: string;
  ts: number;
  status?: string;
  assistant_text?: string;
  tool_plan_suggested?: unknown[];
  trade_monitor_report?: unknown;
  error?: string;
};

export type AgentSkillsExecuteResponse = {
  ok: boolean;
  queued?: boolean;
  trace_id?: string;
  ts: number;
  results?: unknown;
  duration_ms?: number;
  error?: string;
};

export type AgentSkillItem = {
  name: string;
  title?: string | null;
  category?: string | null;
  description?: string | null;
  input_schema?: Record<string, unknown>;
  enabled?: boolean;
};

export type AgentSkillsListResponse = {
  ok: boolean;
  items?: AgentSkillItem[];
  count?: number;
  ts: number;
  error?: string;
};

export const sendAgentChatCommand = async (payload: {
  trace_id?: string;
  intent: unknown;
  tool_plan?: unknown[];
  risk_level?: string;
  idempotency_key?: string;
  sync?: boolean;
  llm_enabled?: boolean;
  llm_provider?: string;
  llm_model?: string;
  llm_timeout_sec?: number;
  llm?: { enabled?: boolean; provider?: string; model?: string; timeout_sec?: number };
  frontend_evidence?: unknown;
}) => (await api.post<AgentChatCommandResponse>('/agent/chat', payload, { timeout: 120000 })).data;

export const fetchAgentSkillsList = async () => (await api.get<AgentSkillsListResponse>('/agent/skills/list')).data;

export const executeAgentSkills = async (payload: {
  trace_id: string;
  tool_plan: unknown[];
  async?: boolean;
}) => (await api.post<AgentSkillsExecuteResponse>('/agent/skills/execute', payload)).data;

export type AgentWorkflowSysMonitorBugfixResponse = {
  ok: boolean;
  queued?: boolean;
  trace_id?: string;
  ts: number;
  error?: string;
  report?: unknown;
};

export const runAgentWorkflowSysMonitorBugfix = async (payload: {
  trace_id: string;
  async?: boolean;
  lookback_days?: number;
  signals_limit?: number;
  signals_per_pair?: number;
  include_alerts?: boolean;
  include_tracker?: boolean;
  include_signals?: boolean;
}) => (await api.post<AgentWorkflowSysMonitorBugfixResponse>('/agent/workflows/sys_monitor_bugfix', payload)).data;

export type AgentTraceReplayResponse = {
  ok: boolean;
  ts: number;
  trace_id?: string;
  pair?: string | null;
  side?: string | null;
  tag?: string | null;
  event?: unknown;
  orders?: unknown[];
  settlements?: unknown[];
  error?: string;
};

export const fetchAgentTraceReplay = async (params: { trace_id: string; max_orders?: number }) =>
  (await api.get<AgentTraceReplayResponse>('/agent/trace/replay', { params })).data;

export type AgentAuditReplayResponse = {
  ok: boolean;
  ts: number;
  trace_id?: string;
  items?: unknown[];
  count?: number;
  error?: string;
};

export const fetchAgentAuditReplay = async (params: { trace_id: string; limit?: number }) =>
  (await api.get<AgentAuditReplayResponse>('/agent/audit/replay', { params })).data;

export type AgentRcaGenerateResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  summary?: unknown;
  timeline?: unknown[];
  causes?: unknown[];
  evidence?: unknown[];
  recommendations?: unknown[];
  error?: string;
};

export const generateAgentRca = async (payload: { trace_id: string; include_dq?: boolean; include_eq?: boolean }) =>
  (await api.post<AgentRcaGenerateResponse>('/agent/rca/generate', payload)).data;

export type AgentRcaAnalyzeResponse = {
  ok: boolean;
  queued?: boolean;
  trace_id?: string;
  ts: number;
  error?: string;
};

export const analyzeAgentRca = async (payload: {
  trace_id: string;
  include_dq?: boolean;
  include_eq?: boolean;
  async?: boolean;
  llm_enabled?: boolean;
  llm_provider?: string;
  llm_model?: string;
  llm_timeout_sec?: number;
  llm?: { enabled?: boolean; provider?: string; model?: string; timeout_sec?: number };
}) => (await api.post<AgentRcaAnalyzeResponse>('/agent/rca/analyze', payload)).data;

export type AgentChangesetDraftResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  evidence?: unknown;
  candidate?: unknown;
  gate_result?: unknown;
  rollback_plan?: unknown;
  doc_refs?: unknown[];
  changeset?: unknown;
  error?: string;
};

export const createAgentChangesetDraft = async (payload: {
  trace_id?: string;
  strategy_id: string;
  source_zip: string;
  config_patch?: Record<string, unknown>;
  doc_refs?: unknown[];
  label?: string;
  reason?: string;
  baseline?: Record<string, unknown> | null;
  rollback_point_id?: string | null;
  rollback_trigger?: Record<string, unknown> | null;
  policy_ref?: string;
  action?: string;
  rca?: Record<string, unknown> | null;
  online?: Record<string, unknown> | null;
}) => (await api.post<AgentChangesetDraftResponse>('/agent/changeset/draft', payload)).data;

export type FetchRecentSignalsParams = {
  limit?: number;
  sort?: string;
  diverse?: number | boolean;
  per_pair?: number;
  scan_limit?: number;
  include_backfill?: number | boolean;
  include_shadow?: number | boolean;
  include_stale?: number | boolean;
  require_bar_closed?: number | boolean;
  executed_only?: number | boolean;
  open_effective_only?: number | boolean;
  open_position_only?: number | boolean;
  no_default_filter?: number | boolean;
  start_ts?: number;
  end_ts?: number;
  pair?: string;
  coin?: string;
  ab_owner?: string;
  book_id?: string;
  strategy_id?: string;
  group_id?: string;
  timeframe?: string;
  side?: string;
  action?: string;
};

export const fetchRecentSignals = async () =>
  (await api.get<Signal[]>('/signals/recent', { params: { limit: 200, sort: 'ingest', diverse: 1, per_pair: 1, scan_limit: 2000, include_stale: 1, include_shadow: 1 }, timeout: 90000 })).data;

export const fetchRecentSignalsWithParams = async (params?: FetchRecentSignalsParams) =>
  (await api.get<Signal[]>('/signals/recent', { params: { limit: 200, sort: 'ingest', diverse: 1, per_pair: 1, scan_limit: 2000, include_stale: 1, include_shadow: 1, ...params }, timeout: 90000 })).data;

export const fetchSignalRejectStats = async (limit: number = 2000, includeShadow: boolean = false) =>
  (await api.get<SignalRejectStats>('/signals/reject_stats', { params: { limit, include_shadow: includeShadow ? 1 : 0 } })).data;

export type StrategyParamsResponse = {
  ok: boolean;
  strategies: Record<string, { group_id: string; feature_set_id: string; params: Record<string, unknown> }>;
};
export const fetchStrategyParams = async () => (await api.get<StrategyParamsResponse>('/strategy/params')).data;

export type StrategyFeederCapability = {
  strategy_id: string;
  can_trigger?: boolean;
  direction_capability?: 'long_only' | 'long_short' | 'unknown' | string;
};

export type StrategyFeederCapabilitiesResponse = {
  ok: boolean;
  supported_strategy_ids: string[];
  strategies?: StrategyFeederCapability[];
  coins_semantics?: { tick?: string; scheduler?: string };
};

export const fetchStrategyFeederCapabilities = async () =>
  (await api.get<StrategyFeederCapabilitiesResponse>('/strategy/feeder/capabilities')).data;

export const triggerStrategy005 = async (coin: string, emit = true, trigger_decision = true) =>
  (await api.post('/signals/hyperliquid/strategy005', { coin, emit, trigger_decision })).data;
export const triggerRegimeHybrid = async (coin: string, emit = true, trigger_decision = true) =>
  (await api.post('/signals/hyperliquid/regime_hybrid', { coin, emit, trigger_decision })).data;
export const triggerBreakout = async (coin: string, emit = true, trigger_decision = true) =>
  (await api.post('/signals/hyperliquid/breakout', { coin, emit, trigger_decision })).data;
export const triggerMultiGroup = async (coin: string, emit = true, trigger_decision = true) =>
  (await api.post('/signals/hyperliquid/multigroup', { coin, emit, trigger_decision })).data;

export const triggerOtt = async (coin: string, emit = true, trigger_decision = true) =>
  (await api.post('/signals/hyperliquid/ott', { coin, emit, trigger_decision })).data;

export const triggerAdaptiveVolatility = async (coin: string, emit = true, trigger_decision = true) =>
  (await api.post('/signals/hyperliquid/adaptive_volatility', { coin, emit, trigger_decision })).data;

export type StrategyFeederConfig = {
  enable_strategy_feeders: boolean;
  feeders_period_seconds: number;
  strategy_feeders: { strategy_id: string; coins: string[]; trigger_decision: boolean; emit: boolean }[];
};
export type AutomationStrategiesConfig = {
  trace_id?: string;
  approval_id?: string;
  confirm_live?: boolean;
  enable_strategy_feeders: boolean;
  feeders_period_seconds: number;
  strategy_feeders: { strategy_id: string; coins: string[]; trigger_decision: boolean; emit: boolean }[];
  use_universe_core?: boolean;
  exit_feeder_period_seconds?: number;
  use_exit_feeder?: boolean;
  use_exit_feeder_strategy?: boolean;
};

export type AutomationStrategiesConfigResponse = {
  ok: boolean;
  automation: AutomationStrategiesConfig;
};

export const setStrategyFeederConfig = async (payload: AutomationStrategiesConfig) =>
  (await api.post<AutomationStrategiesConfigResponse>('/automation/strategies/config', payload)).data;
export const setStrategyFeederUseCore = async (enabled: boolean, periodSeconds = 30) => {
  try {
    return (
      await api.post<AutomationStrategiesConfigResponse>('/automation/strategies/config', {
        use_universe_core: enabled,
        enable_strategy_feeders: enabled,
        feeders_period_seconds: periodSeconds,
      })
    ).data;
  } catch {
    return { ok: false, automation: { enable_strategy_feeders: false, feeders_period_seconds: periodSeconds, strategy_feeders: [] } };
  }
};
export const fetchAutomationState = async () => (await api.post<AutomationStrategiesConfigResponse>('/automation/strategies/config', {})).data;
export const fetchAutomationStrategiesState = async () => (await api.get<AutomationStrategiesConfigResponse>('/automation/strategies/state')).data;

export type AutomationManagementStateResponse = {
  ok: boolean;
  ts: number;
  shadow?: {
    enabled?: boolean;
    autostart?: boolean;
    cooldown_minutes?: number;
    candidate_limit?: number;
    baseline_enabled?: boolean;
    skip_paramopt?: boolean;
    state?: Record<string, unknown> | null;
  };
  paramopt_daily?: {
    enabled?: boolean;
    shadow_required?: boolean;
    shadow_enabled?: boolean;
    config?: Record<string, unknown> | null;
    shadow_gate?: Record<string, unknown> | null;
    last?: Record<string, unknown> | null;
  };
  twitter?: { enabled?: boolean };
  error?: string;
};

export const fetchAutomationManagementState = async () => (await api.get<AutomationManagementStateResponse>('/automation/management/state')).data;

export type AutomationProgressStepV1 = {
  key: string;
  label: string;
  status: 'WAIT' | 'RUN' | 'DONE' | 'FAIL' | 'SKIP' | string;
  ts_ms?: number | null;
  evidence?: Record<string, unknown>;
};

export type AutomationProgressV1 = {
  schema_version: 'v1';
  pct: number;
  steps: AutomationProgressStepV1[];
};

export type AutomationCardStateV1 = {
  schema_version: 'v1';
  card_id: 'gtw_global_workflow' | 'shadow_switch' | 'strategy_supply_chain' | 'strategy_shadow_loop' | 'paramopt_automation' | 'twitter_delivery' | 'web3_market_digest' | 'other';
  status: 'OFF' | 'ON' | 'RUNNING' | 'BLOCKED' | 'ERROR';
  updated_at_ms: number;
  trace_id?: string | null;
  progress?: AutomationProgressV1;
  stuck?: {
    stuck_at?: string;
    stuck_since_ms?: number;
    reason_code?: string;
    reason?: string;
  } | null;
  actions?: {
    id: string;
    label: string;
    kind: 'navigate' | 'readonly' | 'controlled';
    href?: string;
    request?: Record<string, unknown>;
  }[];
  details?: Record<string, unknown>;
};

export type AutomationCardsStateResponse = {
  ok: boolean;
  schema_version: 'v1';
  ts: number;
  cards: AutomationCardStateV1[];
  error?: string;
};

export const fetchAutomationCardsState = async (params?: { details?: boolean }) =>
  (await api.get<AutomationCardsStateResponse>('/automation/cards/state', { params: { details: params?.details ? 1 : 0 } })).data;

export type AutomationConfigSetResponse = { ok: boolean; automation?: Record<string, unknown>; trace_id?: string; approval_id?: string | null; rollback_point?: string | null; ts?: number; error?: string };
export const setAutomationConfig = async (payload: {
  trace_id?: string;
  approval_id?: string;
  confirm_live?: boolean;
  enable_shadow_automation_loop?: boolean;
  shadow_automation_autostart?: boolean;
  enable_paramopt_daily?: boolean;
  enable_sys_monitor_bugfix?: boolean;
  sys_monitor_light_poll_enabled?: boolean;
  sys_monitor_light_poll_interval_sec?: number;
  sys_monitor_global_poll_enabled?: boolean;
  sys_monitor_global_poll_hour_utc?: number;
  sys_monitor_global_poll_minute_utc?: number;
  sys_monitor_global_poll_lookback_days?: number;
  sys_monitor_global_poll_timerange_days?: number;
  sys_monitor_global_poll_timeout_sec?: number;
  sys_monitor_auto_alert_cooldown_sec?: number;
  [k: string]: unknown;
}) => (await api.post<AutomationConfigSetResponse>('/automation/config', payload)).data;

export type AutomationParamoptTriggerResponse = {
  ok: boolean;
  error?: string;
  trace_id?: string;
  ts?: number;
  http?: number;
  result?: Record<string, unknown> | null;
};
export const triggerAutomationParamopt = async (payload: { trace_id?: string; confirm_live?: boolean; mode?: string; [k: string]: unknown }) =>
  (await api.post<AutomationParamoptTriggerResponse>('/automation/paramopt/trigger', payload)).data;
export const triggerAutomationParamoptExplore = async (payload: { trace_id?: string; confirm_live?: boolean; mode?: string; [k: string]: unknown }) =>
  (await api.post<AutomationParamoptTriggerResponse>('/automation/paramopt/explore/trigger', payload)).data;

export type AutomationParamoptScenariosEnsureResponse = {
  ok: boolean;
  queued?: boolean;
  trace_id?: string;
  ts?: number;
  scenarios?: string[];
  max_batches?: number;
  error?: string;
};
export const runAutomationParamoptScenariosEnsure = async (payload: {
  trace_id?: string;
  scenarios?: string[];
  max_batches?: number;
  ensure_missing_only?: boolean;
  budget?: Record<string, unknown>;
  context_extra?: Record<string, unknown>;
  source?: string;
  [k: string]: unknown;
}) => (await api.post<AutomationParamoptScenariosEnsureResponse>('/automation/paramopt/scenarios/ensure', payload)).data;

export type AutomationParamoptSmokeApplyResponse = {
  ok: boolean;
  trace_id?: string;
  ts?: number;
  paramopt_http?: number;
  paramopt?: Record<string, unknown> | null;
  patch?: Record<string, unknown> | null;
  apply_http?: number;
  apply?: Record<string, unknown> | null;
  rollback_http?: number | null;
  rollback?: Record<string, unknown> | null;
  error?: string;
};
export const runAutomationParamoptSmokeApply = async (payload: {
  trace_id?: string;
  rollback_after?: boolean;
  scenario?: string;
  trigger_event?: string;
  preset?: string;
  family?: string;
  eval_mode?: string;
  folds?: number;
  n_init?: number;
  n_iter?: number;
  keys?: string[];
  [k: string]: unknown;
}) => (await api.post<AutomationParamoptSmokeApplyResponse>('/automation/paramopt/live/smoke_apply', payload)).data;

export type AutomationWeb3MarketDigestRunResponse = {
  ok: boolean;
  error?: string;
  trace_id?: string;
  ts?: number;
  digest?: Record<string, unknown> | null;
};
export const runAutomationWeb3MarketDigest = async (payload: { force?: boolean; trigger_event?: string | null; [k: string]: unknown }) =>
  (await api.post<AutomationWeb3MarketDigestRunResponse>('/automation/web3/market_digest/run', payload)).data;

export type ApprovalGetResponse = {
  ok: boolean;
  id?: string;
  approval?: Record<string, unknown> | null;
  ts?: number;
  error?: string;
};
export const fetchApprovalGet = async (params: { id: string }) =>
  (await api.get<ApprovalGetResponse>('/approvals/get', { params })).data;

export type ChangesetDraftGetResponse = {
  ok: boolean;
  id?: string;
  entry?: Record<string, unknown> | null;
  ts?: number;
  error?: string;
};
export const fetchAgentChangesetDraftGet = async (params: { id: string }) =>
  (await api.get<ChangesetDraftGetResponse>('/agent/changeset/draft/get', { params })).data;

export type AgentAutomationWeb3MarketDigestResponse = {
  ok: boolean;
  error?: string;
  ts?: number;
  hold_sec?: number;
  latest_age_sec?: number | null;
  state?: Record<string, unknown> | null;
  latest?: Record<string, unknown> | null;
  latest_any?: Record<string, unknown> | null;
};

export const fetchAgentAutomationWeb3MarketDigest = async () =>
  (await api.get<AgentAutomationWeb3MarketDigestResponse>('/agent/automation/web3_market_digest')).data;

export type AgentAutomationAutoTradeStateResponse = {
  ok: boolean;
  error?: string;
  ts?: number;
  auto_trade_enabled?: boolean;
  auto_trade_mode?: string;
  auto_trade_env?: string;
  auto_trade_kill_switch?: boolean;
  auto_trade_require_isolation?: boolean;
  auto_trade_auto_exit_enabled?: boolean;
  auto_trade_binance_spot_open_in_prod?: boolean;
  kill_switch_triggered?: boolean;
  isolation?: Record<string, unknown> | null;
  state?: Record<string, unknown> | null;
};

export const fetchAgentAutomationAutoTradeState = async () =>
  (await api.get<AgentAutomationAutoTradeStateResponse>('/agent/automation/auto_trade')).data;

export type AutoTradeDecisionItem = {
  id?: string;
  trace_id?: string;
  ts?: number;
  type?: string;
  decision_id?: string;
  chain_id?: string;
  candidate?: { symbol?: string; contractAddress?: string };
  constraints?: Record<string, unknown>;
  scoring?: Record<string, unknown>;
  digest_ref?: Record<string, unknown>;
};

export type AgentAutomationAutoTradeDecisionsResponse = {
  ok: boolean;
  ts?: number;
  window_sec?: number;
  outbox?: string;
  items?: AutoTradeDecisionItem[];
  error?: string;
};

export const fetchAgentAutomationAutoTradeDecisions = async (params?: { window_sec?: number }) =>
  (await api.get<AgentAutomationAutoTradeDecisionsResponse>('/agent/automation/auto_trade/decisions', { params })).data;

export type AutoTradeKillSwitchTriggerResponse = { ok: boolean; ts?: number; triggered?: boolean; reason?: string; error?: string };
export const triggerAutoTradeKillSwitch = async (payload: { trace_id?: string; reason?: string }) =>
  (await api.post<AutoTradeKillSwitchTriggerResponse>('/agent/automation/auto_trade/kill_switch/trigger', payload)).data;

export type AutoTradePrecheckRunResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  type?: string;
  chain_id?: string;
  contract_address?: string;
  audit?: Record<string, unknown>;
  tradeable?: Record<string, unknown>;
  gate?: { decision?: string; reason?: string };
  error?: string;
};

export const runAutoTradePrecheck = async (payload: { trace_id?: string; chain_id?: string; contract_address: string; timeout_sec?: number }) =>
  (await api.post<AutoTradePrecheckRunResponse>('/agent/automation/auto_trade/precheck/run', payload)).data;

export type AutoTradeOrderIntentResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  type?: string;
  intent_id?: string;
  chain_id?: string;
  contract_address?: string;
  symbol?: string | null;
  side?: string;
  router?: string | null;
  max_slippage_bps?: number;
  notional_usd?: unknown;
  size_token?: unknown;
  pretrade_checks?: Record<string, unknown>;
  error?: string;
};

export const createAutoTradeOrderIntent = async (payload: {
  trace_id?: string;
  chain_id?: string;
  contract_address: string;
  symbol?: string;
  side?: 'buy' | 'sell' | string;
  router?: string;
  max_slippage_bps?: number;
  notional_usd?: number;
  size_token?: number;
  pretrade_checks?: Record<string, unknown>;
}) => (await api.post<AutoTradeOrderIntentResponse>('/agent/automation/auto_trade/order/intent', payload)).data;

export type AutoTradeOrderReceiptResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  type?: string;
  intent_id?: string;
  order_id?: string | null;
  tx_hash?: string | null;
  status?: string;
  error?: unknown;
};

export const createAutoTradeOrderReceipt = async (payload: {
  trace_id?: string;
  intent_id: string;
  order_id?: string;
  tx_hash?: string;
  status?: string;
  filled_qty?: number;
  avg_price?: number;
  fee?: number;
  error?: unknown;
  meta?: Record<string, unknown>;
}) => (await api.post<AutoTradeOrderReceiptResponse>('/agent/automation/auto_trade/order/receipt', payload)).data;

export type AutoTradeExitReceiptResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  type?: string;
  intent_id?: string;
  position_id?: string | null;
  tx_hash?: string | null;
  status?: string;
  error?: unknown;
};

export const createAutoTradeExitReceipt = async (payload: {
  trace_id?: string;
  intent_id: string;
  position_id?: string;
  tx_hash?: string;
  status?: string;
  filled_qty?: number;
  avg_price?: number;
  fee?: number;
  error?: unknown;
  meta?: Record<string, unknown>;
}) => (await api.post<AutoTradeExitReceiptResponse>('/agent/automation/auto_trade/exit/receipt', payload)).data;

export type AutoTradePositionsResponse = {
  ok: boolean;
  ts?: number;
  positions?: Record<string, unknown>[];
  error?: string;
};

export const fetchAutoTradePositions = async () =>
  (await api.get<AutoTradePositionsResponse>('/agent/automation/auto_trade/positions')).data;

export type AutoTradePositionOpenResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  position_id?: string;
  position?: Record<string, unknown>;
  error?: string;
};

export const createAutoTradePositionOpen = async (payload: {
  trace_id?: string;
  chain_id?: string;
  contract_address: string;
  symbol?: string;
  entry_ref?: string;
  size_token?: number;
  notional_usd?: number;
}) => (await api.post<AutoTradePositionOpenResponse>('/agent/automation/auto_trade/position/open', payload)).data;

export type AutoTradePositionSnapshotResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  type?: string;
  position_id?: string | null;
  chain_id?: string;
  contract_address?: string;
  symbol?: string | null;
  refresh_period?: string | null;
  factors?: Record<string, unknown>;
  error?: string;
};

export const createAutoTradePositionSnapshot = async (payload: {
  trace_id?: string;
  position_id?: string;
  chain_id?: string;
  contract_address?: string;
  refresh_period?: string;
  factors?: Record<string, unknown>;
}) => (await api.post<AutoTradePositionSnapshotResponse>('/agent/automation/auto_trade/position/snapshot', payload)).data;

export type AutoTradeExitIntentResponse = {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  type?: string;
  intent_id?: string;
  position_id?: string | null;
  mode?: string;
  reason?: string;
  selected_factors?: string[];
  confirm_count?: number;
  risk_score?: number | null;
  value_score?: number | null;
  action?: 'hold' | 'reduce' | 'close' | string;
  reduce_ratio?: number;
  error?: string;
};

export const createAutoTradeExitIntent = async (payload: {
  trace_id?: string;
  position_id?: string;
  reason?: string;
  mode?: 'manual' | 'auto' | string;
  selected_factors?: string[];
  confirm_count?: number;
  risk_score?: number;
  value_score?: number;
  action?: 'hold' | 'reduce' | 'close' | string;
  reduce_ratio?: number;
}) => (await api.post<AutoTradeExitIntentResponse>('/agent/automation/auto_trade/exit/intent', payload)).data;

export type AutoTradeExitReviewRunResponse = {
  ok: boolean;
  ts?: number;
  checked?: number;
  emitted?: number;
  skipped?: boolean;
  reason?: string;
  error?: string;
};

export const runAutoTradeExitReview = async (payload?: { reason?: string }) =>
  (await api.post<AutoTradeExitReviewRunResponse>('/agent/automation/auto_trade/exit/review/run', payload ?? {})).data;

export type AutomationShadowLoopRunResponse = {
  ok: boolean;
  error?: string;
  trace_id?: string;
  ts?: number;
  http?: number;
  result?: Record<string, unknown> | null;
};

export const runAutomationShadowLoop = async (payload: {
  mode?: 'new' | 'retry' | string;
  trace_id?: string;
  candidate_limit?: number;
  baseline_enabled?: boolean;
  skip_paramopt?: boolean;
  gates?: string[];
}) => (await api.post<AutomationShadowLoopRunResponse>('/automation/shadow_loop/run', payload)).data;

export type AutomationBacktestRunResponse = {
  ok: boolean;
  error?: string;
  cmd?: string[];
  stdout?: string;
  stderr?: string;
  result_zip?: string | null;
  metrics_summary?: Record<string, unknown> | null;
  summary?: { metrics?: Record<string, unknown> };
  report?: Record<string, unknown>;
};

export const runAutomationBacktest = async (payload: {
  config?: string;
  timerange?: string;
  strategy?: string;
  sandbox_path?: string;
  strategy_name?: string;
  env?: Record<string, string | number | boolean | null>;
  timeout_sec?: number;
}) => (await api.post<AutomationBacktestRunResponse>('/automation/backtest/run', payload)).data;

export type AutomationSupplyChainRunResponse = {
  ok: boolean;
  trace_id?: string;
  approval_id?: string | null;
  error?: string;
  details?: Record<string, unknown> | null;
  ts?: number;
};

export const runAutomationSupplyChain = async (payload: {
  trace_id?: string;
  mode?: 'auto' | 'local' | 'github' | string;
  timerange?: string;
  timerange_days?: number;
  config?: string;
  strategy_name?: string;
  repo_url?: string;
  branch?: string;
  commit?: string;
  path?: string;
  family?: string;
  stage?: string;
  timeout_sec?: number;
  enqueue_sandbox?: boolean;
  verify_live?: boolean;
}) => (await api.post<AutomationSupplyChainRunResponse>('/automation/supply_chain/run', payload)).data;

export type AutomationSystemMonitorRunResponse = {
  ok: boolean;
  error?: string;
  trace_id?: string;
  ts?: number;
  result?: Record<string, unknown> | null;
};

export const runAutomationSystemMonitor = async (payload: {
  mode?: 'new' | 'retry' | string;
  trace_id?: string;
  pair?: string;
  strategy?: string;
  lookback_days?: number;
  timerange?: string;
  timerange_days?: number;
  config?: string;
  timeout_sec?: number;
  run_link_check?: boolean;
  run_backtest?: boolean;
}) => (await api.post<AutomationSystemMonitorRunResponse>('/automation/system_monitor/run', payload)).data;

export type AutomationGtwRunResponse = {
  ok: boolean;
  error?: string;
  ts?: number;
  decision_id?: string;
  trace_id?: string;
  package?: Record<string, unknown> | null;
};
export const runAutomationGtw = async (payload: { force?: boolean; trigger_event?: string | null }) =>
  (await api.post<AutomationGtwRunResponse>('/automation/gtw/run', payload)).data;

 

export type AutomationTrainingRunResponse = {
  ok: boolean;
  error?: string;
  details?: Record<string, unknown> | null;
};

export const runAutomationTraining = async (payload: { family?: string; params?: Record<string, unknown> }) =>
  (await api.post<AutomationTrainingRunResponse>('/automation/training/run', payload)).data;

export type RollingVerifyResponse = { ok: boolean; error?: string; summary?: Record<string, unknown> | null; details?: Record<string, unknown> | null };
export const runEvaluationRollingVerify = async (payload: {
  family?: string;
  folds?: number;
  calibrate_method?: string;
  embargo_ms?: number;
  use_thresholds?: boolean;
  stress_cost_pct?: number;
  bucketed?: boolean;
}) => (await api.post<RollingVerifyResponse>('/evaluation/rolling_verify', payload)).data;

export type MonteCarloResponse = { ok: boolean; error?: string; summary?: Record<string, unknown> | null; details?: Record<string, unknown> | null };
export const runEvaluationMonteCarlo = async (payload: {
  family?: string;
  runs?: number;
  window?: number;
  calibrated?: boolean;
  p_noise_std?: number;
  ret_noise_std?: number;
  cost_pct?: number;
  bootstrap?: boolean;
  drop_frac?: number;
  seed?: number;
}) => (await api.post<MonteCarloResponse>('/evaluation/monte_carlo', payload)).data;

export type RollbackListResponse = { ok: boolean; count: number; items: { id?: string; ts?: number; label?: string; reason?: string }[] };
export const fetchRollbackList = async (params?: { limit?: number }) => (await api.get<RollbackListResponse>('/evaluation/rollback/list', { params })).data;
export const createRollbackSnapshot = async (payload: { label?: string; reason?: string; include_arena?: boolean; include_dynamic_thresholds?: boolean; include_active_model?: boolean; include_tracker_state?: boolean; include_arena_state?: boolean }) =>
  (await api.post<{ ok: boolean; point?: Record<string, unknown> }>('/evaluation/rollback/snapshot', payload)).data;
export type RollbackRestoreResponse = {
  ok: boolean;
  error?: string;
  point_id?: string;
  latest?: boolean;
  reason?: string;
  threshold_hits?: unknown;
  evidence?: unknown;
  pre_snapshot?: string | null;
  approval_id?: string | null;
  trace_id?: string;
  ts?: number;
};

export const restoreRollbackSnapshot = async (payload: {
  id?: string;
  latest?: boolean;
  restore_thresholds?: boolean;
  restore_arena?: boolean;
  restore_active_model?: boolean;
  restore_tracker_state?: boolean;
  restore_config?: boolean;
  reason?: string;
  threshold_hits?: unknown;
  evidence?: unknown;
}) => (await api.post<RollbackRestoreResponse>('/evaluation/rollback/restore', payload)).data;

export type ApprovalsSummaryResponse = {
  ok: boolean;
  counts: { total: number; pending: number; approved: number; rejected: number; other: number };
  pending: {
    id?: string | null;
    trace_id?: string | null;
    action?: string | null;
    reason?: string | null;
    approver?: string | null;
    decision?: string | null;
    ts?: number | null;
    expires_at?: number | null;
    ttl_ms?: number | null;
    is_explore?: boolean | null;
    auto_reject_policy?: string | null;
  }[];
  recent_auto_rejected?: { id?: string | null; trace_id?: string | null; action?: string | null; reason?: string | null; approver?: string | null; decision?: string | null; ts?: number | null }[];
  latest: { id?: string | null; trace_id?: string | null; action?: string | null; decision?: string | null; ts?: number | null } | null;
  path?: string;
  ts?: number;
  error?: string;
};

export const fetchApprovalsSummary = async (params?: { max_lines?: number; max_bytes?: number }) =>
  (await api.get<ApprovalsSummaryResponse>('/approvals/summary', { params })).data;

export type ApprovalHistoryItem = {
  id?: string | null;
  trace_id?: string | null;
  action?: string | null;
  decision?: string | null;
  reason?: string | null;
  approver?: string | null;
  ts?: number | null;
};
export type ApprovalsHistoryResponse = {
  ok: boolean;
  items: ApprovalHistoryItem[];
  total_scanned?: number;
  total_matched?: number;
  returned?: number;
  offset?: number;
  limit?: number;
  has_more?: boolean;
  path?: string;
  ts?: number;
  error?: string;
};
export const fetchApprovalsHistory = async (params?: {
  limit?: number;
  offset?: number;
  days?: number;
  decision?: string;
  action?: string;
  q?: string;
  max_lines?: number;
  max_bytes?: number;
}) => (await api.get<ApprovalsHistoryResponse>('/approvals/history', { params })).data;

export type ApprovalDetailResponse = {
  ok: boolean;
  id?: string;
  approval?: Record<string, unknown>;
  ts?: number;
  error?: string;
};
export const fetchApprovalDetail = async (params: { id: string }) =>
  (await api.get<ApprovalDetailResponse>('/approvals/get', { params })).data;

export type ApprovalBriefGetResponse = {
  ok: boolean;
  id?: string;
  brief?: Record<string, unknown>;
  ts?: number;
  error?: string;
};
export const fetchApprovalBriefGet = async (params: { id: string }) =>
  (await api.get<ApprovalBriefGetResponse>('/agent/approvals/brief/get', { params })).data;

export type ApprovalBriefGenerateResponse = {
  ok: boolean;
  id?: string;
  skipped?: boolean;
  brief?: Record<string, unknown>;
  ts?: number;
  error?: string;
};
export const generateApprovalBrief = async (payload: { id: string; force?: boolean }) =>
  (await api.post<ApprovalBriefGenerateResponse>('/agent/approvals/brief/generate', payload)).data;

export type ApprovalBriefHealthTier = {
  tier: 'remote' | 'local' | 'rule' | string;
  provider?: string;
  model?: string;
  available?: boolean;
  reason?: string;
};
export type ApprovalBriefHealthResponse = {
  ok: boolean;
  ts?: number;
  enabled?: boolean;
  selected_tier?: string;
  order?: string[];
  tiers?: {
    remote?: ApprovalBriefHealthTier;
    local?: ApprovalBriefHealthTier;
    rule?: ApprovalBriefHealthTier;
  };
  config?: Record<string, unknown>;
  error?: string;
};
export const fetchApprovalBriefHealth = async () =>
  (await api.get<ApprovalBriefHealthResponse>('/agent/approvals/brief/health')).data;

export type ApprovalLogResponse = { ok: boolean; id?: string; saved?: number; ts?: number; error?: string };
export const logApprovalDecision = async (payload: {
  id: string;
  trace_id?: string;
  approver?: string;
  decision: 'approved' | 'reject' | 'pending';
  action?: string;
  reason?: string;
  baseline_version?: string;
  gate_results?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  doc_refs?: Record<string, unknown>[];
}) => (await api.post<ApprovalLogResponse>('/approvals/log', payload)).data;

export type AgentGovernancePolicyRow = {
  change_type: string;
  allowed_envs: string[];
  required_gates: string[];
  auto_reject_on_baseline_worse: boolean;
  approval: Record<string, string>;
  mip: boolean;
  canary_and_second_approval: Record<string, string>;
};
export type AgentGovernancePolicyResponse = { ok: boolean; env: string; policy_table: AgentGovernancePolicyRow[]; ts: number; error?: string };
export const fetchAgentGovernancePolicy = async () => (await api.get<AgentGovernancePolicyResponse>('/agent/governance/policy')).data;

export type AgentGovernanceContaminationHit = { path: string; kind: string; value?: string | null };
export type AgentGovernanceScanContaminationResponse = {
  ok: boolean;
  env: string;
  skipped: boolean;
  reason?: string;
  hits: AgentGovernanceContaminationHit[];
  count: number;
  ts: number;
  error?: string;
};
export const scanAgentGovernanceContamination = async (params?: { limit?: number }) =>
  (await api.get<AgentGovernanceScanContaminationResponse>('/agent/governance/scan_contamination', { params })).data;

export type AgentMipListItem = {
  id: string;
  ts?: number;
  type?: string;
  bucket_id?: string;
  status?: string;
  trace_id?: string;
  draft_id?: string;
  action?: string;
  reason?: string;
  approval_id?: string;
  [k: string]: unknown;
};
export type AgentMipListResponse = { ok: boolean; bucket_id: string; items: AgentMipListItem[]; count: number; ts: number; error?: string };
export const fetchAgentMipList = async (params?: { bucket_id?: string; limit?: number }) => (await api.get<AgentMipListResponse>('/agent/mip/list', { params })).data;
export const promoteAgentMip = async (payload: { bucket_id?: string; ids: string[] }) =>
  (await api.post<{ ok: boolean; bucket_id: string; promoted: { id: string; approval_id: string }[]; count: number; ts: number; error?: string }>('/agent/mip/promote', payload)).data;

export type RolloutFreezeGetResponse = { ok: boolean; freeze: boolean; ts: number; error?: string };
export type RolloutFreezeSetResponse = {
  ok: boolean;
  freeze?: boolean;
  rollback_point?: Record<string, unknown>;
  trace_id?: string;
  approval_id?: string;
  ts?: number;
  error?: string;
};
export const fetchRolloutFreeze = async () => (await api.get<RolloutFreezeGetResponse>('/rollout/freeze')).data;
export const setRolloutFreeze = async (payload: { freeze: boolean; trace_id?: string; approval_id?: string; confirm_live?: boolean }) =>
  (await api.post<RolloutFreezeSetResponse>('/rollout/freeze', payload)).data;

export type GovernanceChangesetApplyResponse = {
  ok: boolean;
  trace_id?: string;
  approval_id?: string;
  ts?: number;
  error?: string;
  [k: string]: unknown;
};
export const applyGovernanceChangeset = async (payload: {
  trace_id?: string;
  confirm_live?: boolean;
  policy_ref?: string;
  approval_id: string;
  changeset: Record<string, unknown>;
}) => (await api.post<GovernanceChangesetApplyResponse>('/governance/changeset/apply', payload)).data;

export type AgentPipelineStateResponse = { ok: boolean; trace_id?: string; pipeline_state?: Record<string, unknown>; ts?: number; error?: string };
export const fetchAgentPipelineState = async (params: { trace_id: string }) =>
  (await api.get<AgentPipelineStateResponse>('/agent/pipeline/state', { params })).data;

export type AgentPipelineArtifactsResponse = {
  ok: boolean;
  items: { offset: number; item: Record<string, unknown> }[];
  next_offset: number;
  ts: number;
  error?: string;
};
export const fetchAgentPipelineArtifacts = async (params: { trace_id: string; kind?: string; offset?: number; limit?: number }) =>
  (await api.get<AgentPipelineArtifactsResponse>('/agent/pipeline/artifacts', { params })).data;

export const resetAutomationState = async () => (await api.post<{ ok: boolean; error?: string }>('/automation/state/reset', {})).data;

export type ServingPipelineStateResponse = { ok: boolean; serving_pipeline?: Record<string, unknown> | null };
export const fetchServingPipelineState = async () => (await api.get<ServingPipelineStateResponse>('/automation/serving/pipeline/state')).data;

export type ServingPipelineConfigPayload = {
  trace_id?: string;
  approval_id?: string;
  confirm_live?: boolean;
  enabled?: boolean;
  phase?: 'shadow' | 'canary' | 'full' | string;
  canary_frac?: number;
  pairs?: string[];
  auto_guard_rollback?: boolean;
  [k: string]: unknown;
};

export const setServingPipelineConfig = async (payload: ServingPipelineConfigPayload) =>
  (await api.post<{ ok: boolean; serving_pipeline?: Record<string, unknown> | null }>('/automation/serving/pipeline/config', payload)).data;

export const advanceServingPipeline = async (payload?: { trace_id?: string; approval_id?: string; confirm_live?: boolean }) =>
  (await api.post<{ ok: boolean; error?: string; phase?: string; reason?: string; from?: string; to?: string; advanced?: boolean }>('/automation/serving/pipeline/advance', payload ?? {})).data;

export type ServingPipelineGuardEvalResponse = {
  ok: boolean;
  phase: 'shadow' | 'canary' | 'full' | string;
  checks: { n: boolean; pf: boolean; dd: boolean };
  metrics: { n: number; pf: number | null; dd: number | null };
  pass: boolean;
  ts: number;
};

export const fetchServingPipelineGuardEval = async (): Promise<ServingPipelineGuardEvalResponse> => {
  try {
    return (await api.get<ServingPipelineGuardEvalResponse>('/automation/serving/pipeline/guard/eval', { timeout: 20000 })).data;
  } catch {
    return { ok: false, phase: 'shadow', checks: { n: false, pf: false, dd: false }, metrics: { n: 0, pf: null, dd: null }, pass: false, ts: Date.now() };
  }
};

export const triggerServingPipelineGuardRollback = async (payload?: { trace_id?: string; approval_id?: string; confirm_live?: boolean; latest?: boolean }) =>
  (await api.post<{ ok: boolean; rolled_back: boolean; ts: number }>('/automation/serving/pipeline/guard/rollback', { trace_id: payload?.trace_id, approval_id: payload?.approval_id, confirm_live: payload?.confirm_live, latest: payload?.latest ?? true }, { timeout: 20000 })).data;

export type UniversePairsResponse = { ok: boolean; coins: string[]; pairs: string[] };
export const fetchUniversePairs = async (): Promise<UniversePairsResponse> => {
  return (await api.get<UniversePairsResponse>('/universe/pairs')).data;
};

export type UniverseBtcCorrResearchRow = {
  coin: string;
  pair: string;
  corr: number | null;
  beta: number | null;
  resid_vol: number | null;
  cache_hit: boolean;
  prev_blocked: boolean;
  blocked_enter: boolean;
  blocked_exit: boolean;
  blocked_state: boolean;
};

export type UniverseBtcCorrResearchResponse = {
  ok: boolean;
  ts: number;
  pool: string;
  enabled: boolean;
  enter_thr: number;
  exit_thr: number;
  hysteresis_delta: number;
  end_ts?: number;
  timeframe?: '30m' | '1h' | string;
  method?: 'pearson' | 'spearman' | string;
  lookback_hours: number;
  window_bars: number;
  bucket_ts: number;
  ttl_sec: number;
  bucket_sec: number;
  n_total: number;
  n_corr: number;
  n_blocked_enter: number;
  n_blocked_state: number;
  rows: UniverseBtcCorrResearchRow[];
};

export const fetchUniverseBtcCorrResearch = async (params?: {
  pool?: string;
  max_n?: number;
  refresh?: 0 | 1;
  end_ts?: number;
  timeframe?: '30m' | '1h';
  window_bars?: number;
  method?: 'pearson' | 'spearman';
}): Promise<UniverseBtcCorrResearchResponse> => {
  return (
    await api.get<UniverseBtcCorrResearchResponse>('/universe/btc_corr/research', {
      params: {
        pool: params?.pool ?? 'core',
        max_n: params?.max_n ?? 200,
        refresh: params?.refresh ?? 0,
        end_ts: params?.end_ts,
        timeframe: params?.timeframe,
        window_bars: params?.window_bars,
        method: params?.method,
      },
      timeout: 60000,
    })
  ).data;
};

export type BtcCorrEvalMetrics = {
  trades: number;
  wins: number;
  losses: number;
  winrate: number | null;
  profit_total_abs: number;
  profit_total_pct: number;
  max_drawdown_account: number;
  profit_factor: number | null;
  sharpe: number | null;
  sortino: number | null;
  avg_trade_duration_min: number | null;
  avg_win_loss_ratio: number | null;
};

export type UniverseBtcCorrAbEvalRow = {
  thr: number;
  n: number;
  coverage: number;
  take_rate: number;
  metrics: BtcCorrEvalMetrics;
};

export type UniverseBtcCorrAbEvalResponse = {
  ok: boolean;
  ts: number;
  zip: string;
  strategy: string | null;
  timerange: { start_ts: number | null; end_ts: number | null };
  corr: { timeframe: '30m' | '1h' | string; window_bars: number; method: 'pearson' | 'spearman' | string };
  assumptions: { fee: number; slippage: number };
  starting_balance: number;
  base: { n: number; metrics: BtcCorrEvalMetrics };
  with_corr: { n: number; metrics: BtcCorrEvalMetrics };
  ab: UniverseBtcCorrAbEvalRow[];
};

export const fetchUniverseBtcCorrAbEval = async (params?: {
  zip?: string;
  strategy?: string;
  thresholds?: string;
  start_ts?: number;
  end_ts?: number;
  timeframe?: '30m' | '1h';
  window_bars?: number;
  method?: 'pearson' | 'spearman';
  fee?: number;
  slippage?: number;
}): Promise<UniverseBtcCorrAbEvalResponse> => {
  return (
    await api.get<UniverseBtcCorrAbEvalResponse>('/universe/btc_corr/ab_eval', {
      params: {
        zip: params?.zip,
        strategy: params?.strategy,
        thresholds: params?.thresholds,
        start_ts: params?.start_ts,
        end_ts: params?.end_ts,
        timeframe: params?.timeframe,
        window_bars: params?.window_bars,
        method: params?.method,
        fee: params?.fee,
        slippage: params?.slippage,
      },
      timeout: 60000,
    })
  ).data;
};

export type UniverseBtcCorrBucketEvalBucket = {
  bucket: string;
  lo: number;
  hi: number;
  n: number;
  coverage: number;
  metrics: BtcCorrEvalMetrics;
};

export type UniverseBtcCorrBucketEvalResponse = {
  ok: boolean;
  ts: number;
  zip: string;
  strategy: string | null;
  timerange: { start_ts: number | null; end_ts: number | null };
  corr: { timeframe: '30m' | '1h' | string; window_bars: number; method: 'pearson' | 'spearman' | string };
  assumptions: { fee: number; slippage: number };
  starting_balance: number;
  with_corr: { n: number };
  buckets: UniverseBtcCorrBucketEvalBucket[];
};

export const fetchUniverseBtcCorrBucketEval = async (params?: {
  zip?: string;
  strategy?: string;
  start_ts?: number;
  end_ts?: number;
  timeframe?: '30m' | '1h';
  window_bars?: number;
  method?: 'pearson' | 'spearman';
  fee?: number;
  slippage?: number;
}): Promise<UniverseBtcCorrBucketEvalResponse> => {
  return (
    await api.get<UniverseBtcCorrBucketEvalResponse>('/universe/btc_corr/bucket_eval', {
      params: {
        zip: params?.zip,
        strategy: params?.strategy,
        start_ts: params?.start_ts,
        end_ts: params?.end_ts,
        timeframe: params?.timeframe,
        window_bars: params?.window_bars,
        method: params?.method,
        fee: params?.fee,
        slippage: params?.slippage,
      },
      timeout: 60000,
    })
  ).data;
};

export type UniverseBtcCorrExperimentGridCell = {
  corr: { timeframe: '30m' | '1h' | string; window_bars: number; method: 'pearson' | 'spearman' | string };
  assumptions: { fee: number; slippage: number };
  result: {
    base: { n: number; metrics: BtcCorrEvalMetrics };
    with_corr: { n: number; metrics: BtcCorrEvalMetrics };
    ab: UniverseBtcCorrAbEvalRow[];
  };
};

export type UniverseBtcCorrExperimentGridResponse = {
  ok: boolean;
  ts: number;
  zip: string;
  strategy: string | null;
  timerange: { start_ts: number | null; end_ts: number | null };
  thresholds: number[];
  starting_balance: number;
  cells: UniverseBtcCorrExperimentGridCell[];
};

export const fetchUniverseBtcCorrExperimentGrid = async (params?: {
  zip?: string;
  strategy?: string;
  start_ts?: number;
  end_ts?: number;
  timeframes?: string;
  methods?: string;
  window_bars_list?: string;
  window_bars?: number;
  thresholds?: string;
  thr_lo?: number;
  thr_hi?: number;
  thr_step?: number;
  fee?: number;
  slippages?: string;
  slippage?: number;
}): Promise<UniverseBtcCorrExperimentGridResponse> => {
  return (
    await api.get<UniverseBtcCorrExperimentGridResponse>('/universe/btc_corr/experiment_grid', {
      params: {
        zip: params?.zip,
        strategy: params?.strategy,
        start_ts: params?.start_ts,
        end_ts: params?.end_ts,
        timeframes: params?.timeframes,
        methods: params?.methods,
        window_bars_list: params?.window_bars_list,
        window_bars: params?.window_bars,
        thresholds: params?.thresholds,
        thr_lo: params?.thr_lo,
        thr_hi: params?.thr_hi,
        thr_step: params?.thr_step,
        fee: params?.fee,
        slippages: params?.slippages,
        slippage: params?.slippage,
      },
      timeout: 120000,
    })
  ).data;
};

export type UniverseBtcCorrWalkforwardPeriodRow = UniverseBtcCorrAbEvalRow;

export type UniverseBtcCorrWalkforwardPeriod = {
  label: string;
  start_ts: number;
  end_ts: number;
  n: number;
  with_corr_n: number;
  best_thr: number | null;
  best: UniverseBtcCorrWalkforwardPeriodRow | null;
  rows: UniverseBtcCorrWalkforwardPeriodRow[];
};

export type UniverseBtcCorrWalkforwardResponse = {
  ok: boolean;
  ts: number;
  zip: string;
  strategy: string | null;
  timerange: { start_ts: number; end_ts: number };
  corr: { timeframe: '30m' | '1h' | string; window_bars: number; method: 'pearson' | 'spearman' | string };
  assumptions: { fee: number; slippage: number };
  starting_balance: number;
  period: 'month' | 'quarter' | string;
  min_trades: number;
  take_rate_min: number;
  take_rate_max: number;
  thresholds: number[];
  summary: {
    n_periods: number;
    n_best: number;
    recommended_enter_thr_low: number | null;
    recommended_enter_thr_mid: number | null;
    recommended_enter_thr_high: number | null;
    best_thr_series: number[];
  };
  periods: UniverseBtcCorrWalkforwardPeriod[];
};

export const fetchUniverseBtcCorrWalkforward = async (params?: {
  zip?: string;
  strategy?: string;
  thresholds?: string;
  start_ts?: number;
  end_ts?: number;
  timeframe?: '30m' | '1h';
  window_bars?: number;
  method?: 'pearson' | 'spearman';
  fee?: number;
  slippage?: number;
  period?: 'month' | 'quarter';
  min_trades?: number;
  take_rate_min?: number;
  take_rate_max?: number;
}): Promise<UniverseBtcCorrWalkforwardResponse> => {
  return (
    await api.get<UniverseBtcCorrWalkforwardResponse>('/universe/btc_corr/walkforward', {
      params: {
        zip: params?.zip,
        strategy: params?.strategy,
        thresholds: params?.thresholds,
        start_ts: params?.start_ts,
        end_ts: params?.end_ts,
        timeframe: params?.timeframe,
        window_bars: params?.window_bars,
        method: params?.method,
        fee: params?.fee,
        slippage: params?.slippage,
        period: params?.period,
        min_trades: params?.min_trades,
        take_rate_min: params?.take_rate_min,
        take_rate_max: params?.take_rate_max,
      },
      timeout: 60000,
    })
  ).data;
};

export type UniverseBtcCorrThresholdReviewMonth = {
  asof_ts: number;
  bucket_ts: number;
  n_corr: number;
  cache_hits: number;
  target_allow_frac: number;
  suggest_enter_thr: number | null;
  current_enter_thr: number;
  current_exit_thr: number;
  current_allow_frac: number | null;
};

export type UniverseBtcCorrThresholdReviewResponse = {
  ok: boolean;
  ts: number;
  pool: string;
  end_ts: number;
  timeframe: '30m' | '1h' | string;
  method: 'pearson' | 'spearman' | string;
  window_bars: number;
  target_allow_frac: number;
  current_enter_thr: number;
  current_exit_thr: number;
  recommended_enter_thr_low: number | null;
  recommended_enter_thr_mid: number | null;
  recommended_enter_thr_high: number | null;
  months: UniverseBtcCorrThresholdReviewMonth[];
};

export const fetchUniverseBtcCorrThresholdReview = async (params?: {
  pool?: string;
  max_n?: number;
  months?: number;
  target_allow_frac?: number;
  refresh?: 0 | 1;
  end_ts?: number;
  timeframe?: '30m' | '1h';
  window_bars?: number;
  method?: 'pearson' | 'spearman';
}): Promise<UniverseBtcCorrThresholdReviewResponse> => {
  return (
    await api.get<UniverseBtcCorrThresholdReviewResponse>('/universe/btc_corr/threshold_review', {
      params: {
        pool: params?.pool ?? 'core',
        max_n: params?.max_n ?? 120,
        months: params?.months ?? 6,
        target_allow_frac: params?.target_allow_frac ?? 0.3,
        refresh: params?.refresh ?? 0,
        end_ts: params?.end_ts,
        timeframe: params?.timeframe,
        window_bars: params?.window_bars,
        method: params?.method,
      },
      timeout: 60000,
    })
  ).data;
};

export type GatingStateResponse = {
  ok: boolean;
  config: {
    enabled: boolean;
    alpha: number;
    beta: number;
    gamma: number;
    delta: number;
    epsilon: number;
    theta_min: number;
    theta_max: number;
    target_spm: number;
    window_sec: number;
    half_life_min: number;
  };
  elastic: {
    ts: number;
    by_group: Record<string, { theta: number; raw: number; u: number; h: number; v: number; d: number; s: number; ts: number }>;
  };
};
export const fetchGatingState = async () => (await api.get<GatingStateResponse>('/gating/state')).data;
export type HyperliquidPingResponse = {
  ok: boolean;
  error?: string;
  base_url?: string;
  btc_mid?: number | null;
  trading_enabled?: boolean;
  trading_enabled_carry?: boolean;
  has_account?: boolean;
  has_api_key?: boolean;
  account_address?: string | null;
  vault_address?: string | null;
  pk_wallet_address?: string | null;
  pk_matches_account?: boolean | null;
};

export const hyperliquidPing = async () => (await api.get<HyperliquidPingResponse>('/execution/hyperliquid/ping')).data;

export type HyperliquidMarketOpenPayload = {
  coin?: string;
  pair?: string;
  side?: 'long' | 'short';
  notional_usdc?: number;
  slippage?: number;
  px?: number | null;
  leverage?: number | null;
  is_cross?: boolean;
  execute?: boolean;
  confirm_execute?: boolean;
};

export type HyperliquidSetLeveragePayload = {
  coin?: string;
  pair?: string;
  leverage: number;
  is_cross?: boolean;
  execute?: boolean;
  confirm_execute?: boolean;
};

export type HyperliquidMarketClosePayload = {
  coin?: string;
  pair?: string;
  side?: 'long' | 'short';
  sz?: number | null;
  slippage?: number;
  px?: number | null;
  execute?: boolean;
  confirm_execute?: boolean;
};

export type HyperliquidCancelPayload = {
  coin?: string;
  pair?: string;
  oid: number;
  execute?: boolean;
  confirm_execute?: boolean;
};

export type HyperliquidCancelAllPayload = {
  coin?: string;
  pair?: string;
  execute?: boolean;
  confirm_execute?: boolean;
};

export type HyperliquidActionResponse = {
  ok: boolean;
  error?: string;
  order_id?: string;
  order?: Order;
  [key: string]: unknown;
};

export const hyperliquidMarketOpen = async (payload: HyperliquidMarketOpenPayload) => {
  const env = getUiEnv();
  const p = env === 'explore' ? { ...payload, execute: false, confirm_execute: false } : payload;
  return (await api.post<HyperliquidActionResponse>('/execution/hyperliquid/market_open', p)).data;
};

export const hyperliquidMarketClose = async (payload: HyperliquidMarketClosePayload) => {
  const env = getUiEnv();
  const p = env === 'explore' ? { ...payload, execute: false, confirm_execute: false } : payload;
  return (await api.post<HyperliquidActionResponse>('/execution/hyperliquid/market_close', p)).data;
};

export const hyperliquidCancel = async (payload: HyperliquidCancelPayload) =>
  (await api.post<HyperliquidActionResponse>('/execution/hyperliquid/cancel', payload)).data;

export const hyperliquidCancelAll = async (payload: HyperliquidCancelAllPayload) =>
  (await api.post<HyperliquidActionResponse>('/execution/hyperliquid/cancel_all', payload)).data;

export const hyperliquidSetLeverage = async (payload: HyperliquidSetLeveragePayload) =>
  (await api.post<HyperliquidActionResponse>('/execution/hyperliquid/set_leverage', payload)).data;

export type AsterPingResponse = {
  ok: boolean;
  error?: string;
  auth_mode?: string;
  has_api_key?: boolean;
  has_secret?: boolean;
  has_user?: boolean;
  has_signer?: boolean;
  has_signer_private_key?: boolean;
  trading_enabled?: boolean;
  [key: string]: unknown;
};

export const asterPing = async () => (await api.get<AsterPingResponse>('/execution/aster/ping')).data;

export type AsterAccountAssetSummary = {
  asset: string;
  walletBalance?: number;
  availableBalance?: number;
  marginBalance?: number;
  unrealizedProfit?: number;
  initialMargin?: number;
  maintMargin?: number;
  positionInitialMargin?: number;
  openOrderInitialMargin?: number;
  crossWalletBalance?: number;
  crossUnPnl?: number;
  maxWithdrawAmount?: number;
  [key: string]: unknown;
};

export type AsterAccountSummaryResponse = {
  ok: boolean;
  error?: string;
  ts?: number;
  owner?: string | null;
  summary?: Record<string, number>;
  assets?: {
    USDT?: AsterAccountAssetSummary | null;
    USDC?: AsterAccountAssetSummary | null;
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

export const asterAccountSummary = async () => (await api.get<AsterAccountSummaryResponse>('/execution/aster/account_summary')).data;

export type AsterPreflightPayload = {
  coin?: string;
  pair?: string;
  notional_usdt?: number;
  notional_usdc?: number;
  notional_usd?: number;
};

export type AsterPreflightResponse = {
  ok: boolean;
  error?: string;
  symbol?: string;
  mid?: number;
  min_qty?: number;
  min_notional?: number;
  step_size?: number;
  raw_qty?: number;
  required_qty?: number;
  required_notional_usdc?: number;
  required_notional_usdt?: number;
  selected_qty?: number;
  selected_notional_usdc?: number;
  selected_notional_usdt?: number;
  floor_qty?: number;
  floor_notional_usdc?: number;
  floor_notional_usdt?: number;
  effective_notional_usdc?: number;
  effective_notional_usdt?: number;
  will_bump?: boolean;
  bump_ratio?: number;
  [key: string]: unknown;
};

export const asterPreflight = async (payload: AsterPreflightPayload) =>
  (await api.post<AsterPreflightResponse>('/execution/aster/preflight', payload)).data;

export type AsterMarketOpenPayload = {
  coin?: string;
  pair?: string;
  side?: 'long' | 'short';
  notional_usdt?: number;
  notional_usdc?: number;
  leverage?: number;
  execute?: boolean;
  confirm_execute?: boolean;
  auto_bump_to_min?: boolean;
  confirm_bump?: boolean;
  max_bump_ratio?: number;
  max_effective_notional_usdc?: number;
  ignore_cooldown?: boolean;
};

export type AsterMarketClosePayload = {
  coin?: string;
  pair?: string;
  sz?: number | null;
  tag?: string;
  exit_owner?: string;
  force?: boolean;
  execute?: boolean;
  confirm_execute?: boolean;
};

export type AsterActionResponse = {
  ok: boolean;
  error?: string;
  order_id?: string;
  order?: Order;
  [key: string]: unknown;
};

export const asterMarketOpen = async (payload: AsterMarketOpenPayload) => {
  const env = getUiEnv();
  const p = env === 'explore' ? { ...payload, execute: false, confirm_execute: false } : payload;
  return (await api.post<AsterActionResponse>('/execution/aster/market_open', p)).data;
};

export const asterMarketClose = async (payload: AsterMarketClosePayload) => {
  const env = getUiEnv();
  const p = env === 'explore' ? { ...payload, execute: false, confirm_execute: false } : payload;
  return (await api.post<AsterActionResponse>('/execution/aster/market_close', p)).data;
};

export type LivePreflightResponse = {
  ok: boolean;
  ts: number;
  ready: boolean;
  blockers: string[];
  warnings: string[];
  execute_guard?: {
    enabled: boolean;
    token_required: boolean;
    allow_remote: boolean;
  };
  config: {
    execution_venue: string;
    dry_run: boolean;
    live_trading_enabled: boolean;
    hl_trading_enabled: boolean;
    aster_trading_enabled: boolean;
    tracker_autosync_hl_enabled: boolean;
    tracker_autosync_aster_enabled: boolean;
  };
  hyperliquid?: Record<string, unknown>;
  aster?: Record<string, unknown>;
  positions?: Record<string, unknown>;
};

export const livePreflight = async () => (await api.get<LivePreflightResponse>('/live/preflight')).data;

export type LiveRiskCheckRequest = {
  strategy_id: string;
};

export type LiveRiskOpenPositions = {
  n: number;
  notional_usdc: number;
};

export type LiveRiskCheckResponse = {
  ok: boolean;
  ts: number;
  strategy_id: string;
  subportfolio: Record<string, unknown>;
  open_positions: LiveRiskOpenPositions;
};

export type LivePlanLeg = {
  symbol: string;
  side: string;
  notional_usdc: number;
};

export type LivePlanRequest = {
  strategy_id: string;
  direction?: string;
  notional_usdc?: number;
  timeframe?: string;
};

export type LivePlanResponse = {
  ok: boolean;
  ts: number;
  strategy_id: string;
  timeframe: string;
  direction: string;
  notional_usdc: number;
  legs: LivePlanLeg[];
  risk?: {
    subportfolio: LiveRiskCheckResponse['subportfolio'];
    open_positions: LiveRiskCheckResponse['open_positions'];
  };
};

export const liveRiskCheck = async (payload: LiveRiskCheckRequest) =>
  (await api.post<LiveRiskCheckResponse>('/live/risk/check', payload)).data;

export const livePlan = async (payload: LivePlanRequest) => (await api.post<LivePlanResponse>('/live/plan', payload)).data;

export interface TrackerStats {
  ok?: boolean;
  ts?: number;
  daily_pnl: Record<string, number>;
  weekly_pnl: Record<string, number>;
  open_positions: Record<string, Record<string, unknown>>;
  carry_open_positions?: Record<string, Record<string, unknown>>;
  quant_open_positions?: Record<string, Record<string, unknown>>;
  order_ts: number[];
  cooldowns?: Record<string, number>;

  hl?: {
    ts?: number;
    account_value?: number;
    unrealized_pnl?: number;
    sync_ok?: boolean;
    last_sync_ts?: number;
    last_sync_error?: string | null;
    [key: string]: unknown;
  };

  aster?: {
    ts?: number;
    account_value?: number;
    unrealized_pnl?: number;
    sync_ok?: boolean;
    last_sync_ts?: number;
    last_sync_error?: string | null;
    [key: string]: unknown;
  };

  gate_history?: Record<string, unknown>[];
  strategy_weights?: Record<string, number>;
  strategy_perf?: Record<string, { rets?: number[]; n?: number; pf?: number; maxdd?: number }>;
  strategy_subportfolios?: Record<string, Record<string, unknown>>;
  post_close_cooldowns?: Record<string, number>;

  macro_btceth_hard_gate_auto?: Record<string, unknown>;

  scheduler?: {
    ts?: number;
    tick?: number;
    [key: string]: unknown;
  };
  feeders?: {
    ts?: number;
    period_seconds?: number;
    n_strategies?: number;
    n_core?: number;
    calls?: number;
    emits?: number;
    ingested?: number;
    null_signals?: number;
    errors?: number;
    per_strategy?: Record<string, { calls?: number; emits?: number; ingested?: number; null_signals?: number; errors?: number }>;
    [key: string]: unknown;
  };

  exit_inflight?: Record<string, number>;
  exit_owner_state?: {
    weights?: Record<string, number>;
    last_reweight_idx?: number;
    history?: {
      ts: number;
      pair?: string;
      owner?: string;
      action?: string;
      reason?: string;
      pnl_u?: number;
      pnl_pct?: number;
      [key: string]: unknown;
    }[];
  };

  ab_alloc_state?: Record<string, unknown>;
  ab_settlements?: Record<string, unknown>[];
  ab_intent_rejects?: Record<string, unknown>[];
  ab_merge_events?: Record<string, unknown>[];
}

export const fetchTrackerStats = async (opts?: { sync?: boolean; force?: boolean; view?: string }) => {
  const sync = opts?.sync === true;
  const force = opts?.force === true;
  const view = typeof opts?.view === 'string' ? opts?.view : undefined;
  return (await api.get<TrackerStats>('/tracker/stats', { params: { sync: sync ? 1 : 0, force: force ? 1 : 0, view } })).data;
};

export const fetchDiagnosticsGateState = async () => (await api.get<DiagnosticsGateStateResponse>('/diagnostics/gate_state')).data;

export type DiagnosticsIsolationScanFinding = {
  ts: number;
  layer: 'L1' | 'L2' | 'L3' | string;
  severity: 'high' | 'medium' | 'low' | string;
  kind: string;
  ref: Record<string, unknown>;
  details: Record<string, unknown>;
};

export type DiagnosticsIsolationScanResponse = {
  ok: boolean;
  ts: number;
  config?: {
    book_isolation_enabled?: boolean;
    book_isolation_default_book_id?: string | null;
    book_run_id?: string;
  };
  limits?: {
    events?: number;
    orders?: number;
    max_findings?: number;
  };
  layers?: {
    L1?: Record<string, unknown>;
    L2?: Record<string, unknown>;
    L3?: Record<string, unknown>;
  };
  counts?: Record<string, number>;
  findings?: DiagnosticsIsolationScanFinding[];
  error?: string;
  [key: string]: unknown;
};

export const fetchDiagnosticsIsolationScan = async (params?: {
  limit_events?: number;
  limit_orders?: number;
  max_findings?: number;
  include_shadow?: boolean | number;
  include_positions?: boolean | number;
}) => (await api.get<DiagnosticsIsolationScanResponse>('/diagnostics/isolation/scan', { params })).data;

export type TrackerClearOpenPositionsPayload = {
  all?: boolean;
  pairs?: string[];
};

export type TrackerClearOpenPositionsResponse = {
  ok: boolean;
  ts?: number;
  removed?: string[];
  n_removed?: number;
  remaining?: number;
  [key: string]: unknown;
};

export const clearTrackerOpenPositions = async (payload: TrackerClearOpenPositionsPayload) =>
  (await api.post<TrackerClearOpenPositionsResponse>('/tracker/open_positions/clear', payload)).data;

export type MacroTrendRow = {
  ts: number;
  close: number | null;
  ema_fast_w: number | null;
  ema_slow_w: number | null;
  ma_fast_d: number | null;
  ma_slow_d: number | null;
  adx_w: number | null;
  time_regime: string;
  trend_w_dir?: number | null;
  trend_d_dir?: number | null;
  trend_shape_5?: string;
  trend_w_slope?: number | null;
  trend_d_slope?: number | null;
  trend_rate_change_dw?: number | null;
};

export type MacroEnergyRow = {
  ts: number;
  close: number | null;
  ret_1d: number | null;
  ret_3d: number | null;
  rsi_14: number | null;
  macd_hist: number | null;
  volume_ratio: number | null;
  volume_z: number | null;
  adx_14: number | null;
  atr_pct: number | null;
  dist_to_ema50: number | null;
  kin_ma: number | null;
  vol_ma: number | null;
  pot_ma: number | null;
  risk_baseline: number | null;
  vol_dir?: number | null;
  vol_chg_dir?: number | null;
  vol_chg_speed?: number | null;
  mom_dir?: number | null;
  mom_chg_dir?: number | null;
  mom_chg_speed?: number | null;
  pot_dir?: number | null;
  pot_chg_dir?: number | null;
  pot_chg_speed?: number | null;
};

export type MacroFlowRow = {
  ts: number;
  rs_btc_vs_mkt: number | null;
  rs_eth_vs_mkt: number | null;
  rs_btc_vs_eth: number | null;
  macro_flow?: number | null;
  macro_flow_dir?: number | null;
  macro_flow_chg_dir?: number | null;
  macro_flow_chg_speed?: number | null;
};

export type MacroSeries<T> = {
  coin?: string;
  coins?: string[];
  rows: T[];
};

export type MacroBtcEthOverviewResponse = {
  ok: boolean;
  ts: number;
  lookback_days: number;
  flow_lookback_days: number;
  std_1h?: {
    ok: boolean;
    valid: boolean;
    ts: number;
    timeframe: string;
    window_hours: number;
    btc: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
    eth: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
  };
  std_12h?: {
    ok: boolean;
    valid: boolean;
    ts: number;
    timeframe: string;
    window_hours: number;
    btc: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
    eth: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
  };
  std_1d?: {
    ok: boolean;
    valid: boolean;
    ts: number;
    timeframe: string;
    window_hours: number;
    btc: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
    eth: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
  };
  std_shape?: {
    ok: boolean;
    valid: boolean;
    ts: number;
    timeframe: string;
    window_hours: number;
    btc: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
    eth: {
      coin?: string;
      risk_pct?: number | null;
      value_pct?: number | null;
      dir?: number | null;
    };
  };
  std_shape_update_hours?: number;
  macro_btceth_shape?: {
    ok: boolean;
    enabled?: boolean;
    valid?: boolean;
    ts?: number;
    w_btc?: number | null;
    w_eth?: number | null;
    risk_sys?: number | null;
    risk_stress?: number | null;
    risk_w?: number | null;
    value_mean?: number | null;
    value_w?: number | null;
    risk_eff?: number | null;
    value_eff?: number | null;
    risk_used?: number | null;
    value_used?: number | null;
    dir_score?: number | null;
    dir_12h?: number | null;
    score_min?: number | null;
    risk_bucket_next?: string | null;
    value_bucket_next?: string | null;
    risk_bucket?: string | null;
    value_bucket?: string | null;
    shape_next?: string | null;
    shape_prev?: string | null;
    shape_candidate?: string | null;
    shape_candidate_n?: number | null;
    shape?: string | null;
    shape_tier?: number | null;
    dir_long_any?: boolean;
    dir_short_any?: boolean;
    shape_persist_bars?: number;
    shape_ema_halflife_hours?: number;
    shape_risk_use_stress?: boolean;
    controls?: {
      size_mult_long?: number | null;
      size_mult_short?: number | null;
      cooldown_mult_long?: number | null;
      cooldown_mult_short?: number | null;
      coin_cooldown_mult_long?: number | null;
      coin_cooldown_mult_short?: number | null;
    } | null;
    policy?: {
      dir0_block_nonhedge?: boolean;
      counter_require_hedge?: boolean;
      block_counter_when_high_risk?: boolean;
      counter_max_signals_frac?: number | null;
    } | null;
    params?: {
      risk_low?: number;
      risk_high?: number;
      value_bear?: number;
      value_bull?: number;
      hysteresis?: number;
    };
    error?: string;
    fail_open?: boolean;
  } | null;
  macro_tri_layer?: {
    ok?: boolean;
    ts?: number;
    timeframe?: string;
    dir_h?: number | null;
    dir_w?: number | null;
    dir_d?: number | null;
    short_n?: number;
    dir_short?: number | null;
    chg_dir_w?: number | null;
    chg_dir_d?: number | null;
    chg_speed_w?: number | null;
    chg_speed_d?: number | null;
    chg_strength?: number | null;
    risk_1h?: number | null;
    risk_d?: number | null;
    risk_budget_tier?: string | null;
    crash_switch?: boolean;
    target_net_bias?: number | null;
    max_net_exposure?: number | null;
    allow_open?: boolean;
    allow_addon?: boolean;
    macro_std?: {
      std_12h?: Record<string, unknown> | null;
      std_1d?: Record<string, unknown> | null;
      std_1h_seq?: {
        dirs?: number[];
        value_pct?: Array<number | null>;
        risk_pct?: Array<number | null>;
      } | null;
    } | null;
  } | null;
  gate_std1h?:
    | {
        ts: number;
        risk_thr: number;
        only_with_alignment: boolean;
        block_counter_when_high_risk?: boolean;
        min_risk?: number | null;
        long_ok: boolean;
        short_ok: boolean;
        long_min_risk?: number | null;
        short_min_risk?: number | null;
        recommend: string;
        data_valid?: boolean;
        effective_enabled?: boolean;
        effective_long_ok?: boolean;
        effective_short_ok?: boolean;
        effective_recommend?: string;
        long?: { blocked?: boolean; reason?: string; reason_code?: string; aligned?: boolean };
        short?: { blocked?: boolean; reason?: string; reason_code?: string; aligned?: boolean };
      }
    | null;
  gate_config?: {
    enabled: boolean;
    fail_open: boolean;
    apply_to_addon: boolean;
    only_with_alignment: boolean;
    risk_thr: number;
  } | null;
  btc: {
    trend: MacroSeries<MacroTrendRow>;
    energy: MacroSeries<MacroEnergyRow>;
  };
  eth: {
    trend: MacroSeries<MacroTrendRow>;
    energy: MacroSeries<MacroEnergyRow>;
  };
  flow: MacroSeries<MacroFlowRow>;
};

export const fetchMacroBtcEthOverview = async (params?: { lookback_days?: number; flow_lookback_days?: number }) =>
  (await api.get<MacroBtcEthOverviewResponse>('/macro/btceth/overview', { params, timeout: 60000 })).data;

export type MacroVizShapeHistoryRow = {
  ts: number;
  risk_sys?: number | null;
  risk_stress?: number | null;
  risk_w?: number | null;
  value_mean?: number | null;
  value_w?: number | null;
  dir_score?: number | null;
  dir_12h?: number | null;
  score_min?: number | null;
  risk_used?: number | null;
  value_used?: number | null;
  risk_bucket?: string | null;
  value_bucket?: string | null;
  shape?: string | null;
  shape_tier?: number | null;
};

export type MacroVizSignalTagRow = {
  tag: string;
  signals_count: number;
  accepted_count: number;
  suppressed_count: number;
  quota_total?: number | null;
  quota_used?: number | null;
  quota_remaining?: number | null;
};

export type MacroVizTopItem = {
  key: string;
  count: number;
};

export type MacroVizResponse = {
  ok: boolean;
  ts: number;
  shape12h?: {
    update_hours?: number;
    persist_bars?: number;
    snapshot?: Record<string, unknown> | null;
    history?: MacroVizShapeHistoryRow[];
  };
  position_budget?: {
    target?: {
      target_source?: string | null;
      target_gross_budget?: number | null;
      target_net_bias?: number | null;
      target_long_share?: number | null;
      target_short_share?: number | null;
    };
    shape12h_baseline?: {
      target_gross_budget?: number | null;
      target_net_bias?: number | null;
      target_long_share?: number | null;
      target_short_share?: number | null;
    };
    tri_layer_target?: {
      target_gross_budget?: number | null;
      target_net_bias?: number | null;
      target_long_share?: number | null;
      target_short_share?: number | null;
      allow_open?: boolean;
      allow_addon?: boolean;
      risk_budget_tier?: string | null;
      crash_switch?: boolean;
      dir_w?: number | null;
      dir_d?: number | null;
    };
    current?: {
      gross_usdc?: number | null;
      long_usdc?: number | null;
      short_usdc?: number | null;
      net_usdc?: number | null;
      long_share?: number | null;
      short_share?: number | null;
      net_bias?: number | null;
    };
  };
  signals?: {
    window_sec: number;
    by_tag: MacroVizSignalTagRow[];
    top_suppressed_reasons: MacroVizTopItem[];
    top_suppressed_groups: MacroVizTopItem[];
    top_suppressed_strategies: MacroVizTopItem[];
    top_macro_related_reasons?: MacroVizTopItem[];
  };
  tri_layer?: {
    snapshot?: Record<string, unknown> | null;
    trace?: {
      allow_open?: boolean;
      allow_addon?: boolean;
      risk_budget_tier?: string | null;
      crash_switch?: boolean;
      expected_tokens?: string[];
      reason_match?: boolean;
      warning?: string | null;
    } | null;
  };
};

export const fetchMacroViz = async (params?: { shape_n?: number; signal_window_h?: number }) =>
  (await api.get<MacroVizResponse>('/macro/viz', { params, timeout: 60000 })).data;

export type MacroBtcRegimeBacktestRow = {
  ts: number;
  close?: number | null;
  risk_baseline?: number | null;
  atr_pct?: number | null;
  trend_w_dir?: number | null;
  trend_d_dir?: number | null;
  trend_rate_change_dw?: number | null;
  trend_shape_5?: string | null;
  rs_btc_vs_mkt?: number | null;
  macro_flow_dir?: number | null;
  macro_flow_chg_dir?: number | null;
  macro_flow_chg_speed?: number | null;
  regime?: string;
  fwd_ret_1d?: number | null;
  regime_info?: Record<string, unknown>;
};

export type MacroBtcRegimeBacktestResponse = {
  ok: boolean;
  ts: number;
  lookback_days: number;
  flow_lookback_days: number;
  params: {
    r_mid_q: number;
    r_high_q: number;
    atr_p80_q: number;
    atr_p95_q: number;
    dom_q: number;
  };
  thresholds: {
    r_mid: number;
    r_high: number;
    atr_p80: number;
    atr_p95: number;
    r5_dom: number;
  };
  quantiles: {
    risk_baseline: { n: number; min: number | null; max: number | null; mean: number | null; p10: number | null; p50: number | null; p90: number | null };
    atr_pct: { n: number; min: number | null; max: number | null; mean: number | null; p10: number | null; p50: number | null; p90: number | null };
    abs_rs_btc_vs_mkt: { n: number; min: number | null; max: number | null; mean: number | null; p10: number | null; p50: number | null; p90: number | null };
  };
  counts: Record<string, number>;
  per_regime: Record<string, { n: number; min: number | null; max: number | null; mean: number | null; p10: number | null; p50: number | null; p90: number | null; win_rate: number | null }>;
  rows: MacroBtcRegimeBacktestRow[];
};

export const fetchMacroBtcRegimeBacktest = async (params?: { lookback_days?: number; flow_lookback_days?: number; r_mid_q?: number; r_high_q?: number; atr_p80_q?: number; atr_p95_q?: number; dom_q?: number }) =>
  (await api.get<MacroBtcRegimeBacktestResponse>('/macro/btc/regime/backtest', { params, timeout: 60000 })).data;

export type ExitLatestFeaturesItem = {
  pair: string;
  side?: string;
  exit_owner?: string | null;
  ts: number;
  event_id: string | null;
  hold_risk: number | null;
  hold_value: number | null;
  l1_decision: Record<string, unknown> | null;
  features: Record<string, unknown>;
};

export type ExitLatestFeaturesResponse = {
  ok: boolean;
  ts: number;
  items: ExitLatestFeaturesItem[];
  macro_flow?: {
    rs_btc_vs_mkt: number;
    rs_eth_vs_mkt: number;
    rs_btc_vs_eth: number;
    macro_flow_dir?: number;
    macro_flow_chg_dir?: number;
    macro_flow_chg_speed?: number;
  };
  macro_btc_trend?: Record<string, unknown> | null;
  macro_eth_trend?: Record<string, unknown> | null;
  macro_btc_energy?: Record<string, unknown> | null;
  macro_eth_energy?: Record<string, unknown> | null;
};

export const fetchExitLatestFeatures = async (params?: { pairs?: string; include_macro?: boolean }) =>
  (await api.get<ExitLatestFeaturesResponse>('/exit/features/latest', { params })).data;

export type ExitEquityPoint = {
  ts: number;
  ret: number;
  cum: number;
};

export type ExitMetricsResponse = {
  ok: boolean;
  schema_version?: number;
  ts?: number;
  equity?: ExitEquityPoint[];
  total?: number;
  maxdd?: number;
  calmar?: number | null;
  sortino?: number | null;
  trades?: number;
  wins?: number;
  losses?: number;
  winrate?: number | null;
  fees_u?: number;
  funding_u?: number;
  [key: string]: unknown;
};

export const fetchExitMetrics = async (params?: { limit?: number }) =>
  (await api.get<ExitMetricsResponse>('/exit/metrics', { params })).data;
export type GateHistoryItem = {
  ts: number;
  pair?: string;
  side?: string;
  reason?: string;
  ok?: boolean;
  system_id?: string;
  [key: string]: unknown;
};
export type TrackerGateHistoryResponse = {
  ok: boolean;
  ts: number;
  filters: Record<string, unknown>;
  history: GateHistoryItem[];
};
export const fetchTrackerGateHistory = async (params?: { limit?: number; pair?: string; side?: string; reason?: string; system_id?: string; ok?: string | number; since_ts?: number; until_ts?: number }) =>
  (await api.get<TrackerGateHistoryResponse>('/tracker/gate_history', { params })).data;

export type ArenaModelState = {
  id?: string;
  name: string;
  capital_u: number;
  weight: number;
  takes: number;
  skips: number;
  wins: number;
  losses: number;
  settled: number;
  revives: number;
  last_settle_ms: number;
  max_dd?: number;
  win_rate?: number;
  avg_logloss?: number;
  turnover?: number;
  equity?: { ts: number; equity_u: number }[] | null;
};

export type ArenaStateResponse = {
  ok: boolean;
  enabled: boolean;
  ts?: number;
  pool_u?: number;
  models?: ArenaModelState[];
};

export type ArenaMode = 'entry' | 'exit';

export type ArenaHistoryItem = {
  id: string;
  ts: number;
  evt_ts: number;
  pair: string;
  side: string;
  tag?: unknown;
  ret: number;
  risk_unit: number;
  risk_usdc?: number;
  notional_usdc?: number;
  pnl_gross_u?: number;
  pnl_net_u?: number;
  fees_u?: number;
  funding_u?: number;
  winner_id?: string | null;
  winner?: string | null;
  chosen_id?: string | null;
  chosen?: string | null;
  explore?: boolean;
  edges?: Record<string, number>;
  logloss?: Record<string, number>;
  pool_u?: number;
};

export type ArenaHistoryResponse = {
  ok: boolean;
  enabled: boolean;
  ts?: number;
  history: ArenaHistoryItem[];
};

export const fetchArenaState = async (mode: ArenaMode = 'entry'): Promise<ArenaStateResponse> => {
  try {
    return (await api.get<ArenaStateResponse>('/arena/state', { params: { mode } })).data;
  } catch {
    return { ok: false, enabled: false, ts: Date.now(), pool_u: 0, models: [] };
  }
};

export const fetchArenaHistory = async (limit: number = 50, mode: ArenaMode = 'entry'): Promise<ArenaHistoryResponse> => {
  try {
    return (await api.get<ArenaHistoryResponse>('/arena/history', { params: { limit, mode } })).data;
  } catch {
    return { ok: false, enabled: false, ts: Date.now(), history: [] };
  }
};

export type ArenaAttribBucketStats = {
  n: number;
  pnl_sum_u: number;
  pnl_mean_u: number;
  pnl_std_u: number;
  pnl_min_u: number;
  pnl_max_u: number;
  pnl_p10_u: number;
  pnl_p25_u: number;
  pnl_p50_u: number;
  pnl_p75_u: number;
  pnl_p90_u: number;
  win_n: number;
  win_rate: number;
  profit_factor: number | null;
  profit_factor_inf: boolean;
  ret_mean: number;
  max_drawdown_u: number;
  max_drawdown_ratio: number;
  avg_hold_ms: number;
};

export type ArenaAttribStatsResponse = {
  ok: boolean;
  enabled: boolean;
  ts?: number;
  n?: number;
  bucket_by?: string;
  filters?: {
    pair?: string | null;
    regime?: string | null;
    strategy_id?: string | null;
    tag?: string | null;
    since_ts?: number;
    until_ts?: number;
    only_disagree?: boolean;
  };
  buckets?: Record<string, ArenaAttribBucketStats>;
};

export type ArenaAttribStatsParams = {
  bucket_by?: 'strategy_id' | 'tag' | 'regime' | 'pair' | 'group_id' | 'feature_set_id';
  pair?: string;
  regime?: string;
  strategy_id?: string;
  tag?: string;
  since_ts?: number;
  until_ts?: number;
  only_disagree?: boolean;
};

export const fetchArenaAttribStats = async (params: ArenaAttribStatsParams): Promise<ArenaAttribStatsResponse> => {
  try {
    return (await api.get<ArenaAttribStatsResponse>('/arena/attrib_stats', { params })).data;
  } catch {
    return { ok: false, enabled: false, ts: Date.now(), n: 0, buckets: {} };
  }
};

export interface ArenaLayer2Status {
  ok: boolean;
  enabled: boolean;
  ts: number;
  layer2_enabled: boolean;
  state: {
    last_train_ms: number;
    attrib_count: number;
    updated: Record<string, {
      oos_mse_base: number;
      oos_mse: number;
      improve: number;
      oos_used: number;
    }>;
  };
  model_calib: Record<string, {
    method: string;
    ts: number;
    metrics: {
      oos_mse_base: number;
      oos_mse: number;
      improve: number;
      n_fit: number;
      oos_rolls: number;
      oos_used: number;
      n_oos: number;
      oos_windows: {
        roll: number;
        n_train: number;
        n_oos: number;
        oos_start_ts: number;
        oos_end_ts: number;
        oos_mse_base: number;
        oos_mse: number;
        improve: number;
      }[];
    };
  }>;
}

export const fetchArenaLayer2Status = async (mode: ArenaMode = 'entry'): Promise<ArenaLayer2Status> => {
  try {
    return (await api.get<ArenaLayer2Status>('/arena/layer2/status', { params: { mode } })).data;
  } catch {
    return {
      ok: false,
      enabled: false,
      ts: Date.now(),
      layer2_enabled: false,
      state: { last_train_ms: 0, attrib_count: 0, updated: {} },
      model_calib: {},
    };
  }
};

export const runArenaLayer2Train = async (force: boolean = false, mode: ArenaMode = 'entry') => {
  try {
    return (await api.post<{ ok: boolean; trained: boolean; updated?: Record<string, unknown> }>('/arena/layer2/run', { force }, { params: { mode } }))
      .data;
  } catch {
    return { ok: false, trained: false };
  }
};

export type ExitMlMonitorCharts = {
  roc_curve_png_base64?: string;
  pr_curve_png_base64?: string;
  calibration_curve_png_base64?: string;
  roc_points?: { fpr: number; tpr: number }[];
  pr_points?: { recall: number; precision: number }[];
  calibration_points?: { prob: number; actual: number; n?: number }[];
};

export type ExitMlMonitorModel = {
  ts?: number;
  task?: string;
  family?: string;
  filename?: string | null;
  saved?: boolean | null;
  loaded?: boolean;
  file_exists?: boolean;
  error?: string | null;
  data?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  built?: Record<string, unknown>;
  keys?: string[];
  walkforward?: Record<string, unknown> | null;
  charts?: ExitMlMonitorCharts;
  meta?: Record<string, unknown> | null;
};

export type ExitMlMonitorResponse = {
  ok: boolean;
  ts: number;
  state_ts?: number;
  models: Record<string, ExitMlMonitorModel>;
};

export type ExitMlTrainRequest = {
  task: 'tail' | 'move' | 'gate' | 'feedback';
  family?: string;
  pair?: string | null;
  start_ms?: number | null;
  end_ms?: number | null;
  limit?: number;
  interval?: string;
  horizon?: number;
  dd_k?: number;
  params?: Record<string, unknown> | null;
  save?: boolean;
  output_charts?: boolean;
};

export type ExitMlTrainResponse = {
  ok: boolean;
  ts: number;
  task?: string;
  family?: string;
  error?: string;
  filename?: string | null;
  saved?: boolean;
  built?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  keys?: string[];
  charts?: ExitMlMonitorCharts;
};

export const fetchExitMlMonitor = async (opts?: { include_charts?: boolean; auto_eval?: boolean; limit?: number }): Promise<ExitMlMonitorResponse> => {
  const include_charts = opts?.include_charts ?? false;
  const auto_eval = opts?.auto_eval ?? false;
  const limit = opts?.limit;
  try {
    return (
      await api.get<ExitMlMonitorResponse>('/exit/ml/monitor', {
        timeout: 60000,
        params: {
          include_charts: include_charts ? 1 : 0,
          auto_eval: auto_eval ? 1 : 0,
          ...(limit != null ? { limit } : {}),
        },
      })
    ).data;
  } catch {
    return { ok: false, ts: Date.now(), models: {} };
  }
};

export const runExitMlTrain = async (req: ExitMlTrainRequest): Promise<ExitMlTrainResponse> => {
  try {
    return (await api.post<ExitMlTrainResponse>('/exit/ml/train', req)).data;
  } catch (e) {
    return { ok: false, ts: Date.now(), error: e instanceof Error ? e.message : String(e) };
  }
};

export const resetArena = async (mode: ArenaMode = 'entry') =>
  (await api.post<{ ok: boolean; enabled?: boolean; ts?: number; error?: string }>('/arena/reset', {}, { params: { mode } })).data;

export interface UniverseState {
  last_update: number;
  core: string[];
  shadow: string[];
  watchlist: string[];
  metadata: {
    stage_a_issues?: Record<string, string[]>;
    ranking_score?: string;
    dedup_threshold?: number;
    churn_protection?: string;
    scoring_weights?: Record<string, number>;
    market_snapshot?: UniverseMarketSnapshot;
    clustering_hyperparams?: UniverseClusteringHyperparams;
    monitoring_hints?: UniverseMonitoringHints;
    trade_whitelist_auto?: UniverseTradeWhitelistAuto;
    top_scores?: {
      coin: string;
      score: number;
      turnover: number;
      atr_pct: number;
      btc_corr: number;
      vol_ratio: number;
      feedback?: number;
    }[];

    candidates?: UniverseCandidate[];
    clusters?: Record<string, UniverseCluster>;
    cluster_consistency?: UniverseClusterConsistency;
    pools?: UniversePools;
    selection_hints?: UniverseSelectionHints;
  };
}

export type UniverseMarketSnapshot = {
  run_ms: number;
  venue?: string;
  symbols_total?: number | null;
  mids_total?: number | null;
  stage_a_candidates?: number | null;
  scored_candidates?: number | null;
  core_size?: number | null;
  shadow_size?: number | null;
  watchlist_size?: number | null;
  [key: string]: unknown;
};

export type UniverseClusteringHyperparams = {
  method?: string;
  timeframe?: string;
  window_bars?: number;
  k_search?: {
    k_min?: number;
    k_max?: number;
    k_selected?: number;
    metric?: string;
    score?: number;
    [key: string]: unknown;
  };
  cluster_count?: number;
  cluster_count_prev?: number;
  cluster_count_change_rate?: number;
  [key: string]: unknown;
};

export type UniverseMonitoringHints = {
  alerts?: { level: 'info' | 'warn' | 'crit'; key: string; message: string; ts: number; context?: Record<string, unknown> }[];
  diagnostics?: Record<string, unknown>;
  [key: string]: unknown;
};

export type UniverseTradeWhitelistAuto = {
  enabled?: boolean;
  source?: string;
  require_alpha_pass?: boolean;
  max?: number;
  coins?: string[];
  whitelist?: string[];
  run_ms?: number;
  [key: string]: unknown;
};

export type UniverseCandidateAlpha = {
  enabled?: boolean;
  enforcement?: string;
  source?: string | null;
  pass?: boolean;
  count?: number;
  win_rate?: number;
  pnl?: number;
  avg_ret?: number;
  profit_factor?: number | null;
  [key: string]: unknown;
};

export type UniverseCandidate = {
  coin: string;
  rank?: number;
  score?: number;
  source?: string;
  issues?: string[];
  liq?: {
    turnover_7d_median?: number;
    age_days?: number;
    gap_rate_7d?: number;
    jump_rate_7d?: number;
  };
  market?: {
    atr_pct_1h?: number;
    vol_ratio_24h_over_7d?: number;
  };
  alpha?: UniverseCandidateAlpha | null;
  btc_exposure?: {
    beta?: number | null;
    beta_std?: number | null;
    corr?: number | null;
    resid_vol?: number | null;
  };
  cluster?: {
    cluster_id?: string | null;
    cluster_rank?: number | null;
  };
  pools?: {
    liq_bucket?: string | null;
    beta_bucket?: string | null;
    quality_bucket?: string | null;
  };
};

export type UniverseCluster = {
  cluster_id: string;
  members: string[];
  centroid?: {
    avg_beta?: number | null;
    avg_corr_to_btc?: number | null;
    avg_resid_vol?: number | null;
    avg_turnover_7d_median?: number | null;
  };
  quality?: {
    intra_corr_mean?: number | null;
    inter_corr_mean?: number | null;
    silhouette?: number | null;
  };
};

export type UniverseClusterConsistency = {
  run_ms: number;
  timeframe?: string;
  window_bars?: number;
  compare_to_run_ms?: number | null;
  ari?: number | null;
  nmi?: number | null;
  cluster_retention?: {
    avg_retention?: number | null;
    by_cluster?: Record<string, number>;
  };
  centroid_drift?: {
    avg_drift?: number | null;
    by_cluster?: Record<string, number>;
  };
  status?: string;
  reasons?: string[];
};

export type UniversePools = {
  liq?: { HIGH?: string[]; MED?: string[]; LOW?: string[] };
  beta?: { HIGH?: string[]; MID?: string[]; LOW?: string[] };
  quality?: { GOOD?: string[]; OK?: string[]; BAD?: string[] };
  cluster?: Record<string, string[]>;
};

export type UniverseSelectionHints = {
  btc_alt_candidates?: string[];
  topk_per_cluster?: number;
  excluded_clusters?: string[];
  excluded_coins?: string[];
  constraints?: Record<string, unknown>;
};

export const fetchUniverseStatus = async (): Promise<UniverseState> => {
  return (await api.get<UniverseState>('/universe/status')).data;
};

export const triggerUniverseBuild = async (opts?: { venue?: string }) => {
  try {
    return (
      await api.post<{ ok: boolean; state?: UniverseState; error?: string }>(
        '/universe/build',
        {},
        {
          params: {
            ...(opts?.venue ? { venue: String(opts.venue) } : {}),
          },
        }
      )
    ).data;
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
};
export const fetchEvaluationData = async (window = 1000): Promise<EvaluationResponse> => {
  const requestedWindow = Math.max(100, Math.min(200000, Number(window) || 1000));
  const ceiling = Math.min(requestedWindow, 2000);
  const fallbackWindows = Array.from(
    new Set(
      [requestedWindow, ceiling, 1000, 500, 200, 100]
        .map((v) => Math.max(100, Math.min(200000, Number(v) || 1000)))
        .filter((v) => v <= requestedWindow),
    ),
  );
  let lastErr: unknown = null;
  for (const w of fallbackWindows) {
    const reqTimeoutMs = w <= 100 ? 6000 : w <= 200 ? 4500 : w <= 500 ? 3500 : 2500;
    try {
      const data = (await api.get<EvaluationResponse>('/evaluation/data', { params: { window: w }, timeout: reqTimeoutMs })).data;
      if (typeof data === 'object' && data && typeof data.ok === 'boolean') {
        return w === requestedWindow ? data : { ...data, warn: `window_fallback:${requestedWindow}->${w}` };
      }
      return { ok: false, error: 'invalid_evaluation_response' };
    } catch (err) {
      lastErr = err;
      const status = Number((err as { response?: { status?: unknown } } | undefined)?.response?.status ?? 0);
      if (status === 401 || status === 403 || status === 404) {
        return { ok: false, error: `http_${status}` };
      }
    }
  }
  const msg = String((lastErr as { message?: unknown } | undefined)?.message ?? 'evaluation_data_unavailable');
  return { ok: false, error: msg };
};
export const fetchEvalModels = async () => (await api.get<{ok:boolean,families:string[],active?:string}>('/evaluation/models')).data;
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type JsonRecord = Record<string, JsonValue>;

export interface EvalMetrics {
  auc?: number;
  brier?: number;
  win_rate?: number;
  sharpe?: number;
}

export interface EvalHistoryItem {
  id?: string;
  family?: string;
  ts?: number;
  metrics?: EvalMetrics;
}

export const trainEvalModel = async (family: string, params: JsonRecord, samples?: {features: Record<string, number>, label: number}[]) => 
  (await api.post<{ok:boolean, model: unknown, metrics: EvalMetrics, run: EvalHistoryItem}>('/evaluation/train', {family, params, samples})).data;
export const predictEval = async (family: string, features: Record<string, number>) =>
  (await api.post<{ok:boolean, family:string, p:number, pc:number, threshold:number, decision:string}>('/evaluation/predict', {family, features})).data;
export const fetchFeatureImportance = async (family: string) =>
  (await api.get<{ok:boolean, family:string, coefficients?:{feature:string, weight:number}[], importance?:{feature:string, gain:number}[]}>('/evaluation/feature-importance', { params: { family } })).data;
export const fetchEvalMetrics = async () =>
  (await api.get<{ok:boolean, family:string, metrics: EvalMetrics}>('/evaluation/metrics')).data;
export const onlineUpdate = async (family: string, features: Record<string, number>, label: number) =>
  (await api.post<{ok:boolean, family:string, count:number, metrics: EvalMetrics}>('/evaluation/online/update', {family, features, label})).data;
export const fetchEvalHistory = async () =>
  (await api.get<{ok:boolean, history: EvalHistoryItem[]}>('/evaluation/history')).data;

export type OnlineUpdateOrchestrationResponse = {
  ok: boolean;
  error?: string;
  ts?: number;
  as_of_ms?: number;
  label?: {
    ok?: boolean;
    added?: number;
    scanned?: number;
    matured?: number;
    skipped?: number;
    errors?: number;
    total_samples?: number;
    label_horizon_hours?: number;
  };
  arena?: Record<string, unknown>;
  arena_layer2?: Record<string, unknown>;
  train?: {
    ok?: boolean;
    trained?: boolean;
    family?: string;
    error?: string;
    details?: Record<string, unknown>;
  };
  promote?: {
    ok?: boolean;
    promoted?: boolean;
    error?: string;
  };
  serving?: Record<string, unknown>;
  state?: {
    last_label_ms?: number;
    last_train_ms?: number;
    last_promote_ms?: number;
    last_save_ms?: number;
    train_sample_count?: number;
    version?: number;
    [k: string]: unknown;
  };
  trace_id?: string;
  approval_id?: string | null;
  rollback_point?: string | null;
};

export const runOnlineUpdate = async (payload?: {
  as_of_ms?: number;
  max_label?: number;
  train?: boolean;
  family?: string;
  force_train?: boolean;
  confirm_live?: boolean;
}): Promise<OnlineUpdateOrchestrationResponse> => (await api.post<OnlineUpdateOrchestrationResponse>('/online/update', payload ?? {})).data;
export const explainEval = async (family: string, features: Record<string, number>) =>
  (await api.post<{ok:boolean, family:string, contribs:{feature:string, value:number}[]}>('/evaluation/explain', {family, features})).data;
export const saveEvalModel = async (family: string) =>
  (await api.post<{ok:boolean}>('/evaluation/save', {family})).data;
export const loadEvalModel = async () =>
  (await api.get<{ok:boolean}>('/evaluation/load')).data;

export const importEvalSamples = async (max_files: number = 20) =>
  (await api.post<{ok:boolean, added:number, scanned:number, total:number}>('/evaluation/samples/import', {max_files})).data;

export type ImportEvalSamplesResponse = {
  ok: boolean;
  error?: string;
  added: number;
  scanned: number;
  scanned_trades?: number;
  total: number;
  max_files?: number;
  max_samples?: number;
  duplicates?: number;
  dropped_outliers?: number;
  errors?: number;
  error_samples?: { file?: string; stage?: string; err?: string }[];
  elapsed_ms?: number;
};

export const importEvalSamplesV2 = async (max_files: number = 20, max_samples: number = 5000, reset: boolean = false) =>
  (await api.post<ImportEvalSamplesResponse>('/evaluation/samples/import', {max_files, max_samples, reset})).data;

export interface EquityCurvePoint {
  ts: number;
  cum_pnl: number;
  p: number;
  threshold: number;
  take: number;
}

export const fetchEvalEquityCurve = async (family: string, window: number = 5000, calibrated: boolean = true) =>
  (await api.get<{ok:boolean, family:string, window:number, calibrated:boolean, curve: EquityCurvePoint[]}>('/evaluation/equity_curve', { params: { family, window, calibrated } })).data;

export const fetchEvalHeatmap = async (family: string, window: number = 2000, calibrated: boolean = true) =>
  (await api.get<{ok:boolean, family:string, window:number, calibrated:boolean, counts: number[][], mean_return: number[][], win_rate: number[][]}>('/evaluation/heatmap', { params: { family, window, calibrated } })).data;

export const trainEvalCalibrator = async (family: string, method: 'platt' | 'isotonic' = 'platt', by_regime: boolean = false) =>
  (await api.post<{ok:boolean, error?:string} & Record<string, unknown>>('/evaluation/calibration/train', { family, method, by_regime })).data;

export const trainEvalCommittee = async (families?: string[]) =>
  (await api.post<{ok:boolean, error?:string, active?:string, members?:string[], weights?:Record<string, number>}>('/evaluation/committee/train', { families })).data;

export const fitEvalThresholds = async (family: string, window: number = 1000, regime?: string) =>
  (await api.post<{ok:boolean, family:string, window:number, fitted?:Record<string, unknown>, errors?:Record<string, unknown>}>('/evaluation/threshold/fit', { family, window, regime })).data;

export const fetchEvalThresholds = async () =>
  (await api.get<{ok:boolean, dynamic: unknown, static: {trend?: number, chop?: number}}>(`/evaluation/threshold/get`)).data;

export const rollingVerifyEval = async (family: string, folds: number = 5, calibrate_method?: 'platt' | 'isotonic') =>
  (await api.post<{ok:boolean, error?:string} & Record<string, unknown>>('/evaluation/rolling_verify', { family, folds, calibrate_method })).data;

export type EvalHealthHistogramBin = {
  lo: number;
  hi: number;
  n: number;
};

export type EvalHealthBucket = {
  lo: number;
  hi: number;
  n: number;
  frac: number;
};

export type EvalHealthOutputSeries = {
  n: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  hist?: EvalHealthHistogramBin[];
  sparkline?: string;
  buckets?: EvalHealthBucket[];
  std?: number;
  tail_frac_0_05_0_95?: number;
  pos_frac?: number;
  neg_frac?: number;
};

export type EvaluationHealthResponse = {
  ok: boolean;
  ts: number;
  issues?: { level: string; code: string; msg: string }[];
  output?: {
    n: number;
    enter_rate?: number | null;
    pc?: EvalHealthOutputSeries;
    threshold?: EvalHealthOutputSeries;
    margin?: EvalHealthOutputSeries;
    plots?: {
      pc_hist_png_base64?: string;
      threshold_hist_png_base64?: string;
      margin_hist_png_base64?: string;
      [k: string]: unknown;
    };
  };
};

export const fetchEvaluationHealth = async (params?: {
  window?: number;
  output_window?: number;
  output_bins?: number;
  output_plot?: boolean;
  compact?: boolean;
}) => (await api.get<EvaluationHealthResponse>('/evaluation/health', { params: { compact: true, ...(params || {}) } })).data;

export type EvaluationAcceptanceStatusResponse = {
  ok: boolean;
  ts: number;
  window: number;
  recent?: { minutes: number; since_ts: number; signals: number; orders: number };
  acceptance?: {
    sampling_phase?: {
      signals_orders_rejects_visible?: boolean;
      reject_reason_stats?: boolean;
      signal_traceable?: boolean;
      online_update_training?: boolean;
    };
    profit_phase?: {
      window_days?: number;
      has_stats?: boolean;
    };
    rollback?: {
      points?: number;
    };
  };
  profit_window?: {
    days: number;
    since_ts: number;
    n: number;
    profit_factor: number | null;
    profit_factor_inf: boolean;
    max_drawdown_u: number | null;
    max_drawdown_ratio: number | null;
    max_recovery_ms: number | null;
    unrecovered_drawdown_ms: number | null;
  };
  rejects?: {
    by_decision?: Record<string, number>;
    by_reason?: Record<string, number>;
  };
};

export const fetchEvaluationAcceptanceStatus = async (params?: {
  window?: number;
  recent_minutes?: number;
  profit_days?: number;
  compact?: boolean;
}) => (await api.get<EvaluationAcceptanceStatusResponse>('/evaluation/acceptance/status', { params: { compact: true, ...(params || {}) } })).data;

export type MonteCarloResult = {
  ok: boolean;
  error?: string;
  family?: string;
  n?: number;
  runs?: number;
  params?: Record<string, unknown>;
  metrics?: {
    mean?: Record<string, number>;
    p05?: Record<string, number>;
    p50?: Record<string, number>;
    p95?: Record<string, number>;
  };
};

export const monteCarloEval = async (payload: {
  family: string;
  runs?: number;
  window?: number;
  calibrated?: boolean;
  p_noise_std?: number;
  ret_noise_std?: number;
  cost_pct?: number;
  bootstrap?: boolean;
  drop_frac?: number;
  seed?: number;
}) => (await api.post<MonteCarloResult>('/evaluation/monte_carlo', payload)).data;

export interface EvaluationResponse {
  ok: boolean;
  error?: string;
  warn?: string;
  family?: string;
  metrics?: EvalMetrics;
  metrics_calibrated?: EvalMetrics;
  calibration?: { prob: number; actual: number }[];
  calibration_calibrated?: { prob: number; actual: number }[];
  pnl?: { date: string; pnl: number; cum_pnl: number }[];
  pnl_calibrated?: { date: string; pnl: number; cum_pnl: number }[];
}

export type QuantPairBtcEthParams = {
  timeframe: string;
  window_ols: number;
  window_z: number;
  beta_std_max?: number;
  beta_abs_max?: number;
  entry_z: number;
  entry_z_long?: number;
  entry_z_short?: number;
  exit_z: number;
  stop_z: number;
  corr_min: number;
  max_hold_bars: number;
  z_cost_buffer_mult: number;
  notional_usdc_per_leg?: number;
  pair_notional_usdc_max?: number | null;
  cooldown_bars_after_exit?: number;
  emergency_close_on_gate_violation?: boolean;
  state_check_interval_sec?: number;
  exit_pnl_enabled?: boolean;
  pnl_stop_loss_r?: number;
  pnl_take_profit_r?: number;
  pnl_trail_start_r?: number;
  pnl_trail_dd_r?: number;
  pnl_min_on_z_exit_r?: number;
  pnl_min_hold_bars?: number;
};

export type QuantPairBtcEthPoint = {
  ts: number;
  spread: number | null;
  z: number | null;
  beta: number | null;
  corr: number | null;
};

export type QuantPairBtcEthGateResult = {
  ok: boolean;
  error?: string;
  enabled?: boolean;
  valid?: boolean;
  pass?: boolean;
  blocked?: boolean;
  fail_count?: number;
  k_fail?: number;
  alpha?: number;
  alpha_eff?: number;
  test_count?: number;
  high_vol?: boolean;
  freq_bars?: number;
  bar_ts?: number;
  adf?: Record<string, unknown>;
  kpss?: Record<string, unknown>;
  log_tail?: Record<string, unknown>[];
};

export type QuantPairBtcEthCostEstimate = {
  ok: boolean;
  error?: string;
  notional_usdc?: number;
  btc_px?: number;
  size_btc?: number;
  mode?: 'maker' | 'taker';
  fee_rate?: number;
  slippage_rate?: number;
  slippage_rate_base?: number;
  slippage_scale?: number;
  maker_timeout_sec?: number;
};

export type QuantPairBtcEthCostParams = {
  slip_mu: number;
  slip_beta: number;
  slip_alpha: number;
  depth_threshold_btc: number;
  avg_depth_btc: number;
  maker_fee: number;
  taker_fee: number;
  maker_timeout_sec: number;
  slip_quantile: number;
};

export type QuantPairBtcEthCostStatus = {
  ok: boolean;
  notional_usdc: number | null;
  params: QuantPairBtcEthCostParams | null;
  estimate: QuantPairBtcEthCostEstimate | null;
  buffer?: Record<string, unknown> | null;
};

export type QuantPairBtcEthMarginLeg = {
  pnl_pct: number;
  trigger: number;
  pressure: boolean;
};

export type QuantPairBtcEthMarginStatus = {
  ok: boolean;
  error?: string;
  cfg?: Record<string, unknown>;
  recommend?: string;
  reduce_frac?: number;
  legs?: Record<string, QuantPairBtcEthMarginLeg>;
};

export type QuantMacroVeto = {
  ok?: boolean;
  blocked?: boolean;
  blocked_reason?: string | null;
  TrendDir12h?: number | null;
  TrendDirW?: number | null;
  TrendDirD?: number | null;
  ChgDir1hN?: number | null;
  ChgStrength?: number | null;
  ChgSpeedD?: number | null;
  RiskBudgetTier?: string | null;
  CrashSwitch?: boolean;
  TargetNetBias?: number | null;
  MaxNetExposure?: number | null;
  AllowOpen?: boolean;
  AllowAddon?: boolean;
  MacroState?: string | null;
  aligned?: boolean;
  conflict?: boolean;
  strong_trend?: boolean;
  strong_thr?: number | null;
  policy?: string | null;
  action?: string | null;
  snap?: Record<string, unknown> | null;
};

export type QuantPairBtcEthStatusResponse = {
  ok: boolean;
  ts?: number;
  timeframe?: string;
  params?: QuantPairBtcEthParams;
  base_params?: QuantPairBtcEthParams;
  latest?: QuantPairBtcEthPoint | null;
  action?: string;
  reason?: string | null;
  series?: QuantPairBtcEthPoint[];
  thresholds?: { entry_z_eff?: number; entry_z_eff_long?: number; entry_z_eff_short?: number; exit_z_eff?: number; z_cost?: number } | null;
  position?: Record<string, unknown> | null;
  pnl?: Record<string, unknown> | null;
  pnl_exit?: Record<string, unknown> | null;
  wfo?: Record<string, unknown> | null;
  gate?: QuantPairBtcEthGateResult | null;
  cost?: QuantPairBtcEthCostStatus | null;
  margin?: QuantPairBtcEthMarginStatus | null;
  cojump?: Record<string, unknown> | null;
  op_gate?: Record<string, unknown> | null;
  funding?: Record<string, unknown> | null;
  macro_veto?: QuantMacroVeto | null;
  position_source?: string | null;
  error?: string;
  n?: number;
};

export type QuantPairBtcEthBacktestTrade = {
  dir: string;
  t0: number;
  t1: number;
  i0: number;
  i1: number;
  hold_bars: number;
  entry_z: number;
  exit_z: number;
  entry_z_eff: number;
  exit_z_eff: number;
  z_cost: number;
  pnl_gross: number;
  pnl_cost: number;
  pnl_funding: number;
  pnl_net: number;
  reason: string;
};

export type QuantPairBtcEthBacktestEquityPoint = { t: number; cum: number };

export type QuantPairBtcEthBacktestSim = {
  ok: boolean;
  error?: string;
  trades?: QuantPairBtcEthBacktestTrade[];
  metrics?: {
    trades: number;
    net_pnl: number;
    net_sharpe: number;
    win_rate: number;
    max_drawdown: number;
    mean_trade_pnl: number;
  };
  equity_curve?: QuantPairBtcEthBacktestEquityPoint[];
};

export type QuantPairBtcEthScaleCurveItem = {
  gross_notional_usdc: number;
  ok: boolean;
  error?: string | null;
  metrics?: QuantPairBtcEthBacktestSim['metrics'] | null;
};

export type QuantPairBtcEthBacktestResponse = {
  ok: boolean;
  error?: string;
  timeframe: string;
  source: string;
  limit: number;
  notional_usdc: number;
  funding_mean_8h_btc?: number;
  funding_mean_8h_eth?: number;
  apply_cost: boolean;
  notional_grid?: number[] | null;
  scale_curve?: QuantPairBtcEthScaleCurveItem[] | null;
  params: QuantPairBtcEthParams;
  base_params: QuantPairBtcEthParams;
  wfo?: Record<string, unknown> | null;
  sim: QuantPairBtcEthBacktestSim;
};

export type QuantPairBtcEthResearchSplitResponse = {
  ok: boolean;
  ts: number;
  timeframe?: string;
  subset?: string;
  params?: {
    window_ols?: number;
    window_z?: number;
    purge_bars?: number;
    embargo_bars?: number;
    gap_bars?: number;
  };
  counts?: { all?: number; train?: number; val?: number; test?: number };
  ranges?: {
    train?: { a?: number; b?: number; ts0?: number | null; ts1?: number | null };
    val?: { a?: number; b?: number; ts0?: number | null; ts1?: number | null };
    test?: { a?: number; b?: number; ts0?: number | null; ts1?: number | null };
  };
  exported?: boolean;
  files?: { dir?: string; train?: string; val?: string; test?: string; all?: string } | null;
  error?: string;
};

export type QuantPairBtcEthResearchCapacityItem = {
  notional_btc_usdc: number;
  ok: boolean;
  metrics?: Record<string, unknown> | null;
};

export type QuantPairBtcEthResearchCapacityResponse = {
  ok: boolean;
  ts: number;
  timeframe?: string;
  subset?: string;
  params?: Record<string, unknown>;
  wfo?: Record<string, unknown> | null;
  items?: QuantPairBtcEthResearchCapacityItem[];
  error?: string;
};

export type QuantPairBtcEthResearchMarginStressResponse = {
  ok: boolean;
  ts: number;
  timeframe?: string;
  inputs?: Record<string, unknown>;
  beta_abs?: number;
  baseline?: Record<string, unknown>[];
  buffer_curve?: { vol_mult?: number; worst?: Record<string, unknown> }[];
  error?: string;
};

export type QuantPairBtcAltResearchSplitResponse = {
  ok: boolean;
  ts: number;
  timeframe?: string;
  alt?: string;
  subset?: string;
  params?: {
    window_ols?: number;
    window_z?: number;
    purge_bars?: number;
    embargo_bars?: number;
    gap_bars?: number;
  };
  counts?: { all?: number; train?: number; val?: number; test?: number };
  ranges?: {
    train?: { a?: number; b?: number; ts0?: number | null; ts1?: number | null };
    val?: { a?: number; b?: number; ts0?: number | null; ts1?: number | null };
    test?: { a?: number; b?: number; ts0?: number | null; ts1?: number | null };
  };
  exported?: boolean;
  files?: { dir?: string; train?: string; val?: string; test?: string; all?: string } | null;
  error?: string;
};

export type QuantPairBtcAltResearchCapacityItem = {
  notional_alt_usdc: number;
  ok: boolean;
  metrics?: Record<string, unknown> | null;
};

export type QuantPairBtcAltResearchCapacityResponse = {
  ok: boolean;
  ts: number;
  timeframe?: string;
  alt?: string;
  subset?: string;
  params?: Record<string, unknown>;
  wfo?: Record<string, unknown> | null;
  items?: QuantPairBtcAltResearchCapacityItem[];
  error?: string;
};

export type QuantPairBtcAltResearchMarginStressResponse = {
  ok: boolean;
  ts: number;
  timeframe?: string;
  alt?: string;
  inputs?: Record<string, unknown>;
  beta_abs?: number;
  baseline?: Record<string, unknown>[];
  buffer_curve?: { vol_mult?: number; worst?: Record<string, unknown> }[];
  error?: string;
};

export type QuantPairBtcEthConfig = {
  timeframe: string;
  window_ols: number;
  window_z: number;
  beta_std_max: number;
  beta_abs_max: number;
  entry_z: number;
  entry_z_long: number;
  entry_z_short: number;
  exit_z: number;
  z_exit_confirm_bars: number;
  stop_z: number;
  corr_min: number;
  max_hold_bars: number;
  z_cost_buffer_mult: number;
  notional_usdc_per_leg: number;
  pair_notional_usdc_max: number;
  cooldown_bars_after_exit: number;
  emergency_close_on_gate_violation: boolean;
  state_check_interval_sec: number;
  exit_pnl_enabled: boolean;
  pnl_stop_loss_r: number;
  pnl_take_profit_r: number;
  pnl_trail_start_r: number;
  pnl_trail_dd_r: number;
  pnl_min_on_z_exit_r: number;
  pnl_min_hold_bars: number;
};

export type QuantPairBtcEthConfigUpdate = Partial<QuantPairBtcEthConfig> & {
  confirm_live?: boolean;
  approval_id?: string;
  wfo_enabled?: boolean;
  wfo_apply?: boolean;
  wfo_refresh_sec?: number;
  wfo_plateau_min_frac?: number;
  wfo_plateau_tol?: number;
  wfo_is_bars?: number;
  wfo_oos_bars?: number;
  wfo_step_bars?: number;
  wfo_embargo_bars?: number;
  wfo_is_duration?: string;
  wfo_oos_duration?: string;
  wfo_step_duration?: string;
  wfo_embargo_duration?: string;
  wfo_grid?: Record<string, unknown> | string | null;
  window_ols_duration?: string;
  window_z_duration?: string;
  max_hold_duration?: string;
};

export type QuantPairBtcAltConfig = {
	timeframe: string;
	window_ols: number;
	window_z: number;
	entry_z: number;
	entry_z_long?: number;
	entry_z_short?: number;
	exit_z: number;
	z_exit_confirm_bars: number;
	stop_z: number;
	corr_min: number;
	max_hold_bars: number;
	z_cost_buffer_mult: number;

	exit_pnl_enabled?: boolean;
	pnl_stop_loss_r?: number;
	pnl_take_profit_r?: number;
	pnl_trail_start_r?: number;
	pnl_trail_dd_r?: number;
	pnl_min_on_z_exit_r?: number;
	pnl_min_hold_bars?: number;

	max_pairs_active: number;
	cluster_max_active: number;
	cluster_risk_budget_frac: number;
	gross_notional_usdc: number;
	pair_notional_usdc_max: number;
	capacity_turnover_frac: number;
	capacity_depth_frac: number;
	risk_weight_mode: 'equal' | 'inv_resid_vol' | 'inv_spread_sigma' | string;
	net_btc_exposure_target: number;
	net_btc_exposure_max: number;
	universe_consistency_min_ari: number;
	universe_consistency_min_nmi: number;
	circuit_breaker_dd_day: number;
	circuit_breaker_dd_week: number;
};

export type DiagnosticsGateStateResponse = {
  ok: boolean;
  ts: number;
  execution_venue?: string;
  live?: boolean;
  cooldown_sec?: number;
  coin_cooldown_sec?: number;
  entry_inflight_cooldown_sec?: number;
  post_close_hours?: number;
  order_rate_window_sec?: number;
  max_orders_per_minute?: number;
  underlying_mutual_exclusive_enabled?: boolean;
  regime_smooth?: Record<string, unknown>;
  macro_gate?: Record<string, unknown>;
  three_screen?: Record<string, unknown>;
  tracker?: Record<string, unknown>;
  cooldowns?: Record<string, unknown>;
  coin_cooldowns?: Record<string, unknown>;
  post_close_cooldowns?: Record<string, unknown>;
  entry_inflight?: Record<string, unknown>;
  gate_history?: Record<string, unknown>[];
  gate_summary?: Record<string, unknown>;
  error?: string;
};

export type QuantPairBtcAltPoint = {
  ts: number;
  spread: number;
  z: number;
  beta: number;
  corr: number;
};

export type QuantPairBtcAltStatusResponse = {
  ok: boolean;
  error?: string;
  ts?: number;
  strategy_mode?: string;
  timeframe?: string;
  alt?: string;
  alt_source?: string;
  alt_candidates?: string[] | null;
  source?: string;
  params?: Record<string, unknown>;
  base_params?: Record<string, unknown>;
  portfolio_params?: Record<string, unknown>;
  sub_pool?: Record<string, unknown> | null;
  thresholds?: { entry_z_eff?: number; exit_z_eff?: number; z_cost?: number } | null;
  latest?: QuantPairBtcAltPoint | null;
  action?: string;
  reason?: string | null;
  macro_veto?: QuantMacroVeto | null;
  series?: QuantPairBtcAltPoint[];
  position?: Record<string, unknown> | null;
  pnl?: Record<string, unknown> | null;
  pnl_exit?: Record<string, unknown> | null;
  gate?: Record<string, unknown> | null;
  corr_gate?: Record<string, unknown> | null;
  cost?: Record<string, unknown> | null;
  cojump?: Record<string, unknown> | null;
  op_gate?: Record<string, unknown> | null;
  funding?: Record<string, unknown> | null;
  regime?: Record<string, unknown> | null;
  rs?: Record<string, unknown> | null;
};

export type QuantPairBtcAltPortfolioSimTrade = {
  coin: string;
  mode: string;
  dir: string;
  t0: number;
  t1: number;
  hold_bars: number;
  pnl_net: number;
  reason: string;
  [key: string]: unknown;
};

export type QuantPairBtcAltPortfolioSimEquityPoint = {
  t: number;
  equity: number;
  realized: number;
  positions: number;
  net_btc_leg_usdc: number;
  gross_alt_notional: number;
  dd_day: number;
  dd_week: number;
};

export type QuantPairBtcAltPortfolioSim = {
  ok: boolean;
  error?: string;
  alts?: string[];
  trades?: QuantPairBtcAltPortfolioSimTrade[];
  metrics?: {
    trades: number;
    equity_end: number;
    realized_pnl: number;
    max_drawdown_usdc: number;
    max_drawdown_frac: number;
    sharpe_bar: number;
  };
  equity_curve?: QuantPairBtcAltPortfolioSimEquityPoint[];
  alloc_notional_alt?: Record<string, number>;
  corr_gate?: Record<string, unknown> | null;
  universe_consistency?: Record<string, unknown> | null;
  regime_latest?: Record<string, unknown> | null;
};

export type QuantPairBtcAltPortfolioSimScaleCurvePoint = {
  gross_notional_usdc: number;
  ok: boolean;
  error?: string | null;
  metrics?: Record<string, unknown> | null;
};

export type QuantPairBtcAltPortfolioSimulateResponse = {
  ok: boolean;
  error?: string;
  ts?: number;
  timeframe?: string;
  source?: string;
  limit?: number;
  alts?: string[];
  gross_notional_usdc?: number;
  notional_grid?: number[] | null;
  scale_curve?: QuantPairBtcAltPortfolioSimScaleCurvePoint[] | null;
  apply_cost?: boolean;
  params?: Record<string, unknown>;
  portfolio_params?: Record<string, unknown>;
  sim?: QuantPairBtcAltPortfolioSim | null;
  n?: number;
};

export type QuantComboSupervisionParams = {
  gross_notional_usdc: number;
  max_pairs_active: number;
  cluster_max_active: number;
  net_btc_exposure_target: number;
  net_btc_exposure_max: number;
};

export type QuantComboSupervisionState = {
  net_btc_leg_usdc: number;
  net_btc_exposure_frac: number;
  open_pairs: number;
  open_pairs_by_cluster: Record<string, number>;
};

export type QuantComboSupervisionNewTrade = {
  alt_coin?: string | null;
  btc_signed_notional_usdc?: number | null;
  net_btc_leg_usdc_after?: number | null;
  net_btc_exposure_frac_after?: number | null;
  would_violate_max_pairs?: boolean | null;
  would_violate_cluster_limit?: boolean | null;
  would_violate_net_btc_exposure?: boolean | null;
  ok?: boolean | null;
};

export type QuantComboSupervisionResponse = {
  ok: boolean;
  ts: number;
  params: QuantComboSupervisionParams;
  state: QuantComboSupervisionState;
  new_trade?: QuantComboSupervisionNewTrade | null;
  reasons?: string[];
};

export type QuantAutoBtcEthLastResponse = {
  ok: boolean;
  ts?: number;
  state?: string;
  mode?: string;
  enabled?: boolean;
  venue?: string;
  execute?: boolean;
  live_blocked_reason?: string | null;
  cooldown_until_ms?: number;
  [key: string]: unknown;
};

export type QuantAutoBtcaltsLastResponse = {
  ok: boolean;
  ts?: number;
  mode?: string;
  enabled?: boolean;
  venue?: string;
  execute?: boolean;
  live_blocked_reason?: string | null;
  decision?: Record<string, unknown> | null;
  blocked?: string | null;
  position?: Record<string, unknown> | null;
  positions?: Record<string, unknown>[] | null;
  opened?: Record<string, unknown>[] | null;
  closes?: Record<string, unknown>[] | null;
  rebalance?: {
    enabled?: boolean;
    min_notional_usdc?: number;
    cooldown_sec?: number;
    max_notional_usdc?: number;
    ignore_cooldown?: boolean;
    combo?: Record<string, unknown> | null;
    skip?: string | null;
    exec?: Record<string, unknown> | null;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
};

export const fetchQuantPairBtcEthStatus = async (params?: { timeframe?: string; limit?: number; source?: string; wfo_run?: boolean }) =>
  (await api.get<QuantPairBtcEthStatusResponse>('/quant/pairs/btceth/status', { params: { ...(params ?? {}) } })).data;

export const fetchQuantAutoBtcEthLast = async () => (await api.get<QuantAutoBtcEthLastResponse>('/quant/auto/btceth/last')).data;

export const fetchQuantAutoBtcaltsLast = async () => (await api.get<QuantAutoBtcaltsLastResponse>('/quant/auto/btcalts/last')).data;

export const quantAutoBtcEthTick = async (payload?: { now_ms?: number }) =>
  (await api.post<QuantAutoBtcEthLastResponse>('/quant/auto/btceth/tick', payload ?? {}, { timeout: 180000 })).data;

export const quantAutoBtcaltsTick = async (payload?: { now_ms?: number }) =>
  (await api.post<QuantAutoBtcaltsLastResponse>('/quant/auto/btcalts/tick', payload ?? {}, { timeout: 180000 })).data;

export const fetchQuantPairBtcAltStatus = async (params?: { alt?: string; coin?: string; symbol?: string; timeframe?: string; limit?: number; source?: string; strategy_mode?: string }) =>
  (await api.get<QuantPairBtcAltStatusResponse>('/quant/pairs/btcalt/status', { params: { ...(params ?? {}) } })).data;

export const fetchQuantComboSupervision = async (params?: { alt?: string; coin?: string; symbol?: string; btc_signed_notional_usdc?: number }) =>
  (await api.get<QuantComboSupervisionResponse>('/quant/pairs/combo/supervision', { params: { ...(params ?? {}) } })).data;

export type QuantPairBtcAltRecommendEval = {
  alt: string;
  ok: boolean;
  error?: string | null;
  bars?: number;
  metrics?: {
    trades?: number;
    net_pnl?: number;
    net_sharpe?: number;
    win_rate?: number;
    max_drawdown?: number;
    mean_trade_pnl?: number;
    [key: string]: unknown;
  };
  score?: number | null;
  [key: string]: unknown;
};

export type QuantPairBtcAltRecommendResponse = {
  ok: boolean;
  error?: string;
  ts: number;
  cached?: boolean;
  cache_ttl_sec?: number;
  timeframe: string;
  source: string;
  limit?: number;
  days?: number | null;
  end_ts?: number;
  apply_cost?: boolean;
  notional_usdc?: number;
  alts?: string[];
  evals?: QuantPairBtcAltRecommendEval[];
  best?: string | null;
  ranked?: string[];
  [key: string]: unknown;
};

export const fetchQuantPairBtcAltRecommend = async (params?: {
  timeframe?: string;
  source?: string;
  limit?: number;
  days?: number;
  apply_cost?: boolean;
  notional_usdc?: number;
  funding_mean_8h_btc?: number;
  funding_mean_8h_alt?: number;
  max_alts?: number;
  cache_ttl_sec?: number;
  alts?: string;
}) => (await api.get<QuantPairBtcAltRecommendResponse>('/quant/pairs/btcalt/recommend', { params, timeout: 60000 })).data;

export type QuantPairBtcAltCandidateSnapshot = {
  ok: boolean;
  error?: string;
  timeframe?: string;
  alt?: string;
  ts?: number | null;
  btc_px?: number | null;
  alt_px?: number | null;
  beta?: number | null;
  corr?: number | null;
  z?: number | null;
  [key: string]: unknown;
};

export type QuantPairBtcAltCandidatesResponse = {
  ok: boolean;
  error?: string;
  ts: number;
  timeframe: string;
  cached?: boolean;
  cache_ttl_sec?: number;
  universe_last_update?: number | null;
  max_alts?: number;
  candidates?: string[];
  snapshots?: QuantPairBtcAltCandidateSnapshot[] | null;
  [key: string]: unknown;
};

export const fetchQuantPairBtcAltCandidates = async (params?: { timeframe?: string; max_alts?: number; include_snap?: boolean; cache_ttl_sec?: number }) =>
  (await api.get<QuantPairBtcAltCandidatesResponse>('/quant/pairs/btcalt/candidates', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcAltOrdersRecent = async (params?: { limit?: number }) =>
  (await api.get<Order[]>('/quant/pairs/btcalt/orders/recent', { params: { limit: 50, ...(params ?? {}) } })).data;

export const fetchQuantPairBtcEthOrdersRecent = async (params?: { limit?: number; live_only?: boolean | number | string }) =>
  (await api.get<Order[]>('/quant/pairs/btceth/orders/recent', { params: { limit: 50, ...(params ?? {}) } })).data;

export const fetchQuantPairBtcEthBacktest = async (params?: { timeframe?: string; limit?: number; notional_usdc?: number; apply_cost?: boolean }) =>
  (await api.get<QuantPairBtcEthBacktestResponse>('/quant/pairs/btceth/backtest', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcEthResearchSplit = async (params?: {
  timeframe?: string;
  subset?: string;
  limit?: number;
  gap_bars?: number;
  purge_bars?: number;
  embargo_bars?: number;
  window_ols?: number;
  window_z?: number;
  export?: boolean;
}) => (await api.get<QuantPairBtcEthResearchSplitResponse>('/quant/pairs/btceth/research/split', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcEthResearchCapacity = async (params?: {
  timeframe?: string;
  subset?: string;
  limit?: number;
  notionals?: string;
  apply_wfo?: boolean;
}) => (await api.get<QuantPairBtcEthResearchCapacityResponse>('/quant/pairs/btceth/research/capacity', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcEthResearchMarginStress = async (params?: {
  timeframe?: string;
  lookback_bars?: number;
  paths?: number;
  horizon_hours?: number;
  leverage?: number;
  notional_btc_usdc?: number;
  imr?: number;
  mmr?: number;
  conf?: number;
  df_t?: number;
  seed?: number;
  vol_mult_levels?: string;
}) => (await api.get<QuantPairBtcEthResearchMarginStressResponse>('/quant/pairs/btceth/research/margin_stress', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcAltResearchSplit = async (params?: {
  timeframe?: string;
  alt?: string;
  subset?: string;
  limit?: number;
  gap_bars?: number;
  purge_bars?: number;
  embargo_bars?: number;
  window_ols?: number;
  window_z?: number;
  export?: boolean;
}) => (await api.get<QuantPairBtcAltResearchSplitResponse>('/quant/pairs/btcalt/research/split', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcAltResearchCapacity = async (params?: {
  timeframe?: string;
  alt?: string;
  subset?: string;
  limit?: number;
  notionals?: string;
  apply_wfo?: boolean;
}) => (await api.get<QuantPairBtcAltResearchCapacityResponse>('/quant/pairs/btcalt/research/capacity', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcAltResearchMarginStress = async (params?: {
  timeframe?: string;
  alt?: string;
  lookback_bars?: number;
  paths?: number;
  horizon_hours?: number;
  leverage?: number;
  notional_btc_usdc?: number;
  imr?: number;
  mmr?: number;
  conf?: number;
  df_t?: number;
  seed?: number;
  vol_mult_levels?: string;
}) => (await api.get<QuantPairBtcAltResearchMarginStressResponse>('/quant/pairs/btcalt/research/margin_stress', { params, timeout: 60000 })).data;

export type QuantPairBtcAltBacktestTrade = {
  dir: string;
  t0: number;
  t1: number;
  hold_bars: number;
  entry?: Record<string, unknown> | null;
  exit?: Record<string, unknown> | null;
  pnl_gross: number;
  pnl_cost: number;
  pnl_funding: number;
  pnl_net: number;
  reason: string;
  [key: string]: unknown;
};

export type QuantPairBtcAltBacktestEquityPoint = { t: number; cum: number };

export type QuantPairBtcAltBacktestSim = {
  ok: boolean;
  error?: string;
  trades?: QuantPairBtcAltBacktestTrade[];
  metrics?: {
    trades: number;
    net_pnl: number;
    net_sharpe: number;
    win_rate: number;
    max_drawdown: number;
    mean_trade_pnl: number;
  };
  equity_curve?: QuantPairBtcAltBacktestEquityPoint[];
  regime_latest?: Record<string, unknown> | null;
  rs_latest?: Record<string, unknown> | null;
};

export type QuantPairBtcAltScaleCurveItem = {
  gross_notional_usdc: number;
  ok: boolean;
  error?: string | null;
  metrics?: QuantPairBtcAltBacktestSim['metrics'] | null;
};

export type QuantPairBtcAltBacktestResponse = {
  ok: boolean;
  error?: string;
  timeframe: string;
  source: string;
  limit: number;
  days?: number | null;
  alt: string;
  notional_usdc: number;
  funding_mean_8h_btc?: number;
  funding_mean_8h_alt?: number;
  apply_cost: boolean;
  notional_grid?: number[] | null;
  scale_curve?: QuantPairBtcAltScaleCurveItem[] | null;
  params: Record<string, unknown>;
  base_params: Record<string, unknown>;
  sim: QuantPairBtcAltBacktestSim;
};

export const fetchQuantPairBtcAltBacktest = async (params?: {
  alt?: string;
  coin?: string;
  symbol?: string;
  timeframe?: string;
  limit?: number;
  days?: number;
  notional_usdc?: number;
  apply_cost?: boolean;
  funding_mean_8h_btc?: number;
  funding_mean_8h_alt?: number;
  notional_grid?: string;
}) =>
  (await api.get<QuantPairBtcAltBacktestResponse>('/quant/pairs/btcalt/backtest', { params, timeout: 60000 })).data;

export const fetchQuantPairBtcAltPortfolioSimulate = async (params?: {
  timeframe?: string;
  limit?: number;
  source?: string;
  gross_notional_usdc?: number;
  notional_grid?: string;
  apply_cost?: boolean;
  alts?: string;
  max_alts?: number;
  window_ols?: number;
  window_z?: number;
  entry_z?: number;
  exit_z?: number;
  stop_z?: number;
  corr_min?: number;
  max_hold_bars?: number;
  z_cost_buffer_mult?: number;
  funding_mean_8h_btc?: number;
  funding_mean_8h_alt?: number;
}) => (await api.get<QuantPairBtcAltPortfolioSimulateResponse>('/quant/pairs/btcalt/portfolio/simulate', { params, timeout: 60000 })).data;

export const updateQuantPairBtcEthConfig = async (cfg: QuantPairBtcEthConfigUpdate) =>
  (await api.post<{ ok: boolean; changed: Record<string, unknown>; params: QuantPairBtcEthParams }>('/quant/pairs/btceth/config', cfg)).data;

export const updateQuantPairBtcAltConfig = async (cfg: Partial<QuantPairBtcAltConfig> & { sync_quant_auto?: boolean }) =>
  (await api.post<{ ok: boolean; changed: Record<string, unknown>; params: Record<string, unknown>; portfolio_params: Record<string, unknown> }>('/quant/pairs/btcalt/config', cfg)).data;

export type PairsBtcEthMarketOpenPayload = {
  venue?: string;
  direction: 'long_btc_short_eth' | 'short_btc_long_eth' | string;
  notional_usdc?: number;
  execute?: boolean;
  confirm_execute?: boolean;
  idempotency_key?: string;
  maker?: boolean | 'auto' | 'on' | 'off' | string;
  maker_timeout_sec?: number;
  maker_price_offset_bps?: number;
  tag?: string;
  strategy_id?: string;
  timeframe?: string;
};

export type PairsBtcEthMarketClosePayload = {
  venue?: string;
  execute?: boolean;
  confirm_execute?: boolean;
  idempotency_key?: string;
  tag?: string;
};

export type PairsBtcEthActionResponse = {
  ok: boolean;
  error?: string;
  [key: string]: unknown;
};

export const pairsBtcEthMarketOpen = async (payload: PairsBtcEthMarketOpenPayload) =>
  (await api.post<PairsBtcEthActionResponse>('/execution/pairs/btceth/market_open', payload, { timeout: 60000 })).data;

export const pairsBtcEthMarketClose = async (payload: PairsBtcEthMarketClosePayload) =>
  (await api.post<PairsBtcEthActionResponse>('/execution/pairs/btceth/market_close', payload, { timeout: 60000 })).data;

export type PairsBtcAltMarketOpenPayload = {
  venue?: string;
  alt?: string;
  coin?: string;
  symbol?: string;
  direction: 'long_alt_short_btc' | 'short_alt_long_btc' | string;
  notional_usdc?: number;
  execute?: boolean;
  confirm_execute?: boolean;
  idempotency_key?: string;
  maker?: boolean | 'auto' | 'on' | 'off' | string;
  maker_timeout_sec?: number;
  maker_price_offset_bps?: number;
  tag?: string;
  strategy_id?: string;
  timeframe?: string;
  strategy_mode?: string;
};

export type PairsBtcAltMarketClosePayload = {
  venue?: string;
  alt?: string;
  coin?: string;
  symbol?: string;
  execute?: boolean;
  confirm_execute?: boolean;
  idempotency_key?: string;
  tag?: string;
};

export const pairsBtcAltMarketOpen = async (payload: PairsBtcAltMarketOpenPayload) =>
  (await api.post<PairsBtcEthActionResponse>('/execution/pairs/btcalt/market_open', payload, { timeout: 60000 })).data;

export const pairsBtcAltMarketClose = async (payload: PairsBtcAltMarketClosePayload) =>
  (await api.post<PairsBtcEthActionResponse>('/execution/pairs/btcalt/market_close', payload, { timeout: 60000 })).data;

// --- Redteam / Pressure Test ---
export type RedteamPromptInjectionResponse = {
  ok: boolean;
  cleaned_text?: string;
  preview?: string;
  strips?: number;
  mode?: string;
  error?: string;
};

export type PressureExecFailureResponse = {
  ok: boolean;
  results?: Array<{ ok: boolean; status: number; error?: string }>;
  n?: number;
  error?: string;
};

export const postRedteamPromptInjection = async (payload: {
  text?: string;
  mode?: string;
}) => (await api.post<RedteamPromptInjectionResponse>('/agent/redteam/prompt_injection', payload)).data;

export const postPressureExecFailure = async (payload: {
  n?: number;
  path?: string;
  http_status?: number;
}) => (await api.post<PressureExecFailureResponse>('/agent/pressure/exec_failure', payload)).data;

// ================================================================
// Regime Evolution — 形态演化引擎 API（Phase 2 前端四面板数据源）
// 对应后端 /regime/evolution/* 4 条 Flask 路由
// ================================================================

export const REGIME_EVOLUTION_ORDER = [
  'TREND_UP_STRONG', 'TREND_UP_MILD', 'RANGE_BOUND', 'CONSOLIDATION',
  'REVERSAL', 'VOLATILE_DROP', 'FOMO_RALLY', 'DISTRIBUTION',
] as const;

export const REGIME_EVOLUTION_COLORS: Record<string, string> = {
  TREND_UP_STRONG: '#16a34a',
  TREND_UP_MILD: '#84cc16',
  RANGE_BOUND: '#a3a3a3',
  CONSOLIDATION: '#78716c',
  REVERSAL: '#f59e0b',
  VOLATILE_DROP: '#ef4444',
  FOMO_RALLY: '#ec4899',
  DISTRIBUTION: '#8b5cf6',
};

export const DOTPLOT_INDICATOR_NAMES = [
  'ma200_above_3d', 'ma50_above', 'ma20_vs_ma50_order',
  'cycle_position_365d', 'ma_alignment_score', 'ma200_slope_signed',
  'dow_hhhl_score', 'log_ret_90d', 'log_ret_30d',
  'ma_slope_wavg', 'volume_trend_conf', 'vol_60d_pct',
] as const;

export const DOTPLOT_INDICATOR_LABELS: Record<string, string> = {
  ma200_above_3d: 'MA200三日确认',
  ma50_above: 'MA50上方',
  ma20_vs_ma50_order: 'MA20/50排列',
  cycle_position_365d: '365d区间位置',
  ma_alignment_score: 'MA对齐评分',
  ma200_slope_signed: 'MA200斜率',
  dow_hhhl_score: '道氏HH/HL',
  log_ret_90d: '90d对数收益',
  log_ret_30d: '30d对数收益',
  ma_slope_wavg: 'MA斜率加权',
  volume_trend_conf: '量能趋势确认',
  vol_60d_pct: '60d波动分位',
};

export type RegimeTrajectoryItem = {
  t: string;
  price: number;
  level_raw: number;
  trend_raw: number;
  level_smooth: number;
  trend_smooth: number;
  regime_probs: Record<string, number>;
  top3: Array<[string, number]>;
  consensus: number;
  hmm_state: number;
  bocpd_cp_prob: number;
  indicators?: Record<string, number>;
};

export type RegimeDotplot = {
  rows: string[];
  cols: string[];
  matrix: number[][];
  marginal_probs: number[];
  target_index: number;
  sample_counts: Record<string, number>;
} | null;

export type RegimeSnapshot = RegimeTrajectoryItem | null;

export type RegimeEvolutionLatestResponse = {
  ok: boolean;
  ts: number;
  symbol: string;
  window: number;
  trajectory: RegimeTrajectoryItem[];
  dotplot: RegimeDotplot;
  indicators: Record<string, number[]>;
  snapshot: RegimeSnapshot;
};

export type RegimeEvolutionTrajectoryResponse = {
  ok: boolean;
  ts: number;
  symbol: string;
  start: string;
  end: string;
  trajectory: RegimeTrajectoryItem[];
};

export type RegimeDotplotAverageResponse = {
  ok: boolean;
  ts: number;
  symbol: string;
  start: string;
  end: string;
  dotplot: RegimeDotplot;
};

export type RegimeWeightsLatestResponse = {
  ok: boolean;
  ts: number;
  weights: {
    week_start: string;
    level_weights: Record<string, number>;
    trend_weights: Record<string, number>;
    regime_centers: Record<string, [number, number]>;
    max_daily_delta: number;
    objective: number;
    comment: string;
  } | null;
};

// ============================================================
// BCRM 2.0 ParameterMapper 输出参数（6 全局 + 5 板块 + identity 基线）
// ============================================================
export type RegimeParamGlobalItem = {
  name: string;
  lo: number;
  hi: number;
  center: number;
  bandwidth: number;
  identity_center: number;
};

export type RegimeParamSectorItem = {
  name: string;
  weight: number;
  identity_weight: number;
};

export type RegimeEvolutionParamsResponse = {
  ok: boolean;
  ts: number;
  symbol: string;
  snapshot_t: string;
  inputs: {
    level_smooth: number;
    trend_smooth: number;
    consensus: number;
  };
  global_params: RegimeParamGlobalItem[];
  sector_weights: RegimeParamSectorItem[];
  sector_weights_sum: number;
  identity: {
    global_params: { name: string; lo: number; hi: number; center: number }[];
    sector_weights: { name: string; weight: number }[];
  };
};

export const fetchRegimeEvolutionLatest = async (params?: { symbol?: string; window?: number }) =>
  (await api.get<RegimeEvolutionLatestResponse>('/regime/evolution/latest', { params, timeout: 60000 })).data;

export const fetchRegimeEvolutionTrajectory = async (params: { symbol?: string; start?: string; end?: string }) =>
  (await api.get<RegimeEvolutionTrajectoryResponse>('/regime/evolution/trajectory', { params, timeout: 60000 })).data;

export const fetchRegimeDotplotAverage = async (params: { symbol?: string; start: string; end: string }) =>
  (await api.get<RegimeDotplotAverageResponse>('/regime/evolution/dotplot_average', { params, timeout: 60000 })).data;

export const fetchRegimeWeightsLatest = async (params?: { symbol?: string }) =>
  (await api.get<RegimeWeightsLatestResponse>('/regime/evolution/weights/latest', { params, timeout: 30000 })).data;

export const fetchRegimeEvolutionParams = async (params?: { symbol?: string }) =>
  (await api.get<RegimeEvolutionParamsResponse>('/regime/evolution/params', { params, timeout: 30000 })).data;
