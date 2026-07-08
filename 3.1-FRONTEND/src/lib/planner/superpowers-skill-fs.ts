/**
 * Superpowers SKILL.md 格式文件系统适配器
 *
 * 位置: 6-图结构上下文压缩/planner/superpowers-skill-fs.ts
 *
 * 功能:
 *   - 从文件/目录导入 Superpowers SKILL.md
 *   - 导出 Superpowers SKILL.md 到文件
 *
 * 注意: 此文件依赖 Node.js fs/path 模块
 *       仅在 Node.js 环境（后端/服务端）使用
 *       浏览器端不要导入此文件
 */

import * as fs from 'fs';
import * as path from 'path';
import {
  importSuperpowersSkill,
  exportToSuperpowersSkill,
  type ImportConfig,
  type SkillCapability,
} from './superpowers-skill-adapter';

/**
 * 从文件导入 Superpowers Skill
 */
export function importSuperpowersSkillFromFile(
  filePath: string,
  config?: ImportConfig,
): SkillCapability {
  const content = fs.readFileSync(filePath, 'utf-8');
  return importSuperpowersSkill(content, config);
}

/**
 * 从目录批量导入 Superpowers Skills
 * 目录结构: skills/<skill-name>/SKILL.md
 */
export function importSuperpowersSkillsFromDir(
  dirPath: string,
  config?: ImportConfig,
): SkillCapability[] {
  const skills: SkillCapability[] = [];

  if (!fs.existsSync(dirPath)) {
    return skills;
  }

  const entries = fs.readdirSync(dirPath, { withFileTypes: true });

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;

    const skillMdPath = path.join(dirPath, entry.name, 'SKILL.md');
    if (!fs.existsSync(skillMdPath)) continue;

    try {
      const skill = importSuperpowersSkillFromFile(skillMdPath, config);
      skills.push(skill);
    } catch (err) {
      console.warn(`[SuperpowersAdapter] 导入失败 ${entry.name}: ${err}`);
    }
  }

  return skills;
}

/**
 * 导出 Skill 到 Superpowers 格式文件
 */
export function exportToSuperpowersSkillFile(
  skill: SkillCapability,
  outputDir: string,
): string {
  const content = exportToSuperpowersSkill(skill);
  const skillDir = path.join(outputDir, skill.metadata.id);

  if (!fs.existsSync(skillDir)) {
    fs.mkdirSync(skillDir, { recursive: true });
  }

  const filePath = path.join(skillDir, 'SKILL.md');
  fs.writeFileSync(filePath, content, 'utf-8');

  return filePath;
}
