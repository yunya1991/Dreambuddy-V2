// ============================================================
// /api/notebook/state — 读写笔记本全局状态 (3.1 内存版)
// GET  — 获取状态 (含 mock 数据 fallback)
// PUT  — 覆盖写入
// ============================================================

import { NextRequest, NextResponse } from 'next/server';
import { loadState, saveState, seedMockData } from '@/lib/notebook/step-controller';
import type { NotebookState } from '@/lib/notebook/types';

export async function GET(_req: NextRequest) {
  // 首次访问时 seed mock 数据
  seedMockData();
  const state = loadState();
  return NextResponse.json({
    success: true,
    data: state,
    timestamp: new Date().toISOString(),
  });
}

export async function PUT(req: NextRequest) {
  try {
    const body = await req.json();
    const state = body as NotebookState;
    if (!state || state.version !== '1.0') {
      return NextResponse.json(
        { success: false, error: 'invalid notebook state' },
        { status: 400 }
      );
    }
    saveState(state);
    return NextResponse.json({
      success: true,
      message: 'state saved',
      data: state,
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
