import { NextResponse } from "next/server";
import { getAdminOrderList } from "@/lib/admin-queries";
import { apiSuccess, apiError, parseListQuery, calculateMeta } from "@/lib/types/admin-api";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const q = parseListQuery(url);
    const { items, total } = await getAdminOrderList(q.page, q.pageSize);
    return NextResponse.json(
      apiSuccess(items, { meta: calculateMeta(total, q.page, q.pageSize) }),
    );
  } catch (error) {
    return NextResponse.json(apiError("获取充值订单失败", error instanceof Error ? error.message : String(error)));
  }
}
