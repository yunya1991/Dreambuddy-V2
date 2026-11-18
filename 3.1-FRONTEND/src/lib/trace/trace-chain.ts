/**
 * trace 贯穿校验（W5 T5.1）。
 * 目标：Ticket / verdict / memory / proposal 共用同一 trace_id，且父子引用可解析。
 * 纯函数，不读写存储。
 */

export type TraceArtifactType = "proposal" | "ticket" | "verdict" | "memory";

export interface TraceArtifact {
  type: TraceArtifactType;
  id: string;
  trace_id?: string;
  /** 上游制品 id；proposal 可指向 finding（finding:*） */
  parent_id?: string;
}

export type TraceIssueCode =
  | "invalid_input"
  | "missing_ticket_root"
  | "multiple_roots"
  | "missing_trace"
  | "trace_mismatch"
  | "duplicate_artifact"
  | "unknown_parent"
  | "invalid_lineage"
  | "cycle_detected";

export interface TraceIssue {
  code: TraceIssueCode;
  artifact_id: string;
  message: string;
}

export interface TraceChainResult {
  ok: boolean;
  trace_id: string;
  issues: TraceIssue[];
}

const ALLOWED_PARENTS: Record<TraceArtifactType, TraceArtifactType[]> = {
  proposal: [],
  ticket: ["proposal"],
  verdict: ["ticket"],
  memory: ["ticket", "verdict"],
};

export function validateTraceChain(artifacts: TraceArtifact[]): TraceChainResult {
  if (!Array.isArray(artifacts) || artifacts.length === 0) {
    return {
      ok: false,
      trace_id: "",
      issues: [{ code: "invalid_input", artifact_id: "", message: "制品为空" }],
    };
  }

  const issues: TraceIssue[] = [];
  const byId = new Map<string, TraceArtifact>();

  for (const a of artifacts) {
    if (!a || !a.id) {
      issues.push({ code: "invalid_input", artifact_id: "", message: "缺少 id" });
      continue;
    }
    if (byId.has(a.id)) {
      issues.push({
        code: "duplicate_artifact",
        artifact_id: a.id,
        message: "制品 id 重复",
      });
    }
    byId.set(a.id, a);
  }

  const roots = artifacts.filter(
    (a) =>
      (a.type === "ticket" || a.type === "proposal") &&
      (!a.parent_id ||
        (a.type === "proposal" && a.parent_id.startsWith("finding:"))),
  );
  if (roots.length === 0) {
    issues.push({
      code: "missing_ticket_root",
      artifact_id: "",
      message: "缺少 ticket/proposal 根节点",
    });
  } else if (roots.length > 1) {
    issues.push({
      code: "multiple_roots",
      artifact_id: roots.map((r) => r.id).join(","),
      message: "存在多个根节点",
    });
  }
  const rootTrace = roots[0]?.trace_id || "";

  for (const a of artifacts) {
    if (!a?.id) continue;
    if (!a.trace_id) {
      issues.push({
        code: "missing_trace",
        artifact_id: a.id,
        message: "缺少 trace_id",
      });
      continue;
    }
    if (rootTrace && a.trace_id !== rootTrace) {
      issues.push({
        code: "trace_mismatch",
        artifact_id: a.id,
        message: `trace_id ${a.trace_id} 与根 ${rootTrace} 不一致`,
      });
    }

    if (!a.parent_id) continue;
    const parent = byId.get(a.parent_id);
    if (!parent) {
      const externalFinding =
        a.type === "proposal" && a.parent_id.startsWith("finding:");
      if (!externalFinding) {
        issues.push({
          code: "unknown_parent",
          artifact_id: a.id,
          message: `父节点 ${a.parent_id} 不存在`,
        });
      }
      continue;
    }
    const allowed = ALLOWED_PARENTS[a.type] || [];
    if (!allowed.includes(parent.type)) {
      issues.push({
        code: "invalid_lineage",
        artifact_id: a.id,
        message: `${a.type} 不能挂在 ${parent.type} 下`,
      });
    }
  }

  if (hasCycle(artifacts)) {
    issues.push({
      code: "cycle_detected",
      artifact_id: "",
      message: "父子引用成环",
    });
  }

  return { ok: issues.length === 0, trace_id: rootTrace, issues };
}

function hasCycle(artifacts: TraceArtifact[]): boolean {
  const parentOf = new Map<string, string>();
  for (const a of artifacts) {
    if (a?.id && a.parent_id) parentOf.set(a.id, a.parent_id);
  }
  for (const id of parentOf.keys()) {
    const seen = new Set<string>();
    let cur: string | undefined = id;
    while (cur) {
      if (seen.has(cur)) return true;
      seen.add(cur);
      cur = parentOf.get(cur);
    }
  }
  return false;
}
