import {
  EvolutionFinding,
  EvolutionLesson,
  EvolutionProposal,
  EvolutionRecord,
  EvolutionPhase,
  EvolutionStatus,
  EvolutionTriggerSource,
  EvolutionEngineConfig,
} from './types';

export class EvolutionEngine {
  private config: EvolutionEngineConfig;
  private records: Map<string, EvolutionRecord> = new Map();

  constructor(config: Partial<EvolutionEngineConfig> = {}) {
    this.config = {
      data_dir: config.data_dir || './evolution_data',
      auto_trigger_dze: config.auto_trigger_dze ?? true,
      auto_trigger_dream_agent: config.auto_trigger_dream_agent ?? true,
      auto_create_approvals: config.auto_create_approvals ?? true,
      approval_timeout_minutes: config.approval_timeout_minutes ?? 30,
      min_severity_for_code_change: config.min_severity_for_code_change ?? 'medium',
    };
  }

  createEvolution(
    triggerSource: EvolutionTriggerSource,
    findings: EvolutionFinding[] = []
  ): EvolutionRecord {
    const id = `evo_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const now = new Date().toISOString();

    const record: EvolutionRecord = {
      id,
      phase: 'discovery',
      status: 'in_progress',
      findings,
      lessons: [],
      proposals: [],
      current_phase: 'discovery',
      trigger_source: triggerSource,
      started_at: now,
      updated_at: now,
      metadata: {
        knowledge_updated: false,
        memory_updated: false,
        index_updated: false,
        code_changed: false,
        dze_chain_triggered: false,
        dream_agent_triggered: false,
        approval_required: false,
        approval_completed: false,
      },
    };

    this.records.set(id, record);
    return record;
  }

  addFinding(evolutionId: string, finding: EvolutionFinding): void {
    const record = this.getRecord(evolutionId);
    record.findings.push(finding);
    record.updated_at = new Date().toISOString();
    this.records.set(evolutionId, record);
  }

  addLessons(evolutionId: string, lessons: EvolutionLesson[]): void {
    const record = this.getRecord(evolutionId);
    record.lessons.push(...lessons);
    if (record.current_phase === 'discovery') {
      this.transitionPhase(evolutionId, 'learning');
    }
    record.updated_at = new Date().toISOString();
    this.records.set(evolutionId, record);
  }

  generateProposals(evolutionId: string): EvolutionProposal[] {
    const record = this.getRecord(evolutionId);
    const proposals: EvolutionProposal[] = [];

    for (const finding of record.findings) {
      const requiresCode = this.requiresCodeChange(finding);
      const changeType = requiresCode
        ? this.determineCodeChangeType(finding)
        : this.determineKnowledgeChangeType(finding);

      const proposal: EvolutionProposal = {
        id: `prop_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        finding_id: finding.id,
        title: this.generateProposalTitle(finding),
        description: this.generateProposalDescription(finding),
        change_type: changeType,
        requires_code: requiresCode,
        rollback_plan_id: `rb_${Date.now()}`,
        evidence_refs: [finding.id],
        status: 'pending_review',
        created_at: new Date().toISOString(),
      };

      proposals.push(proposal);
    }

    record.proposals = proposals;
    if (record.current_phase === 'learning') {
      this.transitionPhase(evolutionId, 'deep_analysis');
    }
    record.updated_at = new Date().toISOString();
    this.records.set(evolutionId, record);

    return proposals;
  }

  applyKnowledgeUpdate(evolutionId: string, proposalId: string): boolean {
    const record = this.getRecord(evolutionId);
    const proposal = record.proposals.find(p => p.id === proposalId);
    if (!proposal) throw new Error(`Proposal ${proposalId} not found`);
    if (proposal.requires_code) return false;

    proposal.status = 'implemented';
    record.metadata.knowledge_updated = true;
    record.metadata.memory_updated = true;
    record.metadata.index_updated = true;

    this.transitionPhase(evolutionId, 'capability_update');
    record.updated_at = new Date().toISOString();
    this.records.set(evolutionId, record);

    return true;
  }

  triggerCodeDevelopment(evolutionId: string, proposalId: string): boolean {
    const record = this.getRecord(evolutionId);
    const proposal = record.proposals.find(p => p.id === proposalId);
    if (!proposal) throw new Error(`Proposal ${proposalId} not found`);
    if (!proposal.requires_code) return false;

    record.metadata.code_changed = true;
    record.metadata.dze_chain_triggered = true;
    proposal.status = 'approved';
    proposal.approved_at = new Date().toISOString();

    this.transitionPhase(evolutionId, 'code_development');
    record.updated_at = new Date().toISOString();
    this.records.set(evolutionId, record);

    return true;
  }

  transitionPhase(evolutionId: string, newPhase: EvolutionPhase): void {
    const record = this.getRecord(evolutionId);
    record.phase = newPhase;
    record.current_phase = newPhase;
    record.updated_at = new Date().toISOString();
    this.records.set(evolutionId, record);
  }

  setStatus(evolutionId: string, status: EvolutionStatus): void {
    const record = this.getRecord(evolutionId);
    record.status = status;
    if (status === 'completed') {
      record.completed_at = new Date().toISOString();
    }
    record.updated_at = new Date().toISOString();
    this.records.set(evolutionId, record);
  }

  getRecord(evolutionId: string): EvolutionRecord {
    const record = this.records.get(evolutionId);
    if (!record) throw new Error(`Evolution record ${evolutionId} not found`);
    return { ...record };
  }

  getAllRecords(): EvolutionRecord[] {
    return Array.from(this.records.values());
  }

  getRecordsByPhase(phase: EvolutionPhase): EvolutionRecord[] {
    return Array.from(this.records.values()).filter(r => r.current_phase === phase);
  }

  getRecordsByStatus(status: EvolutionStatus): EvolutionRecord[] {
    return Array.from(this.records.values()).filter(r => r.status === status);
  }

  private requiresCodeChange(finding: EvolutionFinding): boolean {
    const severityRank = { low: 0, medium: 1, high: 2, critical: 3 };
    const thresholdRank = severityRank[this.config.min_severity_for_code_change];
    if (severityRank[finding.severity] < thresholdRank) return false;

    const codeAreas = ['code', 'skill', 'engine', 'module', 'component', 'api'];
    return finding.affected_areas.some(area =>
      codeAreas.some(ca => area.toLowerCase().includes(ca))
    );
  }

  private determineCodeChangeType(
    finding: EvolutionFinding
  ): 'code_change' | 'skill_update' | 'architecture_change' {
    if (finding.affected_areas.some(a => a.toLowerCase().includes('architect'))) {
      return 'architecture_change';
    }
    if (finding.affected_areas.some(a => a.toLowerCase().includes('skill'))) {
      return 'skill_update';
    }
    return 'code_change';
  }

  private determineKnowledgeChangeType(
    finding: EvolutionFinding
  ): 'knowledge_update' | 'memory_update' {
    if (finding.source === 'lesson_distilled' || finding.source === 'a8_reflection') {
      return 'knowledge_update';
    }
    return 'memory_update';
  }

  private generateProposalTitle(finding: EvolutionFinding): string {
    return `[${finding.severity.toUpperCase()}] ${finding.title}`;
  }

  private generateProposalDescription(finding: EvolutionFinding): string {
    return `
Source: ${finding.source}
Severity: ${finding.severity}
Affected areas: ${finding.affected_areas.join(', ')}

${finding.description}
    `.trim();
  }
}
