/**
 * 通信渠道配置 API 路由
 * GET    - 获取渠道列表
 * POST   - 添加渠道
 * PATCH  - 更新渠道
 * DELETE - 删除渠道
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveChannelsRouteUid } from '@/lib/development-route-uids';
import { encrypt } from '@/lib/encryption';

// GET /api/config/channels
export async function GET(request: NextRequest) {
  const uid = await resolveChannelsRouteUid(request);

  try {
    const channels = await prisma.channelConfig.findMany({
      where: { uid },
      select: {
        id: true,
        channelType: true,
        label: true,
        pushRules: true,
        silentStart: true,
        silentEnd: true,
        format: true,
        isOnline: true,
        lastTestAt: true,
        createdAt: true,
        updatedAt: true,
      },
      orderBy: { createdAt: 'desc' },
    });

    return NextResponse.json({ success: true, data: channels });
  } catch (error) {
    console.error('获取渠道列表失败:', error);
    return NextResponse.json(
      { success: false, error: '获取渠道列表失败' },
      { status: 500 }
    );
  }
}

// POST /api/config/channels - 添加渠道
export async function POST(request: NextRequest) {
  const uid = await resolveChannelsRouteUid(request);

  try {
    const body = await request.json();
    const { channelType, label, credentials, pushRules, silentStart, silentEnd, format } = body;

    if (!channelType || !label || !credentials) {
      return NextResponse.json(
        { success: false, error: '缺少必填字段: channelType, label, credentials' },
        { status: 400 }
      );
    }

    // 加密凭证
    const credentialsJson = JSON.stringify(credentials);
    const { encryptedData, iv, authTag } = encrypt(credentialsJson);

    const channel = await prisma.channelConfig.create({
      data: {
        uid,
        channelType,
        label,
        encryptedData,
        iv,
        authTag,
        pushRules: pushRules || { enabledTypes: ['trade_signal', 'risk_alert'], format: 'CONCISE' },
        silentStart: silentStart || null,
        silentEnd: silentEnd || null,
        format: format || 'CONCISE',
      },
    });

    return NextResponse.json({
      success: true,
      data: {
        id: channel.id,
        channelType: channel.channelType,
        label: channel.label,
        isOnline: channel.isOnline,
      },
    });
  } catch (error) {
    console.error('添加渠道失败:', error);
    return NextResponse.json(
      { success: false, error: '添加渠道失败' },
      { status: 500 }
    );
  }
}

// PATCH /api/config/channels - 更新渠道
export async function PATCH(request: NextRequest) {
  const uid = await resolveChannelsRouteUid(request);

  try {
    const body = await request.json();
    const { id, label, credentials, pushRules, silentStart, silentEnd, format } = body;

    if (!id) {
      return NextResponse.json({ success: false, error: '缺少渠道ID' }, { status: 400 });
    }

    const existing = await prisma.channelConfig.findFirst({ where: { id, uid } });
    if (!existing) {
      return NextResponse.json({ success: false, error: '渠道不存在或无权限' }, { status: 404 });
    }

    const updateData: Record<string, unknown> = {};
    if (label) updateData.label = label;
    if (pushRules) updateData.pushRules = pushRules;
    if (silentStart !== undefined) updateData.silentStart = silentStart;
    if (silentEnd !== undefined) updateData.silentEnd = silentEnd;
    if (format) updateData.format = format;

    // 如果更新了凭证，重新加密
    if (credentials) {
      const credentialsJson = JSON.stringify(credentials);
      const { encryptedData, iv, authTag } = encrypt(credentialsJson);
      updateData.encryptedData = encryptedData;
      updateData.iv = iv;
      updateData.authTag = authTag;
      updateData.isOnline = false; // 凭证变更后需重新测试
    }

    await prisma.channelConfig.update({ where: { id }, data: updateData });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('更新渠道失败:', error);
    return NextResponse.json({ success: false, error: '更新渠道失败' }, { status: 500 });
  }
}

// DELETE /api/config/channels
export async function DELETE(request: NextRequest) {
  const uid = await resolveChannelsRouteUid(request);

  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get('id');

    if (!id) {
      return NextResponse.json({ success: false, error: '缺少渠道ID' }, { status: 400 });
    }

    const existing = await prisma.channelConfig.findFirst({ where: { id, uid } });
    if (!existing) {
      return NextResponse.json({ success: false, error: '渠道不存在或无权限' }, { status: 404 });
    }

    await prisma.channelConfig.delete({ where: { id } });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('删除渠道失败:', error);
    return NextResponse.json({ success: false, error: '删除渠道失败' }, { status: 500 });
  }
}
