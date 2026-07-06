/**
 * 意图 Spec 文档生成器 - 借鉴 Superpowers brainstorming 的 spec 产出模式
 *
 * 位置: 6-图结构上下文压缩/planner/intent-spec-writer.ts
 *
 * 功能:
 *   - 澄清完成后生成结构化的意图确认文档 (intent spec)
 *   - 文档持久化到 artifacts/intent-specs/
 *   - 作为 A 层编排的输入依据
 *
 * 设计依据: Superpowers brainstorming 阶段产出设计文档
 *   用户确认需求后，生成结构化 spec 作为后续阶段的输入
 */

import * as fs from 'fs';
import * as path from 'path';
import { IntentType } from './planner-types';
import { ClarificationAssessment, ClarificationQuestion } from './intent-clarification-engine';

// ============================================================
// 类型定义
// ============================================================

/** 澄清对话轮次 */
export interface ClarificationRound {
  round: number;
  question: string;
  questionType: 'multiple_choice' | 'open_ended';
  dimension: string;
  userAnswer: string;
  selectedOptionKey?: string;
  inferredIntent?: IntentType;
  inferredEntities?: Record<string, string>;
}

/** 意图 Spec 文档 */
export interface IntentSpec {
  /** Spec ID */
  specId: string;
  /** 关联的任务 ID */
  taskId: string;
  /** 关联的会话 ID */
  sessionId: string;
  /** 创建时间 */
  createdAt: string;
  /** 更新时间 */
  updatedAt: string;
  /** 用户原始请求 */
  originalMessage: string;
  /** 最终确认的意图 */
  finalIntent: IntentType;
  /** 最终确认的实体 */
  finalEntities: Record<string, string>;
  /** 意图置信度 */
  confidence: number;
  /** 澄清轮次记录 */
  clarificationRounds: ClarificationRound[];
  /** 初始模糊度评估 */
  initialAssessment: {
    ambiguityScore: number;
    ambiguityLevel: string;
    reasons: string[];
  };
  /** 范围边界（澄清后明确的） */
  scope: {
    included: string[];
    excluded: string[];
  };
  /** 成功标准 */
  successCriteria: string[];
  /** 约束条件 */
  constraints: string[];
  /** Spec 状态 */
  status: 'draft' | 'confirmed' | 'superseded';
}

// ============================================================
// Spec 文档生成器
// ============================================================

export class IntentSpecWriter {
  private specDir: string;

  constructor(artifactsDir: string) {
    this.specDir = path.join(artifactsDir, 'intent-specs');
    this.ensureDir();
  }

  private ensureDir(): void {
    if (!fs.existsSync(this.specDir)) {
      fs.mkdirSync(this.specDir, { recursive: true });
    }
  }

  /**
   * 创建初始 Spec（澄清开始前）
   */
  createInitialSpec(
    taskId: string,
    sessionId: string,
    originalMessage: string,
    initialIntent: IntentType,
    initialEntities: Record<string, string>,
    initialConfidence: number,
    assessment: ClarificationAssessment,
  ): IntentSpec {
    const specId = `spec_${taskId}`;
    const now = new Date().toISOString();

    const spec: IntentSpec = {
      specId,
      taskId,
      sessionId,
      createdAt: now,
      updatedAt: now,
      originalMessage,
      finalIntent: initialIntent,
      finalEntities: { ...initialEntities },
      confidence: initialConfidence,
      clarificationRounds: [],
      initialAssessment: {
        ambiguityScore: assessment.ambiguityScore,
        ambiguityLevel: assessment.ambiguity,
        reasons: [...assessment.ambiguityReasons],
      },
      scope: {
        included: [],
        excluded: [],
      },
      successCriteria: [],
      constraints: [],
      status: 'draft',
    };

    this.saveSpec(spec);
    return spec;
  }

  /**
   * 记录一轮澄清问答
   */
  recordClarificationRound(
    spec: IntentSpec,
    question: ClarificationQuestion,
    userAnswer: string,
    selectedOptionKey?: string,
    inferredIntent?: IntentType,
    inferredEntities?: Record<string, string>,
  ): IntentSpec {
    const round: ClarificationRound = {
      round: spec.clarificationRounds.length + 1,
      question: question.question,
      questionType: question.type,
      dimension: question.dimension,
      userAnswer,
      selectedOptionKey,
      inferredIntent,
      inferredEntities,
    };

    spec.clarificationRounds.push(round);
    spec.updatedAt = new Date().toISOString();

    if (inferredIntent) {
      spec.finalIntent = inferredIntent;
    }
    if (inferredEntities) {
      spec.finalEntities = { ...spec.finalEntities, ...inferredEntities };
    }

    this.saveSpec(spec);
    return spec;
  }

  /**
   * 确认 Spec（澄清完成，用户确认后）
   */
  confirmSpec(spec: IntentSpec): IntentSpec {
    spec.status = 'confirmed';
    spec.updatedAt = new Date().toISOString();
    this.saveSpec(spec);
    return spec;
  }

  /**
   * 从 Spec 生成 Markdown 文档
   */
  toMarkdown(spec: IntentSpec): string {
    const lines: string[] = [];

    lines.push(`# 意图确认文档 (${spec.specId})`);
    lines.push('');
    lines.push(`- **任务 ID**: ${spec.taskId}`);
    lines.push(`- **会话 ID**: ${spec.sessionId}`);
    lines.push(`- **创建时间**: ${spec.createdAt}`);
    lines.push(`- **状态**: ${spec.status}`);
    lines.push('');

    lines.push('## 1. 用户原始请求');
    lines.push('');
    lines.push(`> ${spec.originalMessage}`);
    lines.push('');

    lines.push('## 2. 初始意图识别');
    lines.push('');
    lines.push(`- **意图**: ${spec.finalIntent}`);
    lines.push(`- **置信度**: ${Math.round(spec.confidence * 100)}%`);
    lines.push(`- **实体**: ${JSON.stringify(spec.finalEntities)}`);
    lines.push('');

    lines.push('## 3. 初始模糊度评估');
    lines.push('');
    lines.push(`- **模糊度评分**: ${spec.initialAssessment.ambiguityScore}/100`);
    lines.push(`- **模糊度级别**: ${spec.initialAssessment.ambiguityLevel}`);
    lines.push(`- **模糊原因**:`);
    for (const reason of spec.initialAssessment.reasons) {
      lines.push(`  - ${reason}`);
    }
    lines.push('');

    if (spec.clarificationRounds.length > 0) {
      lines.push('## 4. 澄清对话记录');
      lines.push('');
      for (const round of spec.clarificationRounds) {
        lines.push(`### 第 ${round.round} 轮（${round.dimension}）`);
        lines.push('');
        lines.push(`**问**: ${round.question}`);
        lines.push('');
        lines.push(`**答**: ${round.userAnswer}`);
        if (round.selectedOptionKey) {
          lines.push(`- 选项: ${round.selectedOptionKey}`);
        }
        if (round.inferredIntent) {
          lines.push(`- 推断意图: ${round.inferredIntent}`);
        }
        if (round.inferredEntities) {
          lines.push(`- 推断实体: ${JSON.stringify(round.inferredEntities)}`);
        }
        lines.push('');
      }
    }

    lines.push('## 5. 最终确认');
    lines.push('');
    lines.push(`- **最终意图**: ${spec.finalIntent}`);
    lines.push(`- **最终实体**: ${JSON.stringify(spec.finalEntities)}`);
    lines.push('');

    if (spec.scope.included.length > 0 || spec.scope.excluded.length > 0) {
      lines.push('## 6. 范围边界');
      lines.push('');
      if (spec.scope.included.length > 0) {
        lines.push('### 包含');
        for (const item of spec.scope.included) {
          lines.push(`- ${item}`);
        }
        lines.push('');
      }
      if (spec.scope.excluded.length > 0) {
        lines.push('### 不包含');
        for (const item of spec.scope.excluded) {
          lines.push(`- ${item}`);
        }
        lines.push('');
      }
    }

    if (spec.successCriteria.length > 0) {
      lines.push('## 7. 成功标准');
      lines.push('');
      for (const criterion of spec.successCriteria) {
        lines.push(`- [ ] ${criterion}`);
      }
      lines.push('');
    }

    if (spec.constraints.length > 0) {
      lines.push('## 8. 约束条件');
      lines.push('');
      for (const constraint of spec.constraints) {
        lines.push(`- ${constraint}`);
      }
      lines.push('');
    }

    lines.push('---');
    lines.push(`*最后更新: ${spec.updatedAt}*`);

    return lines.join('\n');
  }

  /**
   * 保存 Spec 到文件
   */
  saveSpec(spec: IntentSpec): void {
    this.ensureDir();
    const jsonPath = path.join(this.specDir, `${spec.specId}.json`);
    fs.writeFileSync(jsonPath, JSON.stringify(spec, null, 2), 'utf-8');

    const mdPath = path.join(this.specDir, `${spec.specId}.md`);
    fs.writeFileSync(mdPath, this.toMarkdown(spec), 'utf-8');
  }

  /**
   * 加载 Spec
   */
  loadSpec(specId: string): IntentSpec | null {
    const jsonPath = path.join(this.specDir, `${specId}.json`);
    if (!fs.existsSync(jsonPath)) {
      return null;
    }
    try {
      const content = fs.readFileSync(jsonPath, 'utf-8');
      return JSON.parse(content) as IntentSpec;
    } catch {
      return null;
    }
  }

  /**
   * 按任务 ID 查找 Spec
   */
  findByTaskId(taskId: string): IntentSpec | null {
    return this.loadSpec(`spec_${taskId}`);
  }

  /**
   * 列出所有 Spec
   */
  listSpecs(limit: number = 20): IntentSpec[] {
    try {
      const files = fs.readdirSync(this.specDir)
        .filter(f => f.endsWith('.json'))
        .sort((a, b) => {
          const aPath = path.join(this.specDir, a);
          const bPath = path.join(this.specDir, b);
          return fs.statSync(bPath).mtime.getTime() - fs.statSync(aPath).mtime.getTime();
        })
        .slice(0, limit);

      return files
        .map(f => {
          try {
            const content = fs.readFileSync(path.join(this.specDir, f), 'utf-8');
            return JSON.parse(content) as IntentSpec;
          } catch {
            return null;
          }
        })
        .filter((s): s is IntentSpec => s !== null);
    } catch {
      return [];
    }
  }
}
