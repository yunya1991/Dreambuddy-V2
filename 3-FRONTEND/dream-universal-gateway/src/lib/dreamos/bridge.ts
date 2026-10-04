/**
 * bridge.ts — DreamOS 桥接胶水层（S3/S4 接线点）
 * 20260829-bridge
 *
 * 职责：把「网关意图识别结果」转成「是否走 DreamOS 物理编排」的决策。
 * 接线方式：src/lib/intent/index.ts 的 routeIntent barrel 包装调用本模块，
 *   feature flag 默认关（DREAMOS_BRIDGE_ENABLED=true 才启用），灰度安全。
 *
 * 纪律：纯函数、零副作用、不 import 运行时业务模块（仅类型）。
 */
import type { RoutingDecision } from "@/lib/intent/smart-router";
import {
  lookupDreamOSDirective,
  type DreamOSDirective,
} from "./intent-canon-map";
import type { DreamOSIntentHint } from "./client";

/** 挂在 RoutingDecision.dreamos 上的桥接指令 */
export interface DreamOSBridgeDirective {
  eligible: true;
  intent_hint: DreamOSIntentHint;
  canon_intent: string;
  note: string;
}

/** feature flag：默认关，灰度开启用 DREAMOS_BRIDGE_ENABLED=true */
export function isDreamOSBridgeEnabled(): boolean {
  return process.env.DREAMOS_BRIDGE_ENABLED === "true";
}

/**
 * 核心匹配：意图 → DreamOS 指令（含 flag 判定）。
 * @param intentType 网关正典意图名
 * @param confidence 意图置信度（透传给 DreamOS 作 intent_hint.confidence）
 */
export function matchDreamOSDirective(
  intentType: string,
  confidence = 0.85,
): DreamOSBridgeDirective | null {
  if (!isDreamOSBridgeEnabled()) return null;
  const d: DreamOSDirective | null = lookupDreamOSDirective(intentType, confidence);
  if (!d) return null;
  return {
    eligible: true,
    intent_hint: {
      intent_type: d.intent_type,
      confidence: d.confidence,
      chain: d.chain,
      provenance: "frontend_canon",
      canon_intent: d.canon_intent,
    },
    canon_intent: d.canon_intent,
    note: d.note,
  };
}

/**
 * 给既有 RoutingDecision 附加 DreamOS 指令（不可变：返回新对象）。
 * 不满足条件时原样返回。
 */
export function attachDreamOSDirective(
  decision: RoutingDecision,
  intentType: string,
  confidence = 0.85,
): RoutingDecision {
  const directive = matchDreamOSDirective(intentType, confidence);
  if (!directive) return decision;
  return { ...decision, dreamos: directive };
}
