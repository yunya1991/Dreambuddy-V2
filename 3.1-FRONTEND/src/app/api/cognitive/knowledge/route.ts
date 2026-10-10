/**
 * GET /api/cognitive/knowledge
 * 知识库向量+全文检索（包裹 9-RAG-INFRA 的检索为 HTTP）。
 *
 * Query:
 *   query (required) - 检索文本
 *   top_k (default 5) - 返回结果数上限
 *   method (default hybrid) - vector / fts / hybrid
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}, 不抛异常。
 */
import { NextRequest, NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const ADAPTER_PATH = path.join(process.cwd(), 'scripts', 'knowledge_search_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 30000;

interface KnowledgeResult {
  content: string;
  score: number;
  source: string;
  heading: string;
  domain: string;
  chunk_id?: string;
}

interface KnowledgeResponse {
  results: KnowledgeResult[];
  method: string;
  degraded: boolean;
}

async function callKnowledgeSearch(
  query: string,
  topK: number,
  method: string
): Promise<{ ok: boolean; data?: KnowledgeResponse; error?: string; degraded?: boolean }> {
  return new Promise((resolve) => {
    let stdoutBuf = '';
    let settled = false;
    const child = spawn(PYTHON_BIN, [
      ADAPTER_PATH, 'search',
      JSON.stringify({ query, top_k: topK, method }),
    ], { stdio: ['ignore', 'pipe', 'pipe'] });

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ ok: false, degraded: true, error: `timeout_${TIMEOUT_MS}ms` });
    }, TIMEOUT_MS);

    child.stdout.on('data', (chunk: Buffer) => { stdoutBuf += chunk.toString(); });
    child.stderr.on('data', () => { /* discard */ });
    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, degraded: true, error: `spawn_failed: ${err.message}` });
    });
    child.on('close', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const lines = stdoutBuf.split('\n').filter((l) => l.trim().startsWith('{'));
      const lastLine = lines[lines.length - 1] || '{}';
      try {
        resolve(JSON.parse(lastLine));
      } catch (e) {
        resolve({
          ok: false, degraded: true,
          error: `parse_failed: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    });
  });
}

export async function GET(req: NextRequest) {
  const query = req.nextUrl.searchParams.get('query') || '';
  const topKRaw = req.nextUrl.searchParams.get('top_k') || '5';
  const method = req.nextUrl.searchParams.get('method') || 'hybrid';

  if (!query) {
    return NextResponse.json(
      { degraded: true, error: 'missing query param' },
      { status: 400 }
    );
  }

  const topK = Math.max(1, Math.min(50, parseInt(topKRaw, 10) || 5));
  const validMethods = ['vector', 'fts', 'hybrid'];
  const finalMethod = validMethods.includes(method) ? method : 'hybrid';

  const result = await callKnowledgeSearch(query, topK, finalMethod);

  if (!result.ok || !result.data) {
    return NextResponse.json(
      { degraded: true, error: result.error, results: [], method: finalMethod },
      { status: 503 }
    );
  }

  return NextResponse.json(result.data);
}
