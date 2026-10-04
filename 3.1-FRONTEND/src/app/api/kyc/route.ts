/**
 * KYC 事件 API 路由 (P1)
 * GET  - 获取当前用户的 KYC 事件列表
 * POST - 提交 KYC 认证事件
 */
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { resolveKycRouteUid } from "@/lib/development-route-uids";

export async function GET(request: NextRequest) {
  const uid = await resolveKycRouteUid(request);

  try {
    const events = await prisma.kycEvent.findMany({
      where: { customerUid: uid },
      orderBy: { createdAt: "desc" },
    });

    const customer = await prisma.customer.findUnique({
      where: { uid },
      select: { kycStatus: true, kycLevel: true },
    });

    return NextResponse.json({
      success: true,
      data: { status: customer?.kycStatus ?? "UNVERIFIED", level: customer?.kycLevel ?? 0, events },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "查询失败" },
      { status: 500 },
    );
  }
}

export async function POST(request: NextRequest) {
  const uid = await resolveKycRouteUid(request);

  try {
    const body = await request.json();
    const { eventType, reason, evidence } = body;

    if (!eventType) {
      return NextResponse.json(
        { success: false, error: "eventType 必填" },
        { status: 400 },
      );
    }

    // 根据事件类型推断状态
    const statusMap: Record<string, string> = {
      SUBMIT: "PENDING",
      REVIEW: "PENDING",
      APPROVE: "VERIFIED",
      REJECT: "REJECTED",
      EXPIRE: "EXPIRED",
      UPDATE: "UNVERIFIED",
    };
    const newStatus = statusMap[eventType] ?? "UNVERIFIED";

    const event = await prisma.kycEvent.create({
      data: {
        customerUid: uid,
        eventType,
        status: newStatus,
        reason,
        evidence,
      },
    });

    // 同步更新客户 KYC 状态
    await prisma.customer.update({
      where: { uid },
      data: { kycStatus: newStatus },
    });

    return NextResponse.json({ success: true, data: event });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "提交失败" },
      { status: 500 },
    );
  }
}
