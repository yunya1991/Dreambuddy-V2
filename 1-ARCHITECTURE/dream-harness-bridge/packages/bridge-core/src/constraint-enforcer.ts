/**
 * F-02: 协议级不变式强制硬约束
 *
 * 职责:
 * 1. 识别交易路径方法（execute_node/open_position/close_position/modify_position）
 * 2. 交易路径强制检查 constraint_passed=true，缺失=false → 拒绝
 * 3. 非交易路径不检查 constraint_passed（FAIL-OPEN）
 * 4. 区分"约束失败"和"执行失败"（ok=false 但 constraint_passed=true = 放行）
 *
 * 来源: SPEC v0.3 七补.1 F-02
 * 调研: A3 契约式设计 + A7 FAIL-OPEN（分路径 fail 策略）
 *
 * 硬约束列表（DreamBuddy 20 条硬约束中与交易路径相关的）:
 * - BDSM direction_constraint (LONG_ONLY/SHORT_ONLY/NEUTRAL)
 * - BCRM2.0 MAX_TRIAL_POSITIONS = 2
 * - SL/TP 价格空间下限 (SL≥4%/TP≥12%)
 * - SL 爆仓安全边际约束
 * - 方案C 8 开关
 */

const TRADING_METHODS = new Set([
  "execute_node",
  "open_position",
  "close_position",
  "modify_position",
]);

export function isTradingMethod(method: string): boolean {
  return TRADING_METHODS.has(method);
}

export class ConstraintViolationError extends Error {
  code: string;
  violations: string[];

  constructor(code: string, message: string, violations: string[] = []) {
    super(message);
    this.name = "ConstraintViolationError";
    this.code = code;
    this.violations = violations;
  }
}

export interface IPCResponseLike {
  ok: boolean;
  constraint_passed?: boolean;
  result?: unknown;
  error?: { code: string; message: string };
}

/**
 * F-02: 强制硬约束检查
 *
 * 交易路径：
 *   - constraint_passed=true → 放行（不论 ok true/false）
 *   - constraint_passed 缺失或 false → 抛出 ConstraintViolationError（FAIL-CLOSED）
 *
 * 非交易路径：
 *   - 不检查 constraint_passed（FAIL-OPEN）
 */
export function enforceConstraint(
  method: string,
  response: IPCResponseLike
): void {
  if (!isTradingMethod(method)) {
    // 非交易路径：FAIL-OPEN，放行
    return;
  }

  // 交易路径：强制检查
  if (response.constraint_passed !== true) {
    // 检查是否是 CONSTRAINT_VIOLATION 错误
    const errorCode = response.error?.code ?? "MISSING_CONSTRAINT";
    const errorMsg =
      response.error?.message ??
      "交易路径缺少 constraint_passed=true（F-02 协议级硬约束）";

    throw new ConstraintViolationError(
      errorCode,
      `FAIL-CLOSED: 交易路径 [${method}] ${errorMsg}`,
      [errorMsg]
    );
  }

  // constraint_passed=true → 放行
  // 注意：ok=false 但 constraint_passed=true = 执行失败（非约束失败），放行
}
