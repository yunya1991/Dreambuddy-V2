/**
 * 客户信息 API 路由 (P1: 三账户隔离)
 * GET    - 获取当前用户的客户信息 + 资金账户 + 交易账户
 * PATCH  - 更新客户信息 (实名/风险等级等)
 */
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { resolveCustomerRouteUid } from "@/lib/development-route-uids";

export async function GET(request: NextRequest) {
  const uid = await resolveCustomerRouteUid(request);

  try {
    const customer = await prisma.customer.findUnique({
      where: { uid },
      include: {
        fundsAccount: true,
        tradingAccount: {
          include: { positions: true },
        },
        kycEvents: { orderBy: { createdAt: "desc" }, take: 5 },
      },
    });

    if (!customer) {
      return NextResponse.json(
        { success: false, error: "客户信息不存在" },
        { status: 404 },
      );
    }

    return NextResponse.json({ success: true, data: customer });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "查询失败" },
      { status: 500 },
    );
  }
}

export async function PATCH(request: NextRequest) {
  const uid = await resolveCustomerRouteUid(request);

  try {
    const body = await request.json();
    const { realName, idCardType, riskLevel, investorType, netWorth, annualIncome, investmentExperience } = body;

    const updateData: Record<string, unknown> = {};
    if (realName !== undefined) updateData.realName = realName;
    if (idCardType !== undefined) updateData.idCardType = idCardType;
    if (riskLevel !== undefined) updateData.riskLevel = riskLevel;
    if (investorType !== undefined) updateData.investorType = investorType;
    if (netWorth !== undefined) updateData.netWorth = netWorth;
    if (annualIncome !== undefined) updateData.annualIncome = annualIncome;
    if (investmentExperience !== undefined) updateData.investmentExperience = investmentExperience;

    const customer = await prisma.customer.update({
      where: { uid },
      data: updateData,
    });

    return NextResponse.json({ success: true, data: customer });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "更新失败" },
      { status: 500 },
    );
  }
}
