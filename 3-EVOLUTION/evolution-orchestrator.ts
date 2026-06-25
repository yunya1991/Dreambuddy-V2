import {
  EvolutionFinding,
  EvolutionLesson,
  EvolutionRecord,
  EvolutionPhase,
  EvolutionTriggerSource,
} from './types';
import { EvolutionEngine } from './evolution-engine';
import { DZEBridge, DZEPhase } from './dze-bridge';
import { DreamAgentBridge } from './dream-agent-bridge';
import { ApprovalBridge } from './approval-bridge';

export interface OrchestratorResult {
  evolutionId: string;
  currentPhase: EvolutionPhase;
  dzeTriggered: boolean;
  dreamAgentTriggered: boolean;
  approvalsCreated: number;
  status: string;
}

export class EvolutionOrchestrator {
  private engine: EvolutionEngine;
  private dzeBridge: DZEBridge;
  private dreamAgentBridge: DreamAgentBridge;
  private approvalBridge: ApprovalBridge;

  constructor() {
    this.engine = new EvolutionEngine();
    this.dzeBridge = new DZEBridge();
    this.dreamAgentBridge = new DreamAgentBridge();
    this.approvalBridge = new ApprovalBridge();
  }

  startEvolution(
    triggerSource: EvolutionTriggerSource,
    findings: EvolutionFinding[]
  ): OrchestratorResult {
    const record = this.engine.createEvolution(triggerSource, findings);

    if (findings.length === 0) {
      return this.buildResult(record);
    }

    this.engine.transitionPhase(record.id, 'learning');

    const lessons = this.extractLessons(findings);
    this.engine.addLessons(record.id, lessons);

    this.engine.generateProposals(record.id);

    this.processProposals(record.id);

    return this.buildResult(record);
  }

  advanceDZEPhase(evolutionId: string, phase: DZEPhase): void {
    const chains = this.dzeBridge.getChainsByEvolution(evolutionId);
    if (chains.length === 0) throw new Error(`No DZE chain found for evolution ${evolutionId}`);

    const chain = chains[0];
    this.dzeBridge.advancePhase(chain.trigger_id, phase);

    const updatedRecord = this.engine.getRecord(evolutionId);
    if (phase === 'e3') {
      this.engine.transitionPhase(evolutionId, 'deployment');
      updatedRecord.metadata.code_changed = true;
    } else if (phase.startsWith('e')) {
      this.engine.transitionPhase(evolutionId, 'code_development');
    }
  }

  passGate1(evolutionId: string, approved: boolean, approver = 'system'): boolean {
    const chains = this.dzeBridge.getChainsByEvolution(evolutionId);
    if (chains.length === 0) return false;

    const chain = chains[0];
    const result = this.dzeBridge.passGate1(chain.trigger_id, approved, approver);

    if (result) {
      this.dzeBridge.advancePhase(chain.trigger_id, 'z1');
      const record = this.engine.getRecord(evolutionId);
      record.metadata.approval_completed = true;
      this.engine.transitionPhase(evolutionId, 'code_development');
    }

    return result;
  }

  passGate2(evolutionId: string, approved: boolean, approver = 'system'): boolean {
    const chains = this.dzeBridge.getChainsByEvolution(evolutionId);
    if (chains.length === 0) return false;

    const chain = chains[0];
    const result = this.dzeBridge.passGate2(chain.trigger_id, approved, approver);

    if (result) {
      this.dzeBridge.advancePhase(chain.trigger_id, 'e1');
      this.registerDreamAgentTask(evolutionId);
    }

    return result;
  }

  completeDreamAgentTask(evolutionId: string, taskId: string): void {
    this.dreamAgentBridge.finalizeTask(taskId, 'governance-agent');

    const chains = this.dzeBridge.getChainsByEvolution(evolutionId);
    if (chains.length > 0) {
      const chain = chains[0];
      this.dzeBridge.completeChain(chain.trigger_id, `deploy_${Date.now()}`);
    }

    this.engine.transitionPhase(evolutionId, 'completed');
    this.engine.setStatus(evolutionId, 'completed');
  }

  processApprovalTimeout(evolutionId: string): number {
    const approvals = this.approvalBridge.getApprovalsByEvolution(evolutionId);
    const pending = approvals.filter(a => a.status === 'pending');

    let autoApproved = 0;
    for (const approval of pending) {
      const result = this.approvalBridge.autoApproveIfEligible(approval.id);
      if (result.approved) {
        autoApproved++;
        if (approval.approval_type === 'design') {
          this.passGate1(evolutionId, true, 'auto-approval-bot');
        } else if (approval.approval_type === 'kickoff') {
          this.passGate2(evolutionId, true, 'auto-approval-bot');
        }
      }
    }

    return autoApproved;
  }

  getEngine(): EvolutionEngine {
    return this.engine;
  }

  getDZEBridge(): DZEBridge {
    return this.dzeBridge;
  }

  getDreamAgentBridge(): DreamAgentBridge {
    return this.dreamAgentBridge;
  }

  getApprovalBridge(): ApprovalBridge {
    return this.approvalBridge;
  }

  getFullStatus(evolutionId: string): {
    evolution: EvolutionRecord;
    dzeChains: ReturnType<DZEBridge['getChainsByEvolution']>;
    dreamAgentTasks: ReturnType<DreamAgentBridge['getTasksByEvolution']>;
    approvals: ReturnType<ApprovalBridge['getApprovalsByEvolution']>;
  } {
    return {
      evolution: this.engine.getRecord(evolutionId),
      dzeChains: this.dzeBridge.getChainsByEvolution(evolutionId),
      dreamAgentTasks: this.dreamAgentBridge.getTasksByEvolution(evolutionId),
      approvals: this.approvalBridge.getApprovalsByEvolution(evolutionId),
    };
  }

  private processProposals(evolutionId: string): void {
    const record = this.engine.getRecord(evolutionId);

    for (const proposal of record.proposals) {
      if (proposal.requires_code) {
        this.triggerCodePath(evolutionId, proposal.id);
      } else {
        this.triggerKnowledgePath(evolutionId, proposal.id);
      }
    }
  }

  private triggerKnowledgePath(evolutionId: string, proposalId: string): void {
    const record = this.engine.getRecord(evolutionId);
    this.engine.applyKnowledgeUpdate(evolutionId, proposalId);
    this.engine.transitionPhase(evolutionId, 'capability_update');

    if (this.allProposalsImplemented(evolutionId)) {
      this.engine.transitionPhase(evolutionId, 'completed');
      this.engine.setStatus(evolutionId, 'completed');
    }
  }

  private triggerCodePath(evolutionId: string, proposalId: string): void {
    const record = this.engine.getRecord(evolutionId);
    const proposal = record.proposals.find(p => p.id === proposalId);
    if (!proposal) return;

    this.dzeBridge.createChainFromEvolution(record, proposal);
    this.engine.triggerCodeDevelopment(evolutionId, proposalId);

    const chains = this.dzeBridge.getChainsByEvolution(evolutionId);
    if (chains.length > 0) {
      this.approvalBridge.createApprovalForGate1(record, chains[0], proposal);
    }

    const updatedRecord = this.engine.getRecord(evolutionId);
    updatedRecord.metadata.approval_required = true;
  }

  private registerDreamAgentTask(evolutionId: string): void {
    const record = this.engine.getRecord(evolutionId);
    const chains = this.dzeBridge.getChainsByEvolution(evolutionId);
    if (chains.length === 0) return;

    this.dreamAgentBridge.registerTaskFromDZE(record, chains[0]);

    const updatedRecord = this.engine.getRecord(evolutionId);
    updatedRecord.metadata.dream_agent_triggered = true;
    this.engine.transitionPhase(evolutionId, 'collaboration');
  }

  private extractLessons(findings: EvolutionFinding[]): EvolutionLesson[] {
    return findings.map((f, i) => ({
      id: `lesson_${Date.now()}_${i}`,
      pattern: f.title,
      type: f.severity === 'high' || f.severity === 'critical' ? 'failure' : 'success',
      frequency: 1,
      severity: f.severity === 'low' ? 1 : f.severity === 'medium' ? 2 : f.severity === 'high' ? 3 : 4,
      description: f.description,
      evidence_refs: [f.id],
      first_seen: f.detected_at,
      last_seen: f.detected_at,
    }));
  }

  private allProposalsImplemented(evolutionId: string): boolean {
    const record = this.engine.getRecord(evolutionId);
    return record.proposals.every(p => p.status === 'implemented');
  }

  private buildResult(record: EvolutionRecord): OrchestratorResult {
    const dzeChains = this.dzeBridge.getChainsByEvolution(record.id);
    const daTasks = this.dreamAgentBridge.getTasksByEvolution(record.id);
    const approvals = this.approvalBridge.getApprovalsByEvolution(record.id);

    return {
      evolutionId: record.id,
      currentPhase: record.current_phase,
      dzeTriggered: dzeChains.length > 0,
      dreamAgentTriggered: daTasks.length > 0,
      approvalsCreated: approvals.length,
      status: record.status,
    };
  }
}
