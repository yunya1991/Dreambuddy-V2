/**
 * 信号订阅管理 API（多渠道）
 * GET    - 查询订阅（可按 signalType / channel 过滤）
 * POST   - 新增订阅
 * PATCH  - 启用/禁用订阅
 * DELETE - 删除订阅
 * 依据 SPEC.md v1.0 第 6.2 节（P2：多渠道）
 */
import { NextRequest, NextResponse } from 'next/server';
import {
  querySubscriptions,
  addSubscription,
  removeSubscription,
  setSubscriptionEnabled,
  CHANNEL_LABELS,
} from '../../../../../../36-通信系统层/src/store';
import type { SubscriptionChannel } from '../../../../../../36-通信系统层/src/store';

const VALID_CHANNELS = new Set(Object.keys(CHANNEL_LABELS));

// GET /api/signal-bus/subscriptions?signalType=&channel=
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const signalType = searchParams.get('signalType') || undefined;
  const channel = searchParams.get('channel') || undefined;
  const items = querySubscriptions({
    signalType: signalType as never,
    channel: channel as never,
  });
  return NextResponse.json({ success: true, data: items });
}

// POST /api/signal-bus/subscriptions
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { uid, signalType, channel, target } = body;
    if (!uid || !signalType || !channel || !target) {
      return NextResponse.json(
        { success: false, error: '缺少必填字段: uid, signalType, channel, target' },
        { status: 400 }
      );
    }
    if (!VALID_CHANNELS.has(channel)) {
      return NextResponse.json(
        { success: false, error: `不支持的渠道: ${channel}，可选: ${Array.from(VALID_CHANNELS).join(', ')}` },
        { status: 400 }
      );
    }
    const record = addSubscription({
      uid,
      signalType,
      channel: channel as SubscriptionChannel,
      target,
    });
    return NextResponse.json({ success: true, data: record });
  } catch (error) {
    const message = error instanceof Error ? error.message : '新增订阅失败';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

// PATCH /api/signal-bus/subscriptions
export async function PATCH(request: NextRequest) {
  try {
    const body = await request.json();
    const { id, enabled, uid } = body;
    if (!id || typeof enabled !== 'boolean') {
      return NextResponse.json(
        { success: false, error: '缺少必填字段: id, enabled(boolean)' },
        { status: 400 }
      );
    }
    const ok = setSubscriptionEnabled(id, enabled, uid);
    return NextResponse.json({ success: ok, ...(ok ? {} : { error: '订阅不存在或无权限' }) });
  } catch (error) {
    const message = error instanceof Error ? error.message : '更新订阅失败';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

// DELETE /api/signal-bus/subscriptions?id=
export async function DELETE(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');
  const uid = searchParams.get('uid') || undefined;
  if (!id) {
    return NextResponse.json({ success: false, error: '缺少订阅ID' }, { status: 400 });
  }
  const ok = removeSubscription(id, uid);
  return NextResponse.json({ success: ok, ...(ok ? {} : { error: '订阅不存在或无权限' }) });
}
