import { NextResponse } from "next/server";
import { getAdminExecutionList } from "@/lib/admin-queries";
import { apiSuccess, parseListQuery, calculateMeta } from "@/lib/types/admin-api";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const q = parseListQuery(url);
  const { items, total } = await getAdminExecutionList(
    q.page,
    q.pageSize,
    q.search,
    q.status,
  );
  return NextResponse.json(apiSuccess(items, { meta: calculateMeta(total, q.page, q.pageSize) }));
}
