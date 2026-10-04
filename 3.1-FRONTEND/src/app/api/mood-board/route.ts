/**
 * Mood Board 情绪板 API (F7.3)
 * GET /api/mood-board     - 获取最新情绪板
 * GET /api/mood-board?date=2026-09-29 - 获取指定日期
 *
 * 数据来源：DreamOS scheduler_data/mood_boards/{date}.json
 */
import { NextRequest, NextResponse } from "next/server";
import { readFile, readdir } from "fs/promises";
import { join } from "path";

const MOOD_BOARDS_DIR = join(
  process.cwd(),
  "..",
  "1-ARCHITECTURE",
  "dreamos",
  "cli",
  "scheduler_data",
  "mood_boards",
);

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date");

    let targetFile: string | null = null;
    if (date) {
      targetFile = `${date}.json`;
    } else {
      const files = await readdir(MOOD_BOARDS_DIR);
      const jsonFiles = files.filter((f) => f.endsWith(".json")).sort().reverse();
      if (jsonFiles.length > 0) {
        targetFile = jsonFiles[0];
      }
    }

    if (!targetFile) {
      return NextResponse.json({ success: false, error: "无情绪板数据" }, { status: 404 });
    }

    const content = await readFile(join(MOOD_BOARDS_DIR, targetFile), "utf-8");
    const moodBoard = JSON.parse(content);

    return NextResponse.json({ success: true, mood_board: moodBoard });
  } catch (e) {
    return NextResponse.json(
      { success: false, error: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    );
  }
}
