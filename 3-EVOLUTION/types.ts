export type EvolutionTriggerSource =
  | 'execution_failure'
  | 'low_confidence'
  | 'chain_disagreement'
  | 'user_feedback'
  | 'governance_alert'
  | 'scheduled_audit'
  | 'lesson_distilled'
  | 'a8_reflection'
  | 'dream_oneirology'
  | 'orchestration_optimization';

export type EvolutionPhase =
  | 'discovery'
  | 'learning'
  | 'deep_analysis'
  | 'capability_update'
  | 'code_development'
  | 'collaboration'
  | 'approval'
  | 'deployment'
  | 'completed';

export type EvolutionStatus =
  | 'pending'
  | 'in_progress'
  | 'blocked'
  | 'completed'
  | 'failed'
  | 'skipped';

export type UpdateLayer = 'knowledge' | 'memory' | 'index' | 'skill' | 'code' | 'architecture';

export interface EvolutionFinding {
  id: string;
  source: EvolutionTriggerSource;
  severity: 'low' | 'medium' | 'high' | 'critical';
  title: string;
  description: string;
  affected_areas: string[];
  detected_at: string;
  raw_data?: Record<string, unknown>;
}

export interface EvolutionLesson {
  id: string;
  pattern: string;
  type: 'success' | 'failure';
  frequency: number;
  severity: number;
  description: string;
  evidence_refs: string[];
  first_seen: string;
  last_seen: string;
}

export interface EvolutionProposal {
  id: string;
  finding_id: string;
  title: string;
  description: string;
  change_type: 'knowledge_update' | 'memory_update' | 'skill_update' | 'code_change' | 'architecture_change';
  requires_code: boolean;
  rollback_plan_id: string;
  evidence_refs: string[];
  status: 'pending_review' | 'approved' | 'rejected' | 'implemented';
  created_at: string;
  approved_at?: string;
}

export interface EvolutionRecord {
  id: string;
  phase: EvolutionPhase;
  status: EvolutionStatus;
  findings: EvolutionFinding[];
  lessons: EvolutionLesson[];
  proposals: EvolutionProposal[];
  current_phase: EvolutionPhase;
  trigger_source: EvolutionTriggerSource;
  started_at: string;
  updated_at: string;
  completed_at?: string;
  metadata: {
    knowledge_updated: boolean;
    memory_updated: boolean;
    index_updated: boolean;
    code_changed: boolean;
    dze_chain_triggered: boolean;
    dream_agent_triggered: boolean;
    approval_required: boolean;
    approval_completed: boolean;
  };
}

export interface DZEChainTrigger {
  evolution_id: string;
  proposal_id: string;
  task_scope: string;
  complexity: 'small' | 'medium' | 'large';
  estimated_lines: number;
  affected_modules: string[];
  starting_phase: 'd1' | 'd2' | 'd3' | 'd4' | 'z1' | 'e1';
  created_at: string;
  chain_state_path?: string;
}

export interface DreamAgentTask {
  evolution_id: string;
  dze_task_id?: string;
  task_id: string;
  title: string;
  description: string;
  assigned_roles: Array<'developer' | 'validator' | 'governance'>;
  priority: 'low' | 'medium' | 'high';
  reward_estimate: number;
  status: 'registered' | 'claimed' | 'in_progress' | 'validated' | 'ledgered';
  created_at: string;
  ledger_ref?: string;
}

export interface ApprovalRequest {
  id: string;
  evolution_id: string;
  proposal_id?: string;
  task_id?: string;
  approval_type: 'design' | 'kickoff' | 'risk' | 'merge' | 'deployment';
  title: string;
  description: string;
  requester: string;
  approvers: string[];
  status: 'pending' | 'approved' | 'rejected' | 'timeout_auto_approved';
  created_at: string;
  decided_at?: string;
  decided_by?: string;
  feishu_approval_code?: string;
  feishu_instance_code?: string;
}

export interface EvolutionEngineConfig {
  data_dir: string;
  auto_trigger_dze: boolean;
  auto_trigger_dream_agent: boolean;
  auto_create_approvals: boolean;
  approval_timeout_minutes: number;
  min_severity_for_code_change: 'low' | 'medium' | 'high';
}
