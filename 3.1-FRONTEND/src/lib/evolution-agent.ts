/**
 * EvolutionAgent — DSH 自进化 Agent
 * ====================================
 * 每次任务执行完成后，异步触发认知系统、SKILL 系统、知识库三大系统自动进化。
 *
 * 三大进化维度（SPEC §3.8）:
 *   1. 认知系统进化 — 复用 cognitive_evolution_scheduler.py 四角色 pipeline
 *   2. SKILL 系统进化 — 复用 callCognitive('verify', ...) + skill_lifecycle_writer.py
 *   3. 知识库进化 — 复用 KnowledgeIngester.ingest()（仅调研类任务）
 *
 * 设计原则:
 *   - 异步不阻塞: trigger() 用 setImmediate 异步触发，不 await
 *   - 不修改交易逻辑/策略参数（那是 L4 自进化引擎的职责）
 *   - APPLIED 需人工审核队列
 *   - 支持 EVOLUTION_ENABLED=false 开关关闭
 *   - FAIL-OPEN: 任一维度失败不阻塞其他
 *
 * 位置: 3.1-FRONTEND/src/lib/evolution-agent.ts
 *
 * 复用（避免重复造轮子）:
 *   - cognitive_evolution_scheduler.py (4-MEMORY/9-工具与接口/) — 四角色 pipeline
 *   - callCognitive (cognitive-client.ts) — verify/record
 *   - KnowledgeIngester (knowledge-ingest.ts) — 知识入库
 */

import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { callCognitive } from './cognitive-client';
import { getKnowledgeIngester, type KnowledgeMetadata } from './knowledge-ingest';

// ============================================================
// 1. 类型定义
// ============================================================

export interface EvolutionReport {
  triggered: boolean;
  timestamp: number;
  cognitive_evolution: {
    triggered: boolean;
    success: boolean;
    role?: string;
    output?: any;
    error?: string;
  };
  skill_evolution: {
    triggered: boolean;
    verified_count: number;
    errors: string[];
  };
  knowledge_evolution: {
    triggered: boolean;
    ingested: boolean;
    stored_path?: string;
    error?: string;
  };
  duration_ms: number;
}

export interface TaskResult {
  /** 任务意图类型 */
  intent_type: string;
  /** 执行的 SKILL ID 列表 */
  skill_ids: string[];
  /** 最终输出内容 */
  final_output?: string;
  /** 是否为调研类任务 */
  is_research_type: boolean;
  /** 任务执行是否成功 */
  success: boolean;
}

// ============================================================
// 2. 配置
// ============================================================

const EVOLUTION_CONFIG = {
  /** 开关: EVOLUTION_ENABLED=false 时跳过 */
  get enabled(): boolean {
    return process.env.EVOLUTION_ENABLED !== 'false';
  },
  /** Python 解释器路径 */
  python_bin: process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3',
  /** 子进程超时 */
  timeout_ms: 60000,
  /** 是否使用 dry-run 模式（APPLIED 需人工审核） */
  dry_run: true,
  /** 是否禁用 LLM（CI/测试默认） */
  no_llm: process.env.EVOLUTION_NO_LLM !== 'false',
};

/** 调研类意图列表 */
const RESEARCH_INTENT_TYPES = [
  'deep_analysis',
  'scenario_sim',
  'strategy_verify',
];

// ============================================================
// 3. 路径解析
// ============================================================

/** 解析 cognitive_evolution_scheduler.py 路径 */
function resolveSchedulerPath(): string {
  const cwd = process.cwd();
  // 路径1: 3.1-FRONTEND/ → ../../4-MEMORY/9-工具与接口/cognitive_evolution_scheduler.py
  const candidate1 = path.resolve(cwd, '..', '..', '4-MEMORY', '9-工具与接口', 'cognitive_evolution_scheduler.py');
  if (fs.existsSync(candidate1)) return candidate1;
  // 路径2: 绝对路径 fallback
  const candidate2 = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_evolution_scheduler.py';
  if (fs.existsSync(candidate2)) return candidate2;
  return candidate1;
}

// ============================================================
// 4. 维度1: 认知系统进化
// ============================================================

/**
 * 调用 cognitive_evolution_scheduler.py 四角色 pipeline
 * 复用现有调度器，不重新实现
 */
function runCognitiveEvolution(): Promise<{
  success: boolean;
  role?: string;
  output?: any;
  error?: string;
}> {
  const scriptPath = resolveSchedulerPath();

  return new Promise((resolve) => {
    const args = [
      scriptPath,
      '--role', 'auto',
    ];
    if (EVOLUTION_CONFIG.dry_run) args.push('--dry-run');
    if (EVOLUTION_CONFIG.no_llm) args.push('--no-llm');

    const child = spawn(EVOLUTION_CONFIG.python_bin, args, {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ success: false, error: 'cognitive_evolution_timeout' });
    }, EVOLUTION_CONFIG.timeout_ms);

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    child.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ success: false, error: `spawn_failed: ${err.message}` });
    });

    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) {
        try {
          // scheduler 输出 JSON 报告
          const lines = stdout.split('\n').filter(l => l.trim().startsWith('{'));
          const lastLine = lines[lines.length - 1] || '{}';
          const output = JSON.parse(lastLine);
          resolve({ success: true, role: output.role || 'auto', output });
        } catch {
          resolve({ success: true, role: 'auto', output: { raw_stdout: stdout.slice(0, 500) } });
        }
      } else {
        resolve({ success: false, error: `exit_${code}: ${stderr.slice(0, 200)}` });
      }
    });
  });
}

// ============================================================
// 5. 维度2: SKILL 系统进化
// ============================================================

/**
 * 对本次任务中执行的 SKILL 调用 verify 更新置信度
 * 复用 callCognitive('verify', ...) MCP 工具
 */
async function runSkillEvolution(taskResult: TaskResult): Promise<{
  verified_count: number;
  errors: string[];
}> {
  let verifiedCount = 0;
  const errors: string[] = [];

  for (const skillId of taskResult.skill_ids) {
    try {
      // verify 接口: memory_id + success
      // 这里用 skillId 作为虚拟 memory_id 前缀，实际 verify 针对的是认知记忆
      const result = await callCognitive('verify', {
        memory_id: `SKILL-${skillId}`,
        success: taskResult.success,
      });
      if (result.ok && !result.degraded) {
        verifiedCount++;
      } else {
        errors.push(`verify_failed_${skillId}: ${result.error || 'unknown'}`);
      }
    } catch (e) {
      errors.push(`verify_error_${skillId}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return { verified_count: verifiedCount, errors };
}

// ============================================================
// 6. 维度3: 知识库进化
// ============================================================

/**
 * 对调研类任务调用 KnowledgeIngester.ingest() 知识入库
 */
async function runKnowledgeEvolution(taskResult: TaskResult): Promise<{
  ingested: boolean;
  stored_path?: string;
  error?: string;
}> {
  if (!taskResult.is_research_type || !taskResult.final_output) {
    return { ingested: false };
  }

  try {
    const ingester = getKnowledgeIngester();
    const meta: KnowledgeMetadata = {
      title: `调研产出-${taskResult.intent_type}-${Date.now()}`,
      domain: taskResult.intent_type,
      tags: ['auto-ingest', taskResult.intent_type],
      source: 'EvolutionAgent',
      category: 'external_research', // 默认分类，ingest 内部会自动重分类
    };

    const result = await ingester.ingest(taskResult.final_output, meta);
    if (result.success) {
      return { ingested: true, stored_path: result.stored_path };
    }
    return { ingested: false, error: result.errors.join('; ') || 'ingest_failed' };
  } catch (e) {
    return { ingested: false, error: `knowledge_evolution_error: ${e instanceof Error ? e.message : String(e)}` };
  }
}

// ============================================================
// 7. EvolutionAgent 主类
// ============================================================

export class EvolutionAgent {
  /**
   * 异步触发自进化（非阻塞）
   * 在任务完成后调用，不阻塞最终输出
   *
   * @param taskResult 任务执行结果
   * @returns EvolutionReport
   */
  async trigger(taskResult: TaskResult): Promise<EvolutionReport> {
    const startTime = Date.now();

    // 开关检查
    if (!EVOLUTION_CONFIG.enabled) {
      return this.emptyReport(false, 'evolution_disabled');
    }

    return this.executeEvolution(taskResult, startTime);
  }

  /**
   * 异步触发（fire-and-forget，不阻塞调用方）
   */
  triggerAsync(taskResult: TaskResult): void {
    if (!EVOLUTION_CONFIG.enabled) return;
    process.nextTick(() => {
      this.executeEvolution(taskResult, Date.now()).catch(() => {
        // FAIL-OPEN: 吞掉所有错误
      });
    });
  }

  /**
   * 实际执行三大维度进化
   */
  private async executeEvolution(
    taskResult: TaskResult,
    startTime: number,
  ): Promise<EvolutionReport> {
    // 三维度并行执行，任一失败不阻塞其他
    const [cognitiveResult, skillResult, knowledgeResult] = await Promise.all([
      runCognitiveEvolution().catch((e) => ({
        success: false,
        error: `cognitive_evolution_crash: ${e instanceof Error ? e.message : String(e)}`,
      })),
      runSkillEvolution(taskResult).catch((e) => ({
        verified_count: 0,
        errors: [`skill_evolution_crash: ${e instanceof Error ? e.message : String(e)}`],
      })),
      runKnowledgeEvolution(taskResult).catch((e) => ({
        ingested: false,
        error: `knowledge_evolution_crash: ${e instanceof Error ? e.message : String(e)}`,
      })),
    ]);

    return {
      triggered: true,
      timestamp: startTime,
      cognitive_evolution: {
        triggered: true,
        success: cognitiveResult.success,
        role: (cognitiveResult as any).role,
        output: (cognitiveResult as any).output,
        error: (cognitiveResult as any).error,
      },
      skill_evolution: {
        triggered: true,
        verified_count: (skillResult as any).verified_count || 0,
        errors: (skillResult as any).errors || [],
      },
      knowledge_evolution: {
        triggered: true,
        ingested: (knowledgeResult as any).ingested || false,
        stored_path: (knowledgeResult as any).stored_path,
        error: (knowledgeResult as any).error,
      },
      duration_ms: Date.now() - startTime,
    };
  }

  /** 构造空报告（开关关闭时） */
  private emptyReport(triggered: boolean, reason: string): EvolutionReport {
    return {
      triggered,
      timestamp: Date.now(),
      cognitive_evolution: { triggered: false, success: false, error: reason },
      skill_evolution: { triggered: false, verified_count: 0, errors: [reason] },
      knowledge_evolution: { triggered: false, ingested: false, error: reason },
      duration_ms: 0,
    };
  }
}

// 单例导出
let _instance: EvolutionAgent | null = null;
export function getEvolutionAgent(): EvolutionAgent {
  if (!_instance) _instance = new EvolutionAgent();
  return _instance;
}
