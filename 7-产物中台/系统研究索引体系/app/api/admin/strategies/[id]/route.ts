import { NextResponse } from "next/server";
import { getAdminStrategyDetail } from "@/lib/admin-queries";
import { apiSuccess, apiError } from "@/lib/types/admin-api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const strategy = await getAdminStrategyDetail(params.id);
  if (!strategy) {
    return NextResponse.json(apiError("策略不存在"), { status: 404 });
  }
  return NextResponse.json(apiSuccess(strategy));
}
