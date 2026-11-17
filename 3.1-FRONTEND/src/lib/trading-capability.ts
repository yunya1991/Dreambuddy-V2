/**
 * trading-capability — A 系列技能到「交易域真实能力」的唯一适配层
 *
 * 背景：前端 planner/skills-registry-init.ts 曾用 Math.random() 伪造 26 个 A 系列技能输出。
 * 本模块把它们统一接到 6-TRADING 的真实实现，四级优先级：
 *   1. script —— 6-TRADING/scripts/*.py 确定性脚本（回测/验证/止损/信号…）
 *   2. llm    —— deepseek_analyst.py 的 a1/a2/a3/gate_c/process_d（辅助大模型输出）
 *   3. dsh    —— DSH 8 SubAgent（交易域暂无实现时的真实分析能力）
 *   4. none   —— 明确返回「暂无实现」，绝不编造
 *
 * 仅服务端可用（Node runtime）。
 */

import { spawn } from 'child_process';
import { PYTHON_BIN, systemDir } from './runtime-paths';
import { callDshHandler } from './dsh-execution-engine';

const TRADING_DIR = systemDir('6-TRADING');
const SCRIPTS_DIR = `${TRADING_DIR}/scripts`;

export type TradingBinding =
  | { kind: 'script'; script: string; buildArgs?: (i: Record<string, any>) => string[]; timeoutMs?: number }
  | { kind: 'llm'; task: 'a1' | 'a2' | 'a3' | 'gate_c' | 'process_d'; buildData: (i: Record<string, any>) => Record<string, any> }
  | { kind: 'dsh'; module: string }
  | { kind: 'none'; reason: string };

const symbolOf = (i: Record<string, any>): string => String(i.symbol || i.instId || 'BTC-USDT-SWAP');
const directionOf = (i: Record<string, any>): string => String(i.direction || 'SHORT').toUpperCase();

/**
 * 技能 ID → 真实能力绑定。
 * 依据：6-TRADING/scripts 实际 CLI（argparse）与 deepseek_analyst.TASKS。
 */
export const TRADING_BINDINGS: Record<string, TradingBinding> = {
  // ── 确定性脚本 ─────────────────────────────────────────────
  'dream-screen1-first': { kind: 'script', script: 'screen1_manual_trigger.py', timeoutMs: 60000 },
  'dream-screen2-second': {
    kind: 'script',
    script: 'screen2_runner.py',
    buildArgs: (i) => ['--direction', directionOf(i), '--score', String(i.score ?? 68), '--dry-run'],
    timeoutMs: 120000,
  },
  'dream-screen3-third': {
    kind: 'script',
    script: 'v15_signal.py',
    buildArgs: (i) => ['--direction', directionOf(i), ...(i.price != null ? ['--price', String(i.price)] : [])],
    timeoutMs: 60000,
  },
  'dream-tactical-validator': { kind: 'script', script: 'a4_validation_executor.py', buildArgs: () => ['--check-only'], timeoutMs: 60000 },
  'dream-tactical-executor': {
    kind: 'script',
    script: 'dream_strategy_pipeline.py',
    buildArgs: (i) => ['--params', JSON.stringify({ symbol: symbolOf(i), direction: directionOf(i) })],
    timeoutMs: 120000,
  },
  'dream-exit-skill-v2': { kind: 'script', script: 'dream_stop_loss_monitor.py', buildArgs: () => ['--report', '--dry'], timeoutMs: 60000 },
  'dream-backtest': { kind: 'script', script: 'backtest_engine_main.py', buildArgs: (i) => ['--inst', symbolOf(i)], timeoutMs: 180000 },
  'dream-bayesian-opt': { kind: 'script', script: 'bayesian_opt_engine.py', buildArgs: () => ['--quick'], timeoutMs: 180000 },

  // ── 辅助大模型（deepseek_analyst.py）────────────────────────
  'dream-strategy-research': {
    kind: 'llm',
    task: 'a1',
    buildData: (i) => ({ context: i.user_request || i.context || `研究 ${symbolOf(i)} 当前市场矛盾与主要驱动` }),
  },
  'dream-first-principles': {
    kind: 'llm',
    task: 'a2',
    buildData: (i) => ({ context: i.user_request || '', a1: i.a1 || i.analysis || {} }),
  },
  'dream-strategy-designer': {
    kind: 'llm',
    task: 'a3',
    buildData: (i) => ({ context: i.user_request || '', a1: i.a1 || {}, a2: i.a2 || {} }),
  },
  'A7-practice-theory': {
    kind: 'llm',
    task: 'gate_c',
    buildData: (i) => ({ context: i.user_request || '', a7_score: Number(i.a7_score ?? 70), signal_score_pct: Number(i.signal_score_pct ?? 60) }),
  },
  'A8-theory-practice-verification': {
    kind: 'llm',
    task: 'process_d',
    buildData: (i) => ({ episodes: i.episodes || [], weekly: i.weekly || {} }),
  },

  // ── 交易域暂无实现 → DSH 真实子代理 ─────────────────────────
  'dream-contradiction-theory': { kind: 'dsh', module: 'c_drive' },
  'master-seminar': { kind: 'dsh', module: 'debate' },
  'dual-agent-conflict-gate': { kind: 'dsh', module: 'debate' },
  'dream-intelligence-monitor': { kind: 'dsh', module: 'sentiment' },
  'learning-episode-writer': { kind: 'dsh', module: 'user_memory' },
  'dream-oneirology': { kind: 'dsh', module: 'sentiment' },
  'dream-regime-detector': { kind: 'dsh', module: 'macro' },
  'dream-signal-scoring-spec': { kind: 'dsh', module: 'technical' },
  'dream-risk-position-sizing': { kind: 'dsh', module: 'risk' },
  'dream-pretrade-gatekeeper': { kind: 'dsh', module: 'risk' },
  'dream-performance-review': { kind: 'dsh', module: 'portfolio' },
  'dream-strategy-parser': { kind: 'dsh', module: 'macro' },
  'dream-fundamental-news': { kind: 'dsh', module: 'sentiment' },
};

export interface TradingCapabilityResult {
  ok: boolean;
  source: 'script' | 'llm' | 'dsh' | 'none';
  output?: unknown;
  error?: string;
}

function runPython(script: string, args: string[], timeoutMs: number): Promise<{ ok: boolean; stdout: string; error?: string }> {
  return new Promise((resolve) => {
    let stdout = '';
    let stderr = '';
    let settled = false;
    const child = spawn(PYTHON_BIN, [script, ...args], { cwd: SCRIPTS_DIR, stdio: ['ignore', 'pipe', 'pipe'] });
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ ok: false, stdout, error: `timeout_${timeoutMs}ms` });
    }, timeoutMs);
    child.stdout.on('data', (d: Buffer) => { stdout += d.toString(); });
    child.stderr.on('data', (d: Buffer) => { stderr += d.toString(); });
    child.on('error', (e) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, stdout, error: `spawn_failed: ${e.message}` });
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code === 0) resolve({ ok: true, stdout });
      else resolve({ ok: false, stdout, error: `exit_${code}: ${stderr.trim().split('\n').pop() || ''}` });
    });
  });
}

/** 从脚本 stdout 提取最后一个 JSON 对象（脚本常混打印日志） */
function parseLastJson(stdout: string): unknown {
  const lines = stdout.split('\n').map((l) => l.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (!line.startsWith('{') && !line.startsWith('[')) continue;
    try { return JSON.parse(line); } catch { /* continue */ }
  }
  return stdout.trim() || null;
}

export async function executeTradingBinding(
  skillId: string,
  inputs: Record<string, any> = {},
): Promise<TradingCapabilityResult> {
  const binding = TRADING_BINDINGS[skillId];
  if (!binding) {
    return { ok: false, source: 'none', error: `6-TRADING 暂无「${skillId}」能力绑定` };
  }

  if (binding.kind === 'none') {
    return { ok: false, source: 'none', error: binding.reason };
  }

  if (binding.kind === 'dsh') {
    const res = await callDshHandler(binding.module, { node_output: inputs }, 20000);
    if (res.ok && res.output != null) return { ok: true, source: 'dsh', output: res.output };
    return { ok: false, source: 'dsh', error: res.error || `${binding.module} 无输出` };
  }

  if (binding.kind === 'llm') {
    const data = binding.buildData(inputs);
    const res = await runPython('deepseek_analyst.py', [binding.task, JSON.stringify(data)], 90000);
    if (!res.ok) return { ok: false, source: 'llm', error: res.error };
    const parsed = parseLastJson(res.stdout);
    if (parsed && typeof parsed === 'object' && 'error' in (parsed as Record<string, unknown>)) {
      return { ok: false, source: 'llm', error: String((parsed as Record<string, unknown>).error) };
    }
    return { ok: true, source: 'llm', output: parsed };
  }

  const args = binding.buildArgs ? binding.buildArgs(inputs) : [];
  const res = await runPython(binding.script, args, binding.timeoutMs ?? 60000);
  if (!res.ok) return { ok: false, source: 'script', error: res.error };
  return { ok: true, source: 'script', output: parseLastJson(res.stdout) };
}
