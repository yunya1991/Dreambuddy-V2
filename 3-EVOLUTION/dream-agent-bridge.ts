import { EvolutionRecord, DreamAgentTask } from './types';
import { DZEChainState } from './dze-bridge';

export type AgentRole = 'developer' | 'validator' | 'governance';

export interface LedgerEntry {
  id: string;
  task_id: string;
  evolution_id: string;
  agent_id: string;
  agent_role: AgentRole;
  action: 'claim' | 'submit' | 'validate' | 'approve' | 'reward';
  reward_amount: number;
  timestamp: string;
  description: string;
  block_height?: number;
}

export interface DreamAgentNetworkState {
  tasks: Map<string, DreamAgentTask>;
  ledger: LedgerEntry[];
  total_dream_rewarded: number;
  block_height: number;
}

export class DreamAgentBridge {
  private state: DreamAgentNetworkState = {
    tasks: new Map(),
    ledger: [],
    total_dream_rewarded: 0,
    block_height: 0,
  };

  registerTaskFromDZE(
    evolutionRecord: EvolutionRecord,
    dzeState: DZEChainState
  ): DreamAgentTask {
    const taskId = `task_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

    const task: DreamAgentTask = {
      evolution_id: evolutionRecord.id,
      dze_task_id: dzeState.trigger_id,
      task_id: taskId,
      title: dzeState.task_scope,
      description: this.generateTaskDescription(evolutionRecord, dzeState),
      assigned_roles: ['developer', 'validator', 'governance'],
      priority: this.calculatePriority(dzeState),
      reward_estimate: this.calculateReward(dzeState),
      status: 'registered',
      created_at: new Date().toISOString(),
    };

    this.state.tasks.set(taskId, task);

    this.addLedgerEntry({
      id: `ledger_${Date.now()}_0`,
      task_id: taskId,
      evolution_id: evolutionRecord.id,
      agent_id: 'evolution-engine',
      agent_role: 'governance',
      action: 'claim',
      reward_amount: 0,
      timestamp: new Date().toISOString(),
      description: `Task registered from evolution ${evolutionRecord.id}`,
    });

    return { ...task };
  }

  assignDeveloper(taskId: string, developerId: string): DreamAgentTask {
    const task = this.getTask(taskId);
    task.status = 'claimed';
    this.state.tasks.set(taskId, task);

    this.addLedgerEntry({
      id: `ledger_${Date.now()}_1`,
      task_id: taskId,
      evolution_id: task.evolution_id,
      agent_id: developerId,
      agent_role: 'developer',
      action: 'claim',
      reward_amount: 0,
      timestamp: new Date().toISOString(),
      description: `Developer ${developerId} claimed task`,
    });

    return { ...task };
  }

  submitForValidation(taskId: string, developerId: string): DreamAgentTask {
    const task = this.getTask(taskId);
    task.status = 'in_progress';
    this.state.tasks.set(taskId, task);

    this.addLedgerEntry({
      id: `ledger_${Date.now()}_2`,
      task_id: taskId,
      evolution_id: task.evolution_id,
      agent_id: developerId,
      agent_role: 'developer',
      action: 'submit',
      reward_amount: 0,
      timestamp: new Date().toISOString(),
      description: `Developer ${developerId} submitted for validation`,
    });

    return { ...task };
  }

  validateTask(
    taskId: string,
    validatorId: string,
    passed: boolean,
    score = 0
  ): DreamAgentTask {
    const task = this.getTask(taskId);

    if (passed) {
      task.status = 'validated';
      const baseReward = task.reward_estimate * 0.6;
      const validatorReward = task.reward_estimate * 0.2;

      this.addLedgerEntry({
        id: `ledger_${Date.now()}_3`,
        task_id: taskId,
        evolution_id: task.evolution_id,
        agent_id: validatorId,
        agent_role: 'validator',
        action: 'validate',
        reward_amount: validatorReward,
        timestamp: new Date().toISOString(),
        description: `Validator ${validatorId} approved task, score: ${score}`,
      });

      this.addLedgerEntry({
        id: `ledger_${Date.now()}_4`,
        task_id: taskId,
        evolution_id: task.evolution_id,
        agent_id: 'developer-auto',
        agent_role: 'developer',
        action: 'reward',
        reward_amount: baseReward,
        timestamp: new Date().toISOString(),
        description: `Developer reward: ${baseReward} DREAM`,
      });

      this.state.total_dream_rewarded += baseReward + validatorReward;
    } else {
      task.status = 'claimed';

      this.addLedgerEntry({
        id: `ledger_${Date.now()}_5`,
        task_id: taskId,
        evolution_id: task.evolution_id,
        agent_id: validatorId,
        agent_role: 'validator',
        action: 'validate',
        reward_amount: 0,
        timestamp: new Date().toISOString(),
        description: `Validator ${validatorId} rejected task, score: ${score}`,
      });
    }

    this.state.tasks.set(taskId, task);
    return { ...task };
  }

  finalizeTask(taskId: string, governanceId: string): DreamAgentTask {
    const task = this.getTask(taskId);
    if (task.status !== 'validated') {
      throw new Error(`Task must be validated before finalizing, current: ${task.status}`);
    }

    task.status = 'ledgered';
    const governanceReward = task.reward_estimate * 0.2;

    this.addLedgerEntry({
      id: `ledger_${Date.now()}_6`,
      task_id: taskId,
      evolution_id: task.evolution_id,
      agent_id: governanceId,
      agent_role: 'governance',
      action: 'approve',
      reward_amount: governanceReward,
      timestamp: new Date().toISOString(),
      description: `Governance ${governanceId} finalized task`,
      block_height: ++this.state.block_height,
    });

    this.state.total_dream_rewarded += governanceReward;
    task.ledger_ref = `block_${this.state.block_height}`;
    this.state.tasks.set(taskId, task);

    return { ...task };
  }

  getTask(taskId: string): DreamAgentTask {
    const task = this.state.tasks.get(taskId);
    if (!task) throw new Error(`Task ${taskId} not found`);
    return { ...task };
  }

  getAllTasks(): DreamAgentTask[] {
    return Array.from(this.state.tasks.values());
  }

  getTasksByEvolution(evolutionId: string): DreamAgentTask[] {
    return Array.from(this.state.tasks.values()).filter(t => t.evolution_id === evolutionId);
  }

  getTasksByStatus(status: DreamAgentTask['status']): DreamAgentTask[] {
    return Array.from(this.state.tasks.values()).filter(t => t.status === status);
  }

  getLedger(): LedgerEntry[] {
    return [...this.state.ledger];
  }

  getLedgerByTask(taskId: string): LedgerEntry[] {
    return this.state.ledger.filter(e => e.task_id === taskId);
  }

  getTotalRewards(): number {
    return this.state.total_dream_rewarded;
  }

  getBlockHeight(): number {
    return this.state.block_height;
  }

  private addLedgerEntry(entry: LedgerEntry): void {
    this.state.ledger.push(entry);
  }

  private generateTaskDescription(
    evolution: EvolutionRecord,
    dzeState: DZEChainState
  ): string {
    return `
Evolution ID: ${evolution.id}
DZE Trigger ID: ${dzeState.trigger_id}
Complexity: ${dzeState.complexity}
Estimated lines: ${dzeState.estimated_lines}
Affected modules: ${dzeState.affected_modules.join(', ')}

Task scope: ${dzeState.task_scope}

---
Roles needed:
- Developer: implement the changes following DZE methodology
- Validator: review and validate the implementation
- Governance: final approval and ledger entry
    `.trim();
  }

  private calculatePriority(dzeState: DZEChainState): DreamAgentTask['priority'] {
    if (dzeState.complexity === 'large') return 'high';
    if (dzeState.complexity === 'medium') return 'medium';
    return 'low';
  }

  private calculateReward(dzeState: DZEChainState): number {
    const baseRewards = {
      small: 100,
      medium: 500,
      large: 2000,
    };
    return baseRewards[dzeState.complexity];
  }
}
