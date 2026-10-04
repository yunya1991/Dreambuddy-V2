import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/lib/auth';
import { prisma } from '@/lib/prisma';

const RECHARGE_PACKAGES: Record<string, { credits: number; price: number; name: string }> = {
  basic: { credits: 500, price: 9.9, name: '基础包' },
  standard: { credits: 2000, price: 29.9, name: '标准包' },
  pro: { credits: 5000, price: 69.9, name: '专业包' },
  enterprise: { credits: 15000, price: 199.9, name: '企业包' },
};

/**
 * POST /api/recharge
 * 积分充值（模拟支付，直接到账）
 */
export async function POST(req: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ message: '未登录' }, { status: 401 });
    }

    const { packageId } = await req.json();
    const pkg = RECHARGE_PACKAGES[packageId];
    if (!pkg) {
      return NextResponse.json({ message: '无效的套餐' }, { status: 400 });
    }

    const uid = session.user.id;
    const expiresAt = new Date();
    expiresAt.setFullYear(expiresAt.getFullYear() + 1);

    const result = await prisma.$transaction(async (tx) => {
      let account = await tx.creditsAccount.findUnique({ where: { uid } });
      if (!account) {
        account = await tx.creditsAccount.create({
          data: { uid, balance: 0, totalEarned: 0, totalSpent: 0 },
        });
      }

      const newBalance = account.balance + pkg.credits;
      const [updated] = await Promise.all([
        tx.creditsAccount.update({
          where: { uid },
          data: {
            balance: newBalance,
            totalEarned: account.totalEarned + pkg.credits,
          },
        }),
        tx.creditsTransaction.create({
          data: {
            uid,
            type: 'EARN',
            category: 'RECHARGE',
            amount: pkg.credits,
            balanceAfter: newBalance,
            description: `充值${pkg.name}`,
            expiresAt,
          },
        }),
      ]);

      return updated;
    });

    return NextResponse.json({
      ok: true,
      balance: result.balance,
      message: `充值成功，获得 ${pkg.credits} 积分`,
    });
  } catch (err: any) {
    console.error('[api/recharge]', err);
    return NextResponse.json({ message: '服务器错误' }, { status: 500 });
  }
}
