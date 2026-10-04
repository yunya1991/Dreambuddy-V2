/**
 * Daily Briefing 详情 API (F7.2)
 * GET /api/briefings/[id] - 按 ID 获取简报完整详情
 *
 * 数据来源：DreamOS scheduler_data/briefings/*.json
 */
import { NextRequest, NextResponse } from "next/server";
import { readFile, readdir } from "fs/promises";
import { join } from "path";

const BRIEFINGS_DIR = join(
  process.cwd(),
  "..",
  "1-ARCHITECTURE",
  "dreamos",
  "cli",
  "scheduler_data",
  "briefings",
);

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const files = await readdir(BRIEFINGS_DIR);
    let briefing: Record<string, unknown> | null = null;
    for (const f of files) {
      if (!f.endsWith(".json")) continue;
      const content = await readFile(join(BRIEFINGS_DIR, f), "utf-8");
      const data = JSON.parse(content);
      if (data.id === id) {
        briefing = data;
        break;
      }
    }

    if (!briefing) {
      return NextResponse.json({ success: false, error: "简报不存在" }, { status: 404 });
    }

    return NextResponse.json({ success: true, briefing });
  } catch (e) {
    return NextResponse.json(
      { success: false, error: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    );
  }
}
