/**
 * DSHExecutionEngine — DSH 执行引擎
 * ====================================
 * 执行 SkillExecutionPlan，节点优先 + LLM 兜底 + 认知上下文注入。
 *
 * 设计原则（HC-2: 节点优先 + LLM 兜底）:
 *   1. 节点优先: skill_id 映射到 DSH SubAgent 时，优先通过 IPC 调用 Python SubAgent（0 token 确定性）
 *   2. LLM 兜底: 无节点映射或 SubAgent 调用失败时，降级为 LLM 输出（FAIL-OPEN）
 *   3. 认知上下文注入: CognitiveContext 作为 node_output 的一部分传入 SubAgent
 *   4. 可观测: SkillResult.source 标记输出来源 ('node' | 'llm' | 'mixed')
 *
 * 性能目标（SPEC §3.3 阶段3）:
 *   - 节点执行延迟 ≤ 3s（Python IPC spawn 开销）
 *   - market_query 系统节点覆盖率 ≥ 70%
 *   - token 消耗降低 ≥ 50%（节点优先绕过 LLM）
 *
 * 位置: 3.1-FRONTEND/src/lib/dsh-execution-engine.ts
 *
 * 复用（避免重复造轮子）:
 *   - Python 侧: subagent_registry.SUBAGENT_REGISTRY_CONFIG（8 个 SubAgent 配置）
 *   - Python 侧: technical_agent.handle_technical_agent 等 8 个 IPC handler
 *   - IPC 模式: 复刻 cognitive-client.ts 的 spawn + 单行 JSON + 超时 + FAIL-OPEN (VM-1789618914215)
 */

import { spawn } from 'child_process';
import * as path from 'path';
import type { CognitiveContext } from './cognitive-context-builder';
import type { SkillExecutionPlan } from './skill-selector';

// ============================================================
// 1. 类型定义（对齐 SPEC §4.4）
// ============================================================

/** SKILL 执行结果（SPEC §4.4 SkillResult） */
export interface SkillResult {
  skill_id: string;
  content: any;                          // SKILL 输出内容
  confidence: number;                     // 0.0 ~ 1.0
  source: 'node' | 'llm' | 'mixed';       // 输出来源
  node_outputs: Record<string, any>;      // 系统节点输出
  llm_output: string | null;              // LLM 输出（如有）
  context_used: boolean;                   // 是否使用了认知上下文
  latency_ms: number;
}

/** IPC 调用结果 */
interface IpcResult {
  ok: boolean;
  output?: any;
  error?: string;
  degraded?: boolean;
}

// ============================================================
// 2. 配置
// ============================================================

const ENGINE_CONFIG = {
  adapter_path: path.join(process.cwd(), 'scripts', 'dsh_adapter.py'),
  python_bin: process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3',
  timeout_ms: 15000,   // SubAgent 执行可能涉及数据查询，给 15s
  confidence_threshold: 0.3,  // 低于此值触发 LLM 兜底
};

/**
 * node_id → module 映射（复用 subagent_registry.SUBAGENT_REGISTRY_CONFIG + SPEC §3.1 映射表）
 * 用于将 skill_id（当为 node_id 形式时）路由到对应 SubAgent
 *
 * 两种 key 形式都支持:
 *   1. DSH_ 前缀（DSH_TECHNICAL 等）→ 直接映射
 *   2. DreamOS 节点 ID（C1/F1/F5 等）→ 经 SPEC §3.1 映射表转换
 */
const SUBAGENT_MODULE_MAP: Record<string, string> = {
  // DSH_ 前缀（直接映射）
  DSH_TECHNICAL:  'technical',
  DSH_SENTIMENT:  'sentiment',
  DSH_MACRO:      'macro',
  DSH_FLOW:       'flow',
  DSH_VALUATION:   'valuation',
  DSH_ONCHAIN:    'onchain',
  DSH_RISK:       'risk',
  DSH_PORTFOLIO:  'portfolio',
  // DreamOS 节点 ID（SPEC §3.1 映射表，C1/C2/C3→technical, F1→sentiment, F5→macro, ...）
  C1: 'technical',  C2: 'technical',  C3: 'technical',
  F1: 'sentiment',
  F5: 'macro',
  F2: 'flow',
  F3: 'valuation',
  F4: 'onchain',
  // A_ORCH → orchestrator_v2（SPEC §5.2 阶段4: 包装为 dream-tactical-executor SKILL）
  // 内联 handler 在 dsh_adapter.py 中，直接 import OrchestratorV2 调用 run_cycle()
  A_ORCH: 'orchestrator',
  // A0-A9 / G1-G2 → 无直接 subagent，走 LLM 兜底（SPEC §3.1）
};

/**
 * skill_id 关键词 → module 启发式映射
 * 当 registry.json 尚无 node_dependencies 字段时（阶段1扩展未完成），
 * 用 skill_id 关键词匹配作为 fallback
 */
const SKILL_KEYWORD_MAP: Array<{ keywords: string[]; module: string }> = [
  { keywords: ['technical', '技术面'], module: 'technical' },
  { keywords: ['sentiment', '情绪面'], module: 'sentiment' },
  { keywords: ['macro', '宏观'], module: 'macro' },
  { keywords: ['flow', '资金面'], module: 'flow' },
  { keywords: ['valuation', '估值'], module: 'valuation' },
  { keywords: ['onchain', '链上'], module: 'onchain' },
  { keywords: ['risk', '风险面'], module: 'risk' },
  { keywords: ['portfolio', '组合'], module: 'portfolio' },
];

// ============================================================
// 3. IPC 调用（复刻 cognitive-client.ts 模式）
// ============================================================

/**
 * 调用 DSH Python handler（通过 dsh_adapter.py 桥接）
 *
 * @param module - SubAgent module 名（technical/sentiment/...）或 'c_drive'/'synthesizer'
 * @param params - handler 参数对象
 * @param timeoutMs - 超时毫秒
 * @returns IpcResult，失败时 degraded=true（FAIL-OPEN）
 */
export function callDshHandler(
  module: string,
  params: Record<string, any>,
  timeoutMs: number = ENGINE_CONFIG.timeout_ms,
): Promise<IpcResult> {
  return new Promise<IpcResult>((resolve) => {
    let stdoutBuf = '';
    let settled = false;

    const child = spawn(
      ENGINE_CONFIG.python_bin,
      [ENGINE_CONFIG.adapter_path, module, JSON.stringify(params)],
      { stdio: ['ignore', 'pipe', 'pipe'] },
    );

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({
        ok: false,
        degraded: true,
        error: `timeout_${timeoutMs}ms`,
      });
    }, timeoutMs);

    child.stdout.on('data', (chunk: Buffer) => {
      stdoutBuf += chunk.toString();
    });
    child.stderr.on('data', () => { /* 丢弃 stderr 噪音 */ });

    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        ok: false,
        degraded: true,
        error: `spawn_failed: ${err.message}`,
      });
    });

    child.on('close', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);

      // adapter 保证 stdout 最后一行是单行 JSON
      const lines = stdoutBuf.split('\n').filter((l) => l.trim().startsWith('{'));
      const lastLine = lines[lines.length - 1] || '{}';
      try {
        const parsed = JSON.parse(lastLine) as IpcResult;
        resolve(parsed);
      } catch (e) {
        resolve({
          ok: false,
          degraded: true,
          error: `parse_failed: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    });
  });
}

// ============================================================
// 4. DSHExecutionEngine 主类
// ============================================================

/**
 * DSH 执行引擎
 *
 * 用法:
 *   const engine = new DSHExecutionEngine();
 *   const result = await engine.execute_skill('DSH_TECHNICAL', { symbol: 'BTC-USDT' }, context);
 *   const results = await engine.execute_plan(plan);
 */
export class DSHExecutionEngine {
  /**
   * 解析 skill_id → SubAgent module
   *
   * 优先级:
   *   1. skill_id 是 node_id（DSH_ 前缀）→ 直接映射
   *   2. skill_id 关键词匹配 → 启发式映射
   *   3. 无匹配 → null（走 LLM 兜底）
   */
  resolveModule(skill_id: string): string | null {
    // 1. node_id 直接映射
    if (SUBAGENT_MODULE_MAP[skill_id]) {
      return SUBAGENT_MODULE_MAP[skill_id];
    }

    // 2. 关键词启发式映射
    const lower = skill_id.toLowerCase();
    for (const entry of SKILL_KEYWORD_MAP) {
      if (entry.keywords.some((kw) => lower.includes(kw.toLowerCase()))) {
        return entry.module;
      }
    }

    // 3. 无匹配
    return null;
  }

  /**
   * 执行单个 SKILL（SPEC §4.4 execute_skill）
   *
   * 流程（HC-2: 节点优先 + LLM 兜底）:
   *   1. 解析 skill_id → module
   *   2. 有映射 → IPC 调用 SubAgent（节点优先，0 token）
   *   3. 无映射 / SubAgent 失败 / 低置信度 → LLM 兜底
   *   4. 返回 SkillResult
   *
   * @param skill_id - SKILL ID 或 node_id（DSH_TECHNICAL 等）
   * @param params - 执行参数（symbol / timeframe / 等）
   * @param context - 认知上下文
   */
  async execute_skill(
    skill_id: string,
    params: Record<string, any>,
    context: CognitiveContext,
  ): Promise<SkillResult> {
    const startTime = Date.now();
    const module = this.resolveModule(skill_id);
    const context_used = this._isContextUsed(context);

    // ── 节点优先: 有 SubAgent 映射 → IPC 调用 ──────────
    if (module) {
      const node_output = {
        ...params,
        // 认知上下文注入（精简，避免 IPC 数据过大）
        cognitive_context: context_used ? {
          intent_type: context.intent_type,
          experiences: context.experiences.slice(0, 3).map((e) => ({
            content: e.content.slice(0, 200),
            confidence: e.confidence,
          })),
          knowledge: context.knowledge.slice(0, 3).map((k) => ({
            content: k.content.slice(0, 200),
            domain: k.domain,
          })),
        } : undefined,
      };

      const ipcResult = await callDshHandler(module, { node_output });

      if (ipcResult.ok && ipcResult.output) {
        const output = ipcResult.output;
        const confidence = typeof output.confidence === 'number'
          ? output.confidence
          : 0.5;

        // 低置信度 → 标记为 mixed（需 LLM 补强）
        const source: SkillResult['source'] = confidence < ENGINE_CONFIG.confidence_threshold
          ? 'mixed'
          : 'node';

        return {
          skill_id,
          content: output,
          confidence,
          source,
          node_outputs: { [module]: output },
          llm_output: null,
          context_used,
          latency_ms: Date.now() - startTime,
        };
      }
    }

    // ── LLM 兜底: 无节点映射 / SubAgent 失败 → 降级 ──────────
    // M2 阶段: LLM 兜底暂返回占位结果（source='llm'）
    // 后续阶段接入百炼 LLM client 后，此处调用 LLM 生成
    return {
      skill_id,
      content: {
        degraded: true,
        reason: module
          ? `SubAgent(${module}) 调用失败或超时，LLM 兜底`
          : `skill_id '${skill_id}' 无 SubAgent 映射，LLM 兜底`,
      },
      confidence: 0.3,
      source: 'llm',
      node_outputs: {},
      llm_output: null,
      context_used,
      latency_ms: Date.now() - startTime,
    };
  }

  /**
   * 执行完整计划（SPEC §4.4 execute_plan）
   *
   * 按 plan.order 顺序执行所有 SKILL，返回 SkillResult[]
   *
   * @param plan - SkillExecutionPlan（来自 SkillSelector）
   */
  async execute_plan(plan: SkillExecutionPlan): Promise<SkillResult[]> {
    const results: SkillResult[] = [];
    const order = plan.order.length > 0 ? plan.order : plan.skill_ids;

    for (const skill_id of order) {
      const result = await this.execute_skill(
        skill_id,
        plan.params,
        plan.context,
      );
      results.push(result);
    }

    return results;
  }

  /**
   * SIE-SPEC §3.2.3 M-2 修复: 获取已注册节点 ID + SKILL ID 白名单
   * 用于 LLM 把文档转执行计划时约束 component 字段
   */
  get_known_components(): string[] {
    // 返回 SUBAGENT_MODULE_MAP 的所有 key（节点 ID）
    return Object.keys(SUBAGENT_MODULE_MAP);
  }

  // ── 内部方法 ────────────────────────────────────────

  /** 判断认知上下文是否被实际使用（用于 F8 验收统计） */
  private _isContextUsed(context: CognitiveContext): boolean {
    return (
      context.experiences.length > 0 ||
      context.knowledge.length > 0 ||
      context.references.length > 0 ||
      context.skill_candidates.length > 0
    );
  }
}

// ============================================================
// 5. 单例导出
// ============================================================

let _instance: DSHExecutionEngine | null = null;

export function getDSHExecutionEngine(): DSHExecutionEngine {
  if (!_instance) _instance = new DSHExecutionEngine();
  return _instance;
}
