import { NextResponse } from "next/server";
import { getAdminChannelList } from "@/lib/admin-queries";
import { apiSuccess, apiError, parseListQuery, calculateMeta } from "@/lib/types/admin-api";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const q = parseListQuery(url);
    const { items, total } = await getAdminChannelList(q.page, q.pageSize);
    return NextResponse.json(
      apiSuccess(items, { meta: calculateMeta(total, q.page, q.pageSize) }),
    );
  } catch (error) {
    return NextResponse.json(apiError("获取渠道配置失败", error instanceof Error ? error.message : String(error)));
  }
}
