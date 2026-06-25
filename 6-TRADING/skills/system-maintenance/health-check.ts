#!/usr/bin/env npx tsx
/**
 * 系统维护 SKILL - 架构健康检查脚本
 * 基于 SYSTEM_ARCHITECTURE_OVERVIEW.md 执行定期检查
 */

import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';

const ROOT = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2';
const ARCH_DOC = path.join(ROOT, '1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md');
const REPORTS_DIR = path.join(ROOT, '1-ARCHITECTURE/.maintenance-reports');

// ==================== 类型定义 ====================

interface CheckResult {
  module: string;
  chapter: string;
  status: '🟢' | '🟡' | '🔴';
  score: number;
  expected: string;
  actual: string;
  issues: string[];
  action: '无需处理' | '待完善' | '需紧急修复';
}

interface MaintenanceReport {
  timestamp: string;
  period: string;
  overallHealth: 'A' | 'B' | 'C' | 'D';
  overallScore: number;
  checks: CheckResult[];
  summary: {
    total: number;
    healthy: number;
    warning: number;
    critical: number;
  };
  nextActions: Array<{
    priority: 'high' | 'medium' | 'low';
    issue: string;
    action: string;
    trigger: string;
  }>;
  trend: {
    lastWeek: string;
    thisWeek: string;
    direction: '↑' | '↓' | '→';
  };
}

// ==================== 检查项定义 ====================

const CHECK_MODULES: Array<{
  id: string;
  name: string;
  chapter: string;
  paths: string[];
  checks: string[];
  expectedStatus: string;
}> = [
  {
    id: 'skeleton',
    name: '骨架层（三链定义）',
    chapter: '第二章',
    paths: [
      '6-图结构上下文压缩/planner/step-types.ts',
      '6-图结构上下文压缩/planner/step-types.ts',
    ],
    checks: ['s_chain_defined', 'c_chain_defined', 'f_chain_defined'],
    expectedStatus: '90%',
  },
  {
    id: 'skills',
    name: '血肉层（SKILL库）',
    chapter: '第五章',
    paths: [
      '6-图结构上下文压缩/planner/skills-registry.ts',
      '6-TRADING/skills/',
    ],
    checks: ['skill_registry_exists', 'skill_count', 'chain_mapping'],
    expectedStatus: '75%',
  },
  {
    id: 'execution',
    name: '灵魂层（动态执行）',
    chapter: '第六章',
    paths: [
      '6-图结构上下文压缩/planner/reflection-engine.ts',
      '3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/',
    ],
    checks: ['reflection_engine', 'five_decisions', 'confidence评估'],
    expectedStatus: '60%',
  },
  {
    id: 'bac',
    name: 'BAC图结构',
    chapter: '第三章',
    paths: [
      '6-图结构上下文压缩/models.ts',
      '6-图结构上下文压缩/compressor.ts',
    ],
    checks: ['models_defined', 'compressor_logic'],
    expectedStatus: '85%',
  },
  {
    id: 'chain_planner',
    name: 'ChainPlanner',
    chapter: '第四章',
    paths: [
      '6-图结构上下文压缩/planner/planner.ts',
      'experiments/ab-trading/core/chain_planner.py',
    ],
    checks: ['planner_exists', 'four_dimensions', 'cost_calculation'],
    expectedStatus: '55%',
  },
  {
    id: 'cross_validation',
    name: '三链交叉验证',
    chapter: '第四章',
    paths: [
      '6-图结构上下文压缩/planner/cross-validator.ts',
    ],
    checks: ['validator_exists', 'voter_logic'],
    expectedStatus: '80%',
  },
  {
    id: 'evolution',
    name: '进化系统（动力引擎）',
    chapter: '第七章',
    paths: [
      '2-KNOWLEDGE/',
      '3-FRONTEND/dream-universal-gateway/src/lib/intent/intent-memory.ts',
      '3-FRONTEND/dream-universal-gateway/src/lib/memory/user-preference-memory.ts',
    ],
    checks: ['knowledge_base', 'memory_system', 'index_system', 'learning_loop'],
    expectedStatus: '55%',
  },
  {
    id: 'dze_chain',
    name: 'DZE开发链',
    chapter: '第八章',
    paths: [
      '3-CHAIN-DEVELOPMENT/',
      '3-CHAIN-DEVELOPMENT/scripts/chain_guard.py',
    ],
    checks: ['d_chain_docs', 'z_chain_docs', 'e_chain_docs', 'guard_exists'],
    expectedStatus: '70%',
  },
  {
    id: 'dream_agent',
    name: 'Dream-Agent协作网络',
    chapter: '第九章',
    paths: [
      '/Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/',
      '/Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/ledger/',
    ],
    checks: ['ledger_exists', 'token_design', 'constitution', 'four_roles'],
    expectedStatus: '65%',
  },
];

// ==================== 检查函数 ====================

function fileExists(relativePath: string): boolean {
  const fullPath = relativePath.startsWith('/')
    ? relativePath
    : path.join(ROOT, relativePath);
  return fs.existsSync(fullPath);
}

function countFiles(dir: string, pattern: string = '*.md'): number {
  try {
    const fullPath = path.join(ROOT, dir);
    if (!fs.existsSync(fullPath)) return 0;
    const files = fs.readdirSync(fullPath, { withFileTypes: true });
    return files.filter(f => f.isFile() && f.name.match(pattern.replace('*', '.*'))).length;
  } catch {
    return 0;
  }
}

function checkFileContent(filePath: string, patterns: string[]): Record<string, boolean> {
  const result: Record<string, boolean> = {};
  try {
    if (!fileExists(filePath)) {
      patterns.forEach(p => result[p] = false);
      return result;
    }
    const content = fs.readFileSync(
      filePath.startsWith('/') ? filePath : path.join(ROOT, filePath),
      'utf-8'
    );
    patterns.forEach(p => {
      result[p] = content.toLowerCase().includes(p.toLowerCase().replace('_', ' '));
    });
  } catch {
    patterns.forEach(p => result[p] = false);
  }
  return result;
}

function calculateScore(checks: Record<string, boolean>): number {
  const values = Object.values(checks);
  if (values.length === 0) return 0;
  const passed = values.filter(v => v).length;
  return Math.round((passed / values.length) * 100);
}

function getStatusFromScore(score: number): '🟢' | '🟡' | '🔴' {
  if (score >= 80) return '🟢';
  if (score >= 50) return '🟡';
  return '🔴';
}

function getActionFromScore(score: number): '无需处理' | '待完善' | '需紧急修复' {
  if (score >= 80) return '无需处理';
  if (score >= 50) return '待完善';
  return '需紧急修复';
}

// ==================== 执行检查 ====================

function runChecks(): CheckResult[] {
  const results: CheckResult[] = [];

  for (const module of CHECK_MODULES) {
    const issues: string[] = [];
    const checkResults: Record<string, boolean> = {};

    // 1. 检查文件存在性
    const existingPaths = module.paths.filter(p => fileExists(p));

    // 2. 执行各项检查
    for (const check of module.checks) {
      if (check === 'skill_count') {
        const count = countFiles('6-TRADING/skills/', '*.md');
        checkResults[check] = count >= 30;
        if (count < 30) issues.push(`SKILL数量不足: ${count}/30`);
      } else if (check === 'knowledge_base') {
        const count = countFiles('2-KNOWLEDGE/', '*.md');
        checkResults[check] = count >= 20;
        if (count < 20) issues.push(`知识库文件不足: ${count}/20`);
      } else if (check === 'memory_system') {
        checkResults[check] = fileExists('3-FRONTEND/dream-universal-gateway/src/lib/intent/intent-memory.ts');
        if (!checkResults[check]) issues.push('意图记忆未实现');
      } else if (check === 'four_roles') {
        const agentDoc = path.join('/Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/docs/02-ARCHITECTURE.md');
        checkResults[check] = fileExists(agentDoc);
        if (!checkResults[check]) issues.push('Dream-Agent架构文档缺失');
      } else {
        checkResults[check] = existingPaths.length > 0;
      }
    }

    const score = calculateScore(checkResults);
    const status = getStatusFromScore(score);

    results.push({
      module: module.name,
      chapter: module.chapter,
      status,
      score,
      expected: module.expectedStatus,
      actual: `${score}%`,
      issues,
      action: getActionFromScore(score),
    });
  }

  return results;
}

// ==================== 报告生成 ====================

function generateReport(checks: CheckResult[]): MaintenanceReport {
  const summary = {
    total: checks.length,
    healthy: checks.filter(c => c.status === '🟢').length,
    warning: checks.filter(c => c.status === '🟡').length,
    critical: checks.filter(c => c.status === '🔴').length,
  };

  const overallScore = Math.round(
    checks.reduce((sum, c) => sum + c.score, 0) / checks.length
  );

  const overallHealth = overallScore >= 90 ? 'A'
    : overallScore >= 75 ? 'B'
    : overallScore >= 60 ? 'C' : 'D';

  const nextActions: MaintenanceReport['nextActions'] = [];

  // 按优先级排序问题
  checks
    .filter(c => c.action !== '无需处理')
    .sort((a, b) => a.score - b.score)
    .forEach(c => {
      const priority = c.status === '🔴' ? 'high' : 'medium';
      nextActions.push({
        priority,
        issue: `${c.module} (${c.score}%)`,
        action: c.action === '需紧急修复' ? '触发开发任务' : '补充实现',
        trigger: c.score < 50 ? 'DZE开发链' : '下期迭代',
      });
    });

  const now = new Date();
  const startOfWeek = new Date(now);
  startOfWeek.setDate(now.getDate() - now.getDay() + 1);

  return {
    timestamp: now.toISOString(),
    period: `${startOfWeek.toISOString().split('T')[0]} ~ ${now.toISOString().split('T')[0]}`,
    overallHealth,
    overallScore,
    checks,
    summary,
    nextActions,
    trend: {
      lastWeek: '未知',
      thisWeek: `${overallScore}分`,
      direction: '→',
    },
  };
}

function formatMarkdownReport(report: MaintenanceReport): string {
  const lines: string[] = [];

  lines.push('# 🔧 系统维护报告');
  lines.push('');
  lines.push(`**维护周期**: ${report.period}`);
  lines.push(`**维护时间**: ${new Date().toLocaleString('zh-CN')}`);
  lines.push(`**维护人**: System`);
  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('## 一、整体健康度');
  lines.push('');
  lines.push(`| 指标 | 值 |`);
  lines.push(`|------|-----|`);
  lines.push(`| 综合评分 | **${report.overallScore}/100** |`);
  lines.push(`| 健康等级 | **${report.overallHealth}级** |`);
  lines.push(`| 正常模块 | ${report.summary.healthy}/${report.summary.total} |`);
  lines.push(`| 警告模块 | ${report.summary.warning}/${report.summary.total} |`);
  lines.push(`| 危急模块 | ${report.summary.critical}/${report.summary.total} |`);
  lines.push('');

  lines.push('## 二、各模块检查详情');
  lines.push('');

  for (const check of report.checks) {
    lines.push(`### ${check.status} ${check.module}`);
    lines.push(`- **章节**: ${check.chapter}`);
    lines.push(`- **期望状态**: ${check.expected}`);
    lines.push(`- **实际状态**: ${check.actual}`);
    lines.push(`- **建议操作**: ${check.action}`);
    if (check.issues.length > 0) {
      lines.push(`- **发现问题**: ${check.issues.join(', ')}`);
    }
    lines.push('');
  }

  lines.push('## 三、待处理问题');
  lines.push('');

  if (report.nextActions.length === 0) {
    lines.push('🎉 所有模块状态良好，无需紧急处理！');
  } else {
    lines.push('| 优先级 | 问题 | 建议操作 | 触发方式 |');
    lines.push('|--------|------|---------|---------|');
    for (const action of report.nextActions) {
      lines.push(`| ${action.priority === 'high' ? '🔴高' : '🟡中'} | ${action.issue} | ${action.action} | ${action.trigger} |`);
    }
  }
  lines.push('');

  lines.push('## 四、下周计划');
  lines.push('');
  for (let i = 0; i < Math.min(3, report.nextActions.length); i++) {
    const action = report.nextActions[i];
    lines.push(`${i + 1}. 【${action.priority === 'high' ? '高优' : '中优'}】${action.issue} - ${action.action}`);
  }
  if (report.nextActions.length === 0) {
    lines.push('1. 【日常】保持当前状态');
    lines.push('2. 【优化】完善细节');
  }
  lines.push('');

  lines.push('---');
  lines.push('*本报告由 System Maintenance SKILL 自动生成*');

  return lines.join('\n');
}

function saveReport(report: MaintenanceReport, markdown: string): void {
  // 确保目录存在
  if (!fs.existsSync(REPORTS_DIR)) {
    fs.mkdirSync(REPORTS_DIR, { recursive: true });
  }

  // 保存 JSON
  const jsonPath = path.join(
    REPORTS_DIR,
    `maintenance-report-${new Date().toISOString().split('T')[0]}.json`
  );
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2));
  console.log(`✅ JSON报告已保存: ${jsonPath}`);

  // 保存 Markdown
  const mdPath = path.join(
    REPORTS_DIR,
    `maintenance-report-${new Date().toISOString().split('T')[0]}.md`
  );
  fs.writeFileSync(mdPath, markdown);
  console.log(`✅ Markdown报告已保存: ${mdPath}`);

  // 更新最新报告链接
  const latestPath = path.join(REPORTS_DIR, 'LATEST.md');
  fs.writeFileSync(latestPath, markdown);
  console.log(`✅ 最新报告已更新: ${latestPath}`);
}

// ==================== 主流程 ====================

function main() {
  console.log('🔧 开始系统维护检查...\n');

  console.log('📋 执行架构健康检查...');
  const checks = runChecks();

  console.log('📊 生成维护报告...');
  const report = generateReport(checks);

  console.log('📝 格式化报告...');
  const markdown = formatMarkdownReport(report);

  console.log('💾 保存报告...');
  saveReport(report, markdown);

  console.log('\n📈 检查结果汇总:');
  console.log(`  - 总体评分: ${report.overallScore}/100 (${report.overallHealth}级)`);
  console.log(`  - 正常模块: ${report.summary.healthy}/${report.summary.total}`);
  console.log(`  - 警告模块: ${report.summary.warning}/${report.summary.total}`);
  console.log(`  - 危急模块: ${report.summary.critical}/${report.summary.total}`);

  if (report.nextActions.length > 0) {
    console.log('\n⚠️ 待处理问题:');
    report.nextActions.forEach((a, i) => {
      console.log(`  ${i + 1}. [${a.priority}] ${a.issue}`);
    });
  } else {
    console.log('\n🎉 所有模块状态良好！');
  }

  console.log('\n✅ 系统维护检查完成！');
}

main();
