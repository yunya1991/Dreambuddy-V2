/**
 * ResearchOrchestrator — 架构调研编排元 SKILL 实现
 * =====================================================
 * 自动编排"问题定义→调研→SPEC→评审→Plan"五阶段闭环。
 * 每步调度子 SKILL 输出结果，用户确认后推进。
 *
 * 设计原则（SPEC §3.9）:
 *   1. 每步强制用户确认门 — 阶段间不可跳过
 *   2. 可回退 — 评审不通过可回退到 SPEC
 *   3. 子 SKILL 选择 — 简单/复杂问题分流
 *   4. 认知闭环 — 每步 record，流程结束 verify
 *
 * 位置: 3.1-FRONTEND/src/lib/research-orchestrator.ts
 *
 * 复用:
 *   - callCognitive (cognitive-client.ts) — record/verify
 *   - 五个子 SKILL（通过 SKILL 注册中心调度）
 */

import { callCognitive } from './cognitive-client';

// ============================================================
// 1. 类型定义
// ============================================================

export type OrchestratorStage =
  | 'INIT'
  | 'PROBLEM'
  | 'RESEARCH'
  | 'SPEC'
  | 'REVIEW'
  | 'PLAN'
  | 'DONE';

export interface StageResult {
  stage: OrchestratorStage;
  skill_called: string;
  output: any;
  recommended_next: string;
  recommended_skill: string;
  needs_confirmation: boolean;
  error?: string;
}

export interface OrchestratorStatus {
  current_stage: OrchestratorStage;
  completed_stages: OrchestratorStage[];
  problem: string;
  stage_outputs: Partial<Record<OrchestratorStage, any>>;
  started_at: number;
}

// ============================================================
// 2. 阶段配置
// ============================================================

interface StageConfig {
  skill: string;
  description: string;
  next: OrchestratorStage;
  allow_rollback_to: OrchestratorStage[];
}

type ConfiguredStage = 'PROBLEM' | 'RESEARCH' | 'SPEC' | 'REVIEW' | 'PLAN';

const STAGE_CONFIGS: Record<ConfiguredStage, StageConfig> = {
  PROBLEM: {
    skill: 'dream-contradiction-theory',
    description: '问题定义（矛盾论拆解）',
    next: 'RESEARCH',
    allow_rollback_to: [],
  },
  RESEARCH: {
    skill: 'dream-research-workflow',
    description: '多源调研（4维交叉验证）',
    next: 'SPEC',
    allow_rollback_to: ['PROBLEM'],
  },
  SPEC: {
    skill: 'dream-qwen-eval-collab',
    description: 'SPEC 形成（spec 合成）',
    next: 'REVIEW',
    allow_rollback_to: ['RESEARCH', 'PROBLEM'],
  },
  REVIEW: {
    skill: 'dream-science-peer-review',
    description: '同行评审（Devil\'s Advocate）',
    next: 'PLAN',
    allow_rollback_to: ['SPEC', 'RESEARCH'],
  },
  PLAN: {
    skill: 'dream-eng-mgmt-workflow',
    description: '工程管理（里程碑/依赖/调度/风险）',
    next: 'DONE',
    allow_rollback_to: ['REVIEW', 'SPEC'],
  },
};

// ============================================================
// 3. ResearchOrchestrator 主类
// ============================================================

export class ResearchOrchestrator {
  private currentStage: OrchestratorStage = 'INIT';
  private completedStages: OrchestratorStage[] = [];
  private problem: string = '';
  private stageOutputs: Partial<Record<OrchestratorStage, any>> = {};
  private startedAt: number = 0;
  private isComplex: boolean = false;

  /**
   * 启动阶段1：问题定义
   *
   * @param problem 用户原始问题
   * @returns StageResult（含 recommended_next）
   */
  async start(problem: string): Promise<StageResult> {
    this.problem = problem;
    this.startedAt = Date.now();
    this.currentStage = 'PROBLEM';

    // 判断问题复杂度（简单/复杂），决定调研阶段用哪个子 SKILL
    this.isComplex = this.detectComplexity(problem);

    // 记录经验
    await this.recordExperience('start', `问题定义阶段启动: ${problem.slice(0, 100)}`);

    return this.executeStage('PROBLEM', problem);
  }

  /**
   * 确认当前阶段完成，推进到下一阶段
   */
  async confirm(): Promise<StageResult> {
    if (this.currentStage === 'INIT') {
      return this.errorResult('INIT', '未启动编排，请先调用 start()');
    }
    if (this.currentStage === 'DONE') {
      return this.doneResult();
    }

    // 记录已完成阶段
    if (!this.completedStages.includes(this.currentStage)) {
      this.completedStages.push(this.currentStage);
    }

    const config = STAGE_CONFIGS[this.currentStage as ConfiguredStage];
    if (!config) {
      return this.errorResult(this.currentStage, `未知的阶段: ${this.currentStage}`);
    }

    const nextStage = config.next;
    this.currentStage = nextStage;

    if (nextStage === 'DONE') {
      // 流程结束，verify
      await this.verifyExperience();
      return this.doneResult();
    }

    return this.executeStage(nextStage as ConfiguredStage, this.getInputForStage(nextStage as ConfiguredStage));
  }

  /**
   * 回退到指定阶段
   */
  async rollback(targetStage: OrchestratorStage): Promise<StageResult> {
    const config = STAGE_CONFIGS[this.currentStage as ConfiguredStage];
    if (!config) {
      return this.errorResult(this.currentStage, `当前阶段不支持回退: ${this.currentStage}`);
    }

    if (!config.allow_rollback_to.includes(targetStage)) {
      return this.errorResult(this.currentStage, `不允许从 ${this.currentStage} 回退到 ${targetStage}`);
    }

    // 移除 targetStage 之后的所有已完成阶段
    const targetIdx = this.completedStages.indexOf(targetStage);
    if (targetIdx >= 0) {
      this.completedStages = this.completedStages.slice(0, targetIdx);
    }

    this.currentStage = targetStage;
    await this.recordExperience('rollback', `回退到 ${targetStage} 阶段`);

    return this.executeStage(targetStage as ConfiguredStage, this.getInputForStage(targetStage as ConfiguredStage));
  }

  /**
   * 获取当前阶段
   */
  getCurrentStage(): OrchestratorStage {
    return this.currentStage;
  }

  /**
   * 获取完整状态
   */
  getStatus(): OrchestratorStatus {
    return {
      current_stage: this.currentStage,
      completed_stages: [...this.completedStages],
      problem: this.problem,
      stage_outputs: { ...this.stageOutputs },
      started_at: this.startedAt,
    };
  }

  // ============================================================
  // 内部方法
  // ============================================================

  /**
   * 执行指定阶段（调度子 SKILL）
   * 注意：本编排器是元 SKILL，实际子 SKILL 调用由上层 Agent 完成
   * 这里只负责返回调度指令和推荐
   */
  private async executeStage(
    stage: ConfiguredStage,
    input: any,
  ): Promise<StageResult> {
    const config = STAGE_CONFIGS[stage];
    if (!config) {
      return this.errorResult(stage, `未知阶段配置: ${stage}`);
    }

    // 调研阶段根据复杂度选择子 SKILL
    let skillCalled = config.skill;
    if (stage === 'RESEARCH') {
      skillCalled = this.isComplex ? 'dream-qwen-eval-collab' : 'dream-research-workflow';
    }

    // 记录阶段输出（实际输出由子 SKILL 返回，此处为占位）
    this.stageOutputs[stage] = { input, skill: skillCalled, executed_at: Date.now() };

    return {
      stage,
      skill_called: skillCalled,
      output: { input, pending: true },
      recommended_next: `确认 ${config.description} 完成后，调用 confirm() 进入 ${config.next} 阶段`,
      recommended_skill: config.next === 'DONE' ? '' : STAGE_CONFIGS[config.next as ConfiguredStage]?.skill || '',
      needs_confirmation: true,
    };
  }

  /**
   * 获取指定阶段的输入（从上一阶段输出中提取）
   */
  private getInputForStage(stage: ConfiguredStage): any {
    const prevStage = this.getPreviousStage(stage);
    if (prevStage) {
      return this.stageOutputs[prevStage] || this.problem;
    }
    return this.problem;
  }

  /**
   * 获取上一阶段
   */
  private getPreviousStage(stage: OrchestratorStage): OrchestratorStage | null {
    const order: OrchestratorStage[] = ['PROBLEM', 'RESEARCH', 'SPEC', 'REVIEW', 'PLAN'];
    const idx = order.indexOf(stage);
    if (idx <= 0) return null;
    return order[idx - 1];
  }

  /**
   * 检测问题复杂度
   */
  private detectComplexity(problem: string): boolean {
    const complexKeywords = ['跨系统', '多模块', '架构重构', '迁移', '全量', '核心', '底层'];
    const length = problem.length;
    const hasComplexKeyword = complexKeywords.some(kw => problem.includes(kw));
    return hasComplexKeyword || length > 200;
  }

  /**
   * 记录经验到认知系统
   */
  private async recordExperience(stage: string, content: string): Promise<void> {
    try {
      await callCognitive('record', {
        content: `[research-orchestrator] ${stage}: ${content}`,
        quality_level: 'B',
        tags: `research-orchestrator,${stage}`,
      });
    } catch {
      // FAIL-OPEN
    }
  }

  /**
   * 验证经验（流程结束后调用）
   */
  private async verifyExperience(): Promise<void> {
    try {
      await callCognitive('verify', {
        memory_id: `research-orchestrator-${this.startedAt}`,
        success: true,
      });
    } catch {
      // FAIL-OPEN
    }
  }

  private errorResult(stage: OrchestratorStage, error: string): StageResult {
    return {
      stage,
      skill_called: '',
      output: null,
      recommended_next: error,
      recommended_skill: '',
      needs_confirmation: false,
      error,
    };
  }

  private doneResult(): StageResult {
    return {
      stage: 'DONE',
      skill_called: '',
      output: { completed: true, stages_completed: this.completedStages },
      recommended_next: '编排已完成，可开始执行',
      recommended_skill: '',
      needs_confirmation: false,
    };
  }
}

// 单例导出
let _instance: ResearchOrchestrator | null = null;
export function getResearchOrchestrator(): ResearchOrchestrator {
  if (!_instance) _instance = new ResearchOrchestrator();
  return _instance;
}
