import { NextResponse } from "next/server";
import { getAdminUserList, getAdminUserDetail } from "@/lib/admin-queries";
import { apiSuccess, apiError, parseListQuery, calculateMeta } from "@/lib/types/admin-api";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const denied = await requireAdminOrResponse();
  if (denied) return denied;
  const url = new URL(request.url);
  const q = parseListQuery(url);
  const { items, total } = await getAdminUserList(q.page, q.pageSize, q.search);
  return NextResponse.json(
    apiSuccess(items, { meta: calculateMeta(total, q.page, q.pageSize) }),
  );
}
