import { NextResponse } from "next/server";
import { getAdminUserDetail } from "@/lib/admin-queries";
import { apiSuccess, apiError } from "@/lib/types/admin-api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: { uid: string } },
) {
  const user = await getAdminUserDetail(params.uid);
  if (!user) {
    return NextResponse.json(apiError("用户不存在"), { status: 404 });
  }
  return NextResponse.json(apiSuccess(user));
}
