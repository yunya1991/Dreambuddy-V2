import { NextRequest, NextResponse } from "next/server";
import {
  appendMemoryRecord,
  listMemoryRecords,
  type MemoryRecordInput,
} from "@/lib/cognition/memory-records";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/memory/records
 * 残差记忆生产入口：必须过准入（四禁入/四残差/三测试）才落盘。
 */
export async function POST(request: NextRequest) {
  let body: MemoryRecordInput;
  try {
    body = (await request.json()) as MemoryRecordInput;
  } catch {
    return NextResponse.json(
      { success: false, error: "invalid_json" },
      { status: 400 },
    );
  }

  if (!body?.content?.trim() || !body?.subclass) {
    return NextResponse.json(
      { success: false, error: "content_and_subclass_required" },
      { status: 400 },
    );
  }

  const result = await appendMemoryRecord(body);
  if (!result.ok) {
    return NextResponse.json(
      { success: false, error: "admission_rejected", admission: result.admission },
      { status: 422 },
    );
  }
  return NextResponse.json(
    { success: true, duplicated: result.duplicated ?? false, record: result.record },
    { status: result.duplicated ? 200 : 201 },
  );
}

/** GET /api/memory/records：读取当前记忆记录（同 id 最新一行） */
export async function GET() {
  const records = await listMemoryRecords();
  return NextResponse.json({ success: true, count: records.length, records });
}
