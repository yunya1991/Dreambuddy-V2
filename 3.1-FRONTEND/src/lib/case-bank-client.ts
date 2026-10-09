/**
 * CaseBankClient — TDR (Training Data Repository) IPC 客户端
 * ==========================================
 * SPEC-20261009 §3.1 + §10 P0-1
 *
 * 通过子进程调用 case_bank_adapter.py，复刻 cognitive-client.ts 的 IPC 模式。
 *
 * 设计原则：
 *   1. 物理隔离：solution_case_bank.db 独立于 cognitive_memory.db
 *   2. FAIL-OPEN：Python 不可用/超时 → 返回 degraded，不抛异常
 *   3. 质量闸门：有 learned 才入库（TS 层拦截，不调 Python）
 *   4. 10s 超时
 *
 * 位置: 3.1-FRONTEND/src/lib/case-bank-client.ts
 */

import { spawn } from 'child_process';
import path from 'path';

// ============================================================
// 1. 类型定义（对齐 SPEC §3.1）
// ============================================================

export type LayerName = 'S' | 'DSH' | 'C' | 'G' | 'LLM';
export type OutcomeClass = 'success' | 'failure' | 'partial' | 'unknown';
export type QualityLevel = 'S' | 'A' | 'B' | 'C';

export interface LayerTag {
  layer: LayerName;
  training_data: unknown;
  bucket_count: number;
  bucket_threshold: number;
}

export interface BaselineOutput {
  trae_intent: string;
  trae_actions: string[];
  trae_outcome: string;
  trae_learned: string[];
  trae_token_usage?: number;
  trae_latency_ms?: number;
}

export interface SolutionCase {
  id: string;
  intent: string;
  actions: string[];
  outcome_text: string;
  learned: string[];
  message_id: string;
  message_summary_time: string;
  outcome: OutcomeClass;
  codebook_index: number[];
  embedding: number[];
  layer_tags: LayerTag[];
  baseline_output: BaselineOutput;
  quality: QualityLevel;
  confidence: number;
  tags: string[];
  source: string;
  created_at: number;
  last_retrieved_at: number;
  replay_count: number;
  verify_count: number;
}

/** store 入参（四元组 + 元数据） */
export interface StoreInput {
  intent: string;
  actions: string[];
  outcome_text: string;
  learned: string[];
  message_id: string;
  message_summary_time: string;
  codebook_index?: number[];
  embedding?: number[];
  layer_tags?: LayerTag[];
  baseline_output?: Partial<BaselineOutput>;
  tags?: string[];
  source?: string;
}

export interface RetrieveResult {
  cases: SolutionCase[];
  scores: number[];
  retrieval_mode: 'exact' | 'semantic' | 'fallback';
}

export interface CaseBankStats {
  total_cases: number;
  by_quality: Record<string, number>;
  by_layer: Record<string, number>;
  by_outcome: Record<string, number>;
  capacity_limit: number;
  lru_evicted_count: number;
}

export interface CaseBankResult<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  degraded?: boolean;
}

// ============================================================
// 2. 配置
// ============================================================

const DEFAULT_ADAPTER_PATH = path.join(process.cwd(), 'scripts', 'case_bank_adapter.py');
const DEFAULT_PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const DEFAULT_TIMEOUT_MS = 10000;
const CAPACITY_LIMIT = 10000;

// 各层桶满阈值（SPEC §4.6 v0.3 各层差异化）
const LAYER_THRESHOLDS: Record<LayerName, number> = {
  S: 50,
  DSH: 100,
  C: 80,
  G: 60,
  LLM: 30,
};

// ============================================================
// 3. CaseBankClient 主类
// ============================================================

export class CaseBankClient {
  private adapterPath: string;
  private pythonBin: string;
  private timeoutMs: number;

  constructor(opts?: { adapterPath?: string; pythonBin?: string; timeoutMs?: number }) {
    this.adapterPath = opts?.adapterPath || DEFAULT_ADAPTER_PATH;
    this.pythonBin = opts?.pythonBin || DEFAULT_PYTHON_BIN;
    this.timeoutMs = opts?.timeoutMs || DEFAULT_TIMEOUT_MS;
  }

  /**
   * 存储案例到 TDR
   * 质量闸门：learned 为空 → 拒绝（TS 层拦截）
   */
  async store(input: StoreInput): Promise<CaseBankResult<{ id: string }>> {
    // 质量闸门：有 learned 才入库
    if (!input.learned || input.learned.length === 0) {
      return {
        ok: false,
        error: 'quality_gate_rejected: learned is empty (SPEC §3.1: 有 learned 即入库)',
      };
    }

    // 补充 outcome 分类和 baseline
    const outcome = this.inferOutcome(input.outcome_text);
    const quality = this.inferQuality(outcome, input.learned);
    const baseline_output: BaselineOutput = {
      trae_intent: input.intent,
      trae_actions: input.actions,
      trae_outcome: input.outcome_text,
      trae_learned: input.learned,
      ...(input.baseline_output || {}),
    };

    const payload = {
      ...input,
      outcome,
      quality,
      confidence: quality === 'B' ? 0.5 : quality === 'C' ? 0.3 : 0.7,
      layer_tags: input.layer_tags || this.inferLayerTags(input.actions),
      baseline_output,
      source: input.source || 'trae-session',
      capacity_limit: CAPACITY_LIMIT,
    };

    return this._callAdapter<{ id: string }>('store', payload);
  }

  /**
   * 检索相似案例
   */
  async retrieve(query: string, topK: number = 5): Promise<CaseBankResult<RetrieveResult>> {
    return this._callAdapter<RetrieveResult>('retrieve', { query, top_k: topK });
  }

  /**
   * TDR 统计
   */
  async stats(): Promise<CaseBankResult<CaseBankStats>> {
    return this._callAdapter<CaseBankStats>('stats', {});
  }

  /**
   * 从 outcome_text 推断结果分类
   */
  inferOutcome(outcomeText: string): OutcomeClass {
    const text = outcomeText.toLowerCase();
    if (text.includes('失败') || text.includes('错误') || text.includes('error') || text.includes('fail')) {
      return 'failure';
    }
    if (text.includes('部分') || text.includes('修改') || text.includes('partial') || text.includes('遗留')) {
      return 'partial';
    }
    if (text.includes('完成') || text.includes('成功') || text.includes('success') || text.includes('通过') || text.includes('done')) {
      return 'success';
    }
    return 'unknown';
  }

  /**
   * 从 outcome + learned 推断质量等级
   * SPEC §4.5: success+learned→B, failure+learned→C, partial+learned→B
   */
  inferQuality(outcome: OutcomeClass, learned: string[]): QualityLevel {
    if (learned.length === 0) return 'D' as QualityLevel; // 不会到这里（质量闸门拦截）
    if (outcome === 'failure') return 'C';
    if (outcome === 'success' || outcome === 'partial') return 'B';
    return 'C';
  }

  /**
   * 从 actions 推断分层标注
   */
  inferLayerTags(actions: string[]): LayerTag[] {
    const text = actions.join(' ').toLowerCase();
    const tags: LayerTag[] = [];

    // S 层：意图识别相关（几乎所有 case 都可供 S 层训练）
    tags.push({ layer: 'S', training_data: null, bucket_count: 0, bucket_threshold: LAYER_THRESHOLDS.S });

    // DSH 层：含执行动作
    if (text.includes('修改') || text.includes('创建') || text.includes('编辑') || text.includes('实现') || text.includes('执行')) {
      tags.push({ layer: 'DSH', training_data: null, bucket_count: 0, bucket_threshold: LAYER_THRESHOLDS.DSH });
    }

    // C 层：含反射/决策
    if (text.includes('检查') || text.includes('验证') || text.includes('分析') || text.includes('调研') || text.includes('对比')) {
      tags.push({ layer: 'C', training_data: null, bucket_count: 0, bucket_threshold: LAYER_THRESHOLDS.C });
    }

    // G 层：含图/结构
    if (text.includes('架构') || text.includes('结构') || text.includes('依赖') || text.includes('关系')) {
      tags.push({ layer: 'G', training_data: null, bucket_count: 0, bucket_threshold: LAYER_THRESHOLDS.G });
    }

    // LLM 层：含生成/推理
    if (text.includes('生成') || text.includes('推理') || text.includes('评估') || text.includes('总结')) {
      tags.push({ layer: 'LLM', training_data: null, bucket_count: 0, bucket_threshold: LAYER_THRESHOLDS.LLM });
    }

    return tags;
  }

  // ============================================================
  // 4. IPC 调用（复刻 cognitive-client.ts 模式）
  // ============================================================

  private _callAdapter<T>(toolName: string, args: Record<string, unknown>): Promise<CaseBankResult<T>> {
    return new Promise<CaseBankResult<T>>((resolve) => {
      let stdoutBuf = '';
      let stderrBuf = '';
      let settled = false;

      const child = spawn(this.pythonBin, [this.adapterPath, toolName, JSON.stringify(args)], {
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try { child.kill('SIGKILL'); } catch { /* noop */ }
        resolve({ ok: false, degraded: true, error: `timeout_${this.timeoutMs}ms` });
      }, this.timeoutMs);

      child.stdout.on('data', (chunk: Buffer) => { stdoutBuf += chunk.toString(); });
      child.stderr.on('data', (chunk: Buffer) => { stderrBuf += chunk.toString(); });

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
          const parsed = JSON.parse(lastLine) as CaseBankResult<T>;
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
}

// ============================================================
// 5. 单例
// ============================================================

let _instance: CaseBankClient | null = null;

export function getCaseBankClient(): CaseBankClient {
  if (!_instance) {
    _instance = new CaseBankClient();
  }
  return _instance;
}
