'use client';

import React, { useState } from 'react';
import { useThreeScreensStore } from '@/stores';
import { Screen1Panel } from '@/components/features/three-screens/Screen1Panel';
import { Screen2Panel } from '@/components/features/three-screens/Screen2Panel';
import { Screen3Panel } from '@/components/features/three-screens/Screen3Panel';
import { PipelineView } from '@/components/features/three-screens/PipelineView';
import { V3Card, V3Badge, V3StatusDot } from '@/components';

type TabKey = 'overview' | 'screen1' | 'screen2' | 'screen3' | 'pipeline';

export default function ThreeScreensPage() {
  const { screen1, screen2, screen3, propagationStatus } = useThreeScreensStore();
  const [activeTab, setActiveTab] = useState<TabKey>('overview');

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

  return (
    <div className="p-4 h-full flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-slate-200">三屏交易系统</h1>
          <V3Badge variant="default">BTC/USDT</V3Badge>
          <V3Badge variant={getPropagationVariant()}>
            {getPropagationLabel()}
          </V3Badge>
        </div>
        {screen1?.directionAnchor && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">方向锚定:</span>
            <V3Badge variant={screen1.directionAnchor === 'bullish' ? 'success' : screen1.directionAnchor === 'bearish' ? 'danger' : 'default'}>
              {screen1.directionAnchor === 'bullish' ? '看多' : screen1.directionAnchor === 'bearish' ? '看空' : '中性'}
            </V3Badge>
          </div>
        )}
      </div>

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
        {activeTab === 'screen2' && <Screen2Panel />}
        {activeTab === 'screen3' && <Screen3Panel />}
        {activeTab === 'pipeline' && <PipelineView />}
      </div>
    </div>
  );
}
