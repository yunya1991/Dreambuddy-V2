/**
 * Hermes 适配器（智能通道）
 * 职责：将交互类信号投递到 Hermes，由其生成分析/汇报
 * 依据 SPEC.md v1.0 第 7.1 节
 */
import type { SignalEnvelope } from '../types';
import { SIGNAL_TYPE_LABELS } from '../types';

/** Hermes 本地 HTTP 接口地址（gateway 消费入口） */
const HERMES_BASE = process.env.HERMES_BASE || 'http://127.0.0.1:9119';

/** 交互类信号 → 目标群映射（与 Hermes config.yaml 群配置对齐） */
const HERMES_CHAT_MAP: Record<string, string> = {
  'intel_update': process.env.HERMES_CHAT_RESEARCH || 'oc_36c575b6f39a8df3dd75057a96685a21',
  'trade_signal.open': process.env.HERMES_CHAT_TRADING || 'oc_36c8543cea823b7546fcaad55d111f9f',
  'trade_signal.close': process.env.HERMES_CHAT_TRADING || 'oc_36c8543cea823b7546fcaad55d111f9f',
};

export interface HermesSendOptions {
  /** 指定目标群 chat_id；缺省按信号类型映射 */
  chatId?: string;
}

/** 渲染投递给 Hermes 的指令文本 */
function renderInstruction(envelope: SignalEnvelope): string {
  const label = SIGNAL_TYPE_LABELS[envelope.type] || envelope.type;
  const payloadJson = JSON.stringify(envelope.payload, null, 2);
  return [
    `[通信系统层信号] ${label}（${envelope.severity}）`,
    `来源: ${envelope.source} · 时间: ${new Date(envelope.ts).toLocaleString('zh-CN')}`,
    `信号ID: ${envelope.id}`,
    '请基于以下负载生成分析汇报：',
    '```json',
    payloadJson,
    '```',
  ].join('\n');
}

/**
 * 投递信号到 Hermes
 * 实现：调用 Hermes dashboard 的本地 API 触发消息处理
 * 若 Hermes 接口不可用，抛出错误由上层决定挂起或重试
 */
export async function sendToHermes(
  envelope: SignalEnvelope,
  options: HermesSendOptions = {}
): Promise<{ ok: boolean; chatId: string; error?: string }> {
  const chatId = options.chatId || HERMES_CHAT_MAP[envelope.type];
  if (!chatId) {
    return { ok: false, chatId: '', error: `信号类型 ${envelope.type} 无 Hermes 群映射且未指定 chatId` };
  }

  const url = `${HERMES_BASE}/api/signal-ingest`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10 * 1000);
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chatId,
        instruction: renderInstruction(envelope),
        envelope: {
          id: envelope.id,
          type: envelope.type,
          severity: envelope.severity,
          source: envelope.source,
          ts: envelope.ts,
        },
      }),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      return { ok: false, chatId, error: `Hermes 接口返回 ${res.status}: ${body.slice(0, 200)}` };
    }
    return { ok: true, chatId };
  } catch (err) {
    return {
      ok: false,
      chatId,
      error: err instanceof Error ? err.message : 'Hermes 接口不可达',
    };
  }
}
