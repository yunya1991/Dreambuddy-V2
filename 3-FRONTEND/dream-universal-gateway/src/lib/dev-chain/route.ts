/**
 * S5 执行引擎 - 步骤定义
 *
 * S5_EXECUTE = 完整的 E 链（E1 → E2 → E3）
 *   E1_TASK_EXECUTE：任务执行 - 生成策略代码
 *   E2_TEST_VALIDATE：测试验证 - 运行测试验证代码正确性
 *   E3_DEPLOY_DELIVER：部署交付 - 部署到运行环境
 *
 * 与后端（6-Trading）的 D-Z-E 链不冲突：
 *   - 前端 S5 链 = 精简版 E 链（仅策略代码相关）
 *   - 后端 D-Z-E = 完整的代码治理链（调研/规划/执行全流程）
 */

import { S5StepId, S5StepDefinition } from './types';

// ============================================================
// 步骤定义（E1→E2→E3）
// ============================================================
export const S5_STEP_DEFINITIONS: Record<S5StepId, S5StepDefinition> = {
  E1_TASK_EXECUTE: {
    id: 'E1_TASK_EXECUTE',
    label: 'E1 策略代码生成',
    icon: '⚡',
    description: '根据 S3/S4 的策略设计，生成可执行的策略代码',
    estimatedTimeMs: 60000,
    estimatedCredits: 150,
    requiresUserConfirmation: false,
    requiresWorkBuddy: true,
  },

  E2_TEST_VALIDATE: {
    id: 'E2_TEST_VALIDATE',
    label: 'E2 测试验证',
    icon: '🧪',
    description: '运行测试套件，验证策略代码的语法、参数和基本逻辑正确性',
    estimatedTimeMs: 45000,
    estimatedCredits: 100,
    requiresUserConfirmation: false,
    requiresWorkBuddy: true,
  },

  E3_DEPLOY_DELIVER: {
    id: 'E3_DEPLOY_DELIVER',
    label: 'E3 部署交付',
    icon: '🚀',
    description: '部署策略代码到运行环境，生成执行文档并交付',
    estimatedTimeMs: 30000,
    estimatedCredits: 80,
    requiresUserConfirmation: false,
    requiresWorkBuddy: true,
  },
};

// ============================================================
// 步骤序列（S5 内部执行顺序）
// ============================================================
export const S5_STEP_SEQUENCE: S5StepId[] = [
  'E1_TASK_EXECUTE',
  'E2_TEST_VALIDATE',
  'E3_DEPLOY_DELIVER',
];

// ============================================================
// 快捷查询
// ============================================================
export function getS5StepDisplay(stepId: S5StepId): {
  label: string;
  icon: string;
  description: string;
} {
  const def = S5_STEP_DEFINITIONS[stepId];
  return {
    label: def?.label || stepId,
    icon: def?.icon || '📋',
    description: def?.description || '',
  };
}

// 用于前端展示的"总步骤数/预估耗时"
export const S5_ESTIMATED_TOTAL_MS =
  S5_STEP_SEQUENCE.reduce((sum, sid) => sum + (S5_STEP_DEFINITIONS[sid]?.estimatedTimeMs || 0), 0);

export const S5_ESTIMATED_TOTAL_CREDITS =
  S5_STEP_SEQUENCE.reduce((sum, sid) => sum + (S5_STEP_DEFINITIONS[sid]?.estimatedCredits || 0), 0);
