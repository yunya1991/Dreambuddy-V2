/**
 * 交易订单 API 路由 (P1)
 * GET  - 获取当前用户的交易订单列表 (支持 status 过滤)
 * POST - 创建交易订单 (状态机起点: DRAFT → PENDING)
 */
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { resolveTradeOrdersRouteUid } from "@/lib/development-route-uids";

// 生成订单号: TO + yyyymmdd + 6位序号
function genOrderNo(): string {
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const seq = Math.floor(Math.random() * 900000) + 100000;
  return `TO${date}${seq}`;
}

export async function GET(request: NextRequest) {
  const uid = await resolveTradeOrdersRouteUid(request);
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status");

  try {
    const where: Record<string, unknown> = { customerUid: uid };
    if (status) where.status = status;

    const orders = await prisma.tradeOrder.findMany({
      where,
      orderBy: { createdAt: "desc" },
      take: 50,
    });

    return NextResponse.json({ success: true, data: orders });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "查询失败" },
      { status: 500 },
    );
  }
}

export async function POST(request: NextRequest) {
  const uid = await resolveTradeOrdersRouteUid(request);

  try {
    const body = await request.json();
    const { symbol, direction, orderType, quantity, price, stopPrice, leverage, strategyId } = body;

    if (!symbol || !direction || !orderType || !quantity) {
      return NextResponse.json(
        { success: false, error: "symbol/direction/orderType/quantity 必填" },
        { status: 400 },
      );
    }

    const order = await prisma.tradeOrder.create({
      data: {
        orderNo: genOrderNo(),
        customerUid: uid,
        symbol,
        direction,
        orderType,
        quantity,
        price,
        stopPrice,
        leverage: leverage ?? 1,
        status: "DRAFT",
        strategyId,
      },
    });

    return NextResponse.json({ success: true, data: order }, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "创建失败" },
      { status: 500 },
    );
  }
}
