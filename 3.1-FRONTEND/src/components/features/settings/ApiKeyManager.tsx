'use client';

import React, { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';
import {
  V3Card, V3Button, V3Badge, V3StatusDot,
  IconPlus, IconRefresh, IconClose,
} from '@/components';

interface ApiKeyEntry {
  id: string;
  category: string;
  provider: string;
  label: string;
  keyHint?: string;
  isConfigured: boolean;
  isVerified?: boolean;
  environment?: string;
  lastVerifiedAt?: string;
}

const CATEGORY_OPTIONS = [
  { value: 'EXCHANGE', label: '交易所' },
  { value: 'LLM', label: 'LLM' },
  { value: 'DATA', label: '数据源' },
];

const PROVIDER_OPTIONS: Record<string, { value: string; label: string }[]> = {
  EXCHANGE: [
    { value: 'OKX', label: 'OKX' },
    { value: 'BINANCE', label: 'Binance' },
    { value: 'BYBIT', label: 'Bybit' },
  ],
  LLM: [
    { value: 'OPENAI', label: 'OpenAI' },
    { value: 'ANTHROPIC', label: 'Anthropic' },
    { value: 'DEEPSEEK', label: 'DeepSeek' },
  ],
  DATA: [
    { value: 'COINGECKO', label: 'CoinGecko' },
    { value: 'GLASSNODE', label: 'Glassnode' },
  ],
};

interface ApiKeyForm {
  id?: string;
  category: string;
  provider: string;
  label: string;
  apiKey: string;
  secretKey: string;
  passphrase: string;
  environment: string;
  baseUrl: string;
}

function emptyForm(): ApiKeyForm {
  return {
    category: 'EXCHANGE',
    provider: 'OKX',
    label: '',
    apiKey: '',
    secretKey: '',
    passphrase: '',
    environment: 'demo',
    baseUrl: '',
  };
}

export function ApiKeyManager() {
  const [keys, setKeys] = useState<ApiKeyEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<ApiKeyForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  useEffect(() => {
    fetchKeys();
  }, []);

  const fetchKeys = async () => {
    setLoading(true);
    try {
      const data = await api.get<ApiKeyEntry[]>('/api/config/api-keys');
      setKeys(Array.isArray(data) ? data : []);
    } catch {
      // 静默处理
    } finally {
      setLoading(false);
    }
  };

  const openAddForm = () => {
    setForm(emptyForm());
    setError(null);
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setError(null);
  };

  const updateCategory = (cat: string) => {
    const providers = PROVIDER_OPTIONS[cat] || [];
    setForm(prev => ({
      ...prev,
      category: cat,
      provider: providers[0]?.value || '',
    }));
  };

  const handleSubmit = async () => {
    setError(null);
    if (!form.category || !form.provider || !form.label || !form.apiKey || !form.secretKey) {
      setError('类别、提供商、标签、API Key、Secret Key 为必填项');
      return;
    }

    setSaving(true);
    try {
      if (form.id) {
        const body: Record<string, unknown> = { id: form.id };
        if (form.apiKey) body.apiKey = form.apiKey;
        if (form.secretKey) body.secretKey = form.secretKey;
        if (form.passphrase) body.passphrase = form.passphrase;
        if (form.environment) body.environment = form.environment;
        if (form.baseUrl !== undefined) body.baseUrl = form.baseUrl;
        if (form.label) body.label = form.label;
        await api.patch('/api/config/api-keys', body);
      } else {
        await api.post('/api/config/api-keys', {
          category: form.category,
          provider: form.provider,
          label: form.label,
          apiKey: form.apiKey,
          secretKey: form.secretKey,
          passphrase: form.passphrase || undefined,
          environment: form.environment,
          baseUrl: form.baseUrl || undefined,
        });
      }
      await fetchKeys();
      closeForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/api/config/api-keys?id=${encodeURIComponent(id)}`);
      setConfirmDelete(null);
      await fetchKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
      setConfirmDelete(null);
    }
  };

  const providers = PROVIDER_OPTIONS[form.category] || [];
  const inputCls = 'w-full bg-gray-900/60 border border-gray-700/50 rounded-md px-2 py-1.5 text-xs text-gray-200';

  return (
    <V3Card
      title="API 密钥"
      subtitle="交易所 / LLM / 数据源"
      actions={
        <div className="flex items-center gap-2">
          <V3Button variant="ghost" size="sm" onClick={fetchKeys} loading={loading} icon={<IconRefresh className="w-3.5 h-3.5" />}>
            刷新
          </V3Button>
          {!formOpen && (
            <V3Button variant="primary" size="sm" onClick={openAddForm} icon={<IconPlus className="w-3.5 h-3.5" />}>
              添加
            </V3Button>
          )}
        </div>
      }
      padding="sm"
    >
      {error && (
        <div className="mb-2 text-[11px] text-red-400 px-2 py-1 bg-red-900/20 rounded">{error}</div>
      )}

      {formOpen && (
        <div className="mb-3 p-3 rounded-lg bg-gray-800/40 border border-gray-700/40 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-200">
              {form.id ? '编辑密钥' : '添加密钥'}
            </span>
            <button onClick={closeForm} className="text-gray-400 hover:text-gray-200">
              <IconClose className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">类别 *</label>
              <select
                value={form.category}
                onChange={e => updateCategory(e.target.value)}
                disabled={!!form.id}
                className={inputCls}
              >
                {CATEGORY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">提供商 *</label>
              <select
                value={form.provider}
                onChange={e => setForm(prev => ({ ...prev, provider: e.target.value }))}
                disabled={!!form.id}
                className={inputCls}
              >
                {providers.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className="text-[10px] text-gray-500 block mb-1">标签 *</label>
            <input
              type="text"
              value={form.label}
              onChange={e => setForm(prev => ({ ...prev, label: e.target.value }))}
              placeholder="如：我的OKX主账户"
              className={inputCls}
            />
          </div>

          <div>
            <label className="text-[10px] text-gray-500 block mb-1">API Key *</label>
            <input
              type="password"
              value={form.apiKey}
              onChange={e => setForm(prev => ({ ...prev, apiKey: e.target.value }))}
              placeholder="API Key"
              className={`${inputCls} font-mono`}
              autoComplete="off"
            />
          </div>

          <div>
            <label className="text-[10px] text-gray-500 block mb-1">Secret Key *</label>
            <input
              type="password"
              value={form.secretKey}
              onChange={e => setForm(prev => ({ ...prev, secretKey: e.target.value }))}
              placeholder="Secret Key"
              className={`${inputCls} font-mono`}
              autoComplete="off"
            />
          </div>

          {form.category === 'EXCHANGE' && (
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">Passphrase</label>
              <input
                type="password"
                value={form.passphrase}
                onChange={e => setForm(prev => ({ ...prev, passphrase: e.target.value }))}
                placeholder="Passphrase（可选）"
                className={`${inputCls} font-mono`}
                autoComplete="off"
              />
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">环境</label>
              <select
                value={form.environment}
                onChange={e => setForm(prev => ({ ...prev, environment: e.target.value }))}
                className={inputCls}
              >
                <option value="demo">Demo</option>
                <option value="live">Live</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">Base URL</label>
              <input
                type="text"
                value={form.baseUrl}
                onChange={e => setForm(prev => ({ ...prev, baseUrl: e.target.value }))}
                placeholder="（可选）"
                className={inputCls}
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <V3Button variant="ghost" size="sm" onClick={closeForm} disabled={saving}>取消</V3Button>
            <V3Button variant="primary" size="sm" onClick={handleSubmit} loading={saving}>
              {form.id ? '保存修改' : '添加'}
            </V3Button>
          </div>
        </div>
      )}

      {keys.length === 0 && !formOpen ? (
        <div className="text-center py-8 text-gray-500 text-xs">
          暂无配置的 API 密钥
          <div className="mt-2">
            <V3Button variant="secondary" size="sm" onClick={openAddForm} icon={<IconPlus className="w-3.5 h-3.5" />}>
              添加第一个密钥
            </V3Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {keys.map((key) => {
            const isConfirming = confirmDelete === key.id;
            return (
              <div key={key.id} className="px-3 py-2 rounded-lg bg-gray-800/20 border border-gray-700/20">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <V3StatusDot status={key.isVerified ? 'success' : 'idle'} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-200 truncate">{key.label || key.provider}</span>
                        <V3Badge variant="default">{key.provider}</V3Badge>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-[10px] text-gray-500">
                        <span>{key.category}</span>
                        {key.keyHint && <span className="font-mono">{key.keyHint}</span>}
                        {key.environment && <span>· {key.environment}</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {key.environment && (
                      <V3Badge variant={key.environment === 'live' ? 'danger' : 'default'}>
                        {key.environment}
                      </V3Badge>
                    )}
                    {key.isVerified && <V3Badge variant="success">已验证</V3Badge>}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-gray-700/20">
                  {isConfirming ? (
                    <>
                      <V3Button variant="danger" size="sm" onClick={() => handleDelete(key.id)}>
                        确认删除
                      </V3Button>
                      <V3Button variant="ghost" size="sm" onClick={() => setConfirmDelete(null)}>
                        取消
                      </V3Button>
                    </>
                  ) : (
                    <V3Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmDelete(key.id)}
                      className="text-red-400 hover:text-red-300"
                    >
                      删除
                    </V3Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </V3Card>
  );
}

export default ApiKeyManager;
