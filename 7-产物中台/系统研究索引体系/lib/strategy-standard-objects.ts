export interface StrategySettingResult {
  settingId: string;
  strategyId: string;
  strategyName: string;
  department: string;
  status: 'active' | 'completed' | 'draft';
  createdAt: string;
  updatedAt: string;
  configuration: StrategyConfiguration;
  validationStatus: 'valid' | 'invalid' | 'pending';
}

export interface StrategyConfiguration {
  version: string;
  rules: StrategyRule[];
  conditions: StrategyCondition[];
  actions: StrategyAction[];
}

export interface StrategyRule {
  id: string;
  name: string;
  description: string;
  priority: number;
  enabled: boolean;
}

export interface StrategyCondition {
  field: string;
  operator: string;
  value: string | number | boolean;
}

export interface StrategyAction {
  type: string;
  parameters: Record<string, unknown>;
}

export interface StrategyTaskTicket {
  ticketId: string;
  strategyId: string;
  title: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  executionId?: string;
  resultArtifactId?: string;
}

export interface ExecutionStatus {
  executionId: string;
  strategyId: string;
  status: 'idle' | 'scheduled' | 'running' | 'completed' | 'failed';
  currentTask?: string;
  progress: number;
  startTime?: string;
  endTime?: string;
  errorMessage?: string;
  metrics: ExecutionMetrics;
}

export interface ExecutionMetrics {
  totalTasks: number;
  completedTasks: number;
  failedTasks: number;
  averageDurationMs: number;
  throughput: number;
}

export interface ResultArtifactReference {
  artifactId: string;
  executionId: string;
  strategyId: string;
  type: string;
  title: string;
  url: string;
  generatedAt: string;
  referencedBy: string[];
}

export interface StrategyFullView {
  setting: StrategySettingResult;
  activeTasks: StrategyTaskTicket[];
  executionStatus: ExecutionStatus;
  results: ResultArtifactReference[];
}

export function parseStrategyArtifact(artifact: Record<string, unknown>): StrategySettingResult | null {
  if (!artifact || artifact.type !== 'strategy') {
    return null;
  }

  return {
    settingId: String(artifact.id || ''),
    strategyId: String(artifact.id || '').split('/').pop() || '',
    strategyName: String(artifact.title || ''),
    department: String(artifact.department || ''),
    status: (artifact.status as string) === 'active' ? 'active' : 
            (artifact.status as string) === 'completed' ? 'completed' : 'draft',
    createdAt: String(artifact.date || ''),
    updatedAt: String(artifact.date || ''),
    configuration: {
      version: '1.0',
      rules: [],
      conditions: [],
      actions: [],
    },
    validationStatus: 'pending',
  };
}

export function buildStrategyFullView(artifact: Record<string, unknown>): StrategyFullView | null {
  const setting = parseStrategyArtifact(artifact);
  if (!setting) {
    return null;
  }

  return {
    setting,
    activeTasks: [],
    executionStatus: {
      executionId: '',
      strategyId: setting.strategyId,
      status: setting.status === 'active' ? 'running' : 'idle',
      progress: setting.status === 'completed' ? 100 : 0,
      metrics: {
        totalTasks: 0,
        completedTasks: 0,
        failedTasks: 0,
        averageDurationMs: 0,
        throughput: 0,
      },
    },
    results: [],
  };
}