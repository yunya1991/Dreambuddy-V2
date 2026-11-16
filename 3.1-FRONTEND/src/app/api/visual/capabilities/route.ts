import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 60;

type Op = 'list' | 'explain' | 'validate' | 'run';
const OPS: Op[] = ['list', 'explain', 'validate', 'run'];

interface CliParams {
  capability_id?: string;
  domain?: string;
  q?: string;
  limit?: number;
  min_n_max?: number | null;
  payload?: Record<string, unknown> | null;
}

function buildArgs(op: Op, params: CliParams): string[] {
  const scriptPath = path.join(process.cwd(), 'scripts', 'stats_capability.py');
  const args = [scriptPath, '--op', op];
  if (params.capability_id) args.push('--capability', String(params.capability_id));
  if (op === 'list') {
    if (params.domain) args.push('--domain', String(params.domain));
    if (params.q) args.push('--q', String(params.q));
    if (params.limit) args.push('--limit', String(params.limit));
    if (params.min_n_max !== null && params.min_n_max !== undefined) {
      args.push('--min-n-max', String(params.min_n_max));
    }
  } else if (params.payload && Object.keys(params.payload).length > 0) {
    args.push('--payload', JSON.stringify(params.payload));
  }
  return args;
}

async function runCli(op: Op, params: CliParams): Promise<any> {
  const pythonBin = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
  const { stdout } = await execFileAsync(pythonBin, buildArgs(op, params), {
    maxBuffer: 20 * 1024 * 1024,
    timeout: 25000,
  });
  const lines = stdout.trim().split('\n').filter((line: string) => line.trim().startsWith('{'));
  return JSON.parse(lines[lines.length - 1] || '{}');
}

// 能力目录 60s 缓存（按过滤条件分键）；失败不缓存，避免粘住故障
const CACHE_TTL_MS = 60_000;
const listCache = new Map<string, { at: number; data: any }>();

export async function GET(request: NextRequest) {
  const search = request.nextUrl.searchParams;
  const params: CliParams = {
    domain: search.get('domain') || undefined,
    q: search.get('q') || undefined,
    limit: Number(search.get('limit')) || 50,
    min_n_max: search.get('min_n_max') ? Number(search.get('min_n_max')) : null,
  };
  const cacheKey = [params.domain, params.q, params.limit, params.min_n_max].join('|');
  const hit = listCache.get(cacheKey);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
    return NextResponse.json(hit.data);
  }

  try {
    const data = await runCli('list', params);
    if (data?.ok) listCache.set(cacheKey, { at: Date.now(), data });
    return NextResponse.json(data);
  } catch (err: any) {
    // FAIL-OPEN：目录不可用时前端降级为空态，不伪造能力
    return NextResponse.json(
      { ok: false, degraded: true, items: [], total: 0, error: err?.message || String(err) },
      { status: 503 },
    );
  }
}

export async function POST(request: NextRequest) {
  let body: any = null;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { ok: false, degraded: true, reason: 'invalid_json' },
      { status: 400 },
    );
  }

  const op = String(body?.op || '') as Op;
  if (!OPS.includes(op) || op === 'list') {
    return NextResponse.json(
      { ok: false, degraded: true, reason: `unsupported_op: ${op || 'missing'}` },
      { status: 400 },
    );
  }
  const capabilityId = String(body?.capability_id || '').trim();
  if (!capabilityId) {
    return NextResponse.json(
      { ok: false, degraded: true, reason: 'capability_id_required' },
      { status: 400 },
    );
  }

  try {
    const data = await runCli(op, {
      capability_id: capabilityId,
      payload:
        body?.payload && typeof body.payload === 'object' && !Array.isArray(body.payload)
          ? body.payload
          : {},
    });
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json(
      { ok: false, degraded: true, reason: err?.message || String(err) },
      { status: 503 },
    );
  }
}
