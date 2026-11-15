import { NextResponse } from "next/server";
import { getAdminCreditsList } from "@/lib/admin-queries";
import { apiSuccess, apiError, parseListQuery, calculateMeta } from "@/lib/types/admin-api";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const denied = await requireAdminOrResponse();
  if (denied) return denied;
  try {
    const url = new URL(request.url);
    const q = parseListQuery(url);
    const { items, total } = await getAdminCreditsList(q.page, q.pageSize);
    return NextResponse.json(
      apiSuccess(items, { meta: calculateMeta(total, q.page, q.pageSize) }),
    );
  } catch (error) {
    return NextResponse.json(apiError("获取积分账户失败", error instanceof Error ? error.message : String(error)));
  }
}
