/**
 * CaseVerifyBridge — SPL 案例验证认知闭环桥接
 * ==========================================
 * SPEC-20261009 §10 P4-3
 *
 * 认知闭环接入：case verify → cognitive verify
 *
 * 职责：
 *   1. 案例执行后，将结果 verify 到认知系统（贝叶斯置信度更新）
 *   2. 新经验/反模式 record 到认知系统
 *   3. FAIL-OPEN: 认知系统不可用时不影响主链路
 *
 * 位置: 3.1-FRONTEND/src/lib/case-verify-bridge.ts
 */

import { callCognitive } from './cognitive-client';

// ============================================================
// 1. 类型定义
// ============================================================

export interface VerifyInput {
  memory_id: string;
  success: boolean;
}

export interface VerifyResult {
  memory_id: string;
  verified: boolean;
  confidence?: number;
  error?: string;
}

export interface RecordInput {
  content: string;
  quality_level: 'S' | 'A' | 'B' | 'C' | 'D';
  tags: string;
}

export interface RecordResult {
  recorded: boolean;
  memory_id?: string;
  error?: string;
}

// ============================================================
// 2. CaseVerifyBridge 主类
// ============================================================

export class CaseVerifyBridge {
  /**
   * 验证案例（case verify → cognitive verify）
   * 触发贝叶斯置信度更新和动态蒸馏
   */
  async verifyCase(input: VerifyInput): Promise<VerifyResult> {
    try {
      const result = await callCognitive<Record<string, unknown>>('verify', {
        memory_id: input.memory_id,
        success: input.success,
      });

      if (!result.ok) {
        return {
          memory_id: input.memory_id,
          verified: false,
          error: result.error,
        };
      }

      return {
        memory_id: input.memory_id,
        verified: true,
        confidence: typeof result.data?.confidence === 'number' ? result.data.confidence : undefined,
      };
    } catch (e) {
      // FAIL-OPEN: 认知系统不可用不影响主链路
      return {
        memory_id: input.memory_id,
        verified: false,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  }

  /**
   * 批量验证案例
   */
  async verifyCases(inputs: VerifyInput[]): Promise<VerifyResult[]> {
    return Promise.all(inputs.map((input) => this.verifyCase(input)));
  }

  /**
   * 记录新经验/反模式到认知系统
   */
  async recordCase(input: RecordInput): Promise<RecordResult> {
    try {
      const result = await callCognitive<{ id?: string }>('record', {
        content: input.content,
        quality_level: input.quality_level,
        tags: input.tags,
      });

      if (!result.ok) {
        return { recorded: false, error: result.error };
      }

      return {
        recorded: true,
        memory_id: result.data?.id,
      };
    } catch (e) {
      return {
        recorded: false,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  }
}

// ============================================================
// 3. 单例
// ============================================================

let _instance: CaseVerifyBridge | null = null;

export function getCaseVerifyBridge(): CaseVerifyBridge {
  if (!_instance) _instance = new CaseVerifyBridge();
  return _instance;
}
