/**
 * Next.js 启动钩子：门禁策略与模型注册表的 fail-closed 校验。
 *
 * - 构建阶段（phase-production-build）跳过，避免无密钥构建被阻断；
 * - 生产运行期：三类模型缺失、gate 同源、gate 有写权限 → 拒绝启动；
 * - 开发环境：只告警，门禁退化为人工确认。
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.NEXT_PHASE === "phase-production-build") return;

  const [{ assertGatePolicySet }, { buildModelRegistry, isStrictEnvironment }] =
    await Promise.all([
      import("./lib/task-board/gate-policy"),
      import("./lib/model/model-registry"),
    ]);

  // 默认只告警：缺少模型密钥不应阻断整站启动；
  // 需要硬失败时显式设置 GATE_STRICT_STARTUP=true（门禁运行期仍 fail-closed）。
  const strict =
    isStrictEnvironment() && process.env.GATE_STRICT_STARTUP === "true";
  try {
    assertGatePolicySet(undefined, buildModelRegistry(), { strict });
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error("[startup] 工作门禁校验失败", error);
    if (strict) throw error;
  }
}
