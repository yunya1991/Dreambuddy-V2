import { NextRequest, NextResponse } from 'next/server';

const BACKEND_HOST = 'http://127.0.0.1:9094';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path } = await params;
    const subPath = path.join('/');
    const backendUrl = `${BACKEND_HOST}/fundamental/${subPath}`;

    const res = await fetch(backendUrl, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('[api/fundamental] GET error:', error);
    return NextResponse.json(
      { error: '无法连接基本面分析后端服务' },
      { status: 503 }
    );
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path } = await params;
    const subPath = path.join('/');
    const backendUrl = `${BACKEND_HOST}/fundamental/${subPath}`;

    let body: any = {};
    try {
      body = await request.json();
    } catch {
      body = {};
    }

    const res = await fetch(backendUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('[api/fundamental] POST error:', error);
    return NextResponse.json(
      { error: '无法连接基本面分析后端服务' },
      { status: 503 }
    );
  }
}
