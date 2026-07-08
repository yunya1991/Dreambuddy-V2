'use client';

import React from 'react';
import { ChatPanel } from '@/components/features/chat/ChatPanel';
import { ChainTracker } from '@/components/features/chain/ChainTracker';
import { CrossValidationPanel } from '@/components/features/chain/CrossValidationPanel';
import { V3Card, V3Badge } from '@/components';
import { useSessionStore, useChainStore, useTradingStore } from '@/stores';

export default function TradePage() {
  const { isStreaming, sLayerIntent } = useSessionStore();
  const { activeChain } = useChainStore();
  const { mode, balance, positions, signals } = useTradingStore();

  return (
    <div className="flex h-full gap-4 p-4">
      {/* 左侧：聊天面板 */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* 聊天头部 */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-200">
              {mode === 'ai_skill' ? 'AI Skill 交易' : '经典交易'}
            </h2>
            <V3Badge variant={isStreaming ? 'info' : 'default'} dot pulse={isStreaming}>
              {isStreaming ? '执行中' : '就绪'}
            </V3Badge>
            {activeChain && (
              <V3Badge variant="sacg-s">链路运行中</V3Badge>
            )}
          </div>
          {sLayerIntent && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">感知层:</span>
              <V3Badge variant="sacg-s">{sLayerIntent}</V3Badge>
            </div>
          )}
        </div>
        {/* 聊天面板 */}
        <div className="flex-1 bg-slate-900/30 rounded-xl border border-slate-700/30 overflow-hidden">
          <ChatPanel />
        </div>
      </div>

      {/* 右侧：链追踪 + 数据 */}
      <div className="w-[380px] shrink-0 overflow-y-auto space-y-3">
        {/* 链追踪 */}
        <V3Card title="链路追踪" padding="sm">
          <ChainTracker />
        </V3Card>

        {/* 交叉验证 */}
        <CrossValidationPanel />

        {/* 余额概览 */}
        {balance && (
          <V3Card title="账户余额" padding="sm">
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">总权益</span>
                <span className="text-slate-200 font-medium">
                  {balance.total.toLocaleString()} {balance.currency}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">可用余额</span>
                <span className="text-slate-300">
                  {balance.available.toLocaleString()} {balance.currency}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">已用保证金</span>
                <span className="text-slate-300">
                  {balance.marginUsed.toLocaleString()} {balance.currency}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">未实现盈亏</span>
                <span className={balance.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {balance.unrealizedPnl >= 0 ? '+' : ''}
                  {balance.unrealizedPnl.toLocaleString()} {balance.currency}
                </span>
              </div>
            </div>
          </V3Card>
        )}

        {/* 持仓列表 */}
        {positions.length > 0 && (
          <V3Card title={`持仓 (${positions.length})`} padding="sm">
            <div className="space-y-2">
              {positions.map((pos, i) => (
                <div key={i} className="flex items-center justify-between px-2 py-1.5 rounded bg-slate-800/20">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-200">{pos.symbol}</span>
                    <V3Badge variant={pos.side === 'long' ? 'success' : 'danger'}>
                      {pos.side === 'long' ? '多' : '空'}
                    </V3Badge>
                    <span className="text-[10px] text-slate-500">{pos.leverage}x</span>
                  </div>
                  <span className={`text-xs ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pos.pnl >= 0 ? '+' : ''}{pos.pnl.toFixed(2)}
                    <span className="text-slate-500 ml-1">({pos.pnlPercent >= 0 ? '+' : ''}{pos.pnlPercent.toFixed(1)}%)</span>
                  </span>
                </div>
              ))}
            </div>
          </V3Card>
        )}

        {/* 最新信号 */}
        {signals.length > 0 && (
          <V3Card title={`信号 (${signals.length})`} padding="sm">
            <div className="space-y-2">
              {signals.slice(0, 5).map((sig) => (
                <div key={sig.id} className="flex items-center justify-between px-2 py-1.5 rounded bg-slate-800/20">
                  <div>
                    <span className="text-xs font-medium text-slate-200">{sig.symbol}</span>
                    <span className="text-[10px] text-slate-500 ml-2">{sig.source}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <V3Badge variant={sig.direction === 'bullish' ? 'success' : sig.direction === 'bearish' ? 'danger' : 'default'}>
                      {sig.direction === 'bullish' ? '看多' : sig.direction === 'bearish' ? '看空' : '中性'}
                    </V3Badge>
                    <span className="text-[10px] text-slate-500">{(sig.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </V3Card>
        )}
      </div>
    </div>
  );
}
