'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useThreeScreensStore } from '@/stores';
import { Screen1Panel } from '@/components/features/three-screens/Screen1Panel';
import { Screen2Panel } from '@/components/features/three-screens/Screen2Panel';
import { Screen3Panel } from '@/components/features/three-screens/Screen3Panel';
import { PipelineView } from '@/components/features/three-screens/PipelineView';
import { V3Card, V3Badge, V3StatusDot } from '@/components';
import { ThreeScreensAPI } from '@/lib/three-screens-api';
import { mapScreen1, mapScreen2, mapScreen3 } from '@/lib/three-screens-mapper';

type TabKey = 'overview' | 'screen1' | 'screen2' | 'screen3' | 'pipeline';

const SYMBOLS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'] as const;

// === 分层轮询间隔（与后端缓存对齐，趋势策略不需要高频）===
// 后端缓存：trend-screen 60s, v4-wave-strategy 60s, data-driven-screens 无缓存
// 后端 _bg_refresh_screen 180s, _bg_refresh_token_signals 300s
// 前端间隔 > 后端缓存，避免每次触发重算
const TREND_INTERVAL_MS = 120_000;       // 2 分钟（战略层：周线/日线趋势变化慢）
const WAVE_INTERVAL_MS = 120_000;        // 2 分钟（战术层：与 trend 错开 60s）
const DATA_DRIVEN_INTERVAL_MS = 300_000; // 5 分钟（基本面/多维数据变化最慢）
const WAVE_INITIAL_DELAY_MS = 60_000;     // wave 错峰 60s 启动
const DATA_DRIVEN_INITIAL_DELAY_MS = 120_000; // data-driven 错峰 120s 启动
const MAX_BACKOFF_MS = 600_000;          // 失败 backoff 封顶 10 分钟

interface ApiStatus {
  loading: boolean;
  error: string | null;
  lastUpdated: number | null;
  failStreak: number;
}

const initialStatus: ApiStatus = {
  loading: false,
  error: null,
  lastUpdated: null,
  failStreak: 0,
};

function nextBackoff(streak: number, baseMs: number): number {
  // 指数退避：base * 2^min(streak, 4)，封顶 MAX_BACKOFF_MS
  const factor = Math.pow(2, Math.min(streak, 4));
  return Math.min(baseMs * factor, MAX_BACKOFF_MS);
}

export default function ThreeScreensPage() {
  const { screen1, screen2, screen3, propagationStatus,
          setScreen1, setScreen2, setScreen3 } = useThreeScreensStore();
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [symbol, setSymbol] = useState<string>('BTC');

  // 每个 API 独立状态（失败不擦旧数据，独立显示）
  const [trendStatus, setTrendStatus] = useState<ApiStatus>(initialStatus);
  const [waveStatus, setWaveStatus] = useState<ApiStatus>(initialStatus);
  const [dataDrivenStatus, setDataDrivenStatus] = useState<ApiStatus>(initialStatus);

  const trendFailRef = useRef(0);
  const waveFailRef = useRef(0);
  const dataDrivenFailRef = useRef(0);

  // === Trend-screen 轮询（Screen1 战略层，2 分钟）===
  const fetchTrend = useCallback(async (sym: string) => {
    setTrendStatus(s => ({ ...s, loading: true, error: null }));
    try {
      const trend = await ThreeScreensAPI.fetchTrendScreen(sym);
      // 只更新 screen1，不传空 wave 避免覆盖 screen2/3
      const screen1Data = mapScreen1(trend, null);
      setScreen1(screen1Data);
      trendFailRef.current = 0;
      setTrendStatus({ loading: false, error: null, lastUpdated: Date.now(), failStreak: 0 });
    } catch (e: any) {
      const streak = trendFailRef.current + 1;
      trendFailRef.current = streak;
      setTrendStatus(s => ({
        ...s,
        loading: false,
        error: e?.message || String(e),
        failStreak: streak,
        // 失败不擦 lastUpdated，保留上次成功时间显示
      }));
    }
  }, [setScreen1]);

  // === V4-wave-strategy 轮询（Screen2/3 战术执行层，2 分钟，错峰 60s）===
  const fetchWave = useCallback(async (sym: string) => {
    setWaveStatus(s => ({ ...s, loading: true, error: null }));
    try {
      const wave = await ThreeScreensAPI.fetchV4WaveStrategy(sym);
      // 用独立 mapper 只更新 screen2/3，不传空 trend 避免覆盖 screen1
      setScreen2(mapScreen2(wave));
      setScreen3(mapScreen3(wave));
      waveFailRef.current = 0;
      setWaveStatus({ loading: false, error: null, lastUpdated: Date.now(), failStreak: 0 });
    } catch (e: any) {
      const streak = waveFailRef.current + 1;
      waveFailRef.current = streak;
      setWaveStatus(s => ({
        ...s,
        loading: false,
        error: e?.message || String(e),
        failStreak: streak,
      }));
    }
  }, [setScreen2, setScreen3]);

  // === Data-driven-screens 轮询（多维基本面，5 分钟，错峰 120s）===
  const fetchDataDriven = useCallback(async (sym: string) => {
    setDataDrivenStatus(s => ({ ...s, loading: true, error: null }));
    try {
      const dataDriven = await ThreeScreensAPI.fetchDataDrivenScreens(sym);
      // data-driven 包含 screen1 的基本面扩展字段，合并到现有 screen1
      if (dataDriven?.screen1) {
        const prev = useThreeScreensStore.getState().screen1;
        if (prev) {
          setScreen1({
            ...prev,
            fundamentalDirection: dataDriven.screen1.fundamental_direction as any,
            fundamentalConfidence: dataDriven.screen1.fundamental_confidence,
            fundamentalDimensions: dataDriven.screen1.fundamental_dimensions,
            fusionConsistent: dataDriven.screen1.fusion?.consistent,
            fusionReason: dataDriven.screen1.fusion?.reason,
          });
        }
      }
      dataDrivenFailRef.current = 0;
      setDataDrivenStatus({ loading: false, error: null, lastUpdated: Date.now(), failStreak: 0 });
    } catch (e: any) {
      const streak = dataDrivenFailRef.current + 1;
      dataDrivenFailRef.current = streak;
      setDataDrivenStatus(s => ({
        ...s,
        loading: false,
        error: e?.message || String(e),
        failStreak: streak,
      }));
    }
  }, [setScreen1]);

  // === 三个独立轮询 useEffect（带失败 backoff）===
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const runWithBackoff = async (sym: string) => {
      await fetchTrend(sym);
      if (!active) return;
      const base = TREND_INTERVAL_MS;
      const delay = trendFailRef.current > 0
        ? nextBackoff(trendFailRef.current, base)
        : base;
      timer = setTimeout(() => runWithBackoff(sym), delay);
    };

    runWithBackoff(symbol);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [symbol, fetchTrend]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const runWithBackoff = async (sym: string) => {
      await fetchWave(sym);
      if (!active) return;
      const base = WAVE_INTERVAL_MS;
      const delay = waveFailRef.current > 0
        ? nextBackoff(waveFailRef.current, base)
        : base;
      timer = setTimeout(() => runWithBackoff(sym), delay);
    };

    // 错峰：WAVE_INITIAL_DELAY_MS 后启轮
    timer = setTimeout(() => runWithBackoff(symbol), WAVE_INITIAL_DELAY_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [symbol, fetchWave]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const runWithBackoff = async (sym: string) => {
      await fetchDataDriven(sym);
      if (!active) return;
      const base = DATA_DRIVEN_INTERVAL_MS;
      const delay = dataDrivenFailRef.current > 0
        ? nextBackoff(dataDrivenFailRef.current, base)
        : base;
      timer = setTimeout(() => runWithBackoff(sym), delay);
    };

    // 错峰：DATA_DRIVEN_INITIAL_DELAY_MS 后启轮
    timer = setTimeout(() => runWithBackoff(symbol), DATA_DRIVEN_INITIAL_DELAY_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [symbol, fetchDataDriven]);

  const handleManualRefresh = useCallback(() => {
    fetchTrend(symbol);
    fetchWave(symbol);
    fetchDataDriven(symbol);
  }, [fetchTrend, fetchWave, fetchDataDriven, symbol]);

  // 总状态汇总
  const anyLoading = trendStatus.loading || waveStatus.loading || dataDrivenStatus.loading;
  const allErrors = [trendStatus.error, waveStatus.error, dataDrivenStatus.error].filter(Boolean);
  const anyError = allErrors.length > 0;
  const lastUpdated = [trendStatus.lastUpdated, waveStatus.lastUpdated, dataDrivenStatus.lastUpdated]
    .filter(Boolean)
    .reduce((max, t) => ((t as number) > (max as number) ? t : max), 0) || null;

  const tabs: Array<{ key: TabKey; label: string; status?: string }> = [
    { key: 'overview', label: '总览' },
    { key: 'screen1', label: 'Screen 1 · 战略', status: screen1 ? '有数据' : '待输入' },
    { key: 'screen2', label: 'Screen 2 · 战术', status: screen2 ? '有数据' : '待 Screen1' },
    { key: 'screen3', label: 'Screen 3 · 执行', status: screen3 ? '运行中' : '待 Screen2' },
    { key: 'pipeline', label: 'Pipeline' },
  ];

  const getPropagationLabel = () => {
    switch (propagationStatus) {
      case 's1_complete': return 'Screen1 完成';
      case 's2_complete': return 'Screen2 完成';
      case 's3_running': return 'Screen3 执行中';
      case 'complete': return '全部完成';
      default: return '等待输入';
    }
  };

  const getPropagationVariant = () => {
    switch (propagationStatus) {
      case 's3_running': return 'warning' as const;
      case 'complete': return 'success' as const;
      case 's1_complete':
      case 's2_complete': return 'info' as const;
      default: return 'default' as const;
    }
  };

  // 单 API 状态指示器
  const ApiStatusBadge = ({ name, status, intervalMs }: { name: string; status: ApiStatus; intervalMs: number }) => {
    const variant = status.error ? (status.failStreak >= 3 ? 'danger' : 'warning') : (status.lastUpdated ? 'success' : 'default');
    const tip = status.error
      ? `${name} 失败×${status.failStreak}（backoff ${Math.round(nextBackoff(status.failStreak, intervalMs) / 1000)}s）`
      : status.lastUpdated
        ? `${name} 更新于 ${new Date(status.lastUpdated).toLocaleTimeString('zh-CN')}`
        : `${name} 待加载`;
    return (
      <span className="inline-flex items-center gap-1" title={tip}>
        <V3StatusDot
          status={status.error ? (status.failStreak >= 3 ? 'error' : 'warning') : (status.lastUpdated ? 'success' : 'idle')}
          size="sm"
          pulse={status.loading}
        />
        <span className="text-[10px] text-slate-500">{name}</span>
      </span>
    );
  };

  return (
    <div className="p-4 h-full flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-slate-200">三屏交易系统</h1>
          {/* 币种切换 */}
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            disabled={anyLoading}
            className="text-xs bg-slate-800/60 border border-slate-700/40 rounded px-2 py-1 text-slate-200 disabled:opacity-50"
          >
            {SYMBOLS.map(s => <option key={s} value={s}>{s}/USDT</option>)}
          </select>
          <V3Badge variant={getPropagationVariant()}>
            {getPropagationLabel()}
          </V3Badge>
          {anyLoading && (
            <V3Badge variant="info" dot pulse>加载中</V3Badge>
          )}
          {anyError && (
            <V3Badge variant="danger" dot>部分异常</V3Badge>
          )}
          {lastUpdated && !anyLoading && !anyError && (
            <span className="text-[10px] text-slate-500">
              最近更新 {new Date(lastUpdated).toLocaleTimeString('zh-CN')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {screen1?.directionAnchor && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">方向锚定:</span>
              <V3Badge variant={screen1.directionAnchor === 'bullish' ? 'success' : screen1.directionAnchor === 'bearish' ? 'danger' : 'default'}>
                {screen1.directionAnchor === 'bullish' ? '看多' : screen1.directionAnchor === 'bearish' ? '看空' : '中性'}
              </V3Badge>
            </div>
          )}
          <button
            onClick={handleManualRefresh}
            disabled={anyLoading}
            className="text-xs px-2 py-1 rounded border border-slate-700/40 hover:border-blue-500/40 text-slate-300 hover:text-blue-400 disabled:opacity-50"
          >
            {anyLoading ? '⏳ 加载中' : '⟳ 刷新全部'}
          </button>
        </div>
      </div>

      {/* API 状态条 + 错误提示 */}
      {(anyError || trendStatus.lastUpdated || waveStatus.lastUpdated || dataDrivenStatus.lastUpdated) && (
        <div className="mb-3 px-3 py-2 bg-slate-900/40 border border-slate-700/30 rounded flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-4 flex-wrap">
            <ApiStatusBadge name="战略层 trend" status={trendStatus} intervalMs={TREND_INTERVAL_MS} />
            <ApiStatusBadge name="战术层 wave" status={waveStatus} intervalMs={WAVE_INTERVAL_MS} />
            <ApiStatusBadge name="基本面 driven" status={dataDrivenStatus} intervalMs={DATA_DRIVEN_INTERVAL_MS} />
          </div>
          <div className="text-[10px] text-slate-600">
            轮询: 战略 2min · 战术 2min · 基本面 5min · 失败指数退避封顶 10min
          </div>
        </div>
      )}

      {anyError && (
        <div className="mb-3 px-3 py-2 bg-red-950/30 border border-red-800/30 rounded flex items-center justify-between">
          <span className="text-xs text-red-300">⚠ 部分接口异常（旧数据保留）: {allErrors.join(' | ').slice(0, 200)}</span>
          <button onClick={() => {
            setTrendStatus(s => ({ ...s, error: null }));
            setWaveStatus(s => ({ ...s, error: null }));
            setDataDrivenStatus(s => ({ ...s, error: null }));
          }} className="text-red-400 hover:text-red-300 text-xs">×</button>
        </div>
      )}

      {/* Tab 切换 */}
      <div className="flex gap-1 mb-4 border-b border-slate-700/30 pb-0">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`
              px-3 py-2 text-xs font-medium rounded-t-lg transition-colors flex items-center gap-1.5
              ${activeTab === tab.key
                ? 'text-blue-400 bg-blue-500/10 border-b-2 border-blue-400'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/30'}
            `}
          >
            {tab.label}
            {tab.status && (
              <V3StatusDot
                status={tab.status === '有数据' ? 'success' : tab.status === '运行中' ? 'warning' : 'idle'}
                size="sm"
              />
            )}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'overview' && (
          <div className="space-y-4">
            {/* 三屏概览 */}
            <div className="grid grid-cols-3 gap-4">
              <V3Card title="Screen 1 · 战略层" padding="sm">
                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">方向锚定</span>
                    <span className="text-slate-200">
                      {screen1?.directionAnchor ? (
                        <V3Badge variant={screen1.directionAnchor === 'bullish' ? 'success' : screen1.directionAnchor === 'bearish' ? 'danger' : 'default'}>
                          {screen1.directionAnchor === 'bullish' ? '看多' : screen1.directionAnchor === 'bearish' ? '看空' : '中性'}
                        </V3Badge>
                      ) : '未设置'}
                    </span>
                  </div>
                  {screen1?.dimensions && (
                    <div className="space-y-1.5 mt-2">
                      {Object.entries(screen1.dimensions).map(([key, val]) => (
                        <div key={key} className="flex justify-between text-[10px]">
                          <span className="text-slate-500">{key}</span>
                          <span className="text-slate-300">{val.label} ({val.score})</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </V3Card>

              <V3Card title="Screen 2 · 战术层" padding="sm">
                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">方向约束</span>
                    <span className="text-slate-200">
                      {screen2?.directionConstraint ? (
                        <V3Badge variant={screen2.directionConstraint === 'bullish' ? 'success' : screen2.directionConstraint === 'bearish' ? 'danger' : 'default'}>
                          {screen2.directionConstraint === 'bullish' ? '看多' : screen2.directionConstraint === 'bearish' ? '看空' : '中性'}
                        </V3Badge>
                      ) : '待传播'}
                    </span>
                  </div>
                  {screen2?.presets && (
                    <div className="text-[10px] text-slate-500 mt-2">
                      预设策略: {screen2.presets.length} 个
                    </div>
                  )}
                  {screen2?.backtest && (
                    <div className="space-y-1 mt-2">
                      <div className="flex justify-between text-[10px]">
                        <span className="text-slate-500">胜率</span>
                        <span className="text-emerald-400">{(screen2.backtest.winRate * 100).toFixed(1)}%</span>
                      </div>
                      <div className="flex justify-between text-[10px]">
                        <span className="text-slate-500">平均 R 倍</span>
                        <span className="text-slate-300">{screen2.backtest.avgR.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between text-[10px]">
                        <span className="text-slate-500">最大回撤</span>
                        <span className="text-red-400">{(screen2.backtest.maxDD * 100).toFixed(1)}%</span>
                      </div>
                      <div className="flex justify-between text-[10px]">
                        <span className="text-slate-500">Sharpe</span>
                        <span className="text-slate-300">{screen2.backtest.sharpe.toFixed(2)}</span>
                      </div>
                    </div>
                  )}
                </div>
              </V3Card>

              <V3Card title="Screen 3 · 执行层" padding="sm">
                <div className="space-y-2">
                  {screen3?.positionState ? (
                    <>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">当前持仓</span>
                        <span className="text-slate-200">{screen3.positionState.symbol}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">方向/数量</span>
                        <span className="text-slate-200">{screen3.positionState.side} · {screen3.positionState.size}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">盈亏</span>
                        <span className={screen3.positionState.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                          {screen3.positionState.pnl >= 0 ? '+' : ''}{screen3.positionState.pnl.toFixed(2)}
                        </span>
                      </div>
                    </>
                  ) : (
                    <div className="text-xs text-slate-500">暂无持仓</div>
                  )}
                  {screen3?.monitorAlerts && screen3.monitorAlerts.length > 0 && (
                    <div className="text-[10px] text-slate-500 mt-2">
                      监控告警: {screen3.monitorAlerts.length} 条
                    </div>
                  )}
                </div>
              </V3Card>
            </div>

            {/* Pipeline 概览 */}
            <V3Card title="传播流程" padding="sm">
              <PipelineView />
            </V3Card>
          </div>
        )}
        {activeTab === 'screen1' && <Screen1Panel />}
        {activeTab === 'screen2' && (
          <Screen2Panel
            loading={waveStatus.loading}
            lastUpdated={waveStatus.lastUpdated}
          />
        )}
        {activeTab === 'screen3' && <Screen3Panel />}
        {activeTab === 'pipeline' && <PipelineView />}
      </div>
    </div>
  );
}

