/**
 * Daily Briefing 列表 API (F7.2)
 * GET /api/briefings          - 获取简报列表（按时间倒序）
 * GET /api/briefings?limit=20 - 限制返回条数
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

interface Briefing {
  id: string;
  type: string;
  title: string;
  generated_at: string;
  date: string;
  summary?: string;
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get("limit") || "50", 10), 100);

    const files = await readdir(BRIEFINGS_DIR);
    const jsonFiles = files
      .filter((f) => f.endsWith(".json"))
      .sort()
      .reverse()
      .slice(0, limit);

    const briefings: Briefing[] = [];
    for (const f of jsonFiles) {
      try {
        const content = await readFile(join(BRIEFINGS_DIR, f), "utf-8");
        const data = JSON.parse(content);
        briefings.push({
          id: data.id,
          type: data.type,
          title: data.title,
          generated_at: data.generated_at,
          date: data.date,
          summary: data.summary,
        });
      } catch {
        // 跳过损坏的文件
      }
    }

    return NextResponse.json({ success: true, count: briefings.length, briefings });
  } catch (e) {
    return NextResponse.json(
      { success: false, error: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    );
  }
}
