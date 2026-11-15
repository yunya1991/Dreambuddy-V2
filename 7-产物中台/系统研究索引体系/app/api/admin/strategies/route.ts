import { NextResponse } from "next/server";
import { getAdminStrategyList } from "@/lib/admin-queries";
import { apiSuccess, parseListQuery, calculateMeta } from "@/lib/types/admin-api";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const denied = await requireAdminOrResponse();
  if (denied) return denied;
  const url = new URL(request.url);
  const q = parseListQuery(url);
  const { items, total } = await getAdminStrategyList(
    q.page, q.pageSize, q.search, q.status, q.type, q.uid,
  );
  return NextResponse.json(apiSuccess(items, { meta: calculateMeta(total, q.page, q.pageSize) }));
}
