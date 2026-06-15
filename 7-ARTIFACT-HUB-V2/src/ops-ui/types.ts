export interface OpsUIConfig {
  port: number;
  artifactHubUrl: string;
  gatewayUrl: string;
}

export interface TaskCard {
  task_id: string;
  title: string;
  status: string;
  owner_agent: string;
  updated_at: string;
}

export interface AuditRow {
  audit_id: string;
  trace_id: string;
  event_type: string;
  agent: string;
  timestamp: string;
}
