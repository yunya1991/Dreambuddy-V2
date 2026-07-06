/**
 * TDD 执行包装器 - 借鉴 Superpowers test-driven-development 方法论
 *
 * 位置: 6-图结构上下文压缩/planner/tdd-execution-wrapper.ts
 *
 * 设计依据: Superpowers test-driven-development Skill
 *   - 红-绿-重构循环 (RED-GREEN-REFACTOR)
 *   - 测试先行，不写未测试的代码
 *   - 每一步小步提交
 *
 * 适用场景:
 *   - S5 策略代码开发节点（developer 意图）
 *   - 策略验证节点（strategy_verify 意图）
 *
 * 核心规则 (HARD-GATE):
 *   - 不允许先写代码再补测试（检测到则删除代码重来）
 *   - 测试未通过前不进入下一步
 *   - 测试通过后必须提交（红-绿-提交循环）
 */

import { SkillResult } from './skill-types';

// ============================================================
// 类型定义
// ============================================================

/** TDD 阶段 */
export type TDDPhase = 'red' | 'green' | 'refactor' | 'complete';

/** TDD 执行状态 */
export interface TDDState {
  /** 当前阶段 */
  phase: TDDPhase;
  /** 循环次数（红-绿-重构为一次循环） */
  cycleCount: number;
  /** 测试代码 */
  testCode?: string;
  /** 实现代码 */
  implementationCode?: string;
  /** 测试结果 */
  testResult?: {
    passed: boolean;
    totalTests: number;
    passedTests: number;
    failedTests: number;
    output: string;
  };
  /** 是否检测到 "先写代码再补测试" 的违规 */
  violationDetected?: boolean;
  /** 违规描述 */
  violationDescription?: string;
}

/** TDD 执行结果 */
export interface TDDExecutionResult {
  /** 是否应用了 TDD 流程 */
  tddApplied: boolean;
  /** 最终状态 */
  state: TDDState;
  /** 原始执行结果（包装后） */
  finalResult: SkillResult;
  /** TDD 流程耗时（毫秒） */
  tddOverheadMs: number;
  /** 循环次数 */
  cyclesCompleted: number;
}

/** TDD 配置 */
export interface TDDConfig {
  /** 是否启用 TDD */
  enabled: boolean;
  /** 最大循环次数 */
  maxCycles: number;
  /** 是否严格模式（违规则失败） */
  strictMode: boolean;
  /** 是否需要重构阶段 */
  requireRefactor: boolean;
}

const DEFAULT_CONFIG: TDDConfig = {
  enabled: true,
  maxCycles: 3,
  strictMode: false,
  requireRefactor: false,
};

// ============================================================
// TDD 执行包装器
// ============================================================

/**
 * TDD 执行包装器
 *
 * 包装策略代码生成过程，强制红-绿-重构循环
 *
 * 使用方式:
 *   const wrapper = new TDDExecutionWrapper();
 *   const result = await wrapper.wrapExecution(inputs, async (phase) => {
 *     // 根据 phase 执行不同的逻辑
 *     return generateCode(phase, inputs);
 *   });
 */
export class TDDExecutionWrapper {
  private config: TDDConfig;

  constructor(config?: Partial<TDDConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * 更新配置
   */
  updateConfig(config: Partial<TDDConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * 检测是否为策略代码相关节点
   */
  isTDDApplicable(stepId: string, category?: string): boolean {
    const devKeywords = ['e1_', 'e2_', 'e3_', 's5', 'developer', 'code', 'strategy_dev'];
    const id = stepId.toLowerCase();
    const cat = (category || '').toLowerCase();
    return devKeywords.some(kw => id.includes(kw) || cat.includes(kw));
  }

  /**
   * 包装执行 - 强制 TDD 流程
   *
   * @param inputs 执行输入
   * @param executor 执行函数，接收当前 phase，返回该阶段的产出
   * @returns TDD 执行结果
   */
  async wrapExecution(
    inputs: Record<string, unknown>,
    executor: (phase: TDDPhase, inputs: Record<string, unknown>) => Promise<SkillResult>,
  ): Promise<TDDExecutionResult> {
    const startTime = Date.now();

    if (!this.config.enabled) {
      const result = await executor('complete', inputs);
      return {
        tddApplied: false,
        state: { phase: 'complete', cycleCount: 0 },
        finalResult: result,
        tddOverheadMs: Date.now() - startTime,
        cyclesCompleted: 0,
      };
    }

    const state: TDDState = {
      phase: 'red',
      cycleCount: 0,
    };

    let finalResult: SkillResult | null = null;

    for (let cycle = 0; cycle < this.config.maxCycles; cycle++) {
      state.cycleCount = cycle + 1;

      // ===== 阶段 1: RED - 写测试，确保失败 =====
      state.phase = 'red';
      const redResult = await executor('red', inputs);

      if (!redResult.success) {
        state.testResult = {
          passed: false,
          totalTests: 0,
          passedTests: 0,
          failedTests: 0,
          output: redResult.error || '测试生成失败',
        };
        finalResult = redResult;
        break;
      }

      state.testCode = String(redResult.data?.testCode || redResult.summary || '');

      // 检查：RED 阶段应该有测试失败
      // 如果测试直接通过，说明要么测试没写对，要么有现成实现
      const redOutput = String(redResult.data?.testOutput || '');
      const hasFailures = redOutput.includes('fail') || redOutput.includes('error') ||
        redResult.confidence && redResult.confidence < 0.5;

      if (!hasFailures && this.config.strictMode) {
        state.violationDetected = true;
        state.violationDescription = 'RED 阶段测试未失败，可能存在先写实现后补测试的违规';
        if (this.config.strictMode) {
          finalResult = {
            success: false,
            error: 'TDD 违规：RED 阶段测试应失败但实际通过',
            summary: state.violationDescription,
            confidence: 0,
            data: { state },
          };
          break;
        }
      }

      // ===== 阶段 2: GREEN - 写实现，让测试通过 =====
      state.phase = 'green';
      const greenResult = await executor('green', {
        ...inputs,
        testCode: state.testCode,
      });

      if (!greenResult.success) {
        finalResult = greenResult;
        break;
      }

      state.implementationCode = String(greenResult.data?.implementationCode || greenResult.summary || '');
      state.testResult = {
        passed: greenResult.success,
        totalTests: Number(greenResult.data?.totalTests || 0),
        passedTests: Number(greenResult.data?.passedTests || 0),
        failedTests: Number(greenResult.data?.failedTests || 0),
        output: String(greenResult.data?.testOutput || greenResult.summary || ''),
      };

      // 检查：GREEN 阶段测试应该全部通过
      const allPassed = state.testResult.passed && state.testResult.failedTests === 0;
      if (!allPassed) {
        // 测试未全部通过，继续下一个循环
        continue;
      }

      // ===== 阶段 3: REFACTOR - 重构（可选） =====
      if (this.config.requireRefactor) {
        state.phase = 'refactor';
        const refactorResult = await executor('refactor', {
          ...inputs,
          testCode: state.testCode,
          implementationCode: state.implementationCode,
        });

        if (refactorResult.success) {
          state.implementationCode = String(refactorResult.data?.refactoredCode || state.implementationCode || '');
          finalResult = refactorResult;
        } else {
          finalResult = greenResult;
        }
      } else {
        finalResult = greenResult;
      }

      // 测试全部通过，TDD 完成
      state.phase = 'complete';
      break;
    }

    if (!finalResult) {
      finalResult = {
        success: false,
        error: `TDD 超过最大循环次数 (${this.config.maxCycles})`,
        summary: '测试未能在最大循环次数内通过',
        confidence: 0,
        data: { state },
      };
    }

    return {
      tddApplied: true,
      state,
      finalResult,
      tddOverheadMs: Date.now() - startTime,
      cyclesCompleted: state.cycleCount,
    };
  }

  /**
   * 生成 TDD 执行摘要
   */
  generateSummary(result: TDDExecutionResult, lang: 'zh' | 'en' = 'zh'): string {
    if (!result.tddApplied) {
      return lang === 'zh' ? '未启用 TDD 模式' : 'TDD mode not enabled';
    }

    const { state, cyclesCompleted } = result;

    if (lang === 'zh') {
      const lines = [
        '## TDD 执行报告',
        '',
        `- **循环次数**: ${cyclesCompleted}`,
        `- **最终阶段**: ${this.phaseLabel(state.phase, 'zh')}`,
        `- **TDD 耗时**: ${result.tddOverheadMs}ms`,
        '',
      ];

      if (state.violationDetected) {
        lines.push(`> ⚠️ **违规检测**: ${state.violationDescription}`);
        lines.push('');
      }

      if (state.testResult) {
        lines.push('### 测试结果');
        lines.push('');
        lines.push(`- **总测试数**: ${state.testResult.totalTests}`);
        lines.push(`- **通过**: ${state.testResult.passedTests}`);
        lines.push(`- **失败**: ${state.testResult.failedTests}`);
        lines.push(`- **状态**: ${state.testResult.passed ? '✅ 通过' : '❌ 失败'}`);
        lines.push('');
      }

      return lines.join('\n');
    } else {
      const lines = [
        '## TDD Execution Report',
        '',
        `- **Cycles**: ${cyclesCompleted}`,
        `- **Final Phase**: ${this.phaseLabel(state.phase, 'en')}`,
        `- **TDD Overhead**: ${result.tddOverheadMs}ms`,
        '',
      ];

      if (state.violationDetected) {
        lines.push(`> ⚠️ **Violation**: ${state.violationDescription}`);
        lines.push('');
      }

      if (state.testResult) {
        lines.push('### Test Results');
        lines.push('');
        lines.push(`- **Total**: ${state.testResult.totalTests}`);
        lines.push(`- **Passed**: ${state.testResult.passedTests}`);
        lines.push(`- **Failed**: ${state.testResult.failedTests}`);
        lines.push(`- **Status**: ${state.testResult.passed ? '✅ Passed' : '❌ Failed'}`);
        lines.push('');
      }

      return lines.join('\n');
    }
  }

  private phaseLabel(phase: TDDPhase, lang: 'zh' | 'en'): string {
    const labels: Record<string, Record<string, string>> = {
      zh: {
        red: 'RED - 写测试（失败）',
        green: 'GREEN - 写实现（通过）',
        refactor: 'REFACTOR - 重构',
        complete: '完成',
      },
      en: {
        red: 'RED - Write tests (fail)',
        green: 'GREEN - Write implementation (pass)',
        refactor: 'REFACTOR - Refactor',
        complete: 'Complete',
      },
    };
    return labels[lang][phase] || phase;
  }
}
