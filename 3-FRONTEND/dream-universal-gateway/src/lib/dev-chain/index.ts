/**
 * S5 执行引擎 - 公共入口
 *
 * 定位：主前端策略代码开发专用，内部执行完整 E 链（E1→E2→E3）。
 * 与后端（6-Trading）的完整 D-Z-E 链不冲突，互为补充。
 *
 * 使用方式：
 *
 * ```ts
 * import { executeS5, renderS5Summary, S5_STEP_DEFINITIONS, S5_STEP_SEQUENCE } from './dev-chain';
 * ```
 */

export { executeS5, renderS5Summary } from './chain-controller';
export { S5_STEP_DEFINITIONS, S5_STEP_SEQUENCE, getS5StepDisplay, S5_ESTIMATED_TOTAL_MS, S5_ESTIMATED_TOTAL_CREDITS } from './route';
export type {
  S5StepId,
  S5StepStatus,
  S5StepRuntime,
  S5ChainState,
  S5StepDefinition,
  S5ExecutionContext,
  S5StepExecutionResult,
  S5ExecutionResult,
} from './types';
