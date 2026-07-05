'use client';

import React from 'react';
import { ChatPanel } from '@/components/features/chat/ChatPanel';
import { ChainTracker } from '@/components/features/chain/ChainTracker';
import { CrossValidationPanel } from '@/components/features/chain/CrossValidationPanel';
import { V3Card } from '@/components/V3Card';
import { V3Badge } from '@/components/V3Badge';
import { V3StatusDot } from '@/components/V3StatusDot';
import { useSessionStore } from '@/stores';
import { useChainStore } from '@/stores';
import { useTradingStore } from '@/stores';
import { useApiConfigStore } from '@/stores';

export default function TradePage() {
  const { isStreaming, lastIntent } = useSessionStore();
  const { activeChain } = useChainStore();
  const { mode, aiSkill } = useTradingStore();
  const { profile } = useApiConfigStore();

  return (
    <div className="flex h-full gap-4 p-4">
      {/* 左侧：聊天面板 */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* 聊天头部 */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-gray-100">AI Skill 交易</h2>
            <V3Badge variant={isStreaming ? 'info' : 'default'} dot pulse={isStreaming}>
              {isStreaming ? '执行中' : '就绪'}
            </V3Badge>
          </div>
          {lastIntent && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">意图:</span>
              <V3Badge variant="sacg-s">{lastIntent.intent}</V3Badge>
              <span className="text-[10px] text-gray-500">{(lastIntent.confidence * 100).toFixed(0)}%</span>
            </div>
          )}
        </div>
        {/* 聊天面板 */}
        <div className="flex-1 bg-gray-900/30 rounded-xl border border-gray-700/30 overflow-hidden">
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
        {aiSkill.balance && (
          <V3Card title="账户余额" padding="sm">
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">总权益</span>
                <span className="text-gray-200 font-medium">{aiSkill.balance.totalEquity.toLocaleString()} USDT</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">可用余额</span>
                <span className="text-gray-300">{aiSkill.balance.availableBalance.toLocaleString()} USDT</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">未实现盈亏</span>
                <span className={aiSkill.balance.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {aiSkill.balance.unrealizedPnl >= 0 ? '+' : ''}{aiSkill.balance.unrealizedPnl.toLocaleString()} USDT
                </span>
              </div>
            </div>
          </V3Card>
        )}

        {/* 持仓列表 */}
        {aiSkill.positions.length > 0 && (
          <V3Card title={`持仓 (${aiSkill.positions.length})`} padding="sm">
            <div className="space-y-2">
              {aiSkill.positions.map((pos) => (
                <div key={pos.id} className="flex items-center justify-between px-2 py-1.5 rounded bg-gray-800/20">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-200">{pos.symbol}</span>
                    <V3Badge variant={pos.side === 'long' ? 'success' : 'danger'}>
                      {pos.side === 'long' ? '多' : '空'}
                    </V3Badge>
                  </div>
                  <span className={`text-xs ${pos.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pos.unrealizedPnl >= 0 ? '+' : ''}{pos.unrealizedPnl.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </V3Card>
        )}

        {/* 策略列表 */}
        {aiSkill.activeStrategies.length > 0 && (
          <V3Card title={`活跃策略 (${aiSkill.activeStrategies.length})`} padding="sm">
            <div className="space-y-2">
              {aiSkill.activeStrategies.map((s) => (
                <div key={s.id} className="flex items-center justify-between px-2 py-1.5 rounded bg-gray-800/20">
                  <div>
                    <span className="text-xs font-medium text-gray-200">{s.name}</span>
                    <span className="text-[10px] text-gray-500 ml-2">{s.symbol}</span>
                  </div>
                  <V3Badge variant={s.status === 'APPROVED' ? 'success' : 'default'}>{s.status}</V3Badge>
                </div>
              ))}
            </div>
          </V3Card>
        )}
      </div>
    </div>
  );
}
