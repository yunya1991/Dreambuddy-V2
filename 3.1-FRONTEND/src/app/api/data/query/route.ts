/**
 * POST /api/data/query
 * L1 数据查询路由 — 三层路由器的 L1 入口（SPEC v1.0 §5 / PLAN-L0L1L2 P3）。
 *
 * Body:
 *   message (required, string) - 用户消息
 *   intent  (optional, string) - 前端 L1_INTENT_REGISTRY v3 预测的意图先验
 *
 * 后端脚本 scripts/l1_route_signal.py:
 *   意图 → L0 cognitive.recall → route_confidence 门控
 *   → L1_DIRECT: 零 token 直答 {handled:true, answer, data, route_signal}
 *   → L2_HANDOFF: {handled:false, route_signal}（前端转 /api/task/stream SSE，
 *     透传 l1_intent_hint）
 *
 * 响应信封（对齐 L0 {ok,data,degraded}）:
 *   { ok:true, data: { intent, handled, answer, data, degraded, route_signal } }
 *
 * FAIL-OPEN: 脚本异常/超时/输出非法 → 200 + { ok:false, data:null }，
 * 前端无合法信号时退回静态门控/直接转 L2，永不阻塞聊天主链路。
 * 只读: GET/PUT/DELETE 返回 405。
 */
import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { traceStage, type TraceStageRecord } from '@/lib/execution-trace';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';

const SCRIPT_TIMEOUT_MS = 8000;
const MAX_MESSAGE_LEN = 2000;

/** 认知系统可能向 stdout 打警告行，取最后一个可解析的 JSON 对象（与 Python extract_json 对齐）。 */
function parseLastJson(stdout: string): unknown {
  const lines = stdout.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!lines[i].startsWith('{')) continue;
    try {
      return JSON.parse(lines[i]);
    } catch {
      // 继续向前找
    }
  }
  return null;
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { ok: false, data: null, error: 'invalid_json_body' },
      { status: 400 },
    );
  }

  const rawMessage = (body as Record<string, unknown>)?.message;
  const rawIntent = (body as Record<string, unknown>)?.intent;
  const rawTraceId = (body as Record<string, unknown>)?.trace_id;
  const message = typeof rawMessage === 'string' ? rawMessage.slice(0, MAX_MESSAGE_LEN) : '';
  const intent = typeof rawIntent === 'string' ? rawIntent.slice(0, 64) : '';
  const trace_id = typeof rawTraceId === 'string' ? rawTraceId.slice(0, 64) : '';

  if (!message) {
    return NextResponse.json(
      { ok: false, data: null, error: 'message_required' },
      { status: 400 },
    );
  }

  const scriptPath = path.join(process.cwd(), 'scripts', 'l1_route_signal.py');
  const payload = JSON.stringify({ message, intent, trace_id });

  // 执行链 trace 台账（G-BCL-3）：L1 无 task_id，按 trace_id 聚合；
  // 交接给 L2 的请求标记 handoff，不重复计入执行单元（由 L2 task 台账覆盖）。
  const stage = (record: Omit<TraceStageRecord, 'task_id' | 'trace_id' | 'entry'>) => {
    if (!trace_id) return;
    traceStage({ ...record, task_id: '', trace_id, entry: 'l1' });
  };
  stage({ stage: 'created', intent });

  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, payload], {
      timeout: SCRIPT_TIMEOUT_MS,
      maxBuffer: 2 * 1024 * 1024,
    });
    const parsed = parseLastJson(stdout) as Record<string, unknown> | null;
    if (!parsed || typeof parsed !== 'object') {
      stage({
        stage: 'route',
        intent,
        route_decision: 'l2_handoff',
        handoff: true,
        degraded: true,
        degraded_reason: 'invalid_script_output',
      });
      return NextResponse.json({ ok: false, data: null, error: 'invalid_script_output' });
    }
    const handled = parsed.handled === true;
    const decision = (parsed.route_signal as Record<string, unknown> | undefined)?.decision;
    if (handled && String(decision).toLowerCase() === 'l1_direct') {
      const degraded = parsed.degraded === true;
      const answered = parsed.success !== false;
      stage({
        stage: 'route',
        intent: typeof parsed.intent === 'string' ? parsed.intent : intent,
        route_decision: 'l1_direct',
      });
      stage({
        stage: 'execute',
        intent: typeof parsed.intent === 'string' ? parsed.intent : intent,
        ...(degraded ? { degraded: true, degraded_reason: 'l1_executor_degraded' } : {}),
      });
      stage({
        stage: 'accept',
        intent: typeof parsed.intent === 'string' ? parsed.intent : intent,
        verdict: answered && !degraded ? 'pass' : 'fail',
        ...(answered && !degraded ? {} : { degraded_reason: degraded ? 'l1_executor_degraded' : 'l1_answer_missing' }),
      });
      stage({
        stage: 'settle',
        intent: typeof parsed.intent === 'string' ? parsed.intent : intent,
        ...(parsed.settle_attempted === true
          ? { meta: { settled: true } }
          : { degraded: true, degraded_reason: 'settle_not_attempted' }),
      });
    } else {
      // 正常交接或路由未命中：由 L2 task 台账承担五阶段，L1 侧只留交接标记
      const l1Reasons = ((parsed.route_signal as Record<string, unknown> | undefined)?.reasons ||
        []) as unknown[];
      const l1Degraded = parsed.degraded === true;
      stage({
        stage: 'route',
        intent: typeof parsed.intent === 'string' ? parsed.intent : intent,
        route_decision: 'l2_handoff',
        handoff: true,
        ...(l1Degraded
          ? {
              degraded: true,
              degraded_reason:
                l1Reasons.map(String).filter(Boolean).join(',') || 'l1_route_degraded',
            }
          : {}),
      });
    }
    return NextResponse.json({ ok: true, data: parsed });
  } catch (e: unknown) {
    // FAIL-OPEN：超时/脚本错误不阻塞，前端无信号 → 静态门控 → L2 SSE
    const reason = e instanceof Error ? e.message : 'script_failed';
    stage({
      stage: 'route',
      intent,
      route_decision: 'l2_handoff',
      handoff: true,
      degraded: true,
      degraded_reason: reason.slice(0, 200),
    });
    return NextResponse.json({ ok: false, data: null, error: reason });
  }
}

export async function GET() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/query accepts POST only' },
    { status: 405 },
  );
}

export async function PUT() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/query accepts POST only' },
    { status: 405 },
  );
}

export async function DELETE() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/query accepts POST only' },
    { status: 405 },
  );
}
