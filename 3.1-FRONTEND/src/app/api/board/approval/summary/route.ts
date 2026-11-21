import { NextResponse } from "next/server";

// 产物中台（49.233.123.96:3456）已下线，审批汇总暂无上游，返回全零。
export async function GET() {
  return NextResponse.json({
    success: true,
    data: { total: 0, pending: 0, approved: 0, rejected: 0 },
  });
}
