/**
 * Hermes-Planner — 调度器统一入口（P0）
 * ============================================
 * 当前阶段：Cost Keeper + Skip Gate 上线
 * 后续阶段：Semantic Router → DAG 执行器 → Incremental Planning
 *
 * 对外暴露统一 API，方便 route.ts 接入
 */

export * from './cost-keeper';
export * from './skip-gate';

export interface PlannerConfig {
  enabled: boolean;
  logLevel?: 'silent' | 'summary' | 'verbose';
  defaultBudgetTokens?: number;
}

/**
 * 版本标识 — 用于日志 & 未来扩展
 */
export const PLANNER_VERSION = '0.1.0 (P0: CostKeeper + SkipGate)';
