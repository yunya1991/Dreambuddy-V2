import { EvolutionRecord, EvolutionProposal, DZEChainTrigger } from './types';

export type DZEPhase = 'd1' | 'd2' | 'd3' | 'd4' | 'z1' | 'z2' | 'z3' | 'z4' | 'e1' | 'e2' | 'e3';

export interface DZEChainState {
  trigger_id: string;
  evolution_id: string;
  proposal_id: string;
  current_phase: DZEPhase;
  task_scope: string;
  complexity: 'small' | 'medium' | 'large';
  estimated_lines: number;
  affected_modules: string[];
  phases_completed: DZEPhase[];
  phases_pending: DZEPhase[];
  gate1_passed: boolean;
  gate2_passed: boolean;
  started_at: string;
  updated_at: string;
  completed_at?: string;
  artifacts: {
    d4_spec_path?: string;
    z4_plan_path?: string;
    e3_deployment_ref?: string;
    e2_test_report?: string;
  };
}

export class DZEBridge {
  private chainStates: Map<string, DZEChainState> = new Map();

  createChainFromEvolution(
    evolutionRecord: EvolutionRecord,
    proposal: EvolutionProposal
  ): DZEChainTrigger {
    const trigger: DZEChainTrigger = {
      evolution_id: evolutionRecord.id,
      proposal_id: proposal.id,
      task_scope: proposal.title,
      complexity: this.estimateComplexity(proposal),
      estimated_lines: this.estimateLines(proposal),
      affected_modules: this.determineAffectedModules(proposal),
      starting_phase: 'd1',
      created_at: new Date().toISOString(),
    };

    const state: DZEChainState = {
      trigger_id: `dze_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      evolution_id: evolutionRecord.id,
      proposal_id: proposal.id,
      current_phase: 'd1',
      task_scope: trigger.task_scope,
      complexity: trigger.complexity,
      estimated_lines: trigger.estimated_lines,
      affected_modules: trigger.affected_modules,
      phases_completed: [],
      phases_pending: ['d1', 'd2', 'd3', 'd4', 'z1', 'z2', 'z3', 'z4', 'e1', 'e2', 'e3'],
      gate1_passed: false,
      gate2_passed: false,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      artifacts: {},
    };

    trigger.chain_state_path = `./dze_chains/${state.trigger_id}.json`;
    this.chainStates.set(state.trigger_id, state);

    return trigger;
  }

  advancePhase(triggerId: string, nextPhase: DZEPhase): DZEChainState {
    const state = this.getState(triggerId);

    const phaseOrder: DZEPhase[] = ['d1', 'd2', 'd3', 'd4', 'z1', 'z2', 'z3', 'z4', 'e1', 'e2', 'e3'];
    const currentIdx = phaseOrder.indexOf(state.current_phase);
    const nextIdx = phaseOrder.indexOf(nextPhase);

    if (nextIdx <= currentIdx) {
      throw new Error(`Cannot go backwards from ${state.current_phase} to ${nextPhase}`);
    }

    for (let i = currentIdx; i <= nextIdx; i++) {
      if (!state.phases_completed.includes(phaseOrder[i])) {
        state.phases_completed.push(phaseOrder[i]);
      }
    }

    state.current_phase = nextPhase;
    state.phases_pending = phaseOrder.slice(nextIdx + 1);
    state.updated_at = new Date().toISOString();

    this.chainStates.set(triggerId, state);
    return { ...state };
  }

  passGate1(triggerId: string, approved: boolean, approver = 'system'): boolean {
    const state = this.getState(triggerId);
    if (state.current_phase !== 'd4') {
      throw new Error(`Gate 1 can only be passed at phase d4, currently at ${state.current_phase}`);
    }
    if (approved) {
      state.gate1_passed = true;
      state.updated_at = new Date().toISOString();
      this.chainStates.set(triggerId, state);
      return true;
    }
    return false;
  }

  passGate2(triggerId: string, approved: boolean, approver = 'system'): boolean {
    const state = this.getState(triggerId);
    if (state.current_phase !== 'z4') {
      throw new Error(`Gate 2 can only be passed at phase z4, currently at ${state.current_phase}`);
    }
    if (approved) {
      state.gate2_passed = true;
      state.updated_at = new Date().toISOString();
      this.chainStates.set(triggerId, state);
      return true;
    }
    return false;
  }

  completeChain(triggerId: string, deploymentRef: string): DZEChainState {
    const state = this.getState(triggerId);
    state.current_phase = 'e3';
    state.phases_completed = ['d1', 'd2', 'd3', 'd4', 'z1', 'z2', 'z3', 'z4', 'e1', 'e2', 'e3'];
    state.phases_pending = [];
    state.artifacts.e3_deployment_ref = deploymentRef;
    state.completed_at = new Date().toISOString();
    state.updated_at = new Date().toISOString();
    this.chainStates.set(triggerId, state);
    return { ...state };
  }

  addArtifact(
    triggerId: string,
    artifactKey: keyof DZEChainState['artifacts'],
    value: string
  ): void {
    const state = this.getState(triggerId);
    state.artifacts[artifactKey] = value;
    state.updated_at = new Date().toISOString();
    this.chainStates.set(triggerId, state);
  }

  getState(triggerId: string): DZEChainState {
    const state = this.chainStates.get(triggerId);
    if (!state) throw new Error(`DZE chain state ${triggerId} not found`);
    return { ...state };
  }

  getAllChains(): DZEChainState[] {
    return Array.from(this.chainStates.values());
  }

  getChainsByEvolution(evolutionId: string): DZEChainState[] {
    return Array.from(this.chainStates.values()).filter(s => s.evolution_id === evolutionId);
  }

  getChainsByPhase(phase: DZEPhase): DZEChainState[] {
    return Array.from(this.chainStates.values()).filter(s => s.current_phase === phase);
  }

  private estimateComplexity(proposal: EvolutionProposal): 'small' | 'medium' | 'large' {
    if (proposal.change_type === 'architecture_change') return 'large';
    if (proposal.change_type === 'skill_update') return 'medium';
    if (proposal.change_type === 'code_change') return 'small';
    return 'small';
  }

  private estimateLines(proposal: EvolutionProposal): number {
    const base = {
      knowledge_update: 0,
      memory_update: 0,
      skill_update: 200,
      code_change: 100,
      architecture_change: 500,
    };
    return base[proposal.change_type] || 50;
  }

  private determineAffectedModules(proposal: EvolutionProposal): string[] {
    const modules: string[] = [];
    const desc = proposal.description.toLowerCase();

    if (desc.includes('chainplanner') || desc.includes('planner')) {
      modules.push('6-图结构上下文压缩');
    }
    if (desc.includes('evolution') || desc.includes('进化')) {
      modules.push('3-EVOLUTION');
    }
    if (desc.includes('feishu') || desc.includes('飞书')) {
      modules.push('8-FEISHU');
    }
    if (desc.includes('dream-agent') || desc.includes('协作网络')) {
      modules.push('7-产物中台');
    }
    if (modules.length === 0) {
      modules.push('core');
    }
    return modules;
  }
}
