import { EvolutionRecord, EvolutionProposal, ApprovalRequest } from './types';
import { DZEChainState } from './dze-bridge';
import { DreamAgentTask } from './dream-agent-bridge';

export type ApprovalGate = 'gate1' | 'gate2' | 'merge' | 'deployment';

export interface AutoApprovalRule {
  approval_type: ApprovalRequest['approval_type'];
  max_severity: 'low' | 'medium' | 'high' | 'critical';
  max_complexity: 'small' | 'medium' | 'large';
  required_checks: string[];
  auto_approve: boolean;
  timeout_minutes: number;
}

export class ApprovalBridge {
  private approvals: Map<string, ApprovalRequest> = new Map();
  private autoApprovalRules: AutoApprovalRule[];
  private defaultTimeoutMinutes: number;

  constructor(config: { defaultTimeoutMinutes?: number } = {}) {
    this.defaultTimeoutMinutes = config.defaultTimeoutMinutes ?? 30;
    this.autoApprovalRules = this.initDefaultRules();
  }

  createApprovalForGate1(
    evolutionRecord: EvolutionRecord,
    dzeState: DZEChainState,
    proposal: EvolutionProposal
  ): ApprovalRequest {
    const approval: ApprovalRequest = {
      id: `appr_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      evolution_id: evolutionRecord.id,
      proposal_id: proposal.id,
      approval_type: 'design',
      title: `[Gate 1 - 方案审批] ${proposal.title}`,
      description: this.generateGate1Description(evolutionRecord, dzeState, proposal),
      requester: 'evolution-engine',
      approvers: ['human-approver', 'governance-agent'],
      status: 'pending',
      created_at: new Date().toISOString(),
    };

    this.approvals.set(approval.id, approval);
    return { ...approval };
  }

  createApprovalForGate2(
    evolutionRecord: EvolutionRecord,
    dzeState: DZEChainState
  ): ApprovalRequest {
    const approval: ApprovalRequest = {
      id: `appr_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      evolution_id: evolutionRecord.id,
      approval_type: 'kickoff',
      title: `[Gate 2 - 开工审批] ${dzeState.task_scope}`,
      description: this.generateGate2Description(evolutionRecord, dzeState),
      requester: 'dze-bridge',
      approvers: ['human-approver', 'governance-agent'],
      status: 'pending',
      created_at: new Date().toISOString(),
    };

    this.approvals.set(approval.id, approval);
    return { ...approval };
  }

  createApprovalForMerge(
    evolutionRecord: EvolutionRecord,
    task: DreamAgentTask
  ): ApprovalRequest {
    const approval: ApprovalRequest = {
      id: `appr_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      evolution_id: evolutionRecord.id,
      task_id: task.task_id,
      approval_type: 'merge',
      title: `[合入审批] ${task.title}`,
      description: this.generateMergeDescription(evolutionRecord, task),
      requester: 'dream-agent-bridge',
      approvers: ['human-approver', 'governance-agent'],
      status: 'pending',
      created_at: new Date().toISOString(),
    };

    this.approvals.set(approval.id, approval);
    return { ...approval };
  }

  createApprovalForDeployment(
    evolutionRecord: EvolutionRecord,
    dzeState: DZEChainState
  ): ApprovalRequest {
    const approval: ApprovalRequest = {
      id: `appr_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      evolution_id: evolutionRecord.id,
      approval_type: 'deployment',
      title: `[部署审批] ${dzeState.task_scope}`,
      description: this.generateDeploymentDescription(evolutionRecord, dzeState),
      requester: 'dze-bridge',
      approvers: ['human-approver'],
      status: 'pending',
      created_at: new Date().toISOString(),
    };

    this.approvals.set(approval.id, approval);
    return { ...approval };
  }

  approve(approvalId: string, approver: string): ApprovalRequest {
    const approval = this.getApproval(approvalId);
    approval.status = 'approved';
    approval.decided_at = new Date().toISOString();
    approval.decided_by = approver;
    this.approvals.set(approvalId, approval);
    return { ...approval };
  }

  reject(approvalId: string, approver: string, reason: string): ApprovalRequest {
    const approval = this.getApproval(approvalId);
    approval.status = 'rejected';
    approval.decided_at = new Date().toISOString();
    approval.decided_by = approver;
    approval.description += `\n\nRejection reason: ${reason}`;
    this.approvals.set(approvalId, approval);
    return { ...approval };
  }

  autoApproveIfEligible(approvalId: string): {
    approved: boolean;
    reason: string;
  } {
    const approval = this.getApproval(approvalId);
    if (approval.status !== 'pending') {
      return { approved: false, reason: `Approval already ${approval.status}` };
    }

    const rule = this.autoApprovalRules.find(r => r.approval_type === approval.approval_type);
    if (!rule || !rule.auto_approve) {
      return { approved: false, reason: 'No auto-approve rule for this type' };
    }

    const created = new Date(approval.created_at).getTime();
    const now = Date.now();
    const elapsed = (now - created) / 60000;

    if (elapsed < rule.timeout_minutes) {
      return {
        approved: false,
        reason: `Timeout not reached: ${elapsed.toFixed(1)}/${rule.timeout_minutes} minutes`,
      };
    }

    approval.status = 'timeout_auto_approved';
    approval.decided_at = new Date().toISOString();
    approval.decided_by = 'auto-approval-bot';
    this.approvals.set(approvalId, approval);

    return {
      approved: true,
      reason: `Auto-approved after ${rule.timeout_minutes} minutes timeout`,
    };
  }

  checkTimeouts(): ApprovalRequest[] {
    const autoApproved: ApprovalRequest[] = [];

    for (const [id, approval] of this.approvals) {
      if (approval.status === 'pending') {
        const result = this.autoApproveIfEligible(id);
        if (result.approved) {
          autoApproved.push(this.getApproval(id));
        }
      }
    }

    return autoApproved;
  }

  getApproval(approvalId: string): ApprovalRequest {
    const approval = this.approvals.get(approvalId);
    if (!approval) throw new Error(`Approval ${approvalId} not found`);
    return { ...approval };
  }

  getAllApprovals(): ApprovalRequest[] {
    return Array.from(this.approvals.values());
  }

  getApprovalsByEvolution(evolutionId: string): ApprovalRequest[] {
    return Array.from(this.approvals.values()).filter(a => a.evolution_id === evolutionId);
  }

  getPendingApprovals(): ApprovalRequest[] {
    return Array.from(this.approvals.values()).filter(a => a.status === 'pending');
  }

  getApprovalsByType(type: ApprovalRequest['approval_type']): ApprovalRequest[] {
    return Array.from(this.approvals.values()).filter(a => a.approval_type === type);
  }

  setAutoApprovalRule(rule: AutoApprovalRule): void {
    const idx = this.autoApprovalRules.findIndex(r => r.approval_type === rule.approval_type);
    if (idx >= 0) {
      this.autoApprovalRules[idx] = rule;
    } else {
      this.autoApprovalRules.push(rule);
    }
  }

  private initDefaultRules(): AutoApprovalRule[] {
    return [
      {
        approval_type: 'design',
        max_severity: 'low',
        max_complexity: 'small',
        required_checks: ['syntax_check', 'impact_analysis'],
        auto_approve: true,
        timeout_minutes: 30,
      },
      {
        approval_type: 'kickoff',
        max_severity: 'low',
        max_complexity: 'small',
        required_checks: ['plan_review', 'risk_assessment'],
        auto_approve: true,
        timeout_minutes: 30,
      },
      {
        approval_type: 'merge',
        max_severity: 'medium',
        max_complexity: 'medium',
        required_checks: ['validator_approved', 'test_passed'],
        auto_approve: true,
        timeout_minutes: 60,
      },
      {
        approval_type: 'deployment',
        max_severity: 'low',
        max_complexity: 'small',
        required_checks: ['staging_test', 'rollback_plan'],
        auto_approve: false,
        timeout_minutes: 120,
      },
      {
        approval_type: 'risk',
        max_severity: 'low',
        max_complexity: 'small',
        required_checks: ['risk_mitigation'],
        auto_approve: false,
        timeout_minutes: 60,
      },
    ];
  }

  private generateGate1Description(
    evolution: EvolutionRecord,
    dze: DZEChainState,
    proposal: EvolutionProposal
  ): string {
    return `
Evolution ID: ${evolution.id}
Proposal ID: ${proposal.id}
Change Type: ${proposal.change_type}
Complexity: ${dze.complexity}
Affected Modules: ${dze.affected_modules.join(', ')}

## 提案内容
${proposal.description}

## 审批要点
1. 技术方案方向是否正确
2. 影响范围评估是否合理
3. 是否需要调整范围

请在 ${this.defaultTimeoutMinutes} 分钟内审批，超时将自动批准。
    `.trim();
  }

  private generateGate2Description(
    evolution: EvolutionRecord,
    dze: DZEChainState
  ): string {
    return `
Evolution ID: ${evolution.id}
DZE Trigger ID: ${dze.trigger_id}
Complexity: ${dze.complexity}
Estimated Lines: ${dze.estimated_lines}
Affected Modules: ${dze.affected_modules.join(', ')}

## 实施计划
- 当前阶段: ${dze.current_phase}
- 已完成阶段: ${dze.phases_completed.join(' → ')}
- 待执行阶段: ${dze.phases_pending.join(' → ')}

## 审批要点
1. 实施计划是否合理
2. 资源评估是否充分
3. 风险预案是否完备

请在 ${this.defaultTimeoutMinutes} 分钟内审批，超时将自动批准。
    `.trim();
  }

  private generateMergeDescription(
    evolution: EvolutionRecord,
    task: DreamAgentTask
  ): string {
    return `
Evolution ID: ${evolution.id}
Task ID: ${task.task_id}
Priority: ${task.priority}
Reward: ${task.reward_estimate} DREAM

## 任务内容
${task.description}

## 审批要点
1. 代码质量是否达标
2. 是否通过 Validator 验证
3. 是否有回滚方案

请在 ${this.defaultTimeoutMinutes} 分钟内审批，超时将自动批准。
    `.trim();
  }

  private generateDeploymentDescription(
    evolution: EvolutionRecord,
    dze: DZEChainState
  ): string {
    return `
Evolution ID: ${evolution.id}
DZE Trigger ID: ${dze.trigger_id}
Deployment Ref: ${dze.artifacts.e3_deployment_ref || 'pending'}

## 部署内容
- 任务范围: ${dze.task_scope}
- 复杂度: ${dze.complexity}
- 影响模块: ${dze.affected_modules.join(', ')}

## 审批要点
1. 生产环境影响评估
2. 回滚方案确认
3. 监控告警确认

部署审批需人工确认，不自动批准。
    `.trim();
  }
}
