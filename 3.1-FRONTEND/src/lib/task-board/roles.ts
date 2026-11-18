/**
 * 门禁角色（本地配置表，§11.8.9）。
 *
 * 角色来源优先取环境变量；全部未配置时进入 bootstrap 模式：
 * 本地单用户可自批，但会在审批记录里标记 bootstrap，便于生产前清理。
 * Agent 身份永远不属于任何角色。
 */

export type GateRole = "owner" | "team_lead" | "risk_reviewer" | "admin";

const ALL_ROLES: GateRole[] = ["owner", "team_lead", "risk_reviewer", "admin"];

type EnvLike = Record<string, string | undefined>;

export interface ResolvedRoles {
  email: string | null;
  roles: GateRole[];
  bootstrap: boolean;
}

export function parseEmailList(raw: string | undefined): string[] {
  return (raw || "")
    .split(/[,;\s]+/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

export function resolveGateRoles(
  email?: string | null,
  env: EnvLike = process.env,
): ResolvedRoles {
  const normalized = (email || "").trim().toLowerCase() || null;
  const teamLeads = parseEmailList(env.GATE_TEAM_LEADS);
  const riskReviewers = parseEmailList(env.GATE_RISK_REVIEWERS);
  const admins = parseEmailList(env.GATE_ADMINS);
  const configured = teamLeads.length + riskReviewers.length + admins.length > 0;

  if (!configured) {
    return { email: normalized, roles: [...ALL_ROLES], bootstrap: true };
  }

  if (!normalized) {
    return { email: null, roles: ["owner"], bootstrap: false };
  }

  const roles = new Set<GateRole>(["owner"]);
  if (teamLeads.includes(normalized)) roles.add("team_lead");
  if (riskReviewers.includes(normalized)) roles.add("risk_reviewer");
  if (admins.includes(normalized)) {
    roles.add("admin");
    roles.add("team_lead");
    roles.add("risk_reviewer");
  }

  return { email: normalized, roles: [...roles], bootstrap: false };
}

export function canApprove(
  roles: GateRole[],
  requiredRoles: string[],
): boolean {
  if (requiredRoles.length === 0) return false;
  return requiredRoles.some((role) =>
    roles.includes(role as GateRole),
  );
}
