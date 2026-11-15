import { NextResponse } from "next/server";
import { getBusinessDataView } from "@/lib/prisma-data-hub";
import { apiSuccess } from "@/lib/types/admin-api";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";

export const dynamic = "force-dynamic";

export async function GET() {
  const denied = await requireAdminOrResponse();
  if (denied) return denied;
  const view = await getBusinessDataView();
  return NextResponse.json(apiSuccess(view));
}
