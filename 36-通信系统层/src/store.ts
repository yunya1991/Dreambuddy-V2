/**
 * 36-通信系统层 - 订阅存储（多渠道）
 * 职责：信号订阅的增删改查，支持所有渠道类型
 * 依据 SPEC.md v1.0 第 6.2 节（P2：多渠道扩展）
 * 持久化：JSON 文件（与 outbox 一致的轻量方案）
 */
import type { SignalType, DispatchChannel } from './types';
import * as fs from 'fs';
import * as path from 'path';

/** 支持的订阅渠道（与前端 ChannelType 对齐 + HERMES） */
export type SubscriptionChannel =
  | 'HERMES'
  | 'FEISHU'
  | 'TELEGRAM'
  | 'WECHAT_SERVERCHAN'
  | 'WECHAT_WORK'
  | 'EMAIL_SMTP'
  | 'DISCORD'
  | 'SLACK';

export interface SubscriptionRecord {
  id: string;
  uid: string;
  signalType: SignalType;
  channel: SubscriptionChannel;
  /** 渠道目标：FEISHU 为群 chat_id；TELEGRAM 为 chat_id；EMAIL 为地址；DISCORD/SLACK 为 webhook；HERMES 为群 chat_id */
  target: string;
  createdAt: number;
  enabled: boolean;
}

const STORE_DIR = process.env.SIGNAL_BUS_STORE_DIR || '/home/luke/logs/signal-bus';
const STORE_FILE = path.join(STORE_DIR, 'subscriptions.json');

function loadAll(): SubscriptionRecord[] {
  try {
    if (!fs.existsSync(STORE_FILE)) return [];
    const content = fs.readFileSync(STORE_FILE, 'utf-8');
    const items = JSON.parse(content);
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
}

function saveAll(items: SubscriptionRecord[]): void {
  try {
    fs.mkdirSync(STORE_DIR, { recursive: true });
    fs.writeFileSync(STORE_FILE, JSON.stringify(items, null, 2), 'utf-8');
  } catch {
    // 持久化失败不阻断
  }
}

function generateId(): string {
  return `sub_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

/** 查询订阅（可按 uid / signalType / channel 过滤） */
export function querySubscriptions(filter: {
  uid?: string;
  signalType?: SignalType;
  channel?: SubscriptionChannel;
} = {}): SubscriptionRecord[] {
  return loadAll().filter((s) => {
    if (filter.uid && s.uid !== filter.uid) return false;
    if (filter.signalType && s.signalType !== filter.signalType) return false;
    if (filter.channel && s.channel !== filter.channel) return false;
    return s.enabled;
  });
}

/** 新增订阅（uid + signalType + channel + target 唯一） */
export function addSubscription(input: {
  uid: string;
  signalType: SignalType;
  channel: SubscriptionChannel;
  target: string;
}): SubscriptionRecord {
  const items = loadAll();
  const dup = items.find(
    (s) =>
      s.uid === input.uid &&
      s.signalType === input.signalType &&
      s.channel === input.channel &&
      s.target === input.target
  );
  if (dup) {
    if (!dup.enabled) {
      dup.enabled = true;
      saveAll(items);
    }
    return dup;
  }
  const record: SubscriptionRecord = {
    id: generateId(),
    uid: input.uid,
    signalType: input.signalType,
    channel: input.channel,
    target: input.target,
    createdAt: Date.now(),
    enabled: true,
  };
  items.push(record);
  saveAll(items);
  return record;
}

/** 删除订阅 */
export function removeSubscription(id: string, uid?: string): boolean {
  const items = loadAll();
  const idx = items.findIndex((s) => s.id === id && (!uid || s.uid === uid));
  if (idx === -1) return false;
  items.splice(idx, 1);
  saveAll(items);
  return true;
}

/** 启用/禁用订阅 */
export function setSubscriptionEnabled(id: string, enabled: boolean, uid?: string): boolean {
  const items = loadAll();
  const record = items.find((s) => s.id === id && (!uid || s.uid === uid));
  if (!record) return false;
  record.enabled = enabled;
  saveAll(items);
  return true;
}

/** 渠道标签（供 Hermes SKILL 与前端展示） */
export const CHANNEL_LABELS: Record<SubscriptionChannel, string> = {
  HERMES: 'Hermes 智能通道',
  FEISHU: '飞书',
  TELEGRAM: 'Telegram',
  WECHAT_SERVERCHAN: 'Server酱（微信）',
  WECHAT_WORK: '企业微信',
  EMAIL_SMTP: '邮件',
  DISCORD: 'Discord',
  SLACK: 'Slack',
};
