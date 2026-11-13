import { NextRequest, NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// 51-OKX CLI 系统的本地 HTTP bridge（用户 venue，与后端 11 旁路隔离）。
const BRIDGE_BASE = process.env.OKX_VENUE_BRIDGE_URL || 'http://127.0.0.1:8097';
const TOKEN_FILE =
  process.env.OKX_VENUE_BRIDGE_TOKEN_FILE ||
  path.join(process.cwd(), '..', '51-OKX CLI 系统', 'runtime', 'audit', 'bridge_token');

// 前端只允许打到这些前缀，避免把 bridge 当成任意后门。
const ALLOWED_PREFIXES = ['health', 'account/', 'market/', 'order-intents', 'live/', 'credentials', 'audit'];

function isAllowed(subPath: string): boolean {
  return ALLOWED_PREFIXES.some((prefix) =>
    prefix.endsWith('/') ? subPath.startsWith(prefix) : subPath === prefix || subPath.startsWith(`${prefix}/`),
  );
}

async function resolveToken(): Promise<string> {
  const envToken = process.env.OKX_VENUE_BRIDGE_TOKEN?.trim();
  if (envToken) return envToken;
  try {
    return (await readFile(TOKEN_FILE, 'utf-8')).trim();
  } catch {
    return '';
  }
}

async function proxy(
  method: 'GET' | 'POST' | 'DELETE',
  segments: string[],
  search: string,
  body?: unknown,
): Promise<NextResponse> {
  const subPath = segments.join('/');
  if (!isAllowed(subPath)) {
    return NextResponse.json(
      { ok: false, error: { code: 'not_allowed', message: `venue bridge 不暴露该路径: ${subPath}` } },
      { status: 404 },
    );
  }

  const token = await resolveToken();
  if (!token) {
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: 'bridge_token_missing',
          message: '未找到 51 bridge token，请先启动 `python3 -m okx_venue.server`（51-OKX CLI 系统）',
        },
      },
      { status: 503 },
    );
  }

  let response: Response;
  try {
    response = await fetch(`${BRIDGE_BASE}/${subPath}${search}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Venue-Token': token,
      },
      body: method === 'POST' ? JSON.stringify(body ?? {}) : undefined,
      cache: 'no-store',
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: 'bridge_unreachable',
          message: `无法连接 51 venue bridge (${BRIDGE_BASE})：${err instanceof Error ? err.message : String(err)}`,
        },
      },
      { status: 503 },
    );
  }

  const text = await response.text();
  let payload: unknown;
  try {
    payload = text ? JSON.parse(text) : { ok: response.ok, data: null };
  } catch {
    payload = {
      ok: false,
      error: { code: 'bridge_invalid_json', message: text.slice(0, 300) },
    };
  }
  return NextResponse.json(payload as Record<string, unknown>, { status: response.status });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: segments } = await params;
  return proxy('GET', segments, request.nextUrl.search);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: segments } = await params;
  let body: unknown = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  return proxy('POST', segments, request.nextUrl.search, body);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: segments } = await params;
  return proxy('DELETE', segments, request.nextUrl.search);
}
