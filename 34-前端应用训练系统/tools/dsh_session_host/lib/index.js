/**
 * D3 单运行时多会话宿主（方案 B）。
 *
 * 生命周期：由 `dsh --profile <p> --patch host.patch.yml` 拉起；插件在 apply 阶段
 * 读取批次输入，创建 1 个根 agent，然后为每个 assignment 启动 1 个 child session，
 * 全部并发执行，结果写入输出文件后退出进程。
 *
 * 因此一个 DSH 进程承载 K 个会话，而不是 K 个进程各承载 1 个会话（方案 A）。
 *
 * 入参（环境变量）：
 *   D3_BATCH_INPUT   批次任务 JSON 文件路径（数组）
 *   D3_BATCH_OUTPUT  结果 JSON 文件路径（对象，key=ticket_id）
 *   D3_HOST_MAX      并发上限（默认 8）
 */

import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { randomUUID } from 'node:crypto';

const DEFAULT_MAX = 8;

function log(line) {
  process.stderr.write(`D3_HOST ${line}\n`);
}

function finish(outputPath, payload, code) {
  try {
    const tmp = `${outputPath}.tmp`;
    writeFileSync(tmp, JSON.stringify(payload), 'utf-8');
    renameSync(tmp, outputPath);
  } catch (exc) {
    log(`write output failed: ${exc}`);
  }
  log(`exit code=${code} tasks=${Object.keys(payload || {}).length}`);
  process.exit(code);
}

function textOf(blocks) {
  if (!Array.isArray(blocks)) return '';
  return blocks
    .filter((b) => b && b.type === 'text' && typeof b.text === 'string')
    .map((b) => b.text)
    .join('');
}

function classify(result) {
  const reason = result && result.stopReason ? result.stopReason : 'error';
  const summary = textOf(result && result.output).slice(0, 2000);
  const diagnostic = result && result.diagnostic ? String(result.diagnostic).slice(0, 1000) : '';
  if (reason === 'completed') {
    return { ok: true, status: 'done', evidence: { summary, artifacts: [], reason: null } };
  }
  if (reason === 'aborted') {
    return {
      ok: false,
      status: 'failed',
      failure_class: 'manual',
      evidence: { summary: summary || diagnostic || 'child aborted', reason: 'timeout' },
    };
  }
  if (reason === 'error') {
    return {
      ok: false,
      status: 'failed',
      failure_class: 'retryable',
      evidence: { summary: summary || diagnostic || 'child error', reason: 'runtime_error' },
    };
  }
  if (reason === 'max-tokens') {
    return {
      ok: false,
      status: 'failed',
      failure_class: 'retryable',
      evidence: { summary: summary || 'child hit token ceiling', reason: 'budget_exceeded' },
    };
  }
  return {
    ok: false,
    status: 'failed',
    failure_class: 'manual',
    evidence: { summary: summary || diagnostic || `stop=${reason}`, reason: 'runtime_error' },
  };
}

export const name = 'd3-session-host';
export const inject = ['agents', 'subagents'];

export async function apply(ctx) {
  const inputPath = process.env.D3_BATCH_INPUT;
  const outputPath = process.env.D3_BATCH_OUTPUT;
  // 非 host 模式（普通 headless 任务）直接放行，不影响其它 profile 用法。
  if (!inputPath || !outputPath) return;

  let tasks = [];
  try {
    tasks = JSON.parse(readFileSync(inputPath, 'utf-8'));
    if (!Array.isArray(tasks)) throw new Error('batch input must be an array');
  } catch (exc) {
    finish(outputPath, { __host_error__: `bad batch input: ${exc}` }, 2);
    return;
  }

  const max = Math.max(1, Number(process.env.D3_HOST_MAX) || DEFAULT_MAX);
  const startedAt = Date.now();
  log(`batch tasks=${tasks.length} max=${max} pid=${process.pid}`);

  let root;
  try {
    const route = {};
    if (process.env.D3_MODEL_PROVIDER) route.provider = process.env.D3_MODEL_PROVIDER;
    if (process.env.D3_MODEL_NAME) route.model = process.env.D3_MODEL_NAME;
    root = await ctx.agents.create({
      sessionId: randomUUID(),
      agentOptions: route,
      meta: { cwd: process.cwd() },
    });
  } catch (exc) {
    finish(outputPath, { __host_error__: `create root agent failed: ${exc}` }, 3);
    return;
  }

  const results = {};
  let cursor = 0;
  // create 返回 AgentHandle；subagents.start 的 parent 需要 live Agent 本体。
  const rootAgent = root.agent || root;

  async function runOne(task) {
    const ticketId = String(task.ticket_id || '');
    const t0 = Date.now();
    const controller = new AbortController();
    const timeoutMs = Number(task.timeout_ms) > 0 ? Number(task.timeout_ms) : 300000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const request = {
        parent: rootAgent,
        prompt: [{ type: 'text', text: String(task.goal || '') }],
        signal: controller.signal,
      };
      const provider = task.provider || process.env.D3_MODEL_PROVIDER;
      const model = task.model || process.env.D3_MODEL_NAME;
      if (provider || model) {
        request.agentOptions = {
          ...(provider ? { provider: String(provider) } : {}),
          ...(model ? { model: String(model) } : {}),
        };
      }
      const run = await ctx.subagents.start('spawn', request);
      try {
        const result = await run.result;
        log(
          `task=${ticketId} raw_result=${JSON.stringify(result).slice(0, 600)}`,
        );
        const verdict = classify(result);
        results[ticketId] = {
          ...verdict,
          session_id: run.id,
          pid: process.pid,
          duration_ms: Date.now() - t0,
        };
        results[ticketId].evidence.duration_ms = Date.now() - t0;
        results[ticketId].evidence.session_id = run.id;
        log(
          `task=${ticketId} status=${verdict.status} session=${run.id} ` +
            `duration_ms=${results[ticketId].duration_ms}`,
        );
      } finally {
        await run.dispose();
      }
    } catch (exc) {
      results[ticketId] = {
        ok: false,
        status: 'failed',
        failure_class: 'retryable',
        evidence: {
          summary: `subagent start failed: ${exc}`,
          reason: 'tool_error',
          duration_ms: Date.now() - t0,
        },
        pid: process.pid,
      };
      log(`task=${ticketId} start-error=${exc}`);
    } finally {
      clearTimeout(timer);
    }
  }

  async function worker() {
    while (cursor < tasks.length) {
      const task = tasks[cursor];
      cursor += 1;
      await runOne(task);
    }
  }

  const lanes = Math.min(max, tasks.length);
  await Promise.all(Array.from({ length: lanes }, () => worker()));

  log(`batch done total_ms=${Date.now() - startedAt} pid=${process.pid}`);
  finish(outputPath, results, 0);
}
