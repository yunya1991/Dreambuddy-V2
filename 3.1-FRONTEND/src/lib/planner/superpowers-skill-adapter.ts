/**
 * Superpowers SKILL.md 格式适配器
 *
 * 位置: 6-图结构上下文压缩/planner/superpowers-skill-adapter.ts
 *
 * 功能:
 *   - 导入 Superpowers SKILL.md 格式为 SkillCapability
 *   - 导出 SkillCapability 为 Superpowers SKILL.md 格式
 *
 * 设计依据: Superpowers 插件生态的 SKILL.md 格式
 *   - frontmatter (YAML): name, description
 *   - Markdown 正文: 指令、检查清单、流程图、HARD-GATE
 *
 * 注意: 导入的 Superpowers Skill 作为 "方法论技能" 注册
 *   它们不直接执行交易逻辑，而是约束执行流程
 */

import {
  SkillCapability,
  SkillMetadata,
  SkillResult,
  ExecutionContext,
  SkillChain,
  ThinkStage,
} from './skill-types';

// ============================================================
// 类型定义
// ============================================================

/** 解析后的 SKILL.md frontmatter */
export interface SkillFrontmatter {
  name: string;
  description: string;
  [key: string]: any;
}

/** Superpowers Skill 解析结果 */
export interface ParsedSuperpowersSkill {
  frontmatter: SkillFrontmatter;
  body: string;
  sections: Record<string, string>;
  hardGates: string[];
  checklists: string[];
}

/** 导入配置 */
export interface ImportConfig {
  /** 分配的链 */
  chain?: SkillChain;
  /** 分配的分类 */
  category?: string;
  /** 适用的阶段 */
  applicableStages?: ThinkStage[];
  /** 适用的意图 */
  applicableIntents?: string[];
  /** 预估 Token 消耗 */
  estimatedTokens?: number;
  /** 预估延迟（毫秒） */
  estimatedLatencyMs?: number;
}

// ============================================================
// 解析器
// ============================================================

/**
 * 解析 Superpowers SKILL.md 格式
 */
export function parseSuperpowersSkill(content: string): ParsedSuperpowersSkill {
  const lines = content.split('\n');
  const frontmatter: SkillFrontmatter = { name: '', description: '' };
  let frontmatterEnd = 0;

  // 解析 YAML frontmatter
  if (lines[0]?.trim() === '---') {
    const fmLines: string[] = [];
    for (let i = 1; i < lines.length; i++) {
      if (lines[i].trim() === '---') {
        frontmatterEnd = i + 1;
        break;
      }
      fmLines.push(lines[i]);
    }

    for (const line of fmLines) {
      const colonIdx = line.indexOf(':');
      if (colonIdx > 0) {
        const key = line.slice(0, colonIdx).trim();
        let value = line.slice(colonIdx + 1).trim();

        // 去掉引号
        if ((value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }

        frontmatter[key] = value;
      }
    }
  }

  const body = lines.slice(frontmatterEnd).join('\n');

  // 提取 HARD-GATE
  const hardGates: string[] = [];
  const gateRegex = /<HARD-GATE>([\s\S]*?)<\/HARD-GATE>/gi;
  let match;
  while ((match = gateRegex.exec(body)) !== null) {
    hardGates.push(match[1].trim());
  }

  // 提取检查清单
  const checklists: string[] = [];
  const checklistRegex = /^[-*]\s+\[.?\]\s+(.+)$/gm;
  while ((match = checklistRegex.exec(body)) !== null) {
    checklists.push(match[1].trim());
  }

  // 按章节分段
  const sections: Record<string, string> = {};
  let currentSection = 'overview';
  const sectionLines: string[] = [];

  for (const line of lines.slice(frontmatterEnd)) {
    const headingMatch = line.match(/^##\s+(.+)$/);
    if (headingMatch) {
      if (sectionLines.length > 0) {
        sections[currentSection] = sectionLines.join('\n').trim();
        sectionLines.length = 0;
      }
      currentSection = headingMatch[1].trim().toLowerCase().replace(/\s+/g, '_');
    } else {
      sectionLines.push(line);
    }
  }
  if (sectionLines.length > 0) {
    sections[currentSection] = sectionLines.join('\n').trim();
  }

  return {
    frontmatter,
    body,
    sections,
    hardGates,
    checklists,
  };
}

// ============================================================
// 导入器
// ============================================================

/**
 * 将 Superpowers SKILL.md 转换为 SkillCapability
 *
 * 注意: 导入的 Skill 作为 "方法论技能"，其 execute 方法
 * 仅返回指令内容，实际执行由 MethodologyExecutor 控制
 */
export function importSuperpowersSkill(
  content: string,
  config: ImportConfig = {},
): SkillCapability {
  const parsed = parseSuperpowersSkill(content);
  const { frontmatter } = parsed;

  const id = `superpowers-${frontmatter.name || 'unknown'}`
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '-')
    .replace(/-+/g, '-');

  const metadata: SkillMetadata = {
    id,
    name: frontmatter.name || id,
    description: frontmatter.description || 'Imported from Superpowers SKILL.md',
    chain: config.chain || 'A',
    category: config.category || 'methodology',
    version: frontmatter.version || '1.0.0',
    tags: [
      'superpowers',
      'methodology',
      frontmatter.name || '',
      ...(parsed.hardGates.length > 0 ? ['has-hard-gate'] : []),
    ].filter(Boolean),
    estimatedTokens: config.estimatedTokens ?? 500,
    estimatedLatencyMs: config.estimatedLatencyMs ?? 1000,
    confidenceRange: [70, 90] as [number, number],
    applicableIntents: config.applicableIntents || ['*'],
    applicableStages: config.applicableStages || ['analysis', 'validate'],
  };

  // 创建方法论技能
  const skill: SkillCapability = {
    metadata,

    inputSchema: [
      {
        name: 'context',
        type: 'object',
        required: false,
        description: '执行上下文',
      },
    ],

    outputSchema: [
      {
        name: 'instructions',
        type: 'string',
        description: '方法论指令内容',
      },
      {
        name: 'hardGates',
        type: 'array',
        description: '硬约束列表',
      },
      {
        name: 'checklists',
        type: 'array',
        description: '检查清单项',
      },
    ],

    async execute(inputs: Record<string, unknown>, context: ExecutionContext): Promise<SkillResult> {
      return {
        success: true,
        capabilityId: id,
        outputs: {
          analysis: parsed.body,
          strategy: frontmatter.name,
          values: {
            hardGatesCount: parsed.hardGates.length,
            checklistsCount: parsed.checklists.length,
          },
        },
        confidence: 75,
        metadata: {
          instructions: parsed.body,
          hardGates: parsed.hardGates,
          checklists: parsed.checklists,
          sections: parsed.sections,
        },
      };
    },

    getFallback: async (inputs: Record<string, unknown>): Promise<SkillResult> => {
      return {
        success: true,
        capabilityId: id,
        outputs: {
          analysis: parsed.body,
        },
        confidence: 70,
        metadata: {
          instructions: parsed.body,
          hardGates: parsed.hardGates,
          checklists: parsed.checklists,
        },
      };
    },
  };

  return skill;
}

// ============================================================
// 导出器
// ============================================================

/**
 * 将 SkillCapability 导出为 Superpowers SKILL.md 格式
 */
export function exportToSuperpowersSkill(skill: SkillCapability): string {
  const { metadata } = skill;

  const frontmatterLines = [
    '---',
    `name: ${metadata.name || metadata.id}`,
    `description: ${metadata.description}`,
    `version: ${metadata.version || '1.0.0'}`,
    `tags: ${metadata.tags.join(', ')}`,
    `category: ${metadata.category}`,
    `chain: ${metadata.chain}`,
    '---',
    '',
  ];

  const bodyLines: string[] = [];

  bodyLines.push(`# ${metadata.name || metadata.id}`);
  bodyLines.push('');
  bodyLines.push(`> ${metadata.description}`);
  bodyLines.push('');

  // 元信息
  bodyLines.push('## Metadata');
  bodyLines.push('');
  bodyLines.push(`- **ID**: ${metadata.id}`);
  bodyLines.push(`- **链**: ${metadata.chain}`);
  bodyLines.push(`- **分类**: ${metadata.category}`);
  bodyLines.push(`- **版本**: ${metadata.version || '1.0.0'}`);
  bodyLines.push(`- **预估 Token**: ${metadata.estimatedTokens}`);
  bodyLines.push(`- **预估延迟**: ${metadata.estimatedLatencyMs}ms`);
  bodyLines.push(`- **置信度范围**: ${metadata.confidenceRange[0]} - ${metadata.confidenceRange[1]}`);
  bodyLines.push('');

  // 适用场景
  bodyLines.push('## Applicable Scenarios');
  bodyLines.push('');
  bodyLines.push(`- **适用意图**: ${metadata.applicableIntents.join(', ')}`);
  bodyLines.push(`- **适用阶段**: ${metadata.applicableStages.join(', ')}`);
  if (metadata.marketConditions) {
    bodyLines.push(`- **市场条件**: ${metadata.marketConditions.join(', ')}`);
  }
  bodyLines.push('');

  // 输入
  if (skill.inputSchema && skill.inputSchema.length > 0) {
    bodyLines.push('## Inputs');
    bodyLines.push('');
    for (const input of skill.inputSchema) {
      const req = input.required ? '(required)' : '(optional)';
      bodyLines.push(`- **${input.name}** (${input.type}) ${req}: ${input.description || ''}`);
    }
    bodyLines.push('');
  }

  // 输出
  if (skill.outputSchema && skill.outputSchema.length > 0) {
    bodyLines.push('## Outputs');
    bodyLines.push('');
    for (const output of skill.outputSchema) {
      bodyLines.push(`- **${output.name}** (${output.type}): ${output.description || ''}`);
    }
    bodyLines.push('');
  }

  // 标签
  if (metadata.tags && metadata.tags.length > 0) {
    bodyLines.push('## Tags');
    bodyLines.push('');
    for (const tag of metadata.tags) {
      bodyLines.push(`- ${tag}`);
    }
    bodyLines.push('');
  }

  bodyLines.push('---');
  bodyLines.push(`*导出自 Dreambuddy OS SkillsRegistry (${new Date().toISOString()})*`);

  return frontmatterLines.join('\n') + bodyLines.join('\n');
}
