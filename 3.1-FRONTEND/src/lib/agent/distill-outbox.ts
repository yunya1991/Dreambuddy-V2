/**
 * 52-LobeHub 协议集成 Phase 3 — 蒸馏桥 outbox 写入器（3.1 协议层侧产物出口）。
 *
 * 边界（SPEC §7.4 / R6 / R3）：
 *  - 本层只向 append-only jsonl outbox 追加条目，绝不直连认知库/DB；
 *  - 回流由 52-lobehub协议集成/bridge/distill_bridge.py 经 L0 cognition 壳完成；
 *  - env BRIDGE_OUTBOX_PATH 未配置时 no-op；任何异常 FAIL-OPEN（console.warn，绝不阻断请求）。
 */
import fs from 'fs';
import type { UIMessage } from 'ai';

export interface DistillEntryInput {
  type: string;
  content: string;
  tags?: string[];
  source_ref?: string;
}

export interface DistillEntry {
  type: string;
  content: string;
  tags: string[];
  source_ref: string;
  bridge_ts: string;
}

const REQUIRED_TAG = 'protocol-bridge';
const SESSION_SUMMARY_MAX_CHARS = 200;

/** 规范化条目：自动补 bridge_ts 与 protocol-bridge tag，tags 去重。 */
export function buildDistillEntry(input: DistillEntryInput): DistillEntry {
  const tags = Array.from(new Set([...(input.tags ?? []), REQUIRED_TAG]));
  return {
    type: input.type,
    content: input.content,
    tags,
    source_ref: input.source_ref ?? `ts-${Date.now()}`,
    bridge_ts: new Date().toISOString(),
  };
}

/**
 * 追加一条蒸馏条目到 outbox（append-only jsonl）。
 * 返回是否实际写入；未配置 BRIDGE_OUTBOX_PATH 或任何异常均 FAIL-OPEN 返回 false。
 */
export function appendDistillEntry(input: DistillEntryInput): boolean {
  const outboxPath = process.env.BRIDGE_OUTBOX_PATH;
  if (!outboxPath) return false; // no-op：未配置出口即静默跳过
  try {
    fs.appendFileSync(outboxPath, JSON.stringify(buildDistillEntry(input)) + '\n', 'utf-8');
    return true;
  } catch (e) {
    // FAIL-OPEN：蒸馏失败绝不阻断主链路
    console.warn('[DistillOutbox] append 失败（FAIL-OPEN）:', e instanceof Error ? e.message : e);
    return false;
  }
}

/** 从 UIMessage 提取纯文本（兼容 parts 与字符串 content 两种形态）。 */
export function extractMessageText(message: UIMessage): string {
  const parts = (message as { parts?: Array<{ type: string; text?: string }> }).parts;
  if (Array.isArray(parts)) {
    return parts
      .filter((p) => p?.type === 'text' && typeof p.text === 'string')
      .map((p) => p.text as string)
      .join('');
  }
  const content = (message as unknown as { content?: unknown }).content;
  return typeof content === 'string' ? content : '';
}

/**
 * chat 流完成回调（onFinish）挂点：仅当会话轮数 ≥2 且本轮有实质工具调用结果时，
 * 写一条 session_summary（R6 → C 级；content = 首条用户消息摘要 ≤200 字；
 * source_ref = 会话首消息 id 或时间戳）。FAIL-OPEN。
 */
export function maybeWriteSessionSummary(params: {
  messages: UIMessage[];
  hasToolResults: boolean;
}): boolean {
  try {
    const { messages, hasToolResults } = params;
    if (!hasToolResults) return false;
    if (!Array.isArray(messages) || messages.length < 2) return false;
    const firstUser = messages.find((m) => m.role === 'user');
    if (!firstUser) return false;
    const text = extractMessageText(firstUser).trim().slice(0, SESSION_SUMMARY_MAX_CHARS);
    if (!text) return false;
    return appendDistillEntry({
      type: 'session_summary',
      content: text,
      tags: ['52-lobehub', 'session_summary'],
      source_ref: firstUser.id || `ts-${Date.now()}`,
    });
  } catch (e) {
    console.warn('[DistillOutbox] session_summary 失败（FAIL-OPEN）:', e instanceof Error ? e.message : e);
    return false;
  }
}
