// ---- Status Types ----
export type ArtifactStatus = 'completed' | 'in_progress' | 'rejected' | 'unknown';

// ---- Department Types ----
export type DepartmentId =
  | 'trading'
  | 'dream'
  | 'governance'
  | 'knowledge'
  | 'hr'
  | 'cfo'
  | 'support';

export interface DepartmentOption {
  id: DepartmentId | 'all';
  label: string;
  color: string;
}

// ---- Artifact Types ----
export interface Artifact {
  id: string;
  title: string;
  department: DepartmentId | string;
  type: string;
  date: string;
  status: ArtifactStatus;
  tags: string[];
  chain_phase: string;
  file_path: string;
  relative_url: string;
  size_bytes: number;
  ep?: string;
  proposal_id?: string;
  priority?: string;
  proposal_type?: string;
}

export interface ArtifactIndex {
  id: string;
  title: string;
  department: string;
  type: string;
  date: string;
  status: string;
  chain_phase: string;
  url: string;
  tags: string; // space-joined
  excerpt?: string; // content preview (first 200 chars)
}

export interface ArtifactsData {
  version: string;
  generated_at: string;
  total: number;
  statistics: {
    by_department: Record<string, number>;
    by_type: Record<string, number>;
    by_status: Record<string, number>;
    by_chain_phase: Record<string, number>;
    by_a_phase: Record<string, number>;
  };
  artifacts: Artifact[];
}

// ---- Time Filter Types ----
export type TimeRange = 'all' | 'today' | 'week' | 'month';

export interface TimeRangeOption {
  id: TimeRange;
  label: string;
}

// ---- Content Types ----
export interface ArtifactContent {
  frontmatter: Record<string, unknown>;
  content: string;
  slug: string;
}

export interface SourceArtifactRecord {
  artifactId: string;
  category: string;
  department: string;
  type: string;
  status: string;
  date: string;
  chainPhase: string;
  tags: string[];
  title: string;
  sourceFile: string;
  sourceType: "markdown" | "json";
}

export interface CanonicalArtifactIndex {
  id: string;
  artifactId: string;
  category: string;
  department: string;
  type: string;
  status: string;
  date: string;
  chainPhase: string;
  tags: string[];
  title: string;
  excerpt?: string;
  sourcePath: string;
  sourceFile: string;
  sourceType: "markdown" | "json";
  detailUrl: string;
}

export interface ArtifactDetailPayload {
  artifactId: string;
  category: string;
  frontmatter: Record<string, unknown>;
  content: string;
  sourcePath: string;
  sourceType: "markdown" | "json";
  canonical: CanonicalArtifactIndex;
}

// ---- Pagination Types ----
export interface PaginationState {
  page: number;
  pageSize: number;
  total: number;
}

// ---- LLM Config Types ----
export type LLMProvider = 'openai' | 'anthropic' | 'aliyun';

export interface LLMConfig {
  provider: LLMProvider;
  model: string;
  apiKey: string;
  apiBase: string;
}

export type RealtimeChannel = "dream-agent" | "meeting" | "system";

export interface RealtimeEventPayload {
  type: string;
  summary: string;
  detail?: string;
  requestId?: string;
  status?: "queued" | "streaming" | "completed" | "failed";
  data?: Record<string, unknown>;
}

export interface RealtimeEvent extends RealtimeEventPayload {
  id: string;
  channel: RealtimeChannel;
  timestamp: number;
}

export interface DreamAgentInvokeInput {
  user_input: string;
  llm_config: LLMConfig;
}

export interface DreamAgentInvokeSuccess {
  success: true;
  response: string;
  requestId: string;
}

export interface DreamAgentInvokeFailure {
  success: false;
  error: string;
  requestId: string;
}

export interface ArtifactRelation {
  artifactId: string;
  chainPhase: string;
  feedHref: string;
  chainHref: string;
  nodeId: string;
  title: string;
  date: string;
}

export type ChainPhaseArtifacts = Record<string, ArtifactRelation[]>;
