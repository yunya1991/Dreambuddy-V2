'use client';

import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKey, queryStaleTime } from '@/lib/query-keys';
import { venue, type VenueCredentialsPublic } from '@/lib/venue-client';
import { ProductLockedNotice, useProductEntitlement } from '@/components/features/product/ProductGate';
import { V3Card, V3Button, V3Badge } from '@/components';

// 用户交易 API（前端策略执行路径）
// 凭证 → AES-256-GCM 落 51 runtime/user_venue → 每次调用以环境变量注入 okx CLI；
// 不写 ~/.okx/config.toml，也不进入后端 22 执行链路的任何配置。
const EMPTY_FORM = {
  api_key: '',
  secret_key: '',
  passphrase: '',
  demo: true,
  label: 'user',
};

function friendlyError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  if (/bridge_unreachable|bridge_token_missing/i.test(message)) {
    return '本地 51 bridge 未启动：请在 51-OKX CLI 系统 下执行 `python3 -m okx_venue.server`。';
  }
  if (/提现权限/.test(message)) {
    return '该 API Key 含提现权限，已拒绝保存。请重建仅含「读取 + 交易」权限的 Key。';
  }
  return message;
}

export function VenueCredentialPanel() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { entitled } = useProductEntitlement();

  const credentialsQuery = useQuery({
    queryKey: queryKey('settings', 'venue-credentials'),
    queryFn: () => venue.credentials(),
    staleTime: queryStaleTime('settings'),
    retry: false,
  });

  const current: VenueCredentialsPublic | undefined = credentialsQuery.data;
  const inputCls =
    'w-full bg-gray-900/60 border border-gray-700/50 rounded-md px-2 py-1.5 text-xs text-gray-200';

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKey('settings', 'venue-credentials') }),
      queryClient.invalidateQueries({ queryKey: queryKey('settings', 'venue-health') }),
      queryClient.invalidateQueries({ queryKey: queryKey('settings', 'venue-account') }),
    ]);
  };

  const handleSave = async () => {
    setError(null);
    setMessage(null);
    if (!form.api_key.trim() || !form.secret_key.trim() || !form.passphrase.trim()) {
      setError('API Key / Secret Key / Passphrase 均为必填');
      return;
    }
    setBusy(true);
    try {
      const saved = await venue.saveCredentials({
        api_key: form.api_key.trim(),
        secret_key: form.secret_key.trim(),
        passphrase: form.passphrase.trim(),
        demo: form.demo,
        label: form.label.trim() || 'user',
      });
      setForm((prev) => ({ ...prev, api_key: '', secret_key: '', passphrase: '' }));
      setMessage(`已保存 ${saved.api_key_hint}（权限：${saved.permissions || '未返回'}）`);
      await invalidate();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  const handleTest = async () => {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const result = await venue.testCredentials();
      setMessage(`连接成功 · ${result.mode} · 余额 ${result.balance} USDT`);
      await invalidate();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      await venue.deleteCredentials();
      setMessage('已删除用户交易 API 凭证');
      await invalidate();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  if (!entitled) {
    return (
      <V3Card
        title="用户交易 API"
        subtitle="前端策略执行路径 · 与后端 22 执行链路隔离"
        actions={<V3Badge variant="default">已锁定</V3Badge>}
        padding="sm"
      >
        <ProductLockedNotice />
      </V3Card>
    );
  }

  return (
    <V3Card
      title="用户交易 API"
      subtitle="前端策略执行路径 · 与后端 22 执行链路隔离"
      actions={
        current?.configured ? (
          <V3Badge variant={current.demo ? 'info' : 'danger'}>
            {current.demo ? '模拟盘' : '实盘'}
          </V3Badge>
        ) : (
          <V3Badge variant="default">未配置</V3Badge>
        )
      }
      padding="sm"
    >
      {error && (
        <div className="mb-2 text-[11px] text-red-400 px-2 py-1 bg-red-900/20 rounded">{error}</div>
      )}
      {message && (
        <div className="mb-2 text-[11px] text-emerald-400 px-2 py-1 bg-emerald-900/20 rounded">
          {message}
        </div>
      )}

      {current?.configured ? (
        <div className="space-y-2">
          <div className="px-2 py-1.5 rounded bg-gray-800/20 border border-gray-700/20 text-[11px] text-gray-300 space-y-1">
            <div className="flex items-center justify-between">
              <span>API Key</span>
              <span className="font-mono text-gray-400">{current.api_key_hint}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>权限</span>
              <span className="font-mono text-gray-400">{current.permissions || '未知'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>环境</span>
              <span className="text-gray-400">{current.demo ? '模拟盘' : '实盘'}</span>
            </div>
          </div>
          <p className="text-[10px] text-gray-500 leading-relaxed">
            凭证使用 AES-256-GCM 加密存放于 <span className="font-mono">51-OKX CLI 系统/runtime/user_venue</span>，
            仅在下单子进程中以环境变量注入，不回传明文、不写入后端 22 配置。
          </p>
          <div className="flex items-center justify-end gap-2">
            <V3Button variant="secondary" size="sm" onClick={handleTest} loading={busy}>
              测试连接
            </V3Button>
            <V3Button variant="danger" size="sm" onClick={handleDelete} loading={busy}>
              删除凭证
            </V3Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div className="col-span-2">
              <label className="text-[10px] text-gray-500 block mb-1">API Key</label>
              <input
                type="password"
                value={form.api_key}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder="OKX API Key（仅读取+交易权限）"
                className={`${inputCls} font-mono`}
                autoComplete="off"
              />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">Secret Key</label>
              <input
                type="password"
                value={form.secret_key}
                onChange={(e) => setForm({ ...form, secret_key: e.target.value })}
                placeholder="Secret Key"
                className={`${inputCls} font-mono`}
                autoComplete="off"
              />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">Passphrase</label>
              <input
                type="password"
                value={form.passphrase}
                onChange={(e) => setForm({ ...form, passphrase: e.target.value })}
                placeholder="Passphrase"
                className={`${inputCls} font-mono`}
                autoComplete="off"
              />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">环境</label>
              <select
                value={form.demo ? 'demo' : 'live'}
                onChange={(e) => setForm({ ...form, demo: e.target.value === 'demo' })}
                className={inputCls}
              >
                <option value="demo">模拟盘（默认）</option>
                <option value="live">实盘</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">标签</label>
              <input
                type="text"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="user"
                className={inputCls}
              />
            </div>
          </div>
          <p className="text-[10px] text-gray-500 leading-relaxed">
            保存前会探测 Key 权限：包含「提现」权限的 Key 将被拒绝。凭证仅用于前端策略执行路径，
            不进入后端 22 执行链路。
          </p>
          <div className="flex items-center justify-end">
            <V3Button variant="primary" size="sm" onClick={handleSave} loading={busy}>
              验证并保存
            </V3Button>
          </div>
        </div>
      )}
    </V3Card>
  );
}

export default VenueCredentialPanel;
