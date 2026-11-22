/**
 * GET /api/news/items
 * 新闻明细只读接口（仅本地开放）。
 *
 * 门禁：
 *   - 必须携带 X-Dreambuddy-Local-Token，且与云端环境变量
 *     DREAMBUDDY_NEWS_LOCAL_TOKEN 常量时间比较一致；缺失/错误 → 403。
 *   - 只提供 GET；POST 显式返回 405，不做任何写入。
 *
 * 数据：
 *   执行 scripts/news_items.py，只读 39-金融语义蒸馏系统/news_digest.json
 *   （缺失时回退 hot_news.json），支持 window/limit/offset/topic/q/
 *   min_importance/sentiment 过滤与分页。
 *
 * 说明：令牌只存云端服务环境与本机 600 文件，不写入仓库、不回显。
 */
import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { timingSafeEqual } from 'crypto';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const SCRIPT_TIMEOUT_MS = 15000;
const MAX_BUFFER = 20 * 1024 * 1024;
const TOKEN_HEADER = 'x-dreambuddy-local-token';
const PYTHON_BIN =
  process.env.NEWS_PYTHON || process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
const ALLOWED_PARAMS = ['window', 'limit', 'offset', 'topic', 'q', 'min_importance', 'sentiment'];

function tokenOk(value: string | null): boolean {
  const expected = (process.env.DREAMBUDDY_NEWS_LOCAL_TOKEN || '').trim();
  if (!expected || !value) return false;
  const actual = Buffer.from(value.trim());
  const target = Buffer.from(expected);
  if (actual.length !== target.length) return false;
  return timingSafeEqual(actual, target);
}

/** 容错解析：Python 可能向 stdout 打警告行，从后向前找可解析的 JSON 片段。 */
function parseLastJson(stdout: string): unknown {
  const text = stdout.trim();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    // 继续按 '{' 切分
  }
  for (let i = text.lastIndexOf('{'); i >= 0; i = text.lastIndexOf('{', i - 1)) {
    try {
      return JSON.parse(text.slice(i));
    } catch {
      // 继续向前找
    }
  }
  return null;
}

export async function GET(request: NextRequest) {
  if (!tokenOk(request.headers.get(TOKEN_HEADER))) {
    return NextResponse.json({ ok: false, error: 'E_LOCAL_ONLY' }, { status: 403 });
  }

  const search = request.nextUrl.searchParams;
  const args = [path.join(process.cwd(), 'scripts', 'news_items.py')];
  for (const key of ALLOWED_PARAMS) {
    const value = search.get(key);
    if (value === null || value === '') continue;
    args.push('--' + key.replace(/_/g, '-'), value);
  }

  try {
    const { stdout } = await execFileAsync(PYTHON_BIN, args, {
      maxBuffer: MAX_BUFFER,
      timeout: SCRIPT_TIMEOUT_MS,
    });
    const payload = parseLastJson(stdout);
    if (!payload) {
      return NextResponse.json({ ok: false, error: 'E_SCHEMA' }, { status: 503 });
    }
    return NextResponse.json(payload, {
      headers: { 'Cache-Control': 'private, max-age=15' },
    });
  } catch (err) {
    console.error('[api/news/items]', err);
    return NextResponse.json({ ok: false, error: 'E_NEWS_ITEMS' }, { status: 503 });
  }
}

export async function POST() {
  return NextResponse.json({ ok: false, error: 'E_READ_ONLY' }, { status: 405 });
}
