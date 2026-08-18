/**
 * POST /api/config/channels/[id]/test
 * 测试通信渠道连接
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveChannelTestRouteUid } from '@/lib/development-route-uids';
import { decrypt } from '@/lib/encryption';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const uid = await resolveChannelTestRouteUid(request);

  try {
    const channel = await prisma.channelConfig.findFirst({ where: { id, uid } });
    if (!channel) {
      return NextResponse.json({ success: false, error: '渠道不存在' }, { status: 404 });
    }

    // 解密凭证
    let credentials: Record<string, string> = {};
    try {
      const decrypted = decrypt(channel.encryptedData, channel.iv, channel.authTag);
      credentials = JSON.parse(decrypted);
    } catch {
      return NextResponse.json({ success: false, error: '凭证解密失败' }, { status: 500 });
    }

    let testResult = { success: false, message: '不支持此渠道类型' };

    // 根据渠道类型测试连接
    if (channel.channelType === 'TELEGRAM' && credentials.botToken) {
      try {
        const res = await fetch(`https://api.telegram.org/bot${credentials.botToken}/getMe`);
        const data = await res.json();
        testResult = data.ok
          ? { success: true, message: `Bot @${data.result.username} 连接成功` }
          : { success: false, message: `Telegram API错误: ${data.description}` };
      } catch {
        testResult = { success: false, message: '无法连接Telegram API' };
      }
    } else if (channel.channelType === 'WECHAT_SERVERCHAN' && credentials.sendKey) {
      try {
        const res = await fetch(`https://sctapi.ftqq.com/${credentials.sendKey}.send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: 'Dream Gateway 测试', desp: '通信渠道连接测试 ✅' }),
        });
        const data = await res.json();
        testResult = data.code === 0
          ? { success: true, message: 'Server酱推送成功' }
          : { success: false, message: `Server酱错误: ${data.message || '未知'}` };
      } catch {
        testResult = { success: false, message: '无法连接Server酱API' };
      }
    }

    // 更新渠道状态
    await prisma.channelConfig.update({
      where: { id },
      data: {
        isOnline: testResult.success,
        lastTestAt: new Date(),
      },
    });

    return NextResponse.json({ success: true, data: testResult });
  } catch (error) {
    console.error('测试渠道失败:', error);
    return NextResponse.json({ success: false, error: '测试渠道失败' }, { status: 500 });
  }
}
