'use client';

import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKey, queryStaleTime } from '@/lib/query-keys';
import { venue, type VenueHealth } from '@/lib/venue-client';
import {
  V3Card, V3Button, V3Badge, V3StatusDot, IconRefresh,
} from '@/components';

// 交易场所账户（51 OKX CLI 用户 venue）
// 凭证由「用户交易 API」面板写入 51 runtime/user_venue，本系统不回传明文。
function friendlyError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  if (/requires api credentials|configure okx_api_key/i.test(message)) {
    return '用户交易 API 未配置：请在下方「用户交易 API」面板填写并验证后重试。';
  }
  if (/bridge_unreachable|bridge_token_missing/i.test(message)) {
    return '本地 51 bridge 未启动：请在 51-OKX CLI 系统 下执行 `python3 -m okx_venue.server`。';
  }
  return message;
}

export function VenueAccountPanel() {
  const queryClient = useQueryClient();
  const [phrase, setPhrase] = useState('');
  const [ttl, setTtl] = useState(1800);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const healthQuery = useQuery({
    queryKey: queryKey('settings', 'venue-health'),
    queryFn: () => venue.health(),
    staleTime: queryStaleTime('settings'),
    retry: false,
    refetchInterval: 15000,
  });

  const accountQuery = useQuery({
    queryKey: queryKey('settings', 'venue-account'),
    queryFn: async () => {
      const [balance, positions] = await Promise.all([venue.balance('USDT'), venue.positions()]);
      return { balance, positions };
    },
    staleTime: queryStaleTime('settings'),
    retry: false,
    refetchInterval: 30000,
  });

  const auditQuery = useQuery({
    queryKey: queryKey('settings', 'venue-audit'),
    queryFn: () => venue.audit(5),
    staleTime: queryStaleTime('settings'),
    retry: false,
  });

  const health: VenueHealth | undefined = healthQuery.data;
  const live = health?.live;
  const accountError = accountQuery.error ? friendlyError(accountQuery.error) : null;
  const healthError = healthQuery.error ? friendlyError(healthQuery.error) : null;

  const refresh = () => {
    setActionError(null);
    void healthQuery.refetch();
    void accountQuery.refetch();
    void auditQuery.refetch();
  };

  const handleUnlock = async () => {
    setActionError(null);
    if (!phrase.trim()) {
      setActionError('请输入确认短语');
      return;
    }
    setBusy(true);
    try {
      await venue.unlockLive(phrase.trim(), ttl);
      setPhrase('');
      await queryClient.invalidateQueries({ queryKey: queryKey('settings', 'venue-health') });
    } catch (err) {
      setActionError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  const handleLock = async () => {
    setActionError(null);
    setBusy(true);
    try {
      await venue.lockLive();
      await queryClient.invalidateQueries({ queryKey: queryKey('settings', 'venue-health') });
    } catch (err) {
      setActionError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  const inputCls =
    'w-full bg-gray-900/60 border border-gray-700/50 rounded-md px-2 py-1.5 text-xs text-gray-200';

  return (
    <V3Card
      title="交易场所账户"
      subtitle="51 OKX CLI 用户 venue · 与后端自链路隔离"
      actions={
        <V3Button
          variant="ghost"
          size="sm"
          onClick={refresh}
          loading={healthQuery.isFetching || accountQuery.isFetching}
          icon={<IconRefresh className="w-3.5 h-3.5" />}
        >
          连接测试
        </V3Button>
      }
      padding="sm"
    >
      {(actionError || healthError) && (
        <div className="mb-2 text-[11px] text-red-400 px-2 py-1 bg-red-900/20 rounded">
          {actionError || healthError}
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap mb-2.5">
        <div className="flex items-center gap-1.5">
          <V3StatusDot status={health ? 'success' : 'error'} />
          <span className="text-[11px] text-gray-300">
            {health ? 'Bridge 已连接' : 'Bridge 未连接'}
          </span>
        </div>
        {health && (
          <>
            <V3Badge variant="default">profile: {health.config.profile}</V3Badge>
            <V3Badge variant={health.effective_mode === 'live' ? 'danger' : 'default'}>
              {health.effective_mode === 'live' ? '实盘环境' : 'demo 模式'}
            </V3Badge>
            <V3Badge variant="default">单笔上限 {health.max_order_size}</V3Badge>
          </>
        )}
      </div>

      <p className="text-[10px] text-gray-500 leading-relaxed mb-2.5">
        {health?.credentials.configured ? (
          <>
            用户 API：<span className="font-mono">{health.credentials.api_key_hint}</span>
            （权限 {health.credentials.permissions || '未知'}）。凭证只在 51 用户 venue 的子进程中
            以环境变量注入，不写 <span className="font-mono">~/.okx</span>、不进后端 22 配置。
          </>
        ) : (
          '尚未配置用户交易 API。请在下方「用户交易 API」中填写，作为前端策略的执行路径；后端自有链路仍走 22。'
        )}
      </p>

      <div className="grid grid-cols-2 gap-2 mb-2.5">
        <div className="px-2 py-1.5 rounded bg-gray-800/20 border border-gray-700/20">
          <div className="text-[10px] text-gray-500">可用余额 (USDT)</div>
          <div className="text-sm text-gray-200 font-medium">
            {accountQuery.data ? accountQuery.data.balance.balance.toLocaleString() : '—'}
          </div>
        </div>
        <div className="px-2 py-1.5 rounded bg-gray-800/20 border border-gray-700/20">
          <div className="text-[10px] text-gray-500">持仓数</div>
          <div className="text-sm text-gray-200 font-medium">
            {accountQuery.data ? accountQuery.data.positions.count : '—'}
          </div>
        </div>
      </div>

      {accountError && (
        <div className="mb-2.5 text-[11px] text-amber-400 px-2 py-1 bg-amber-900/20 rounded">
          {accountError}
        </div>
      )}

      <div className="p-2 rounded-lg bg-gray-800/30 border border-gray-700/30 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-gray-300">
            实盘解锁 {live?.unlocked ? `（剩余 ${live.expires_in_s}s）` : ''}
          </span>
          {live?.unlocked && (
            <V3Button variant="danger" size="sm" onClick={handleLock} loading={busy}>
              立即锁定
            </V3Button>
          )}
        </div>
        {!live?.unlocked && (
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              placeholder="输入 UNLOCK LIVE TRADING"
              className={`${inputCls} font-mono`}
              autoComplete="off"
            />
            <select
              value={ttl}
              onChange={(e) => setTtl(Number(e.target.value))}
              className={`${inputCls} w-24`}
            >
              <option value={900}>15 分钟</option>
              <option value={1800}>30 分钟</option>
              <option value={3600}>60 分钟</option>
            </select>
            <V3Button variant="secondary" size="sm" onClick={handleUnlock} loading={busy}>
              解锁
            </V3Button>
          </div>
        )}
      </div>

      {(auditQuery.data?.records?.length ?? 0) > 0 && (
        <div className="mt-2.5">
          <div className="text-[10px] text-gray-500 mb-1">最近审计</div>
          <div className="space-y-1">
            {auditQuery.data!.records.map((record, index) => (
              <div
                key={`${record.trace_id || index}-${index}`}
                className="flex items-center justify-between text-[10px] text-gray-400 px-2 py-1 rounded bg-gray-800/20"
              >
                <span className="font-mono truncate max-w-[160px]">{record.operation}</span>
                <span className={record.ok ? 'text-emerald-400' : 'text-red-400'}>
                  {record.ok ? 'ok' : record.error_code || 'fail'}
                </span>
                <span className="text-gray-600">{record.mode}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </V3Card>
  );
}

export default VenueAccountPanel;
