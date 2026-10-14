/**
 * 飞书直推适配器（API 通道）
 * 复用 15 号模块凭证模式：环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
 * 依据 SPEC.md v1.0 第 5、9 章
 */
import type { SignalEnvelope } from '../types';
import { SIGNAL_TYPE_LABELS, SEVERITY_EMOJI } from '../types';

const TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal';
const MSG_URL = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id';

/** 默认群路由：按信号类型映射（与 15 号模块 CHAT_IDS 对齐） */
const DEFAULT_CHAT_MAP: Record<string, string> = {
  'trade_signal.open': process.env.FEISHU_CHAT_TRADING || 'oc_36c8543cea823b7546fcaad55d111f9f',
  'trade_signal.close': process.env.FEISHU_CHAT_TRADING || 'oc_36c8543cea823b7546fcaad55d111f9f',
  'trade_signal.skip': process.env.FEISHU_CHAT_TRADING || 'oc_36c8543cea823b7546fcaad55d111f9f',
  'risk_alert': process.env.FEISHU_CHAT_RISK || 'oc_20fcedf0c35035568ea8fa947380f75d',
  'strategy_update': process.env.FEISHU_CHAT_MANAGEMENT || 'oc_9cf9f141613b4e6a0f34651843cf8b9b',
  'strategy_executed': process.env.FEISHU_CHAT_TRADING || 'oc_36c8543cea823b7546fcaad55d111f9f',
  'intel_update': process.env.FEISHU_CHAT_RESEARCH || 'oc_36c575b6f39a8df3dd75057a96685a21',
  'daily_report': process.env.FEISHU_CHAT_MANAGEMENT || 'oc_9cf9f141613b4e6a0f34651843cf8b9b',
  'system_notice': process.env.FEISHU_CHAT_MANAGEMENT || 'oc_9cf9f141613b4e6a0f34651843cf8b9b',
};

let cachedToken: { token: string; expireAt: number } | null = null;

async function getTenantAccessToken(): Promise<string> {
  const appId = process.env.FEISHU_APP_ID;
  const appSecret = process.env.FEISHU_APP_SECRET;
  if (!appId || !appSecret) {
    throw new Error('缺少飞书凭证：请设置 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量');
  }
  if (cachedToken && Date.now() < cachedToken.expireAt) {
    return cachedToken.token;
  }
  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
  });
  const data = await res.json();
  if (data.code !== 0) {
    throw new Error(`获取飞书 token 失败: ${data.msg}`);
  }
  cachedToken = {
    token: data.tenant_access_token,
    // 提前 5 分钟过期，避免边界失败
    expireAt: Date.now() + (data.expire - 300) * 1000,
  };
  return cachedToken.token;
}

/** 渲染信号为飞书文本消息（CONCISE 格式） */
export function renderSignalText(envelope: SignalEnvelope): string {
  const label = SIGNAL_TYPE_LABELS[envelope.type] || envelope.type;
  const emoji = SEVERITY_EMOJI[envelope.severity] || '🔵';
  const lines = [`${emoji} [${label}] ${envelope.severity.toUpperCase()}`];
  for (const [key, value] of Object.entries(envelope.payload)) {
    if (value === undefined || value === null) continue;
    lines.push(`${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`);
  }
  lines.push(`— 来源 ${envelope.source} · ${new Date(envelope.ts).toLocaleString('zh-CN')}`);
  return lines.join('\n');
}

export interface FeishuSendOptions {
  /** 指定目标群 chat_id；缺省按信号类型默认路由 */
  chatId?: string;
}

/** 发送信号到飞书群 */
export async function sendToFeishu(
  envelope: SignalEnvelope,
  options: FeishuSendOptions = {}
): Promise<{ ok: boolean; chatId: string; error?: string }> {
  const chatId = options.chatId || DEFAULT_CHAT_MAP[envelope.type];
  if (!chatId) {
    return { ok: false, chatId: '', error: `信号类型 ${envelope.type} 无默认群路由且未指定 chatId` };
  }
  try {
    const token = await getTenantAccessToken();
    const res = await fetch(MSG_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        receive_id: chatId,
        msg_type: 'text',
        content: JSON.stringify({ text: renderSignalText(envelope) }),
      }),
    });
    const data = await res.json();
    if (data.code !== 0) {
      return { ok: false, chatId, error: `飞书发送失败: ${data.msg}` };
    }
    return { ok: true, chatId };
  } catch (err) {
    return { ok: false, chatId, error: err instanceof Error ? err.message : '未知错误' };
  }
}
