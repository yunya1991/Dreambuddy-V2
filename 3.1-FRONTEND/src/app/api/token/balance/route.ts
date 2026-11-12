import { NextResponse } from 'next/server';
import { auth } from '@/lib/auth';
import { prisma } from '@/lib/prisma';

/**
 * GET /api/token/balance
 * 当前登录用户的积分余额（供前端 TokenMonitor 使用）
 */
export async function GET() {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ message: '未登录' }, { status: 401 });
    }

    const account = await prisma.creditsAccount.findUnique({
      where: { uid: session.user.id },
      select: { balance: true, totalEarned: true, totalSpent: true },
    });

    return NextResponse.json({
      balance: account?.balance ?? 0,
      totalEarned: account?.totalEarned ?? 0,
      totalSpent: account?.totalSpent ?? 0,
    });
  } catch (err) {
    console.error('[api/token/balance]', err);
    return NextResponse.json({ message: '服务器错误' }, { status: 500 });
  }
}
