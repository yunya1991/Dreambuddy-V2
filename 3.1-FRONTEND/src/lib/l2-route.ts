/**
 * L2 路线选择（认知裁决产物，SPEC-56 IF-1 / SPEC-v1.4 §3.4，P1-1 trace 侧）。
 *
 * Python 侧 `56/runtime/l2_route.py` 依据 `cognition_signal`（覆盖度 + 域内外）
 * 产出 `retrieval_augmented` / `deep_reasoning`；前端只做**枚举收敛与透传**，
 * 不重新裁决，缺省/非法值统一记 `unspecified`（不猜）。
 */

export const L2_ROUTE_RETRIEVAL = "retrieval_augmented";
export const L2_ROUTE_DEEP = "deep_reasoning";
export const L2_ROUTE_UNSPECIFIED = "unspecified";

export type L2Route = typeof L2_ROUTE_RETRIEVAL | typeof L2_ROUTE_DEEP;
export type TraceL2Route = L2Route | typeof L2_ROUTE_UNSPECIFIED;

/** 收敛任意输入为合法路线；未知一律 unspecified。 */
export function normalizeL2Route(value: unknown): TraceL2Route {
  return value === L2_ROUTE_RETRIEVAL || value === L2_ROUTE_DEEP
    ? value
    : L2_ROUTE_UNSPECIFIED;
}

/** 从 route_signal（含 cognition_signal）读取 L2 路线；缺失/非法 → unspecified。 */
export function l2RouteFromRouteSignal(signal: unknown): TraceL2Route {
  if (typeof signal !== "object" || signal === null) return L2_ROUTE_UNSPECIFIED;
  const cognition = (signal as Record<string, unknown>).cognition_signal;
  if (typeof cognition !== "object" || cognition === null) return L2_ROUTE_UNSPECIFIED;
  return normalizeL2Route((cognition as Record<string, unknown>).l2_route);
}
