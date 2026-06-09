/**
 * Intent Module - 统一意图识别与智能路由 + 记忆库
 * 导出所有 intent 相关功能
 */

export {
  recognizeIntent,
  checkLLMStatus,
  QWEN_CONFIG,
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

export {
  routeIntent,
  downgradeChain,
  getLoopColor,
  getLoopLabel,
  normalizeChainName,
  CHAIN_STEPS,
} from './smart-router';

export type {
  LoopType,
  RoutingDecision,
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
