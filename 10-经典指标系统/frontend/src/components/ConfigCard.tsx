
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { asterAccountSummary, asterMarketClose, asterMarketOpen, asterPing, asterPreflight, authMe, fetchConfig, getExecuteToken, getUiEnv, hasOperatorToken, hyperliquidCancelAll, hyperliquidMarketClose, hyperliquidMarketOpen, hyperliquidPing, hyperliquidSetLeverage, livePreflight, setExecuteToken, subscribeConfigToken, subscribeExecuteToken, subscribeMaintenanceToken, updateCarryConfig, updateConfig } from '../lib/api';
import { Settings, Save, ChevronDown, ChevronRight } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';

export const ConfigCard: React.FC = () => {
  const queryClient = useQueryClient();
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: fetchConfig });
  const { data: authMeData } = useQuery({
    queryKey: ['authMe'],
    queryFn: authMe,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: hlPingData } = useQuery({
    queryKey: ['hyperliquidPing'],
    queryFn: hyperliquidPing,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: asterPingData } = useQuery({
    queryKey: ['asterPing'],
    queryFn: asterPing,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: asterAccountData } = useQuery({
    queryKey: ['asterAccountSummary'],
    queryFn: asterAccountSummary,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  
  const [patch, setPatch] = useState<Record<string, unknown>>({});
  const [lastSavePayload, setLastSavePayload] = useState<Record<string, unknown> | null>(null);
  const [lastSaveVerify, setLastSaveVerify] = useState<string>('');
  const [carrySaveResult, setCarrySaveResult] = useState<string>('');
  const [macroHardGateSaveResult, setMacroHardGateSaveResult] = useState<string>('');
  const [exitPresetSaveResult, setExitPresetSaveResult] = useState<string>('');
  const [showExitPresetDetails, setShowExitPresetDetails] = useState<boolean>(false);
  const suppressSaveVerifyRef = useRef<boolean>(false);
  const [hlCoin, setHlCoin] = useState<string>('BTC');
  const [hlSide, setHlSide] = useState<'long' | 'short'>('long');
  const [hlNotionalUsdc, setHlNotionalUsdc] = useState<number>(400);
  const [hlSlippage, setHlSlippage] = useState<number>(0.02);
  const [hlLeverage, setHlLeverage] = useState<number>(10);
  const [hlIsCross, setHlIsCross] = useState<boolean>(true);
  const [hlPx, setHlPx] = useState<string>('');
  const [hlCloseSz, setHlCloseSz] = useState<string>('');
  const [hlResult, setHlResult] = useState<string>('');

  const [asCoin, setAsCoin] = useState<string>('BTC');
  const [asSide, setAsSide] = useState<'long' | 'short'>('long');
  const [asNotionalUsdc, setAsNotionalUsdc] = useState<number>(80);
  const [asLeverage, setAsLeverage] = useState<number>(10);
  const [asCloseSz, setAsCloseSz] = useState<string>('');
  const [asIgnoreCooldown, setAsIgnoreCooldown] = useState<boolean>(false);
  const [asAutoBumpToMin, setAsAutoBumpToMin] = useState<boolean>(true);
  const [asConfirmBump, setAsConfirmBump] = useState<boolean>(false);
  const [asResult, setAsResult] = useState<string>('');
  const [asPreflight, setAsPreflight] = useState<string>('');
  const [asBatchText, setAsBatchText] = useState<string>('50@3\n60@5\n80@8\n100@10');
  const [asBatchResult, setAsBatchResult] = useState<string>('');
  const [asBatchRunning, setAsBatchRunning] = useState<boolean>(false);
  const [livePreflightResult, setLivePreflightResult] = useState<string>('');
  const [confirmLive, setConfirmLive] = useState<boolean>(false);
  const [hasToken, setHasToken] = useState<boolean>(() => hasOperatorToken());
  const [executeTokenInput, setExecuteTokenInput] = useState<string>(() => getExecuteToken());
  const [tradeWhitelistNewSymbol, setTradeWhitelistNewSymbol] = useState<string>('');
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [collapsed, setCollapsed] = useState<boolean>(false);

  useEffect(() => {
    const refresh = () => setHasToken(hasOperatorToken());
    const unsub = subscribeExecuteToken((t) => {
      refresh();
      setExecuteTokenInput(String(t || ''));
    });
    const unsubConfig = subscribeConfigToken(() => refresh());
    const unsubMaintenance = subscribeMaintenanceToken(() => refresh());
    const onStorage = (e: StorageEvent) => {
      if (e.key !== 'execute_token' && e.key !== 'config_token' && e.key !== 'maintenance_token') return;
      refresh();
      setExecuteTokenInput(getExecuteToken());
    };
    window.addEventListener('storage', onStorage);
    return () => {
      unsub();
      unsubConfig();
      unsubMaintenance();
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  const formState = useMemo(() => {
    if (!config) {
      return null;
    }
    return { ...config, ...patch };
  }, [config, patch]);

  const notionalDiagnostics = useMemo(() => {
    if (!formState) return null;
    const fromBackend = (formState as unknown as { notional_diagnostics?: unknown })?.notional_diagnostics;
    if (fromBackend && typeof fromBackend === 'object') return fromBackend as Record<string, unknown>;

    const num = (v: unknown): number | null => {
      const x = Number(v);
      if (!Number.isFinite(x)) return null;
      return x;
    };
    const pos = (x: number | null): number | null => {
      if (x == null) return null;
      return x > 0 ? x : null;
    };

    const venue = String((formState as Record<string, unknown>)?.execution_venue ?? 'stub').toLowerCase().trim();
    const entryMin = pos(num((formState as Record<string, unknown>)?.entry_min_notional_usdc));
    const entryMax = pos(num((formState as Record<string, unknown>)?.entry_max_notional_usdc));

    const asterMin = pos(num((formState as Record<string, unknown>)?.aster_min_notional_usdc));
    const asterMax = pos(num((formState as Record<string, unknown>)?.aster_max_notional_usdc));
    const asterEffMin = Math.max(...[asterMin, entryMin].filter((x): x is number => x != null));
    const asterEffMax = Math.min(...[asterMax, entryMax].filter((x): x is number => x != null));

    const okMinMax = (lo: number | null, hi: number | null): boolean => {
      if (lo == null || hi == null) return true;
      return lo <= hi + 1e-12;
    };

    const issues: Array<Record<string, unknown>> = [];
    if (!okMinMax(entryMin, entryMax) && entryMin != null && entryMax != null) {
      issues.push({ code: 'entry_min_gt_entry_max', severity: 'high', entry_min_notional_usdc: entryMin, entry_max_notional_usdc: entryMax });
    }
    if (!okMinMax(asterMin, asterMax) && asterMin != null && asterMax != null) {
      issues.push({ code: 'aster_min_gt_aster_max', severity: 'high', aster_min_notional_usdc: asterMin, aster_max_notional_usdc: asterMax });
    }
    if (venue === 'aster' && !okMinMax(asterEffMin, asterEffMax) && Number.isFinite(asterEffMin) && Number.isFinite(asterEffMax)) {
      issues.push({ code: 'aster_effective_range_empty', severity: 'high', effective_min_notional_usdc: asterEffMin, effective_max_notional_usdc: asterEffMax });
    }

    return {
      ok: issues.every((x) => x.severity !== 'high'),
      venue,
      entry: { min_notional_usdc: entryMin, max_notional_usdc: entryMax },
      aster: {
        min_notional_usdc: asterMin,
        max_notional_usdc: asterMax,
        effective_min_notional_usdc: Number.isFinite(asterEffMin) ? asterEffMin : null,
        effective_max_notional_usdc: Number.isFinite(asterEffMax) ? asterEffMax : null,
      },
      issues,
    };
  }, [formState]);

  const getErrorMessage = (err: unknown) => {
    const axiosErr = err as AxiosError<{ error?: string }>;
    const msg = axiosErr.response?.data?.error;
    if (msg) return msg;
    if (axiosErr.message) return axiosErr.message;
    return String(err);
  };

  const fmtNum = (v: unknown, digits: number = 4) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return '-';
    return n.toFixed(digits);
  };

  const fmtAmount = (v: unknown, digits: number = 2): string => {
    const n = Number(v);
    if (!Number.isFinite(n)) return '-';
    return n.toFixed(digits);
  };

  const buildAsterPreflightText = (res: Record<string, unknown>): string => {
    const ok = Boolean(res?.ok);
    if (!ok) {
      const err = String(res?.error ?? 'unknown_error').trim() || 'unknown_error';
      return `Aster 预检失败：${err}`;
    }
    const willBump = Boolean(res?.will_bump);
    const required = Number(res?.required_notional_usdt ?? res?.required_notional_usdc ?? NaN);
    const effective = Number(res?.effective_notional_usdt ?? res?.effective_notional_usdc ?? res?.selected_notional_usdt ?? res?.selected_notional_usdc ?? NaN);
    if (willBump) {
      return `Aster 预检通过：需补齐最小名义（>= ${fmtAmount(required)} USDT）`;
    }
    return `Aster 预检通过：可直接下单（有效名义 ${fmtAmount(effective)} USDT）`;
  };

  const buildLivePreflightText = (res: Record<string, unknown>): string => {
    const ready = Boolean(res?.ready);
    const blockers = Array.isArray(res?.blockers) ? (res.blockers as unknown[]).length : 0;
    const warnings = Array.isArray(res?.warnings) ? (res.warnings as unknown[]).length : 0;
    if (ready && blockers === 0) {
      return warnings > 0 ? `实盘预检通过（警告 ${warnings} 项）` : '实盘预检通过';
    }
    return `实盘预检未通过（阻断 ${blockers} 项，警告 ${warnings} 项）`;
  };

  const buildExitPresetPatch = (preset: 'trend' | 'chop'): Record<string, unknown> => {
    if (preset === 'trend') {
      return {
        strategy_exit_enabled: false,
        use_exit_feeder_strategy: false,
        exit_tb_enabled: true,
        exit_tstp_enabled: true,
        exit_apply_leverage_to_thresholds: true,
        exit_tb_sl_atr_mult: 5.0,
        exit_tb_tp_atr_mult: 9.0,
        exit_tb_sl_min_pct: 0.03,
        exit_tb_tp_min_pct: 0.03,
        exit_tstp_tp_min_pct: 0.03,
        exit_tb_time_barrier_sec: 86400,
        exit_tb_take_reduce_frac: 0.5,
        exit_tb_time_reduce_frac: 0.4,
        exit_l2_take_profit_pct: 0.03,
        exit_l2_trailing_retrace_pct: 0.35,
        exit_l2_reduce_frac: 0.45,
        exit_l1_hold_risk_reduce_threshold: 0.72,
        exit_l1_hold_risk_close_threshold: 0.88,
        exit_l1_reduce_min_profit_pct: 0.01,
        exit_l1_reduce_base_frac: 0.3,
        exit_l1_reduce_max_frac: 0.6,
        exit_risk_gate_enabled: true,
        exit_risk_gate_cooldown_min: 90,
        exit_risk_gate_confirm_n: 2,
        exit_l0_max_hold_sec: 86400,
        exit_feeder_max_open_age_sec: 86400,
      };
    }
    return {
      strategy_exit_enabled: false,
      use_exit_feeder_strategy: false,
      exit_tb_enabled: true,
      exit_tstp_enabled: true,
      exit_apply_leverage_to_thresholds: true,
      exit_tb_sl_atr_mult: 2.5,
      exit_tb_tp_atr_mult: 4.0,
      exit_tb_sl_min_pct: 0.02,
      exit_tb_tp_min_pct: 0.015,
      exit_tstp_tp_min_pct: 0.015,
      exit_tb_time_barrier_sec: 21600,
      exit_tb_take_reduce_frac: 0.65,
      exit_tb_time_reduce_frac: 0.6,
      exit_l2_take_profit_pct: 0.015,
      exit_l2_trailing_retrace_pct: 0.25,
      exit_l2_reduce_frac: 0.6,
      exit_l1_hold_risk_reduce_threshold: 0.62,
      exit_l1_hold_risk_close_threshold: 0.78,
      exit_l1_reduce_min_profit_pct: 0.006,
      exit_l1_reduce_base_frac: 0.45,
      exit_l1_reduce_max_frac: 0.75,
      exit_risk_gate_enabled: true,
      exit_risk_gate_cooldown_min: 60,
      exit_risk_gate_confirm_n: 1,
      exit_l0_max_hold_sec: 43200,
      exit_feeder_max_open_age_sec: 43200,
    };
  };

  const trendExitPreset = useMemo(() => buildExitPresetPatch('trend'), []);
  const chopExitPreset = useMemo(() => buildExitPresetPatch('chop'), []);

  const strategyExitPresetFields: Array<{ key: string; label: string }> = [
    { key: 'strategy_exit_enabled', label: '策略出场执行开关' },
    { key: 'use_exit_feeder_strategy', label: 'Feeder读取策略出场信号' },
    { key: 'exit_tb_enabled', label: 'Triple Barrier 启用' },
    { key: 'exit_tstp_enabled', label: '时间衰减止盈启用' },
    { key: 'exit_tb_sl_atr_mult', label: 'TB 止损 ATR 倍数' },
    { key: 'exit_tb_tp_atr_mult', label: 'TB 止盈 ATR 倍数' },
    { key: 'exit_tb_time_barrier_sec', label: 'TB 时间屏障（秒）' },
    { key: 'exit_l1_hold_risk_reduce_threshold', label: 'L1 减仓阈值' },
    { key: 'exit_l1_hold_risk_close_threshold', label: 'L1 平仓阈值' },
    { key: 'exit_l2_take_profit_pct', label: 'L2 止盈阈值' },
    { key: 'exit_l2_trailing_retrace_pct', label: 'L2 回撤阈值' },
    { key: 'exit_risk_gate_cooldown_min', label: '风险闸门冷却（分钟）' },
    { key: 'exit_l0_max_hold_sec', label: 'L0 最大持仓时长（秒）' },
    { key: 'exit_feeder_max_open_age_sec', label: 'Feeder 最大持仓时长（秒）' },
  ];

  const formatPresetValue = (value: unknown): string => {
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) return '-';
      return Number.isInteger(value) ? String(value) : value.toFixed(4);
    }
    if (value == null) return '-';
    return String(value);
  };

  const mutation = useMutation({
    mutationFn: updateConfig,
    onSuccess: (res) => {
      try {
        if (res && typeof res === 'object' && 'config' in res) {
          const nextCfg = (res as unknown as { config?: unknown })?.config;
          if (nextCfg && typeof nextCfg === 'object') {
            queryClient.setQueryData(['config'], nextCfg);
          }
        }
      } catch {
        void 0;
      }
      queryClient.invalidateQueries({ queryKey: ['config'] });
      if (suppressSaveVerifyRef.current) {
        setLastSaveVerify('');
        suppressSaveVerifyRef.current = false;
        return;
      }
      try {
        const payload = lastSavePayload;
        if (payload && typeof payload === 'object') {
          const nextCfg = (res?.config ?? {}) as unknown as Record<string, unknown>;
          const keys = Object.keys(payload)
            .filter((k) => k !== 'confirm_live' && k !== 'approval_id')
            .sort();

          const stableStringify = (v: unknown): string => {
            if (v == null) return String(v);
            if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return JSON.stringify(v);
            if (Array.isArray(v)) return `[${v.map(stableStringify).join(',')}]`;
            if (typeof v === 'object') {
              const o = v as Record<string, unknown>;
              const ks = Object.keys(o).sort();
              return `{${ks.map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`).join(',')}}`;
            }
            return JSON.stringify(String(v));
          };

          const valueEq = (a: unknown, b: unknown): boolean => {
            if (typeof a === 'number' && typeof b === 'number') {
              if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
              return Math.abs(a - b) <= 1e-9;
            }
            if (typeof a === 'boolean' && typeof b === 'boolean') return a === b;
            if (typeof a === 'string' && typeof b === 'string') return a === b;
            return stableStringify(a) === stableStringify(b);
          };

          const missing: string[] = [];
          const mismatched: Array<{ key: string; sent: unknown; applied: unknown }> = [];

          for (const k of keys) {
            if (!(k in nextCfg)) {
              missing.push(k);
              continue;
            }
            const sent = (payload as Record<string, unknown>)[k];
            const applied = nextCfg[k];
            if (!valueEq(sent, applied)) {
              mismatched.push({ key: k, sent, applied });
            }
          }

          const runtimeVersion = String(
            (res as unknown as { runtime_config_version?: unknown })?.runtime_config_version ?? '',
          ).trim();
          const appliedKeys = Array.isArray((res as unknown as { applied_keys?: unknown })?.applied_keys)
            ? ((res as unknown as { applied_keys?: unknown })?.applied_keys as unknown[]).length
            : keys.length;
          const warnParts: string[] = [];
          if (missing.length > 0) warnParts.push(`缺失${missing.length}项`);
          if (mismatched.length > 0) warnParts.push(`不一致${mismatched.length}项`);
          const warnText = warnParts.length ? `；校验提示：${warnParts.join('，')}` : '';
          const verText = runtimeVersion ? `；版本 ${runtimeVersion}` : '';
          setLastSaveVerify(`配置已更新（${appliedKeys}项）${verText}${warnText}`);
        }
      } catch {
        setLastSaveVerify('');
      }
    },
    onError: (err) => {
      if (suppressSaveVerifyRef.current) {
        setLastSaveVerify('');
        suppressSaveVerifyRef.current = false;
        return;
      }
      const axiosErr = err as AxiosError<Record<string, unknown>>;
      const data = axiosErr.response?.data;
      if (data && typeof data === 'object') {
        try {
          const error = String((data as Record<string, unknown>)?.error ?? '').trim();
          const violations = (data as Record<string, unknown>)?.violations;
          const vList = Array.isArray(violations) ? (violations as Array<Record<string, unknown>>) : [];
          const hasLiveEnableBlocked = vList.some((v) => v?.key === 'live_trading_enabled' && v?.error === 'cannot_enable');
          const touchesDevUnlockKeys = vList.some((v) => {
            const k = String(v?.key ?? '');
            return k === 'execution_venue' || k === 'aster_trading_enabled' || k === 'signals_auto_decision' || k === 'signals_v1_restrict_trigger_non_feeder';
          });
          if (error === 'config_patch_rejected') {
            if (hasLiveEnableBlocked || touchesDevUnlockKeys) {
              setLastSaveVerify('配置被安全策略拒绝：当前环境禁止直接开启实盘或修改执行权限。');
              return;
            }
            setLastSaveVerify(`配置校验未通过（${vList.length}项），请在 Network 查看 /config/set 返回详情。`);
            return;
          }
          if (error) {
            setLastSaveVerify(`保存失败：${error}`);
            return;
          }
        } catch {
          void 0;
        }
      }
      const msg = getErrorMessage(err);
      setLastSaveVerify(`保存失败：${msg}`);
    }
  });

  const carryMutation = useMutation({
    mutationFn: updateCarryConfig,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      const ok = Boolean((res as { ok?: unknown } | undefined)?.ok);
      const changed = (res as { changed?: unknown } | undefined)?.changed;
      const changedCount = changed && typeof changed === 'object' ? Object.keys(changed as Record<string, unknown>).length : 0;
      if (ok) {
        setCarrySaveResult(changedCount > 0 ? `Carry 配置已更新（${changedCount}项）` : 'Carry 配置已更新');
        return;
      }
      setCarrySaveResult('Carry 配置更新失败');
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setCarrySaveResult(`Carry 配置更新失败：${msg}`);
    }
  });

  const hlOpenMutation = useMutation({
    mutationFn: hyperliquidMarketOpen,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      setHlResult(res.order_id ? `market_open ok: ${res.order_id}` : 'market_open ok');
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setHlResult(`market_open error: ${msg}`);
    }
  });

  const hlCloseMutation = useMutation({
    mutationFn: hyperliquidMarketClose,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      setHlResult(res.order_id ? `market_close ok: ${res.order_id}` : 'market_close ok');
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setHlResult(`market_close error: ${msg}`);
    }
  });

  const hlCancelAllMutation = useMutation({
    mutationFn: hyperliquidCancelAll,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      setHlResult(res.order_id ? `cancel_all ok: ${res.order_id}` : 'cancel_all ok');
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setHlResult(`cancel_all error: ${msg}`);
    }
  });

  const hlSetLeverageMutation = useMutation({
    mutationFn: hyperliquidSetLeverage,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      setHlResult(res.order_id ? `set_leverage ok: ${res.order_id}` : 'set_leverage ok');
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setHlResult(`set_leverage error: ${msg}`);
    }
  });

  const asPreflightMutation = useMutation({
    mutationFn: asterPreflight,
    onSuccess: (res) => {
      setAsPreflight(buildAsterPreflightText(res as unknown as Record<string, unknown>));
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setAsPreflight(`Aster 预检失败：${msg}`);
    }
  });

  const asOpenMutation = useMutation({
    mutationFn: asterMarketOpen,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      setAsResult(res.order_id ? `market_open ok: ${res.order_id}` : 'market_open ok');
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setAsResult(`market_open error: ${msg}`);
    }
  });

  const asCloseMutation = useMutation({
    mutationFn: asterMarketClose,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      setAsResult(res.order_id ? `market_close ok: ${res.order_id}` : 'market_close ok');
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setAsResult(`market_close error: ${msg}`);
    }
  });

  const livePreflightMutation = useMutation({
    mutationFn: livePreflight,
    onSuccess: (res) => {
      setLivePreflightResult(buildLivePreflightText(res as unknown as Record<string, unknown>));
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setLivePreflightResult(`实盘预检失败：${msg}`);
    }
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    setPatch(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? (e.target as HTMLInputElement).checked :
              type === 'number' ? (value === '' ? undefined : parseFloat(value)) : value,
    }));
  };
  
  const handleModeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const mode = e.target.value;
    setConfirmLive(false);
    if (mode === 'dry') {
      setPatch(prev => ({ ...prev, dry_run: true, live_trading_enabled: false }));
      return;
    }
    if (mode === 'shadow') {
      setPatch(prev => ({ ...prev, dry_run: false, live_trading_enabled: false }));
      return;
    }
    setPatch(prev => ({ ...prev, dry_run: false, live_trading_enabled: true }));
  };

  const handleAutomationModeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const mode = e.target.value;
    if (mode === 'global') {
      setPatch(prev => ({ ...prev, signals_auto_decision: true, signals_v1_restrict_trigger_non_feeder: false }));
      return;
    }
    if (mode === 'feeder_open') {
      setPatch(prev => ({ ...prev, signals_auto_decision: false, signals_v1_restrict_trigger_non_feeder: true }));
      return;
    }
  };

  const handleBoolSelectField = (name: string) => (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value === 'true';
    if (name === 'trade_whitelist_enabled' && v) {
      setPatch(prev => ({
        ...prev,
        [name]: v,
        whitelist_gate_enabled: true,
        whitelist_gate_dynamic_enabled: true,
        whitelist_gate_vote_rule_base: '2of5',
        whitelist_gate_vote_rule_relax: '1of5',
        whitelist_gate_eval_window_hours: 24,
        whitelist_gate_target_entries_per_day: 2,
        whitelist_gate_resume_entries_per_day: 4,
        whitelist_gate_pnl_window_days: 7,
        whitelist_gate_pnl_floor: 0,
        whitelist_gate_dd_ceiling: 0.05,
        whitelist_gate_min_switch_interval_hours: 12,
      }));
      return;
    }
    setPatch(prev => ({ ...prev, [name]: v }));
  };

  const handleTriBoolSelectField = (name: string) => (e: React.ChangeEvent<HTMLSelectElement>) => {
    const raw = e.target.value;
    const v = raw === 'inherit' ? null : raw === 'true';
    setPatch(prev => ({ ...prev, [name]: v }));
  };

  const handleServingPhaseChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const phase = e.target.value;
    if (phase === 'shadow') {
      setPatch(prev => ({ ...prev, serving_shadow_mode: true, serving_canary_enabled: false }));
      return;
    }
    if (phase === 'canary') {
      setPatch(prev => ({ ...prev, serving_shadow_mode: false, serving_canary_enabled: true }));
      return;
    }
    setPatch(prev => ({ ...prev, serving_shadow_mode: false, serving_canary_enabled: false }));
  };

  const handleCanaryPairsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const parts = e.target.value
      .split(',')
      .map(s => s.trim())
      .filter(Boolean);
    setPatch(prev => ({ ...prev, serving_canary_pairs: parts }));
  };

  const parsedPx = (() => {
    const v = hlPx.trim();
    if (!v) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  })();
  const parsedCloseSz = (() => {
    const v = hlCloseSz.trim();
    if (!v) return null;
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : null;
  })();

  if (!formState) return <div>Loading...</div>;

  const canWrite = hasToken || Boolean(authMeData?.ok);

  const tradingMode = (() => {
    if (formState.dry_run) return 'dry';
    return (formState.live_trading_enabled ?? false) ? 'live' : 'shadow';
  })();

  const servingPhase = (() => {
    if (formState.serving_shadow_mode) return 'shadow';
    return (formState.serving_canary_enabled ?? false) ? 'canary' : 'full';
  })();

  const automationMode = (() => {
    const global = Boolean(formState.signals_auto_decision ?? false);
    const restrict = Boolean(formState.signals_v1_restrict_trigger_non_feeder ?? false);
    if (global && !restrict) return 'global';
    if ((!global) && restrict) return 'feeder_open';
    return 'custom';
  })();

  const canaryPairsText = Array.isArray(formState.serving_canary_pairs) ? formState.serving_canary_pairs.join(',') : '';

  const tradeWhitelist = Array.isArray(formState.trade_whitelist) ? formState.trade_whitelist : [];

  const voteMode = ((formState.elastic_gating_enabled ?? false) ? 'elastic' : 'hard') as 'hard' | 'elastic';

  const applyVoteModePreset = (mode: 'hard' | 'elastic') => {
    const preset = (mode === 'hard')
      ? {
          elastic_gating_enabled: false,
          elastic_vote_rule: '3of5',
          arena_entry_relax_quorum: false,
          arena_entry_min_votes: 3,
        }
      : {
          elastic_gating_enabled: true,
          elastic_vote_rule: '2of5',
          arena_entry_relax_quorum: false,
          arena_entry_min_votes: 2,
        };

    if (!canWrite) return;
    setPatch((prev) => ({
      ...prev,
      ...preset,
    }));
  };

  const liveExecute = (!formState.dry_run) && (formState.live_trading_enabled ?? false);

  const patchObj = patch as Record<string, unknown>;
  const patchHas = (k: string) => Object.prototype.hasOwnProperty.call(patchObj, k);

  const currentDryRun = Boolean(formState.dry_run);
  const currentLiveTradingEnabled = Boolean(formState.live_trading_enabled ?? false);
  const currentLive = currentLiveTradingEnabled && (!currentDryRun);

  const nextDryRun = patchHas('dry_run') ? Boolean(patchObj.dry_run) : currentDryRun;
  let nextLiveTradingEnabled = patchHas('live_trading_enabled')
    ? Boolean(patchObj.live_trading_enabled)
    : currentLiveTradingEnabled;

  if (patchHas('dry_run')) {
    if (nextDryRun) {
      nextLiveTradingEnabled = false;
    } else {
      if (!patchHas('live_trading_enabled')) nextLiveTradingEnabled = true;
    }
  }

  const nextLive = nextLiveTradingEnabled && (!nextDryRun);
  const nextHlTradingEnabled = patchHas('hl_trading_enabled')
    ? Boolean(patchObj.hl_trading_enabled)
    : Boolean(formState.hl_trading_enabled ?? false);
  const nextAsterTradingEnabled = patchHas('aster_trading_enabled')
    ? Boolean(patchObj.aster_trading_enabled)
    : Boolean(formState.aster_trading_enabled ?? false);

  const patchTouchesLiveSensitive = (
    ['dry_run', 'live_trading_enabled', 'execution_venue', 'hl_trading_enabled', 'aster_trading_enabled', 'hl_account_address_override']
  ).some(patchHas);

  const needsLivePreflight = nextLive && (patchTouchesLiveSensitive || (!currentLive));
  const needsConfirmLive = Boolean(
    needsLivePreflight ||
    (patchHas('hl_trading_enabled') && nextHlTradingEnabled && (!nextDryRun)) ||
    (patchHas('aster_trading_enabled') && nextAsterTradingEnabled && (!nextDryRun))
  );

  const liveActionBlocked = liveExecute && (!canWrite || !confirmLive);
  const saveDisabled = !canWrite || mutation.isPending || (needsConfirmLive && !confirmLive);

  const parseAsterRounds = (raw: string): Array<{ notional_usdc: number; leverage: number }> => {
    const tokens = raw
      .split(/[\n,]+/)
      .map((t) => t.trim())
      .filter(Boolean);

    const rounds: Array<{ notional_usdc: number; leverage: number }> = [];
    for (const tok of tokens) {
      const m = tok.match(/^(\d+(?:\.\d+)?)\s*(?:@|x|\*)\s*(\d+(?:\.\d+)?)$/i);
      if (m) {
        const notional = Number(m[1]);
        const leverage = Number(m[2]);
        if (Number.isFinite(notional) && notional > 0 && Number.isFinite(leverage) && leverage > 0) {
          rounds.push({ notional_usdc: notional, leverage: Math.floor(leverage) });
        }
        continue;
      }
      const notionalOnly = Number(tok);
      if (Number.isFinite(notionalOnly) && notionalOnly > 0) {
        rounds.push({ notional_usdc: notionalOnly, leverage: Math.floor(Number(asLeverage) || 10) });
      }
    }
    return rounds;
  };

  const runAsterBatchPreflight = async () => {
    if (asBatchRunning) return;
    setAsBatchRunning(true);
    setAsBatchResult('');

    try {
      const rounds = parseAsterRounds(asBatchText);
      const out: Array<Record<string, unknown>> = [];
      for (let i = 0; i < rounds.length; i++) {
        const r = rounds[i];
        const res = await asterPreflight({ coin: asCoin, notional_usdt: r.notional_usdc });
        out.push({ i: i + 1, ...r, preflight: res });
      }
      const passed = out.filter((x) => Boolean((x as { preflight?: { ok?: unknown } })?.preflight?.ok)).length;
      const needBump = out.filter((x) => Boolean((x as { preflight?: { will_bump?: unknown } })?.preflight?.will_bump)).length;
      setAsBatchResult(`批量预检完成：通过 ${passed}/${out.length}；需补齐最小名义 ${needBump} 笔`);
    } catch (err) {
      const msg = getErrorMessage(err);
      setAsBatchResult(`批量预检失败：${msg}`);
    } finally {
      setAsBatchRunning(false);
    }
  };

  const runAsterBatchOpen = async () => {
    if (asBatchRunning) return;
    setAsBatchRunning(true);
    setAsBatchResult('');

    try {
      const rounds = parseAsterRounds(asBatchText);
      const out: Array<Record<string, unknown>> = [];

      for (let i = 0; i < rounds.length; i++) {
        const r = rounds[i];

        try {
          const pf = await asterPreflight({ coin: asCoin, notional_usdt: r.notional_usdc });
          const willBump = Boolean((pf as unknown as { will_bump?: unknown })?.will_bump);
          const need = Number(
            (pf as unknown as { required_notional_usdt?: unknown })?.required_notional_usdt ??
            (pf as unknown as { required_notional_usdc?: unknown })?.required_notional_usdc ??
            NaN,
          );
          if (willBump) {
            if (!asAutoBumpToMin) {
              out.push({ i: i + 1, ...r, skipped: true, reason: 'notional_too_small', required_notional_usdt: (Number.isFinite(need) ? need : null) });
              continue;
            }
            if (liveExecute && !asConfirmBump) {
              out.push({ i: i + 1, ...r, skipped: true, reason: 'bump_confirmation_required', required_notional_usdt: (Number.isFinite(need) ? need : null) });
              continue;
            }
          }
        } catch (err) {
          out.push({ i: i + 1, ...r, skipped: true, reason: `preflight_error:${getErrorMessage(err)}` });
          continue;
        }

        const res = await asterMarketOpen({
          coin: asCoin,
          side: asSide,
          notional_usdt: r.notional_usdc,
          notional_usdc: r.notional_usdc,
          leverage: r.leverage,
          ignore_cooldown: asIgnoreCooldown,
          auto_bump_to_min: asAutoBumpToMin,
          confirm_bump: asConfirmBump,
          max_bump_ratio: Number(formState.aster_max_bump_ratio ?? 2),
          execute: liveExecute,
          confirm_execute: liveExecute ? confirmLive : false,
        });
        out.push({ i: i + 1, ...r, order_id: res.order_id, order: res.order });
      }

      queryClient.invalidateQueries({ queryKey: ['orders'] });

      const success = out.filter((x) => String((x as { order_id?: unknown })?.order_id ?? '').trim().length > 0).length;
      const skipped = out.filter((x) => Boolean((x as { skipped?: unknown })?.skipped)).length;
      const modeText = liveExecute ? '实盘' : '模拟';
      setAsBatchResult(`批量开仓完成（${modeText}）：成功 ${success}，跳过 ${skipped}，总计 ${out.length}`);
    } catch (err) {
      const msg = getErrorMessage(err);
      setAsBatchResult(`批量开仓失败：${msg}`);
    } finally {
      setAsBatchRunning(false);
    }
  };

  const uiEnv = getUiEnv();
  const showLivePanel = uiEnv === 'prod';
  if (!showLivePanel) {
    return (
      <Card className="h-full">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-lg font-medium">Configuration</CardTitle>
          <div className="flex items-center gap-2">
            <Settings className="h-4 w-4 text-muted-foreground" />
          </div>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-slate-700">
            非 Prod 环境：实盘控制入口已隐藏（看不到、点不到、发不出去）。
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="h-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-lg font-medium">Configuration</CardTitle>
        <div className="flex items-center gap-2">
          <Settings className="h-4 w-4 text-muted-foreground" />
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2" onClick={() => setCollapsed(v => !v)}>
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            <span className="ml-1 text-xs">{collapsed ? '展开' : '折叠'}</span>
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {collapsed ? null : (
          <div className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-base font-semibold text-slate-800">ML 实盘控制面板</div>
              <div className="text-sm text-slate-600">执行/API、杠杆护栏、下单额度、Strategy/Quant 开关</div>
            </div>
            <Button type="button" variant="outline" onClick={() => setShowAdvanced(v => !v)}>
              {showAdvanced ? '隐藏高级配置' : '显示高级配置'}
            </Button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card A：执行 / API</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                  <div className="rounded border border-slate-200 bg-white p-3">
                    <div className="font-semibold mb-2">Aster</div>
                    <div className="flex justify-between"><span>ping</span><span>{String(asterPingData?.ok ?? false)}</span></div>
                    <div className="flex justify-between"><span>auth_mode</span><span>{String(asterPingData?.auth_mode ?? '-')}</span></div>
                    <div className="flex justify-between"><span>has_api_key</span><span>{String(asterPingData?.has_api_key ?? false)}</span></div>
                    <div className="flex justify-between"><span>has_secret</span><span>{String(asterPingData?.has_secret ?? false)}</span></div>
                    <div className="mt-2 border-t border-slate-100 pt-2">
                      <div className="flex justify-between"><span>acct</span><span>{String(asterAccountData?.ok ?? false)}</span></div>
                      <div className="flex justify-between"><span>USDT avail</span><span>{fmtNum(asterAccountData?.assets?.USDT?.availableBalance)}</span></div>
                      <div className="flex justify-between"><span>USDT wallet</span><span>{fmtNum(asterAccountData?.assets?.USDT?.walletBalance)}</span></div>
                      <div className="flex justify-between"><span>USDC avail</span><span>{fmtNum(asterAccountData?.assets?.USDC?.availableBalance)}</span></div>
                      <div className="flex justify-between"><span>USDC wallet</span><span>{fmtNum(asterAccountData?.assets?.USDC?.walletBalance)}</span></div>
                      {asterAccountData?.ok ? null : (
                        <div className="mt-1 text-xs text-rose-600 break-words">{String(asterAccountData?.error ?? '')}</div>
                      )}
                    </div>
                  </div>
                  <div className="rounded border border-slate-200 bg-white p-3">
                    <div className="font-semibold mb-2">Hyperliquid</div>
                    <div className="flex justify-between"><span>ping</span><span>{String(hlPingData?.ok ?? false)}</span></div>
                    <div className="flex justify-between"><span>has_account</span><span>{String(hlPingData?.has_account ?? false)}</span></div>
                    <div className="flex justify-between"><span>has_api_key</span><span>{String(hlPingData?.has_api_key ?? false)}</span></div>
                    <div className="flex justify-between"><span>btc_mid</span><span>{hlPingData?.btc_mid == null ? '-' : String(hlPingData.btc_mid)}</span></div>
                  </div>

                  <div className="space-y-2 sm:col-span-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">execute_token</label>
                    <Input
                      value={executeTokenInput}
                      onChange={(e) => {
                        const v = String(e.target.value || '');
                        setExecuteTokenInput(v);
                        setExecuteToken(v);
                      }}
                      placeholder="CONFIG_TOKEN / MAINTENANCE_TOKEN"
                    />
                    <div className="text-xs text-slate-500">
                      token 可选：未使用 Admin 登录时，用于解锁写配置与执行类接口
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Mode</label>
                    <select
                      value={tradingMode}
                      onChange={handleModeChange}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="dry">Dry Run</option>
                      <option value="shadow">Shadow (no execution)</option>
                      <option value="live">Live Trading</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">自动化模式</label>
                    <select
                      value={automationMode}
                      onChange={handleAutomationModeChange}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="custom" disabled>自定义（当前组合）</option>
                      <option value="feeder_open">只对 feeder 的 open 信号自动化</option>
                      <option value="global">全局自动化（所有 open 信号可触发）</option>
                    </select>
                    <div className="text-xs text-slate-500">
                      该开关会同时设置 signals_auto_decision 与 signals_v1_restrict_trigger_non_feeder；需点 Update Config 生效
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Execution Venue</label>
                    <select
                      name="execution_venue"
                      value={String(formState.execution_venue ?? 'stub')}
                      onChange={handleChange}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="stub">Stub</option>
                      <option value="aster">Aster</option>
                      <option value="hyperliquid" disabled={!!(hlPingData?.error && String(hlPingData.error).includes('hyperliquid_sdk_unavailable'))}>
                        {hlPingData?.error && String(hlPingData.error).includes('hyperliquid_sdk_unavailable') ? 'Hyperliquid (SDK missing)' : 'Hyperliquid'}
                      </option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Trading Enabled</label>
                    <select
                      value={String(formState.aster_trading_enabled ?? false)}
                      onChange={handleBoolSelectField('aster_trading_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">HL Trading Enabled</label>
                    <select
                      value={String(formState.hl_trading_enabled ?? false)}
                      onChange={handleBoolSelectField('hl_trading_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card B：杠杆范围</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">HL Default Leverage (1..20)</label>
                    <Input
                      type="number"
                      step="1"
                      min={1}
                      max={20}
                      name="hl_default_leverage"
                      value={Number(formState.hl_default_leverage ?? 3)}
                      onChange={handleChange}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Default Leverage (1..20)</label>
                    <Input
                      type="number"
                      step="1"
                      min={1}
                      max={20}
                      name="aster_default_leverage"
                      value={Number(formState.aster_default_leverage ?? 10)}
                      onChange={handleChange}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Dynamic Leverage Enabled</label>
                    <select
                      value={String(formState.leverage_dynamic_enabled ?? false)}
                      onChange={handleBoolSelectField('leverage_dynamic_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Leverage Min (1..20)</label>
                    <Input
                      type="number"
                      step="1"
                      min={1}
                      max={20}
                      name="leverage_dynamic_min"
                      value={Number(formState.leverage_dynamic_min ?? 3)}
                      onChange={handleChange}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Leverage Max (1..20)</label>
                    <Input
                      type="number"
                      step="1"
                      min={1}
                      max={20}
                      name="leverage_dynamic_max"
                      value={Number(formState.leverage_dynamic_max ?? 10)}
                      onChange={handleChange}
                    />
                  </div>
                  <div className="text-xs text-slate-600 sm:col-span-2">后端会强制裁剪到 [1, 20]，且若 max &lt; min 会自动修正。</div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card C：下单额度范围</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Min Notional (USDC)</label>
                    <Input
                      type="number"
                      step="1"
                      name="entry_min_notional_usdc"
                      value={Number(formState.entry_min_notional_usdc ?? 0)}
                      onChange={handleChange}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Max Notional (USDC)</label>
                    <Input
                      type="number"
                      step="1"
                      name="entry_max_notional_usdc"
                      value={Number(formState.entry_max_notional_usdc ?? 0)}
                      onChange={handleChange}
                    />
                  </div>
                  <div className="text-xs text-slate-600 sm:col-span-2">约定：0 表示不启用该边界。</div>
                  {(() => {
                    if (!notionalDiagnostics || typeof notionalDiagnostics !== 'object') return null;
                    const nd = notionalDiagnostics as Record<string, unknown>;
                    const venue = String((nd as Record<string, unknown>).venue ?? '').toLowerCase();
                    const a = ((nd as Record<string, unknown>).aster && typeof (nd as Record<string, unknown>).aster === 'object')
                      ? ((nd as Record<string, unknown>).aster as Record<string, unknown>)
                      : {};

                    const loRaw = a.effective_min_notional_usdc;
                    const hiRaw = a.effective_max_notional_usdc;
                    const lo = (typeof loRaw === 'number' && Number.isFinite(loRaw)) ? loRaw : null;
                    const hi = (typeof hiRaw === 'number' && Number.isFinite(hiRaw)) ? hiRaw : null;
                    if (venue !== 'aster') return null;
                    const bad = lo != null && hi != null && lo > hi + 1e-9;
                    return (
                      <div className={`text-xs sm:col-span-2 ${bad ? 'text-red-600' : 'text-slate-600'}`}>
                        Aster 生效下单额度范围（Entry 与交易所共同约束）：{lo ?? '—'} ~ {hi ?? '—'}
                      </div>
                    );
                  })()}
                  {(() => {
                    if (!notionalDiagnostics || typeof notionalDiagnostics !== 'object') return null;
                    const nd = notionalDiagnostics as Record<string, unknown>;
                    const issues = (nd as Record<string, unknown>).issues;
                    if (!Array.isArray(issues) || issues.length === 0) return null;
                    const codes = issues
                      .map((x) => {
                        if (!x || typeof x !== 'object') return '';
                        const code = (x as Record<string, unknown>).code;
                        return String(code ?? '').trim();
                      })
                      .filter(Boolean)
                      .slice(0, 6);
                    if (codes.length === 0) return null;
                    return (
                      <div className="text-xs sm:col-span-2 text-amber-700">
                        Notional 配置提示：{codes.join(', ')}
                      </div>
                    );
                  })()}

                  <details className="sm:col-span-2 rounded border border-slate-200 bg-white p-3">
                    <summary className="cursor-pointer text-sm font-medium text-slate-700">高级：交易所侧裁剪</summary>
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Min Notional (USDC)</label>
                        <Input type="number" step="1" name="aster_min_notional_usdc" value={Number(formState.aster_min_notional_usdc ?? 0)} onChange={handleChange} />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Max Notional (USDC)</label>
                        <Input type="number" step="1" name="aster_max_notional_usdc" value={Number(formState.aster_max_notional_usdc ?? 0)} onChange={handleChange} />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Adjust To Min</label>
                        <select
                          value={String(formState.aster_adjust_to_min ?? true)}
                          onChange={handleBoolSelectField('aster_adjust_to_min')}
                          className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                        >
                          <option value="false">False</option>
                          <option value="true">True</option>
                        </select>
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Max Bump Ratio</label>
                        <Input type="number" step="0.01" name="aster_max_bump_ratio" value={Number(formState.aster_max_bump_ratio ?? 2)} onChange={handleChange} />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">HL Min Notional (USDC)</label>
                        <Input type="number" step="1" name="hl_min_notional_usdc" value={Number(formState.hl_min_notional_usdc ?? 0)} onChange={handleChange} />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">HL Max Notional (USDC)</label>
                        <Input type="number" step="1" name="hl_max_notional_usdc" value={Number(formState.hl_max_notional_usdc ?? 0)} onChange={handleChange} />
                      </div>
                    </div>
                  </details>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card D：Strategy / Quant 开关</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Strategy Live Trading (override)</label>
                    <div className="flex gap-2">
                      <select
                        value={(formState.strategy_live_trading_enabled === true) ? 'true' : (formState.strategy_live_trading_enabled === false) ? 'false' : 'inherit'}
                        onChange={handleTriBoolSelectField('strategy_live_trading_enabled')}
                        className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value="inherit">Inherit</option>
                        <option value="false">False</option>
                        <option value="true">True</option>
                      </select>
                      <Button type="button" variant="outline" onClick={() => setPatch(prev => ({ ...prev, strategy_live_trading_enabled: true }))}>On</Button>
                      <Button type="button" variant="outline" onClick={() => setPatch(prev => ({ ...prev, strategy_live_trading_enabled: false }))}>Off</Button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Quant Live Trading (override)</label>
                    <div className="flex gap-2">
                      <select
                        value={(formState.quant_live_trading_enabled === true) ? 'true' : (formState.quant_live_trading_enabled === false) ? 'false' : 'inherit'}
                        onChange={handleTriBoolSelectField('quant_live_trading_enabled')}
                        className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value="inherit">Inherit</option>
                        <option value="false">False</option>
                        <option value="true">True</option>
                      </select>
                      <Button type="button" variant="outline" onClick={() => setPatch(prev => ({ ...prev, quant_live_trading_enabled: true }))}>On</Button>
                      <Button type="button" variant="outline" onClick={() => setPatch(prev => ({ ...prev, quant_live_trading_enabled: false }))}>Off</Button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Strategy Tier Trading Enabled</label>
                    <select
                      value={String(formState.strategy_tier_trading_enabled ?? true)}
                      onChange={handleBoolSelectField('strategy_tier_trading_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Quant BTCALTs Strategy Mode</label>
                    <select
                      name="quant_auto_btcalts_strategy_mode"
                      value={String(formState.quant_auto_btcalts_strategy_mode ?? 'B')}
                      onChange={handleChange}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="A">A</option>
                      <option value="B">B</option>
                      <option value="C">C</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Strategy Tier Default</label>
                    <select
                      name="strategy_tier_default"
                      value={String(formState.strategy_tier_default ?? 'A')}
                      onChange={handleChange}
                      disabled={formState.strategy_tier_trading_enabled === false}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                    >
                      <option value="A">A</option>
                      <option value="B">B</option>
                      <option value="C">C</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Carry Trade Enabled</label>
                    <select
                      value={String(formState.carry_trade_enabled ?? false)}
                      onChange={handleBoolSelectField('carry_trade_enabled')}
                      disabled={!canWrite}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Carry Trade Sandbox</label>
                    <select
                      value={String(formState.carry_trade_sandbox ?? true)}
                      onChange={handleBoolSelectField('carry_trade_sandbox')}
                      disabled={!canWrite}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                    >
                      <option value="true">True</option>
                      <option value="false">False</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Carry Trade Venue</label>
                    <select
                      name="carry_trade_venue"
                      value={String(formState.carry_trade_venue ?? 'hyperliquid')}
                      onChange={handleChange}
                      disabled={!canWrite}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                    >
                      <option value="hyperliquid">hyperliquid</option>
                    </select>
                  </div>

                  <div className="sm:col-span-2 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        if (!formState) return;
                        setCarrySaveResult('');
                        carryMutation.mutate({
                          carry_trade_enabled: Boolean(formState.carry_trade_enabled ?? false),
                          carry_trade_sandbox: Boolean(formState.carry_trade_sandbox ?? true),
                          carry_trade_venue: String(formState.carry_trade_venue ?? 'hyperliquid'),
                        });
                      }}
                      disabled={!canWrite || carryMutation.isPending}
                    >
                      Apply Carry（/carry/config）
                    </Button>
                    <div className="text-xs text-slate-600 break-all">{carrySaveResult}</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card G：Strategy Exit（Exit Feeder，策略信号禁用）</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="sm:col-span-2 text-xs text-slate-600">
                    说明：止盈/止损阈值默认按杠杆放大（PnL_eff = PnL * leverage），会显得更“快”。
                  </div>
                  <div className="sm:col-span-2 text-xs text-slate-600">
                    文档目标：以 CTA 波动率屏障（Triple Barrier）作为主框架，让出场宽度与波动率同尺度。
                  </div>
                  <div className="sm:col-span-2 text-xs text-slate-600">
                    当前开关：strategy_exit_enabled={String(formState.strategy_exit_enabled ?? false)}，use_exit_feeder_strategy={String((formState as Record<string, unknown>).use_exit_feeder_strategy ?? false)}
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Apply Leverage To Thresholds</label>
                    <select
                      value={String(formState.exit_apply_leverage_to_thresholds ?? true)}
                      onChange={handleBoolSelectField('exit_apply_leverage_to_thresholds')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>

                  <div className="sm:col-span-2 text-xs font-semibold text-slate-700 pt-2">Triple Barrier（CTA 主框架）</div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">TB Enabled</label>
                    <select
                      value={String(formState.exit_tb_enabled ?? true)}
                      onChange={handleBoolSelectField('exit_tb_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">TB Time Barrier (sec)</label>
                    <Input type="number" step="60" name="exit_tb_time_barrier_sec" value={Number(formState.exit_tb_time_barrier_sec ?? 0)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">TB SL ATR Mult</label>
                    <Input type="number" step="0.1" name="exit_tb_sl_atr_mult" value={Number(formState.exit_tb_sl_atr_mult ?? 6.0)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">TB TP ATR Mult</label>
                    <Input type="number" step="0.1" name="exit_tb_tp_atr_mult" value={Number(formState.exit_tb_tp_atr_mult ?? 9.0)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">TB Take Reduce Frac</label>
                    <Input type="number" step="0.05" name="exit_tb_take_reduce_frac" value={Number(formState.exit_tb_take_reduce_frac ?? 0.5)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">TB Time Reduce Frac</label>
                    <Input type="number" step="0.05" name="exit_tb_time_reduce_frac" value={Number(formState.exit_tb_time_reduce_frac ?? 0.0)} onChange={handleChange} />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L0 Max Hold (sec)</label>
                    <Input type="number" step="60" name="exit_l0_max_hold_sec" value={Number(formState.exit_l0_max_hold_sec ?? 86400)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L0 Stop Loss (pnl_pct)</label>
                    <Input type="number" step="0.001" name="exit_l0_max_unrealized_loss_pct" value={Number(formState.exit_l0_max_unrealized_loss_pct ?? -0.05)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L0 Liq Buffer (pct)</label>
                    <Input type="number" step="0.001" name="exit_l0_liq_buffer_pct" value={Number(formState.exit_l0_liq_buffer_pct ?? 0.02)} onChange={handleChange} />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Enabled</label>
                    <select
                      value={String(formState.exit_l1_enabled ?? false)}
                      onChange={handleBoolSelectField('exit_l1_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Mode</label>
                    <select
                      name="exit_l1_mode"
                      value={String(formState.exit_l1_mode ?? 'heuristic')}
                      onChange={handleChange}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="heuristic">heuristic</option>
                      <option value="mrd">mrd</option>
                      <option value="ml">ml</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Hysteresis N</label>
                    <Input type="number" step="1" name="exit_l1_hysteresis_n" value={Number(formState.exit_l1_hysteresis_n ?? 2)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Action Cooldown (sec)</label>
                    <Input type="number" step="10" name="exit_l1_action_cooldown_sec" value={Number(formState.exit_l1_action_cooldown_sec ?? 300)} onChange={handleChange} />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Hold Risk Reduce Thr</label>
                    <Input type="number" step="0.01" name="exit_l1_hold_risk_reduce_threshold" value={Number(formState.exit_l1_hold_risk_reduce_threshold ?? 0.7)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Hold Risk Close Thr</label>
                    <Input type="number" step="0.01" name="exit_l1_hold_risk_close_threshold" value={Number(formState.exit_l1_hold_risk_close_threshold ?? 0.85)} onChange={handleChange} />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Reduce Min Profit (pct)</label>
                    <Input type="number" step="0.001" name="exit_l1_reduce_min_profit_pct" value={Number(formState.exit_l1_reduce_min_profit_pct ?? 0.01)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Reduce Base Frac</label>
                    <Input type="number" step="0.05" name="exit_l1_reduce_base_frac" value={Number(formState.exit_l1_reduce_base_frac ?? 0.3)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L1 Reduce Max Frac</label>
                    <Input type="number" step="0.05" name="exit_l1_reduce_max_frac" value={Number(formState.exit_l1_reduce_max_frac ?? 0.7)} onChange={handleChange} />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L2 Reduce Frac</label>
                    <Input type="number" step="0.05" name="exit_l2_reduce_frac" value={Number(formState.exit_l2_reduce_frac ?? 0.5)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L2 Take Profit (pct)</label>
                    <Input type="number" step="0.001" name="exit_l2_take_profit_pct" value={Number(formState.exit_l2_take_profit_pct ?? 0.04)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">L2 Trailing Retrace (dd_pct)</label>
                    <Input type="number" step="0.01" name="exit_l2_trailing_retrace_pct" value={Number(formState.exit_l2_trailing_retrace_pct ?? 0.35)} onChange={handleChange} />
                  </div>
                  <div className="sm:col-span-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowExitPresetDetails((v) => !v)}
                      className="px-0 text-sm font-semibold text-slate-700"
                    >
                      {showExitPresetDetails ? '收起预设参数说明' : '展开预设参数说明'}
                    </Button>
                    {showExitPresetDetails ? (
                      <div className="mt-2 overflow-x-auto">
                        <table className="min-w-full text-xs">
                          <thead>
                            <tr className="border-b border-slate-200 text-slate-600">
                              <th className="py-1 pr-3 text-left font-medium">策略离场主要参数</th>
                              <th className="py-1 pr-3 text-left font-medium">趋势市默认参数</th>
                              <th className="py-1 text-left font-medium">震荡市默认参数</th>
                            </tr>
                          </thead>
                          <tbody>
                            {strategyExitPresetFields.map((item) => (
                              <tr key={item.key} className="border-b border-slate-100 last:border-b-0">
                                <td className="py-1 pr-3 text-slate-700">{item.label}</td>
                                <td className="py-1 pr-3 font-mono text-slate-700">{formatPresetValue(trendExitPreset[item.key])}</td>
                                <td className="py-1 font-mono text-slate-700">{formatPresetValue(chopExitPreset[item.key])}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </div>
                  <div className="sm:col-span-2 flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setLastSavePayload(null);
                        setLastSaveVerify('');
                        setExitPresetSaveResult('');
                        suppressSaveVerifyRef.current = true;
                        const payload = buildExitPresetPatch('trend');
                        mutation.mutate(payload, {
                          onSuccess: () => {
                            setExitPresetSaveResult(`已应用：趋势市默认参数（${Object.keys(payload).length}项）`);
                            setPatch((prev) => {
                              const next = { ...prev };
                              for (const k of Object.keys(payload)) {
                                delete next[k];
                              }
                              return next;
                            });
                          },
                          onError: (err) => {
                            const msg = getErrorMessage(err);
                            setExitPresetSaveResult(`save error: ${msg}`);
                          },
                        });
                      }}
                      disabled={!canWrite || mutation.isPending}
                    >
                      趋势市默认参数
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setLastSavePayload(null);
                        setLastSaveVerify('');
                        setExitPresetSaveResult('');
                        suppressSaveVerifyRef.current = true;
                        const payload = buildExitPresetPatch('chop');
                        mutation.mutate(payload, {
                          onSuccess: () => {
                            setExitPresetSaveResult(`已应用：震荡市默认参数（${Object.keys(payload).length}项）`);
                            setPatch((prev) => {
                              const next = { ...prev };
                              for (const k of Object.keys(payload)) {
                                delete next[k];
                              }
                              return next;
                            });
                          },
                          onError: (err) => {
                            const msg = getErrorMessage(err);
                            setExitPresetSaveResult(`save error: ${msg}`);
                          },
                        });
                      }}
                      disabled={!canWrite || mutation.isPending}
                    >
                      震荡市默认参数
                    </Button>
                    <div className="text-xs text-slate-600 break-all">{exitPresetSaveResult}</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card H：Quant Exit</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="sm:col-span-2 text-xs font-semibold text-slate-700">Pairs · BTC/ETH</div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Z</label>
                    <Input type="number" step="0.05" name="quant_pairs_btceth_exit_z" value={Number(formState.quant_pairs_btceth_exit_z ?? 0.5)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Stop Z</label>
                    <Input type="number" step="0.1" name="quant_pairs_btceth_stop_z" value={Number(formState.quant_pairs_btceth_stop_z ?? 4.0)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Z Exit Confirm Bars</label>
                    <Input type="number" step="1" name="quant_pairs_btceth_z_exit_confirm_bars" value={Number(formState.quant_pairs_btceth_z_exit_confirm_bars ?? 1)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit PnL Enabled</label>
                    <select
                      value={String(formState.quant_pairs_btceth_exit_pnl_enabled ?? true)}
                      onChange={handleBoolSelectField('quant_pairs_btceth_exit_pnl_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PnL Stop Loss (r)</label>
                    <Input type="number" step="0.001" name="quant_pairs_btceth_pnl_stop_loss_r" value={Number(formState.quant_pairs_btceth_pnl_stop_loss_r ?? -0.01)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PnL Take Profit (r)</label>
                    <Input type="number" step="0.001" name="quant_pairs_btceth_pnl_take_profit_r" value={Number(formState.quant_pairs_btceth_pnl_take_profit_r ?? 0.008)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PnL Min On Z Exit (r)</label>
                    <Input type="number" step="0.001" name="quant_pairs_btceth_pnl_min_on_z_exit_r" value={Number(formState.quant_pairs_btceth_pnl_min_on_z_exit_r ?? 0.0)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Cooldown Bars After Exit</label>
                    <Input type="number" step="1" name="quant_pairs_btceth_cooldown_bars_after_exit" value={Number(formState.quant_pairs_btceth_cooldown_bars_after_exit ?? 4)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2 sm:col-span-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Emergency Close On Gate Violation</label>
                    <select
                      value={String(formState.quant_pairs_btceth_emergency_close_on_gate_violation ?? true)}
                      onChange={handleBoolSelectField('quant_pairs_btceth_emergency_close_on_gate_violation')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>

                  <div className="sm:col-span-2 text-xs font-semibold text-slate-700 pt-2">Pairs · BTC/ALT</div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Z</label>
                    <Input type="number" step="0.05" name="quant_pairs_btcalt_exit_z" value={Number(formState.quant_pairs_btcalt_exit_z ?? 0.5)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Stop Z</label>
                    <Input type="number" step="0.1" name="quant_pairs_btcalt_stop_z" value={Number(formState.quant_pairs_btcalt_stop_z ?? 4.0)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Z Exit Confirm Bars</label>
                    <Input type="number" step="1" name="quant_pairs_btcalt_z_exit_confirm_bars" value={Number(formState.quant_pairs_btcalt_z_exit_confirm_bars ?? 1)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit PnL Enabled</label>
                    <select
                      value={String(formState.quant_pairs_btcalt_exit_pnl_enabled ?? true)}
                      onChange={handleBoolSelectField('quant_pairs_btcalt_exit_pnl_enabled')}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                    >
                      <option value="false">False</option>
                      <option value="true">True</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PnL Stop Loss (r)</label>
                    <Input type="number" step="0.001" name="quant_pairs_btcalt_pnl_stop_loss_r" value={Number(formState.quant_pairs_btcalt_pnl_stop_loss_r ?? -0.01)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PnL Take Profit (r)</label>
                    <Input type="number" step="0.001" name="quant_pairs_btcalt_pnl_take_profit_r" value={Number(formState.quant_pairs_btcalt_pnl_take_profit_r ?? 0.008)} onChange={handleChange} />
                  </div>
                  <div className="space-y-2 sm:col-span-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PnL Min On Z Exit (r)</label>
                    <Input type="number" step="0.001" name="quant_pairs_btcalt_pnl_min_on_z_exit_r" value={Number(formState.quant_pairs_btcalt_pnl_min_on_z_exit_r ?? 0.0)} onChange={handleChange} />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card E：Machine Voting</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="sm:col-span-2 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant={voteMode === 'hard' ? 'default' : 'outline'}
                      onClick={() => applyVoteModePreset('hard')}
                      disabled={!canWrite || mutation.isPending}
                    >
                      Hard
                    </Button>
                    <Button
                      type="button"
                      variant={voteMode === 'elastic' ? 'default' : 'outline'}
                      onClick={() => applyVoteModePreset('elastic')}
                      disabled={!canWrite || mutation.isPending}
                    >
                      Elastic
                    </Button>
                    <div className="ml-2 text-xs text-slate-600">Current: {voteMode === 'hard' ? 'Hard' : 'Elastic'}</div>
                  </div>

                  {voteMode === 'hard' ? (
                    <>
                      <div className="sm:col-span-2 text-xs text-slate-600">Hard parameters</div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Hard Vote Rule</label>
                        <select
                          name="elastic_vote_rule"
                          value={String(formState.elastic_vote_rule ?? '3of5')}
                          onChange={handleChange}
                          disabled={!canWrite}
                          className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                        >
                          <option value="2of5">2/5</option>
                          <option value="3of5">3/5</option>
                        </select>
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Min Votes (absolute)</label>
                        <Input type="number" step="1" name="arena_entry_min_votes" value={Number(formState.arena_entry_min_votes ?? 3)} onChange={handleChange} disabled={!canWrite} />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Min Weight Sum</label>
                        <Input type="number" step="0.01" name="arena_entry_min_weight_sum" value={Number(formState.arena_entry_min_weight_sum ?? 0.55)} onChange={handleChange} disabled={!canWrite} />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Weight Sum Floor Votes</label>
                        <Input type="number" step="1" name="arena_entry_weight_sum_floor_votes" value={Number(formState.arena_entry_weight_sum_floor_votes ?? 2)} onChange={handleChange} disabled={!canWrite} />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Eligible Only</label>
                        <select
                          value={String(formState.arena_entry_vote_eligible_only ?? true)}
                          onChange={handleBoolSelectField('arena_entry_vote_eligible_only')}
                          disabled={!canWrite}
                          className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                        >
                          <option value="true">True</option>
                          <option value="false">False</option>
                        </select>
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Relax Quorum</label>
                        <select
                          value={String(formState.arena_entry_relax_quorum ?? false)}
                          onChange={handleBoolSelectField('arena_entry_relax_quorum')}
                          disabled={!canWrite}
                          className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                        >
                          <option value="false">False</option>
                          <option value="true">True</option>
                        </select>
                      </div>
                    </>
                  ) : (
                    <div className="sm:col-span-2 text-xs text-slate-600">Elastic mode uses elastic gating (vote rule stored in elastic_vote_rule).</div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Card F：Macro BTC/ETH Hard Gate</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Mode</label>
                    <select
                      name="entry_macro_btceth_hard_gate_mode"
                      value={String(formState.entry_macro_btceth_hard_gate_mode ?? 'manual')}
                      onChange={handleChange}
                      disabled={!canWrite}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                    >
                      <option value="manual">manual</option>
                      <option value="auto">auto</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Enabled (manual only)</label>
                    <select
                      name="entry_macro_btceth_hard_gate_enabled"
                      value={String(Boolean(formState.entry_macro_btceth_hard_gate_enabled ?? true))}
                      onChange={handleBoolSelectField('entry_macro_btceth_hard_gate_enabled')}
                      disabled={!canWrite || String(formState.entry_macro_btceth_hard_gate_mode ?? 'manual') === 'auto'}
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
                    >
                      <option value="true">True</option>
                      <option value="false">False</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Auto Period (sec)</label>
                    <Input
                      type="number"
                      step="1"
                      name="entry_macro_btceth_hard_gate_auto_period_seconds"
                      value={Number(formState.entry_macro_btceth_hard_gate_auto_period_seconds ?? 60)}
                      onChange={handleChange}
                      disabled={!canWrite}
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Unlock Cooldown (h)</label>
                    <Input
                      type="number"
                      step="0.5"
                      name="entry_macro_btceth_hard_gate_auto_unlock_cooldown_hours"
                      value={Number(formState.entry_macro_btceth_hard_gate_auto_unlock_cooldown_hours ?? 2)}
                      onChange={handleChange}
                      disabled={!canWrite}
                    />
                  </div>

                  <div className="sm:col-span-2 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setMacroHardGateSaveResult('');

                        const payload = {
                          entry_macro_btceth_hard_gate_mode: String(formState.entry_macro_btceth_hard_gate_mode ?? 'manual'),
                          entry_macro_btceth_hard_gate_enabled: Boolean(formState.entry_macro_btceth_hard_gate_enabled ?? true),
                          entry_macro_btceth_hard_gate_auto_period_seconds: Number(formState.entry_macro_btceth_hard_gate_auto_period_seconds ?? 60),
                          entry_macro_btceth_hard_gate_auto_unlock_cooldown_hours: Number(formState.entry_macro_btceth_hard_gate_auto_unlock_cooldown_hours ?? 2),
                        };

                        setLastSavePayload(payload);
                        mutation.mutate(payload, {
                          onSuccess: (res) => {
                            const ok = Boolean((res as { ok?: unknown } | undefined)?.ok);
                            setMacroHardGateSaveResult(ok ? 'Macro Hard Gate 配置已应用' : 'Macro Hard Gate 配置应用失败');
                            setPatch((prev) => {
                              const next = { ...prev };
                              delete next.entry_macro_btceth_hard_gate_mode;
                              delete next.entry_macro_btceth_hard_gate_enabled;
                              delete next.entry_macro_btceth_hard_gate_auto_period_seconds;
                              delete next.entry_macro_btceth_hard_gate_auto_unlock_cooldown_hours;
                              return next;
                            });
                          },
                          onError: (err) => {
                            const msg = getErrorMessage(err);
                            setMacroHardGateSaveResult(`Macro Hard Gate 保存失败：${msg}`);
                          },
                        });
                      }}
                      disabled={!canWrite || mutation.isPending}
                    >
                      Apply（/config/set）
                    </Button>
                    <div className="text-xs text-slate-600 break-all">{macroHardGateSaveResult}</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {showAdvanced ? (
            <div className="pt-2">
              <div className="text-sm font-semibold text-slate-700 mb-2">高级配置</div>
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2 text-sm font-semibold text-slate-700">Trading</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Trend Threshold</label>
            <Input 
              type="number" step="0.01" name="threshold_trend"
              value={formState.threshold_trend} onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Chop Threshold</label>
            <Input 
              type="number" step="0.01" name="threshold_chop"
              value={formState.threshold_chop} onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Min Size</label>
            <Input 
              type="number" step="0.001" name="min_trade_size"
              value={formState.min_trade_size} onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max Size</label>
            <Input 
              type="number" step="0.001" name="max_trade_size"
              value={formState.max_trade_size} onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Mode</label>
            <select 
              value={tradingMode} onChange={handleModeChange}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="dry">Dry Run</option>
              <option value="shadow">Shadow (no execution)</option>
              <option value="live">Live Trading</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Live Trading Enabled</label>
            <select
              value={String(formState.live_trading_enabled ?? false)}
              onChange={handleBoolSelectField('live_trading_enabled')}
              disabled={formState.dry_run}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-50"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Trade Whitelist Enabled</label>
            <select
              value={String(formState.trade_whitelist_enabled ?? true)}
              onChange={handleBoolSelectField('trade_whitelist_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Trade Whitelist Enforcement</label>
            <select
              name="trade_whitelist_enforcement"
              value={String(formState.trade_whitelist_enforcement ?? 'hard')}
              onChange={handleChange}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="off">off</option>
              <option value="soft">soft</option>
              <option value="hard">hard</option>
            </select>
          </div>

          <div className="col-span-2 space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Trade Whitelist</label>
            <div className="flex gap-2">
              <Input
                value={tradeWhitelistNewSymbol}
                onChange={(e) => setTradeWhitelistNewSymbol(e.target.value)}
                placeholder="BTCUSDT"
              />
              <Button
                type="button"
                onClick={() => {
                  const sym = tradeWhitelistNewSymbol.trim().toUpperCase();
                  if (!sym) return;
                  const next = Array.from(new Set([...(tradeWhitelist || []), sym]));
                  next.sort();
                  setPatch((prev) => ({ ...prev, trade_whitelist: next }));
                  setTradeWhitelistNewSymbol('');
                }}
              >
                Add
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {tradeWhitelist.length ? tradeWhitelist.map((s) => (
                <div key={s} className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-2 py-1 text-sm">
                  <span className="font-mono">{s}</span>
                  <button
                    type="button"
                    className="text-slate-500 hover:text-slate-900"
                    onClick={() => {
                      const next = (tradeWhitelist || []).filter((x) => String(x).toUpperCase() !== String(s).toUpperCase());
                      setPatch((prev) => ({ ...prev, trade_whitelist: next }));
                    }}
                  >
                    ×
                  </button>
                </div>
              )) : (
                <div className="text-sm text-slate-500">(empty)</div>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Execution Venue</label>
            <select
              name="execution_venue"
              value={String(formState.execution_venue ?? 'stub')}
              onChange={handleChange}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="stub">Stub</option>
              <option value="aster">Aster</option>
              <option value="hyperliquid" disabled={!!(hlPingData?.error && String(hlPingData.error).includes('hyperliquid_sdk_unavailable'))}>
                {hlPingData?.error && String(hlPingData.error).includes('hyperliquid_sdk_unavailable') ? 'Hyperliquid (SDK missing)' : 'Hyperliquid'}
              </option>
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">HL Trading Enabled</label>
            <select
              value={String(formState.hl_trading_enabled ?? false)}
              onChange={handleBoolSelectField('hl_trading_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Trading Enabled</label>
            <select
              value={String(formState.aster_trading_enabled ?? false)}
              onChange={handleBoolSelectField('aster_trading_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Serving</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Serving Phase</label>
            <select
              value={String(servingPhase)}
              onChange={handleServingPhaseChange}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="shadow">Shadow</option>
              <option value="canary">Canary</option>
              <option value="full">Full</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Canary Size Fraction</label>
            <Input
              type="number"
              step="0.01"
              name="serving_canary_size_frac"
              disabled={!(formState.serving_canary_enabled ?? false)}
              value={Number(formState.serving_canary_size_frac ?? 0.05)}
              onChange={handleChange}
            />
          </div>
          <div className="col-span-2 space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Canary Pairs (comma separated)</label>
            <Input
              value={String(canaryPairsText)}
              disabled={!(formState.serving_canary_enabled ?? false)}
              onChange={handleCanaryPairsChange}
              placeholder="BTC,ETH"
            />
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Execution</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Fixed Notional Enabled</label>
            <select
              value={String(formState.entry_fixed_notional_enabled ?? true)}
              onChange={handleBoolSelectField('entry_fixed_notional_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Fixed Notional (USDC)</label>
            <Input
              type="number"
              step="1"
              name="entry_fixed_notional_usdc"
              value={Number(formState.entry_fixed_notional_usdc ?? 200)}
              onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Min Notional (USDC)</label>
            <Input
              type="number"
              step="1"
              name="entry_min_notional_usdc"
              value={Number(formState.entry_min_notional_usdc ?? 100)}
              onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Max Notional (USDC)</label>
            <Input
              type="number"
              step="1"
              name="entry_max_notional_usdc"
              value={Number(formState.entry_max_notional_usdc ?? 200)}
              onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Min Notional (USDC)</label>
            <Input
              type="number"
              step="1"
              name="aster_min_notional_usdc"
              value={Number(formState.aster_min_notional_usdc ?? 10)}
              onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Max Notional (USDC)</label>
            <Input
              type="number"
              step="1"
              name="aster_max_notional_usdc"
              value={Number(formState.aster_max_notional_usdc ?? 500)}
              onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Adjust To Min</label>
            <select
              value={String(formState.aster_adjust_to_min ?? true)}
              onChange={handleBoolSelectField('aster_adjust_to_min')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Aster Max Bump Ratio</label>
            <Input
              type="number"
              step="0.01"
              name="aster_max_bump_ratio"
              value={Number(formState.aster_max_bump_ratio ?? 2)}
              onChange={handleChange}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Allow Remote Execute</label>
            <select
              value={String(formState.live_execute_allow_remote ?? false)}
              onChange={handleBoolSelectField('live_execute_allow_remote')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>
          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Risk Limits</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Loss Gate Enabled (daily/weekly)</label>
            <select
              value={String(formState.loss_gate_enabled ?? true)}
              onChange={handleBoolSelectField('loss_gate_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max Daily Loss</label>
            <Input type="number" step="0.01" name="max_daily_loss" value={Number(formState.max_daily_loss ?? -0.05)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max Weekly Loss</label>
            <Input type="number" step="0.01" name="max_weekly_loss" value={Number(formState.max_weekly_loss ?? -0.12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Strategy Max Daily Loss</label>
            <Input type="number" step="0.01" name="strategy_max_daily_loss" value={Number(formState.strategy_max_daily_loss ?? formState.max_daily_loss ?? -0.05)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Strategy Max Weekly Loss</label>
            <Input type="number" step="0.01" name="strategy_max_weekly_loss" value={Number(formState.strategy_max_weekly_loss ?? formState.max_weekly_loss ?? -0.12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Quant Max Daily Loss</label>
            <Input type="number" step="0.01" name="quant_max_daily_loss" value={Number(formState.quant_max_daily_loss ?? formState.max_daily_loss ?? -0.05)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Quant Max Weekly Loss</label>
            <Input type="number" step="0.01" name="quant_max_weekly_loss" value={Number(formState.quant_max_weekly_loss ?? formState.max_weekly_loss ?? -0.12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Carry Max Daily Loss</label>
            <Input type="number" step="0.01" name="carry_max_daily_loss" value={Number(formState.carry_max_daily_loss ?? formState.max_daily_loss ?? -0.05)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Carry Max Weekly Loss</label>
            <Input type="number" step="0.01" name="carry_max_weekly_loss" value={Number(formState.carry_max_weekly_loss ?? formState.max_weekly_loss ?? -0.12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max Open Trades</label>
            <Input type="number" step="1" name="max_open_trades" value={Number(formState.max_open_trades ?? 5)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max Orders/Minute</label>
            <Input type="number" step="1" name="max_orders_per_minute" value={Number(formState.max_orders_per_minute ?? 12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Order Rate Window (sec)</label>
            <Input type="number" step="1" name="order_rate_window_sec" value={Number(formState.order_rate_window_sec ?? 60)} onChange={handleChange} />
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Signal Gates</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Signals Dedup TTL (sec)</label>
            <Input type="number" step="300" name="signals_dedup_ttl_sec" value={Number(formState.signals_dedup_ttl_sec ?? 3600)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Signals Dedup Bucket (sec)</label>
            <Input type="number" step="30" name="signals_dedup_bucket_sec" value={Number(formState.signals_dedup_bucket_sec ?? 60)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Signals Pair+Side Cooldown (sec)</label>
            <Input type="number" step="1" name="signals_pair_side_cooldown_sec" value={Number(formState.signals_pair_side_cooldown_sec ?? 600)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Signals Coin+Side Cooldown (sec)</label>
            <Input type="number" step="1" name="signals_coin_side_cooldown_sec" value={Number(formState.signals_coin_side_cooldown_sec ?? 300)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Inflight Cooldown (sec)</label>
            <Input type="number" step="1" name="entry_inflight_cooldown_sec" value={Number(formState.entry_inflight_cooldown_sec ?? 90)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Post-close Freeze (hours)</label>
            <Input type="number" step="0.25" name="coin_freeze_post_close_hours" value={Number(formState.coin_freeze_post_close_hours ?? 4)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PC Hysteresis Delta</label>
            <Input type="number" step="0.001" name="pc_hysteresis_delta" value={Number(formState.pc_hysteresis_delta ?? 0)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Signals Confirm Enabled</label>
            <select
              value={String(formState.signals_v1_confirm_enabled ?? false)}
              onChange={handleBoolSelectField('signals_v1_confirm_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Signals Confirm N</label>
            <Input type="number" step="1" name="signals_v1_confirm_n" value={Number(formState.signals_v1_confirm_n ?? 2)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Signals Confirm M</label>
            <Input type="number" step="1" name="signals_v1_confirm_m" value={Number(formState.signals_v1_confirm_m ?? 3)} onChange={handleChange} />
          </div>

          <div className="col-span-2 pt-2">
            <details className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <summary className="cursor-pointer select-none text-sm font-semibold text-slate-700">高级配置（折叠）</summary>
              <div className="grid grid-cols-2 gap-4 mt-3">
                <div className="space-y-2">
                  <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Strategy Live Trading (override)</label>
                  <select
                    value={(formState.strategy_live_trading_enabled === true) ? 'true' : (formState.strategy_live_trading_enabled === false) ? 'false' : 'inherit'}
                    onChange={handleTriBoolSelectField('strategy_live_trading_enabled')}
                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                  >
                    <option value="inherit">Inherit</option>
                    <option value="false">False</option>
                    <option value="true">True</option>
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Quant Live Trading (override)</label>
                  <select
                    value={(formState.quant_live_trading_enabled === true) ? 'true' : (formState.quant_live_trading_enabled === false) ? 'false' : 'inherit'}
                    onChange={handleTriBoolSelectField('quant_live_trading_enabled')}
                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                  >
                    <option value="inherit">Inherit</option>
                    <option value="false">False</option>
                    <option value="true">True</option>
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Strategy Exit Enabled</label>
                  <select
                    value={String(formState.strategy_exit_enabled ?? false)}
                    onChange={handleBoolSelectField('strategy_exit_enabled')}
                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                  >
                    <option value="false">False</option>
                    <option value="true">True</option>
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Regime Method</label>
                  <select 
                    name="regime_method"
                    value={String(formState.regime_method ?? 'adx_chop')}
                    onChange={handleChange}
                    className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                  >
                    <option value="adx_chop">ADX + CHOP</option>
                    <option value="adx">ADX</option>
                    <option value="chop">CHOP</option>
                  </select>
                </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">RISK Gate</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Risk Gate Enabled</label>
            <select
              value={String(formState.entry_risk_gate_enabled ?? true)}
              onChange={handleBoolSelectField('entry_risk_gate_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Long Max Risk</label>
            <Input type="number" step="0.01" name="entry_risk_gate_long_max" value={Number(formState.entry_risk_gate_long_max ?? 0.2)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Entry Short Max Risk</label>
            <Input type="number" step="0.01" name="entry_risk_gate_short_max" value={Number(formState.entry_risk_gate_short_max ?? 0.2)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Risk Gate Enabled</label>
            <select
              value={String(formState.exit_risk_gate_enabled ?? true)}
              onChange={handleBoolSelectField('exit_risk_gate_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Long Risk Threshold</label>
            <Input type="number" step="0.01" name="exit_risk_gate_long_thr" value={Number(formState.exit_risk_gate_long_thr ?? 0.5)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Short Risk Threshold</label>
            <Input type="number" step="0.01" name="exit_risk_gate_short_thr" value={Number(formState.exit_risk_gate_short_thr ?? 0.4)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Risk Cooldown (min)</label>
            <Input type="number" step="1" name="exit_risk_gate_cooldown_min" value={Number(formState.exit_risk_gate_cooldown_min ?? 30)} onChange={handleChange} />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Exit Apply Leverage To Thresholds</label>
            <select
              value={String(formState.exit_apply_leverage_to_thresholds ?? false)}
              onChange={handleBoolSelectField('exit_apply_leverage_to_thresholds')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Addon Entries</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Addon Entry Enabled</label>
            <select
              value={String(formState.addon_entry_enabled ?? false)}
              onChange={handleBoolSelectField('addon_entry_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Addon Entry Max Count</label>
            <Input type="number" step="1" name="addon_entry_max_count" value={Number(formState.addon_entry_max_count ?? 3)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Addon Entry Min Interval (sec)</label>
            <Input type="number" step="1" name="addon_entry_min_interval_sec" value={Number(formState.addon_entry_min_interval_sec ?? 3600)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Macro Addon Counter Block</label>
            <select
              value={String(formState.entry_macro_addon_block_counter ?? false)}
              onChange={handleBoolSelectField('entry_macro_addon_block_counter')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Macro BTC/ETH Hard Gate Apply To Addon</label>
            <select
              value={String(formState.entry_macro_btceth_hard_gate_apply_to_addon ?? false)}
              onChange={handleBoolSelectField('entry_macro_btceth_hard_gate_apply_to_addon')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">BTC TV Hard Gate Apply To Addon</label>
            <select
              value={String(formState.entry_btc_tv_hard_gate_apply_to_addon ?? false)}
              onChange={handleBoolSelectField('entry_btc_tv_hard_gate_apply_to_addon')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="false">False</option>
              <option value="true">True</option>
            </select>
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Correlation Filter</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Correlation Threshold</label>
            <Input type="number" step="0.01" name="correlation_threshold" value={Number(formState.correlation_threshold ?? 0.85)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Lookback (hours)</label>
            <Input type="number" step="1" name="correlation_lookback_hours" value={Number(formState.correlation_lookback_hours ?? 72)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Cache TTL (sec)</label>
            <Input type="number" step="1" name="correlation_cache_ttl_sec" value={Number(formState.correlation_cache_ttl_sec ?? 900)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Cache Bucket (sec)</label>
            <Input type="number" step="1" name="correlation_cache_bucket_sec" value={Number(formState.correlation_cache_bucket_sec ?? 300)} onChange={handleChange} />
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">BTC CORR Gate</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Enabled</label>
            <select
              value={String(formState.strategy_btc_corr_gate_enabled ?? true)}
              onChange={handleBoolSelectField('strategy_btc_corr_gate_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Threshold (enter)</label>
            <Input type="number" step="0.01" name="strategy_btc_corr_threshold" value={Number(formState.strategy_btc_corr_threshold ?? 0.7)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Hysteresis Delta</label>
            <Input type="number" step="0.01" name="strategy_btc_corr_hysteresis_delta" value={Number(formState.strategy_btc_corr_hysteresis_delta ?? 0.03)} onChange={handleChange} />
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Strategy Sub-Portfolio</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Enabled</label>
            <select
              value={String(formState.strategy_subportfolio_enabled ?? false)}
              onChange={handleBoolSelectField('strategy_subportfolio_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Init Equity (USDC)</label>
            <Input type="number" step="1" name="strategy_subportfolio_init_equity_usdc" value={Number(formState.strategy_subportfolio_init_equity_usdc ?? 100)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max DD</label>
            <Input type="number" step="0.01" name="strategy_subportfolio_max_dd" value={Number(formState.strategy_subportfolio_max_dd ?? 0.25)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max Daily Loss</label>
            <Input type="number" step="0.01" name="strategy_subportfolio_max_daily_loss" value={Number(formState.strategy_subportfolio_max_daily_loss ?? -0.05)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Max Weekly Loss</label>
            <Input type="number" step="0.01" name="strategy_subportfolio_max_weekly_loss" value={Number(formState.strategy_subportfolio_max_weekly_loss ?? -0.12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">DD Cooldown (sec)</label>
            <Input type="number" step="1" name="strategy_subportfolio_dd_cooldown_sec" value={Number(formState.strategy_subportfolio_dd_cooldown_sec ?? 21600)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Daily Cooldown (sec)</label>
            <Input type="number" step="1" name="strategy_subportfolio_daily_cooldown_sec" value={Number(formState.strategy_subportfolio_daily_cooldown_sec ?? 10800)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Weekly Cooldown (sec)</label>
            <Input type="number" step="1" name="strategy_subportfolio_weekly_cooldown_sec" value={Number(formState.strategy_subportfolio_weekly_cooldown_sec ?? 86400)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Vol Target ATR%</label>
            <Input type="number" step="0.001" name="strategy_subportfolio_vol_target_atr_pct" value={Number(formState.strategy_subportfolio_vol_target_atr_pct ?? 0.03)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Vol Scale Min</label>
            <Input type="number" step="0.01" name="strategy_subportfolio_vol_scale_min" value={Number(formState.strategy_subportfolio_vol_scale_min ?? 0.25)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Vol Scale Max</label>
            <Input type="number" step="0.01" name="strategy_subportfolio_vol_scale_max" value={Number(formState.strategy_subportfolio_vol_scale_max ?? 4)} onChange={handleChange} />
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Strategy Reward & Weights</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Enabled</label>
            <select
              value={String(formState.strategy_reward_enabled ?? true)}
              onChange={handleBoolSelectField('strategy_reward_enabled')}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Window (trades)</label>
            <Input type="number" step="1" name="strategy_reward_window" value={Number(formState.strategy_reward_window ?? 60)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PF Up</label>
            <Input type="number" step="0.01" name="strategy_reward_pf_up" value={Number(formState.strategy_reward_pf_up ?? 1.2)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">PF Down</label>
            <Input type="number" step="0.01" name="strategy_reward_pf_down" value={Number(formState.strategy_reward_pf_down ?? 0.9)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">MaxDD Up</label>
            <Input type="number" step="0.01" name="strategy_reward_maxdd_up" value={Number(formState.strategy_reward_maxdd_up ?? 0.12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">MaxDD Down</label>
            <Input type="number" step="0.01" name="strategy_reward_maxdd_down" value={Number(formState.strategy_reward_maxdd_down ?? 0.2)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Step Up</label>
            <Input type="number" step="0.01" name="strategy_reward_step_up" value={Number(formState.strategy_reward_step_up ?? 0.05)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Step Down</label>
            <Input type="number" step="0.01" name="strategy_reward_step_down" value={Number(formState.strategy_reward_step_down ?? 0.07)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Weight Floor</label>
            <Input type="number" step="0.01" name="strategy_weight_floor" value={Number(formState.strategy_weight_floor ?? 0.25)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Weight Cap</label>
            <Input type="number" step="0.01" name="strategy_weight_cap" value={Number(formState.strategy_weight_cap ?? 2.0)} onChange={handleChange} />
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Labeling & Weighting</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Label Horizon (hours)</label>
            <Input type="number" step="1" name="label_horizon_hours" value={Number(formState.label_horizon_hours ?? 12)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Label Mode</label>
            <select
              name="label_mode"
              value={String(formState.label_mode ?? 'tk')}
              onChange={handleChange}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="tk">T+K</option>
              <option value="simple">Simple</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Return Clip (abs)</label>
            <Input type="number" step="0.01" name="return_clip_abs" value={Number(formState.return_clip_abs ?? 0.5)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Time Decay</label>
            <Input type="number" step="0.001" name="weight_time_decay" value={Number(formState.weight_time_decay ?? 0.01)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Target ATR% for Weight</label>
            <Input type="number" step="0.001" name="weight_target_atr_pct" value={Number(formState.weight_target_atr_pct ?? 0.03)} onChange={handleChange} />
          </div>

          <div className="col-span-2 text-sm font-semibold text-slate-700 pt-2">Scaling & Thresholds</div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Scaler Type</label>
            <select
              name="scaler_type"
              value={String(formState.scaler_type ?? 'robust')}
              onChange={handleChange}
              className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            >
              <option value="robust">Robust</option>
              <option value="standard">Standard</option>
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Online Scaler Window</label>
            <Input type="number" step="1" name="online_scaler_window" value={Number(formState.online_scaler_window ?? 2000)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Threshold Fit Window</label>
            <Input type="number" step="1" name="threshold_fit_window" value={Number(formState.threshold_fit_window ?? 1000)} onChange={handleChange} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Threshold TTL (min)</label>
            <Input type="number" step="1" name="threshold_ttl_minutes" value={Number(formState.threshold_ttl_minutes ?? 360)} onChange={handleChange} />
          </div>
              </div>
            </details>
          </div>
              </div>
            </div>
          ) : null}

          {needsConfirmLive ? (
            <div className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={confirmLive}
                onChange={(e) => setConfirmLive(e.target.checked)}
              />
              <span>Confirm live trading (required to save and execute)</span>
            </div>
          ) : null}

        <div className="mt-6 border-t pt-4">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-700">Manual Orders (Hyperliquid)</div>
            <div className="text-xs text-slate-500">
              {formState.dry_run ? 'Dry Run' : ((formState.live_trading_enabled ?? false) ? 'Live Enabled' : 'Live Disabled')}
              {hlPingData?.ok && hlPingData.btc_mid != null ? ` · HL ${hlPingData.trading_enabled ? 'enabled' : 'disabled'}` : ''}
            </div>
          </div>

          {hlPingData && !hlPingData.btc_mid && hlPingData.error && String(hlPingData.error).includes('hyperliquid_sdk_unavailable') && (
            <div className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              Hyperliquid SDK 未安装，仅禁用实盘下单，不影响本地回测与 Dashboard 浏览。
            </div>
          )}

          <div className="grid grid-cols-2 gap-4 mt-3">
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Coin</label>
              <Input value={hlCoin} onChange={(e) => setHlCoin(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Side</label>
              <select
                value={hlSide}
                onChange={(e) => setHlSide(e.target.value === 'short' ? 'short' : 'long')}
                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
              >
                <option value="long">Long</option>
                <option value="short">Short</option>
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Notional (USDC)</label>
              <Input
                type="number"
                step="0.1"
                value={hlNotionalUsdc}
                onChange={(e) => setHlNotionalUsdc(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Slippage</label>
              <Input
                type="number"
                step="0.001"
                value={hlSlippage}
                onChange={(e) => setHlSlippage(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Leverage</label>
              <Input
                type="number"
                step="1"
                min={1}
                value={hlLeverage}
                onChange={(e) => setHlLeverage(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Margin</label>
              <select
                value={hlIsCross ? 'cross' : 'isolated'}
                onChange={(e) => setHlIsCross(e.target.value === 'cross')}
                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
              >
                <option value="cross">Cross</option>
                <option value="isolated">Isolated</option>
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Limit Px (optional)</label>
              <Input
                placeholder="empty = market"
                value={hlPx}
                onChange={(e) => setHlPx(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Close Sz (optional)</label>
              <Input
                placeholder="empty = close all"
                value={hlCloseSz}
                onChange={(e) => setHlCloseSz(e.target.value)}
              />
            </div>
          </div>

          <div className="mt-4 grid grid-cols-4 gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setHlResult('');
                hlSetLeverageMutation.mutate({
                  coin: hlCoin,
                  leverage: hlLeverage,
                  is_cross: hlIsCross,
                  execute: liveExecute,
                  confirm_execute: liveExecute ? confirmLive : false,
                });
              }}
              disabled={hlSetLeverageMutation.isPending || liveActionBlocked}
            >
              Set Lev
            </Button>
            <Button
              onClick={() => {
                setHlResult('');
                hlOpenMutation.mutate({
                  coin: hlCoin,
                  side: hlSide,
                  notional_usdc: hlNotionalUsdc,
                  slippage: hlSlippage,
                  px: parsedPx,
                  leverage: hlLeverage,
                  is_cross: hlIsCross,
                  execute: liveExecute,
                  confirm_execute: liveExecute ? confirmLive : false,
                });
              }}
              disabled={hlOpenMutation.isPending || liveActionBlocked}
            >
              Open
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setHlResult('');
                hlCloseMutation.mutate({
                  coin: hlCoin,
                  side: hlSide,
                  sz: parsedCloseSz,
                  slippage: hlSlippage,
                  px: parsedPx,
                  execute: liveExecute,
                  confirm_execute: liveExecute ? confirmLive : false,
                });
              }}
              disabled={hlCloseMutation.isPending || liveActionBlocked}
            >
              Close
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setHlResult('');
                hlCancelAllMutation.mutate({
                  coin: hlCoin,
                  execute: liveExecute,
                  confirm_execute: liveExecute ? confirmLive : false,
                });
              }}
              disabled={hlCancelAllMutation.isPending || liveActionBlocked}
            >
              Cancel All
            </Button>
          </div>

          {hlResult ? (
            <div className="mt-3 text-xs font-mono text-slate-600 break-all">{hlResult}</div>
          ) : null}
        </div>

        <div className="mt-6 border-t pt-4">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-700">Manual Orders (Aster)</div>
            <div className="text-xs text-slate-500">
              {formState.dry_run ? 'Dry Run' : ((formState.live_trading_enabled ?? false) ? 'Live Enabled' : 'Live Disabled')}
              {asterPingData?.ok ? ` · Aster ${asterPingData.trading_enabled ? 'enabled' : 'disabled'}` : ''}
            </div>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setLivePreflightResult('');
                livePreflightMutation.mutate();
              }}
              disabled={livePreflightMutation.isPending}
            >
              Live Preflight
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setAsPreflight('');
                asPreflightMutation.mutate({
                  coin: asCoin,
                  notional_usdt: Number(asNotionalUsdc || 0),
                });
              }}
              disabled={asPreflightMutation.isPending}
            >
              Aster Preflight
            </Button>
          </div>

          {livePreflightResult ? (
            <div className="mt-2 text-xs font-mono text-slate-600 break-all">{livePreflightResult}</div>
          ) : null}

          {asPreflight ? (
            <div className="mt-2 text-xs font-mono text-slate-600 break-all">{asPreflight}</div>
          ) : null}

          <div className="mt-3 rounded border border-slate-200 bg-white p-3">
            <div className="text-sm font-semibold text-slate-700">Batch Rounds</div>
            <div className="mt-1 text-xs text-slate-500">Format: 50@3 (USDT@Notional, leverage), separated by newline or comma</div>
            <textarea
              value={asBatchText}
              onChange={(e) => setAsBatchText(e.target.value)}
              className="mt-2 w-full min-h-[88px] rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={runAsterBatchPreflight} disabled={asBatchRunning}>
                Batch Preflight
              </Button>
              <Button type="button" onClick={runAsterBatchOpen} disabled={asBatchRunning || liveActionBlocked}>
                Batch Open
              </Button>
            </div>
            {asBatchResult ? (
              <div className="mt-2 text-xs font-mono text-slate-600 break-all">{asBatchResult}</div>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-4 mt-3">
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Coin</label>
              <Input value={asCoin} onChange={(e) => setAsCoin(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Side</label>
              <select
                value={asSide}
                onChange={(e) => setAsSide(e.target.value as 'long' | 'short')}
                className="flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
              >
                <option value="long">Long</option>
                <option value="short">Short</option>
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Notional (USDT)</label>
              <Input
                type="number"
                step="0.1"
                min={1}
                value={Number(asNotionalUsdc)}
                onChange={(e) => setAsNotionalUsdc(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Leverage</label>
              <Input
                type="number"
                step="1"
                min={1}
                value={Number(asLeverage)}
                onChange={(e) => setAsLeverage(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">Close Size (optional)</label>
              <Input value={asCloseSz} onChange={(e) => setAsCloseSz(e.target.value)} placeholder="leave empty = close all" />
            </div>
            <div className="col-span-2 flex flex-wrap items-center gap-3 text-sm text-slate-700">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={asIgnoreCooldown} onChange={(e) => setAsIgnoreCooldown(e.target.checked)} />
                Ignore Cooldown
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={asAutoBumpToMin} onChange={(e) => setAsAutoBumpToMin(e.target.checked)} />
                Auto bump to min
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={asConfirmBump} onChange={(e) => setAsConfirmBump(e.target.checked)} />
                Confirm bump
              </label>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              onClick={async () => {
                setAsResult('');

                const requestedNotional = Number(asNotionalUsdc || 0);
                if (liveExecute) {
                  try {
                    const pf = await asterPreflight({ coin: asCoin, notional_usdt: requestedNotional });
                    const willBump = Boolean((pf as unknown as { will_bump?: unknown })?.will_bump);
                    const need = Number(
                      (pf as unknown as { required_notional_usdt?: unknown })?.required_notional_usdt ??
                      (pf as unknown as { required_notional_usdc?: unknown })?.required_notional_usdc ??
                      NaN,
                    );
                    if (willBump) {
                      if (!asAutoBumpToMin) {
                        setAsResult(`blocked: notional too small (need >= ${Number.isFinite(need) ? need.toFixed(2) : 'unknown'} USDT)`);
                        return;
                      }
                      if (!asConfirmBump) {
                        setAsResult(`blocked: will bump to >= ${Number.isFinite(need) ? need.toFixed(2) : 'unknown'} USDT; enable Confirm bump or raise notional`);
                        return;
                      }
                    }
                  } catch (err) {
                    const msg = getErrorMessage(err);
                    setAsResult(`preflight error: ${msg}`);
                    return;
                  }
                }

                asOpenMutation.mutate({
                  coin: asCoin,
                  side: asSide,
                  notional_usdt: requestedNotional,
                  notional_usdc: requestedNotional,
                  leverage: Number(asLeverage) || 10,
                  ignore_cooldown: asIgnoreCooldown,
                  auto_bump_to_min: asAutoBumpToMin,
                  confirm_bump: asConfirmBump,
                  max_bump_ratio: Number(formState.aster_max_bump_ratio ?? 2),
                  execute: liveExecute,
                  confirm_execute: confirmLive,
                });
              }}
              disabled={asOpenMutation.isPending}
            >
              Open
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setAsResult('');
                const v = asCloseSz.trim();
                const n = v ? Number(v) : null;
                asCloseMutation.mutate({
                  coin: asCoin,
                  sz: (n != null && Number.isFinite(n) && n > 0 ? n : null),
                  force: true,
                  execute: liveExecute,
                  confirm_execute: confirmLive,
                });
              }}
              disabled={asCloseMutation.isPending}
            >
              Close
            </Button>
          </div>

          {asResult ? (
            <div className="mt-3 text-xs font-mono text-slate-600 break-all">{asResult}</div>
          ) : null}
        </div>
        
          <div className="mt-2">
            {lastSaveVerify ? (
              <div className="mb-2 text-xs font-mono text-slate-600 break-all">{lastSaveVerify}</div>
            ) : null}
            <Button
              className="w-full"
              onClick={() => {
                const extra = (needsConfirmLive && confirmLive) ? { confirm_live: true } : {};
                const payload = { ...patch, ...extra };
                setLastSavePayload(payload);
                mutation.mutate(payload, {
                  onSuccess: () => setPatch({}),
                })
              }}
              disabled={saveDisabled}
            >
              <Save size={16} className="mr-2" />
              {mutation.isPending ? 'Saving...' : 'Update Config'}
            </Button>
          </div>
        </div>
        )}
      </CardContent>
    </Card>
  );
};
