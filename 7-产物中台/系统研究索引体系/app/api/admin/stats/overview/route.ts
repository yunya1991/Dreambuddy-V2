import { NextResponse } from "next/server";
import { getBusinessDataView } from "@/lib/prisma-data-hub";
import { apiSuccess } from "@/lib/types/admin-api";

export const dynamic = "force-dynamic";

export async function GET() {
  const view = await getBusinessDataView();
  return NextResponse.json(apiSuccess(view));
}
