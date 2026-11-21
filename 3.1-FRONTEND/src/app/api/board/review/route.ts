import { NextResponse } from "next/server";

// 产物中台（49.233.123.96:3456）已下线，策略回测评审数据暂无上游，返回空列表。
export async function GET() {
  return NextResponse.json({ success: true, data: [] });
}
