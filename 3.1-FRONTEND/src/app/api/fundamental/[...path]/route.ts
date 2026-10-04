import { NextRequest, NextResponse } from 'next/server';

const BACKEND_HOST = 'http://127.0.0.1:9094';

async function proxy(request: NextRequest, segments: string[]): Promise<NextResponse> {
  const subPath = segments.join('/');
  const backendUrl = `${BACKEND_HOST}/fundamental/${subPath}`;

  let body: string | undefined;
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    try {
      body = JSON.stringify(await request.json());
    } catch {
      body = undefined;
    }
  }

  try {
    const res = await fetch(backendUrl, {
      method: request.method,
      headers: { 'Content-Type': 'application/json' },
      body,
      cache: 'no-store',
    });

    const text = await res.text();
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('[api/fundamental] proxy error:', error);
    return NextResponse.json(
      { error: '无法连接基本面分析后端服务（9094）' },
      { status: 503 }
    );
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxy(request, path);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxy(request, path);
}
