/**
 * Intent Module - 统一意图识别与智能路由 + 记忆库
 * 导出所有 intent 相关功能
 */

export {
  recognizeIntent,
  checkLLMStatus,
  DEEPSEEK_CONFIG,
  extractEntities,
} from './fallback-engine';

export type {
  IntentType,
  ComplexityLevel,
  SessionContext,
  IntentRecognitionResult,
  ExperiencePattern,
  LLMConfig,
} from './fallback-engine';

// ============ routeIntent：DreamOS 桥接包装（20260829-bridge S3）============
// flag 默认关 → 行为与原版 100% 一致（纯透传）；
// DREAMOS_BRIDGE_ENABLED=true 时，intelligence 环分析意图的决策
// 会附加 decision.dreamos 指令，消费方改走 /api/dreamos 物理编排。
import { routeIntent as routeIntentRaw } from './smart-router';
import type {
  IntentType as _IntentType,
  ComplexityLevel as _ComplexityLevel,
  SessionContext as _SessionContext,
} from './fallback-engine';
import type { RoutingDecision as _RoutingDecision } from './smart-router';
import { attachDreamOSDirective } from '../dreamos/bridge';

export function routeIntent(
  intent: _IntentType,
  complexity: _ComplexityLevel,
  context?: _SessionContext,
): _RoutingDecision {
  const decision = routeIntentRaw(intent, complexity, context);
  return attachDreamOSDirective(decision, String(intent));
}

export {
  downgradeChain,
  getLoopColor,
  getLoopLabel,
  normalizeChainName,
  CHAIN_STEPS,
  requiresStepConfirmation,
  isExecutionChainStep,
  generateStepConfirmationPrompt,
  getNextConfirmationStep,
  parseUserConfirmation,
} from './smart-router';

export type {
  LoopType,
  RoutingDecision,
  ExecMode,
} from './smart-router';

// Memory Bank
export {
  recordRecognition,
  recordFeedback,
  getMemoryRecords,
  getMemoryStats,
  getCandidatePatterns,
  getConfidenceAdjustments,
  applyAdjustments,
  adoptCandidate,
  loadExperienceMemory,
  updateLastRoutingChain,
} from './intent-memory';

export type {
  IntentMemoryRecord,
  CandidatePattern,
  ConfidenceAdjustment,
  IntentMemoryStats,
} from './intent-memory';
