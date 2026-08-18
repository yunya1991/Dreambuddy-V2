// ---- Org Tree Types ----
export interface OrgNode {
  id: string;
  name: string;
  skill?: string;
  description?: string;
  version?: string;
  status: 'idle' | 'active' | 'blocked' | 'error' | 'completed';
  // Inferred status
  inferredStatus?: 'green' | 'amber' | 'red' | 'gray';
  inferredReason?: string;
  // Associated artifacts
  recentArtifacts?: string[];
}

export interface OrgSubsystem {
  id: string;
  name: string;
  nodes: OrgNode[];
  node_count: number;
}

export interface OrgDepartment {
  id: string;
  name: string;
  subsystems: OrgSubsystem[];
  node_count: number;
}

export interface OrgCompany {
  name: string;
  departments: OrgDepartment[];
  total_nodes: number;
}

export interface OrgTreeData {
  company: OrgCompany;
  stats: {
    total_skills: number;
    in_org_tree: number;
    utility: number;
    unclassified: number;
    has_frontmatter: number;
    missing_frontmatter: string[];
  };
  all_skills: Record<string, SkillInfo>;
}

export interface SkillInfo {
  name: string;
  description: string;
  version: string;
  has_frontmatter: boolean;
  department: string;
  in_org_tree: boolean;
}

// ---- Artifact Index (for status inference) ----
export interface ArtifactIndex {
  id: string;
  title: string;
  department: string;
  type: string;
  date: string;
  status: string;
  chain_phase: string;
  url: string;
  tags: string;
}
