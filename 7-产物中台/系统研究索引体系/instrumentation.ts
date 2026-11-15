// ============================================================================
// 启动自检（SPEC-7 §12.1 / ADR-9）
// ----------------------------------------------------------------------------
// Next.js instrumentation hook：进程启动时执行一次三重写门禁评估，
// 不满足条件只告警 + 关闭写能力（UI 退化为只读），绝不静默放开写入。
// ============================================================================

export async function register() {
  // Edge runtime 不执行（管理台只在 Node 运行时写库）
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const { evaluateWriteGate } = await import("./lib/admin/gate");
  const gate = evaluateWriteGate();

  if (gate.enabled) {
    console.log(
      `[admin-write-gate] 写能力已启用 | INSTANCE_ROLE=${gate.instanceRole} dbHost=${gate.dbHost}`,
    );
    return;
  }

  console.error(
    "[admin-write-gate] 写能力已禁用（只读模式）：\n" +
      gate.reasons.map((r) => `  - ${r}`).join("\n"),
  );

  // 密钥缺失同样是致命配置错误，提前暴露而不是等到首个请求
  const secret = process.env.ADMIN_AUTH_SECRET;
  if (!secret || secret.length < 32) {
    console.error(
      "[admin-write-gate] ADMIN_AUTH_SECRET 缺失或不足 32 位：管理台登录将不可用",
    );
  }
}
