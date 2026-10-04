'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';
import {
  V3Card, V3Button, V3Badge, V3StatusDot,
  IconRefresh, IconPlus, IconClose,
} from '@/components';
import type { ChannelType, PushMessageType } from '@/types';

// 后端 GET 返回的字段（pushRules 是 JSON 字段）
interface ChannelEntry {
  id: string;
  channelType: ChannelType;
  label: string;
  pushRules?: {
    enabledTypes?: PushMessageType[];
    format?: 'CONCISE' | 'DETAILED';
  };
  silentStart?: string | null;
  silentEnd?: string | null;
  format?: 'CONCISE' | 'DETAILED';
  isOnline?: boolean;
  lastTestAt?: string;
  createdAt: string;
}

interface ChannelForm {
  id?: string;
  channelType: ChannelType;
  label: string;
  credentials: Record<string, string>;
  format: 'CONCISE' | 'DETAILED';
  silentStart: string;
  silentEnd: string;
  enabledTypes: PushMessageType[];
}

const CHANNEL_OPTIONS: { value: ChannelType; label: string }[] = [
  { value: 'TELEGRAM', label: 'Telegram' },
  { value: 'WECHAT_SERVERCHAN', label: '微信 (Server酱)' },
  { value: 'WECHAT_WORK', label: '企业微信' },
  { value: 'EMAIL_SMTP', label: 'Email' },
  { value: 'DISCORD', label: 'Discord' },
  { value: 'SLACK', label: 'Slack' },
];

// 各渠道类型的凭证字段
const CREDENTIAL_FIELDS: Record<ChannelType, { key: string; label: string; placeholder?: string; required?: boolean }[]> = {
  TELEGRAM: [
    { key: 'botToken', label: 'Bot Token', placeholder: '123456:ABC-...', required: true },
    { key: 'chatId', label: 'Chat ID', placeholder: '@channel 或 -100...', required: true },
  ],
  WECHAT_SERVERCHAN: [
    { key: 'sendKey', label: 'SendKey', placeholder: 'SCT...', required: true },
  ],
  WECHAT_WORK: [
    { key: 'webhook', label: 'Webhook URL', placeholder: 'https://qyapi.weixin.qq.com/...', required: true },
    { key: 'secret', label: 'Secret (可选)' },
  ],
  EMAIL_SMTP: [
    { key: 'host', label: 'SMTP Host', placeholder: 'smtp.gmail.com', required: true },
    { key: 'port', label: 'Port', placeholder: '465', required: true },
    { key: 'user', label: 'Username', required: true },
    { key: 'pass', label: 'Password', required: true },
    { key: 'from', label: 'From Email', placeholder: 'noreply@example.com' },
  ],
  DISCORD: [
    { key: 'webhookUrl', label: 'Webhook URL', placeholder: 'https://discord.com/api/webhooks/...', required: true },
  ],
  SLACK: [
    { key: 'webhookUrl', label: 'Webhook URL', placeholder: 'https://hooks.slack.com/...', required: true },
    { key: 'channel', label: 'Channel (可选)', placeholder: '#general' },
  ],
};

const PUSH_TYPE_OPTIONS: { value: PushMessageType; label: string }[] = [
  { value: 'trade_signal', label: '交易信号' },
  { value: 'risk_alert', label: '风险告警' },
  { value: 'intel_update', label: '情报更新' },
  { value: 'daily_report', label: '每日报告' },
  { value: 'strategy_update', label: '策略推荐' },
  { value: 'strategy_executed', label: '策略执行' },
  { value: 'system_notice', label: '系统通知' },
];

const TESTABLE_CHANNELS: ChannelType[] = ['TELEGRAM', 'WECHAT_SERVERCHAN'];

function emptyForm(): ChannelForm {
  return {
    channelType: 'TELEGRAM',
    label: '',
    credentials: {},
    format: 'CONCISE',
    silentStart: '',
    silentEnd: '',
    enabledTypes: ['trade_signal', 'risk_alert'],
  };
}

export function ChannelManager() {
  const [channels, setChannels] = useState<ChannelEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<ChannelForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; message: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchChannels();
  }, []);

  const fetchChannels = async () => {
    setLoading(true);
    try {
      const data = await api.get<ChannelEntry[]>('/api/config/channels');
      setChannels(Array.isArray(data) ? data : []);
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

  const openEditForm = (ch: ChannelEntry) => {
    setForm({
      id: ch.id,
      channelType: ch.channelType,
      label: ch.label,
      credentials: {},
      format: ch.format || ch.pushRules?.format || 'CONCISE',
      silentStart: ch.silentStart || '',
      silentEnd: ch.silentEnd || '',
      enabledTypes: ch.pushRules?.enabledTypes || ['trade_signal', 'risk_alert'],
    });
    setError(null);
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setError(null);
  };

  const updateChannelType = (type: ChannelType) => {
    setForm((prev) => ({ ...prev, channelType: type, credentials: {} }));
  };

  const updateCredential = (key: string, value: string) => {
    setForm((prev) => ({
      ...prev,
      credentials: { ...prev.credentials, [key]: value },
    }));
  };

  const togglePushType = (type: PushMessageType) => {
    setForm((prev) => {
      const has = prev.enabledTypes.includes(type);
      return {
        ...prev,
        enabledTypes: has
          ? prev.enabledTypes.filter((t) => t !== type)
          : [...prev.enabledTypes, type],
      };
    });
  };

  const handleSubmit = async () => {
    setError(null);
    if (!form.channelType || !form.label) {
      setError('渠道类型和标签为必填项');
      return;
    }

    // 校验必填凭证字段（仅新建模式）
    const credFields = CREDENTIAL_FIELDS[form.channelType] || [];
    if (!form.id) {
      for (const f of credFields) {
        if (f.required && !form.credentials[f.key]) {
          setError(`缺少必填凭证字段：${f.label}`);
          return;
        }
      }
    }

    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        channelType: form.channelType,
        label: form.label,
        format: form.format,
        silentStart: form.silentStart || null,
        silentEnd: form.silentEnd || null,
        pushRules: {
          enabledTypes: form.enabledTypes,
          format: form.format,
        },
      };

      if (form.id) {
        // 编辑模式：仅当填了凭证字段才更新凭证
        const hasNewCreds = credFields.some((f) => form.credentials[f.key]);
        if (hasNewCreds) {
          body.credentials = form.credentials;
        }
        body.id = form.id;
        await api.patch('/api/config/channels', body);
      } else {
        body.credentials = form.credentials;
        await api.post('/api/config/channels', body);
      }
      await fetchChannels();
      closeForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (ch: ChannelEntry) => {
    setTestingId(ch.id);
    setTestResult(null);
    try {
      const result = await api.post<{ success: boolean; message: string }>(
        `/api/config/channels/${ch.id}/test`,
        {}
      );
      setTestResult({ id: ch.id, success: result.success, message: result.message });
      if (result.success) {
        await fetchChannels();
      }
    } catch (err) {
      setTestResult({
        id: ch.id,
        success: false,
        message: err instanceof Error ? err.message : '测试失败',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    setError(null);
    try {
      await api.delete(`/api/config/channels?id=${encodeURIComponent(id)}`);
      setConfirmDelete(null);
      await fetchChannels();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
      setConfirmDelete(null);
    }
  };

  const credFields = CREDENTIAL_FIELDS[form.channelType] || [];
  const isTestable = (type: ChannelType) => TESTABLE_CHANNELS.includes(type);

  const inputCls = 'w-full bg-gray-900/60 border border-gray-700/50 rounded-md px-2 py-1.5 text-xs text-gray-200';
  const selectCls = inputCls;

  return (
    <V3Card
      title="通信渠道"
      subtitle="消息推送 · 告警通知"
      actions={
        <div className="flex items-center gap-2">
          <V3Button variant="ghost" size="sm" onClick={fetchChannels} loading={loading} icon={<IconRefresh className="w-3.5 h-3.5" />}>
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
              {form.id ? '编辑渠道' : '添加渠道'}
            </span>
            <button onClick={closeForm} className="text-gray-400 hover:text-gray-200">
              <IconClose className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">渠道类型 *</label>
              <select
                value={form.channelType}
                onChange={(e) => updateChannelType(e.target.value as ChannelType)}
                disabled={!!form.id}
                className={selectCls}
              >
                {CHANNEL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">标签 *</label>
              <input
                type="text"
                value={form.label}
                onChange={(e) => setForm((prev) => ({ ...prev, label: e.target.value }))}
                placeholder="如：我的Telegram"
                className={inputCls}
              />
            </div>
          </div>

          {/* 凭证字段 */}
          <div className="space-y-2 pt-1">
            <div className="text-[10px] text-gray-500">
              凭证 {form.id && <span className="text-gray-600 ml-1">（留空则不修改）</span>}
            </div>
            {credFields.map((f) => (
              <div key={f.key}>
                <label className="text-[10px] text-gray-500 block mb-1">
                  {f.label}{f.required && <span className="text-red-400 ml-0.5">*</span>}
                </label>
                <input
                  type={f.key.toLowerCase().includes('token') || f.key.toLowerCase().includes('pass') || f.key.toLowerCase().includes('secret') ? 'password' : 'text'}
                  value={form.credentials[f.key] || ''}
                  onChange={(e) => updateCredential(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  className={`${inputCls} font-mono`}
                  autoComplete="off"
                />
              </div>
            ))}
          </div>

          {/* 推送格式 */}
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">推送格式</label>
            <select
              value={form.format}
              onChange={(e) => setForm((prev) => ({ ...prev, format: e.target.value as 'CONCISE' | 'DETAILED' }))}
              className={selectCls}
            >
              <option value="CONCISE">简洁</option>
              <option value="DETAILED">详细</option>
            </select>
          </div>

          {/* 免打扰时段 */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">免打扰开始</label>
              <input
                type="time"
                value={form.silentStart}
                onChange={(e) => setForm((prev) => ({ ...prev, silentStart: e.target.value }))}
                className={inputCls}
              />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">免打扰结束</label>
              <input
                type="time"
                value={form.silentEnd}
                onChange={(e) => setForm((prev) => ({ ...prev, silentEnd: e.target.value }))}
                className={inputCls}
              />
            </div>
          </div>

          {/* 推送类型多选 */}
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">订阅消息类型</label>
            <div className="flex flex-wrap gap-1.5">
              {PUSH_TYPE_OPTIONS.map((o) => {
                const active = form.enabledTypes.includes(o.value);
                return (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => togglePushType(o.value)}
                    className={`px-2 py-1 rounded-md text-[10px] border transition-colors ${
                      active
                        ? 'bg-blue-600/30 border-blue-500/40 text-blue-300'
                        : 'bg-gray-800/30 border-gray-700/40 text-gray-500 hover:text-gray-400'
                    }`}
                  >
                    {active ? '✓ ' : ''}{o.label}
                  </button>
                );
              })}
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

      {channels.length === 0 && !formOpen ? (
        <div className="text-center py-8 text-gray-500 text-xs">
          暂无通信渠道
          <div className="mt-2">
            <V3Button variant="secondary" size="sm" onClick={openAddForm} icon={<IconPlus className="w-3.5 h-3.5" />}>
              添加第一个渠道
            </V3Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {channels.map((ch) => {
            const isTesting = testingId === ch.id;
            const result = testResult?.id === ch.id ? testResult : null;
            const isConfirming = confirmDelete === ch.id;
            const canTest = isTestable(ch.channelType);
            const enabledTypes = ch.pushRules?.enabledTypes || [];
            return (
              <div
                key={ch.id}
                className="px-3 py-2 rounded-lg bg-gray-800/20 border border-gray-700/20"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <V3StatusDot status={ch.isOnline ? 'success' : 'idle'} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-200 truncate">{ch.label}</span>
                        <V3Badge variant="default">{ch.channelType}</V3Badge>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-[10px] text-gray-500">
                        {ch.format && <span>{ch.format === 'CONCISE' ? '简洁' : '详细'}</span>}
                        {ch.silentStart && ch.silentEnd && (
                          <>
                            <span>·</span>
                            <span>免打扰 {ch.silentStart}-{ch.silentEnd}</span>
                          </>
                        )}
                        {enabledTypes.length > 0 && (
                          <>
                            <span>·</span>
                            <span>订阅 {enabledTypes.length} 类</span>
                          </>
                        )}
                        {ch.lastTestAt && (
                          <>
                            <span>·</span>
                            <span>测试于 {new Date(ch.lastTestAt).toLocaleDateString('zh-CN')}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  {ch.isOnline && <V3Badge variant="success">在线</V3Badge>}
                </div>

                {result && (
                  <div className={`mt-2 text-[10px] px-2 py-1 rounded ${result.success ? 'bg-emerald-900/20 text-emerald-400' : 'bg-red-900/20 text-red-400'}`}>
                    {result.success ? '✓' : '✗'} {result.message}
                  </div>
                )}

                <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-gray-700/20">
                  {canTest && (
                    <V3Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleTest(ch)}
                      loading={isTesting}
                    >
                      测试
                    </V3Button>
                  )}
                  <V3Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openEditForm(ch)}
                  >
                    编辑
                  </V3Button>
                  {isConfirming ? (
                    <>
                      <V3Button variant="danger" size="sm" onClick={() => handleDelete(ch.id)}>
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
                      onClick={() => setConfirmDelete(ch.id)}
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

export default ChannelManager;
