// ============================================================
// /api/notebook/state — 读写笔记本全局状态
// 版本: v1.0 | 日期: 2026-06-15
// ============================================================

import { NextRequest, NextResponse } from "next/server";
import { loadState, saveState } from "@/lib/notebook/step-controller";
import type { NotebookState } from "@/lib/notebook/types";

export async function GET(_req: NextRequest) {
  const state = loadState();
  return NextResponse.json({
    success: true,
    data: state,
    timestamp: new Date().toISOString(),
  });
}

// 覆盖写入 — 用于客户端全量同步服务端
export async function PUT(req: NextRequest) {
  try {
    const body = await req.json();
    const state = body as NotebookState;
    if (!state || state.version !== "1.0") {
      return NextResponse.json(
        { success: false, error: "invalid notebook state" },
        { status: 400 }
      );
    }
    saveState(state);
    return NextResponse.json({
      success: true,
      message: "state saved",
      data: state,
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
