import { NextRequest, NextResponse } from "next/server";
import {
  buildModelRegistry,
  isStrictEnvironment,
  validateModelRegistry,
} from "@/lib/model/model-registry";
import {
  DEFAULT_GATE_POLICIES,
  getGateMode,
  validateGatePolicies,
} from "@/lib/task-board/gate-policy";
import { loadGateClientConfig, probeGateModel } from "@/lib/model/gate-client";
import { loadJevClientConfig, probeJevModel } from "@/lib/model/jev-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/gate/health — 门禁配置与模型连通性自检。
 *
 * 默认只做静态校验（不产生模型调用费用）；
 * `?probe=1` 时调用一次门禁模型，验证凭据与输出契约。
 */
export async function GET(request: NextRequest) {
  const probe = request.nextUrl.searchParams.get("probe") === "1";
  const registry = buildModelRegistry();
  const issues = [
    ...validateGatePolicies(DEFAULT_GATE_POLICIES),
    ...validateModelRegistry(registry, { strict: isStrictEnvironment() }),
  ];
  const config = loadGateClientConfig();
  const jevConfig = loadJevClientConfig();

  const gate = probe
    ? await probeGateModel()
    : {
        configured: Boolean(config),
        ok: Boolean(config),
        model: config?.model ?? null,
      };
  const jev = probe
    ? await probeJevModel()
    : {
        configured: Boolean(jevConfig),
        ok: Boolean(jevConfig),
        model: jevConfig?.model ?? null,
      };

  const brief = (spec: typeof registry.worker) =>
    spec ? { id: spec.id, family: spec.family } : null;

  return NextResponse.json({
    success: !issues.some((issue) => issue.level === "error"),
    strict: isStrictEnvironment(),
    mode: getGateMode(),
    models: {
      worker: brief(registry.worker),
      judge: brief(registry.judge),
      gate: brief(registry.gate),
      gate_secondary: brief(registry.gate_secondary),
    },
    gate,
    jev,
    issues,
  });
}
