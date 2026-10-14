/**
 * 36-通信系统层 - 多渠道推送适配器
 * 职责：将信号投递到订阅的各渠道（飞书以外）
 * 依据 SPEC.md v1.0 第 5、6.2 节（P2：多渠道订阅）
 */
import type { SignalEnvelope } from '../types';
import { renderSignalText } from './feishu';
import type { SubscriptionChannel } from '../store';

export interface ChannelSendResult {
  ok: boolean;
  error?: string;
}

/** Telegram：target 为 chat_id，凭证经环境变量 TELEGRAM_BOT_TOKEN */
async function sendTelegram(envelope: SignalEnvelope, target: string): Promise<ChannelSendResult> {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) return { ok: false, error: '缺少 TELEGRAM_BOT_TOKEN 环境变量' };
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: target, text: renderSignalText(envelope) }),
    });
    const data = await res.json();
    return data.ok ? { ok: true } : { ok: false, error: `Telegram 错误: ${data.description}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Telegram 不可达' };
  }
}

/** Server酱：target 为 sendKey */
async function sendServerChan(envelope: SignalEnvelope, target: string): Promise<ChannelSendResult> {
  try {
    const res = await fetch(`https://sctapi.ftqq.com/${target}.send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: `[${envelope.type}] ${envelope.severity}`,
        desp: renderSignalText(envelope),
      }),
    });
    const data = await res.json();
    return data.code === 0 ? { ok: true } : { ok: false, error: `Server酱错误: ${data.message || '未知'}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Server酱不可达' };
  }
}

/** 企业微信：target 为群机器人 webhook 地址 */
async function sendWechatWork(envelope: SignalEnvelope, target: string): Promise<ChannelSendResult> {
  try {
    const res = await fetch(target, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        msgtype: 'text',
        text: { content: renderSignalText(envelope) },
      }),
    });
    const data = await res.json();
    return data.errcode === 0 ? { ok: true } : { ok: false, error: `企业微信错误: ${data.errmsg}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : '企业微信不可达' };
  }
}

/** Discord：target 为 webhook 地址 */
async function sendDiscord(envelope: SignalEnvelope, target: string): Promise<ChannelSendResult> {
  try {
    const res = await fetch(target, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: renderSignalText(envelope).slice(0, 2000) }),
    });
    return res.ok ? { ok: true } : { ok: false, error: `Discord 返回 ${res.status}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Discord 不可达' };
  }
}

/** Slack：target 为 webhook 地址 */
async function sendSlack(envelope: SignalEnvelope, target: string): Promise<ChannelSendResult> {
  try {
    const res = await fetch(target, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: renderSignalText(envelope) }),
    });
    return res.ok ? { ok: true } : { ok: false, error: `Slack 返回 ${res.status}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Slack 不可达' };
  }
}

/** 邮件：target 为收件地址，SMTP 配置经环境变量（P2 简化实现：记录投递日志） */
async function sendEmail(envelope: SignalEnvelope, target: string): Promise<ChannelSendResult> {
  // SMTP 发送依赖 nodemailer，P2 阶段先返回明确提示，凭证就绪后接入
  return { ok: false, error: `邮件渠道待接入 SMTP 配置（目标: ${target}）` };
}

/** 统一入口：按渠道类型分发 */
export async function sendToChannel(
  channel: SubscriptionChannel,
  envelope: SignalEnvelope,
  target: string
): Promise<ChannelSendResult> {
  switch (channel) {
    case 'TELEGRAM':
      return sendTelegram(envelope, target);
    case 'WECHAT_SERVERCHAN':
      return sendServerChan(envelope, target);
    case 'WECHAT_WORK':
      return sendWechatWork(envelope, target);
    case 'DISCORD':
      return sendDiscord(envelope, target);
    case 'SLACK':
      return sendSlack(envelope, target);
    case 'EMAIL_SMTP':
      return sendEmail(envelope, target);
    default:
      return { ok: false, error: `渠道 ${channel} 不在多渠道适配器范围内` };
  }
}
