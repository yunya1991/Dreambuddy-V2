import type { OrgNode, OrgTreeData } from './org-types';

/**
 * Three-state color system for org nodes
 * 🟢 GREEN (#639922) → completed/active
 * 🟡 AMBER (#BA7517) → in_progress/waiting
 * 🔴 RED   (#E24B4A) → rejected/blocked/error
 * ⚪ GRAY  (#888780) → idle/unknown
 */
export type NodeColor = 'green' | 'amber' | 'red' | 'gray';

export const STATUS_COLORS: Record<NodeColor, string> = {
  green: '#639922',
  amber: '#BA7517',
  red: '#E24B4A',
  gray: '#888780',
};

export const STATUS_LABELS: Record<NodeColor, string> = {
  green: '正常',
  amber: '等待',
  red: '异常',
  gray: '待机',
};

/**
 * Infer node status from production artifacts (chain_phase matching)
 * Level 1: Product-based inference
 */
export function inferNodeStatus(
  node: OrgNode,
  artifactsByPhase: Record<string, { status: string; date: string }[]>
): { color: NodeColor; reason: string } {
  const chainPhaseId = node.id;

  // Special node IDs that map to specific phases
  const phaseMap: Record<string, string> = {
    A1: 'A1', A2: 'A2', A3: 'A3', A4: 'A4', A5: 'A5',
    A6: 'A6', A7: 'A7', A8: 'A8', A9: 'A9',
  };

  const phase = phaseMap[chainPhaseId] || chainPhaseId;
  const artifacts = artifactsByPhase[phase];

  if (!artifacts || artifacts.length === 0) {
    return { color: 'gray', reason: '无产物(待启动)' };
  }

  // Check for today's products
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  const todayArtifacts = artifacts.filter((a) => {
    try {
      const d = new Date(a.date);
      return d >= todayStart;
    } catch {
      return false;
    }
  });

  // Check for completed products
  const completed = artifacts.filter((a) => a.status === 'completed');
  const inProgress = artifacts.filter((a) => a.status === 'in_progress');
  const rejected = artifacts.filter((a) => a.status === 'rejected');

  if (rejected.length > 0) {
    return { color: 'red', reason: `${rejected.length}个产物被拒绝` };
  }

  if (todayArtifacts.length > 0) {
    const todayCompleted = todayArtifacts.filter((a) => a.status === 'completed');
    if (todayCompleted.length > 0) {
      return { color: 'green', reason: `今日${todayCompleted.length}个产物已完成` };
    }
    if (todayArtifacts.some((a) => a.status === 'in_progress')) {
      return { color: 'amber', reason: '今日有产物执行中' };
    }
  }

  if (inProgress.length > 0) {
    return { color: 'amber', reason: `${inProgress.length}个产物执行中` };
  }

  if (completed.length > 0) {
    const latest = completed[0]; // sorted by date desc
    const daysAgo = Math.floor(
      (now.getTime() - new Date(latest.date).getTime()) / (1000 * 60 * 60 * 24)
    );
    if (daysAgo <= 1) {
      return { color: 'green', reason: `最近${daysAgo}天前完成` };
    }
    return { color: 'gray', reason: `${daysAgo}天前完成(需刷新)` };
  }

  return { color: 'gray', reason: '待运行' };
}

/**
 * Build artifacts-by-phase index for status inference
 */
export function buildPhaseIndex(
  artifacts: { chain_phase: string; status: string; date: string }[]
): Record<string, { status: string; date: string }[]> {
  const index: Record<string, { status: string; date: string }[]> = {};

  for (const a of artifacts) {
    if (a.chain_phase) {
      if (!index[a.chain_phase]) {
        index[a.chain_phase] = [];
      }
      index[a.chain_phase].push({ status: a.status, date: a.date });
    }
  }

  // Sort each phase by date descending
  for (const phase of Object.keys(index)) {
    index[phase].sort((a, b) => {
      if (a.date === 'unknown') return 1;
      if (b.date === 'unknown') return -1;
      return b.date.localeCompare(a.date);
    });
  }

  return index;
}

/**
 * Apply status inference to all nodes in org tree
 */
export function applyStatusInference(
  data: OrgTreeData,
  artifacts: { chain_phase: string; status: string; date: string }[]
): OrgTreeData {
  const phaseIndex = buildPhaseIndex(artifacts);
  const company = { ...data.company };

  company.departments = company.departments.map((dept) => ({
    ...dept,
    subsystems: dept.subsystems.map((sub) => ({
      ...sub,
      nodes: sub.nodes.map((node) => {
        const inferred = inferNodeStatus(node, phaseIndex);
        return {
          ...node,
          inferredStatus: inferred.color,
          inferredReason: inferred.reason,
        };
      }),
    })),
  }));

  return { ...data, company };
}

/**
 * Get all node paths for static generation
 */
export function getAllNodePaths(data: OrgTreeData): { dept: string; sub: string; node: string }[] {
  const paths: { dept: string; sub: string; node: string }[] = [];
  for (const dept of data.company.departments) {
    for (const sub of dept.subsystems) {
      for (const node of sub.nodes) {
        paths.push({ dept: dept.id, sub: sub.id, node: node.id });
      }
    }
  }
  return paths;
}
