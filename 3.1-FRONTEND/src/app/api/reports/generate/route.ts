/**
 * 生成研报 API
 * POST /api/reports/generate  body: { task_id: string }
 *
 * 读取 task result 文件，组装 markdown 报告，写入 ARTIFACTS_DIR 并更新 index.json
 */
import { NextRequest, NextResponse } from 'next/server';
import { readFile, writeFile, mkdir } from 'fs/promises';
import { join } from 'path';
import { existsSync } from 'fs';
import { homedir } from 'os';

const ARTIFACTS_DIR = join(homedir(), '.workbuddy', 'artifacts', 'trading');
const INDEX_FILE = join(ARTIFACTS_DIR, 'index.json');

// === 复用 task/result/[id]/route.ts 的目录解析逻辑 ===
function resolveResultsDir(): string {
  const cwd = process.cwd();
  const candidates = [
    join(cwd, '..', 'dreambuddy', 'artifacts', 'results'),
    join(cwd, 'dreambuddy', 'artifacts', 'results'),
    join(cwd, 'artifacts', 'results'),
    join(cwd, '..', 'artifacts', 'results'),
  ];
  for (const dir of candidates) {
    if (existsSync(dir)) return dir;
  }
  // 兜底：再向上一级查找
  const upCandidates = [
    join(cwd, '..', '..', 'dreambuddy', 'artifacts', 'results'),
    join(cwd, '..', '..', 'artifacts', 'results'),
  ];
  for (const dir of upCandidates) {
    if (existsSync(dir)) return dir;
  }
  return join(cwd, '..', 'dreambuddy', 'artifacts', 'results');
}

function resolveTasksDir(): string {
  const resultsDir = resolveResultsDir();
  const tasksDir = join(resultsDir, '..', 'tasks');
  if (existsSync(tasksDir)) return tasksDir;
  return join(resultsDir, '..', '..', 'tasks');
}

function sanitizeId(id: string): string {
  return id.replace(/[^a-zA-Z0-9_\-]/g, '');
}

interface ReportStep {
  stepId: string;
  stepName: string;
  stage: string;
  decision: string;
  confidence: number;
  answer: string;
  skillResults: Array<{
    skillId: string;
    skillName: string;
    status: string;
    confidence: number;
    data: unknown;
  }>;
}

interface ReportData {
  taskId: string;
  taskType: string;
  intent: string;
  input: string;
  summary: string;
  overallConfidence: number;
  totalTokens: number;
  durationMs: number;
  steps: ReportStep[];
  createdAt: string;
  deepeningOptions: Array<{ key: string; label: string; description: string }>;
}

// === 从 task result 组装 markdown ===
function buildMarkdown(report: ReportData): string {
  const now = new Date().toLocaleString('zh-CN');
  const lines: string[] = [];

  lines.push(`# ${report.intent || '深度分析'} 任务报告`);
  lines.push('');
  lines.push(`> 任务 ID: ${report.taskId}`);
  lines.push(`> 生成时间: ${now}`);
  lines.push('');

  lines.push('## 任务概览');
  lines.push('');
  lines.push(`- **意图类型**: ${report.intent}`);
  lines.push(`- **任务类型**: ${report.taskType}`);
  lines.push(`- **创建时间**: ${new Date(report.createdAt).toLocaleString('zh-CN')}`);
  lines.push(`- **执行耗时**: ${(report.durationMs / 1000).toFixed(1)}s`);
  lines.push(`- **综合置信度**: ${report.overallConfidence.toFixed(0)}%`);
  lines.push(`- **Token 用量**: ${report.totalTokens}`);
  lines.push(`- **执行步骤数**: ${report.steps.length}`);
  lines.push('');

  if (report.input) {
    lines.push('## 原始输入');
    lines.push('');
    lines.push('> ' + report.input.split('\n').join('\n> '));
    lines.push('');
  }

  if (report.summary) {
    lines.push('## 核心摘要');
    lines.push('');
    lines.push(report.summary);
    lines.push('');
  }

  if (report.steps.length > 0) {
    lines.push('## 执行步骤详情');
    lines.push('');
    report.steps.forEach((step, i) => {
      const conf = step.confidence > 0 ? ` (${step.confidence.toFixed(0)}%)` : '';
      lines.push(`### ${i + 1}. ${step.stepName} [${step.stage}]${conf}`);
      lines.push('');
      if (step.decision) {
        lines.push(`- **决策**: ${step.decision}`);
      }
      if (step.answer) {
        lines.push('');
        lines.push('**步骤输出**:');
        lines.push('');
        lines.push('```');
        lines.push(step.answer);
        lines.push('```');
        lines.push('');
      }
      if (step.skillResults.length > 0) {
        lines.push('**Skill 调用**:');
        lines.push('');
        for (const sk of step.skillResults) {
          const skConf = sk.confidence > 0 ? ` (${sk.confidence.toFixed(0)}%)` : '';
          lines.push(`- \`${sk.skillName}\` — ${sk.status}${skConf}`);
        }
        lines.push('');
      }
    });
  }

  if (report.deepeningOptions.length > 0) {
    lines.push('## 深入选项');
    lines.push('');
    report.deepeningOptions.forEach((opt, i) => {
      lines.push(`${i + 1}. **${opt.label}** — ${opt.description || ''}`);
    });
    lines.push('');
  }

  lines.push('---');
  lines.push('*本报告由 DreamBuddy 任务执行系统自动生成，仅供参考，不构成投资建议*');
  return lines.join('\n');
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => null);
    const taskIdRaw = body?.task_id;
    if (typeof taskIdRaw !== 'string' || !taskIdRaw.trim()) {
      return NextResponse.json(
        { success: false, error: '缺少 task_id 参数' },
        { status: 400 }
      );
    }
    const taskId = sanitizeId(taskIdRaw);
    if (!taskId) {
      return NextResponse.json(
        { success: false, error: '无效的 task_id' },
        { status: 400 }
      );
    }

    const RESULTS_DIR = resolveResultsDir();
    const resultFile = join(RESULTS_DIR, `result_${taskId}.json`);
    if (!existsSync(resultFile)) {
      return NextResponse.json(
        { success: false, error: `任务结果不存在: ${taskId}（路径: ${resultFile}）` },
        { status: 404 }
      );
    }

    const rawData = await readFile(resultFile, 'utf-8');
    const raw = JSON.parse(rawData);

    // 读取 task 文件以获取 message（可选）
    let taskData: any = null;
    try {
      const TASKS_DIR = resolveTasksDir();
      const taskFile = join(TASKS_DIR, `${taskId}.json`);
      taskData = JSON.parse(await readFile(taskFile, 'utf-8'));
    } catch {
      // task file not found is ok
    }

    // 复用 task/result/[id]/route.ts 的转换逻辑
    const plannerSteps = raw.execution_summary?.planner_result?.steps || [];
    const steps: ReportStep[] = plannerSteps.map((step: any) => {
      const skillsCalled = step.skillsCalled || [];
      return {
        stepId: step.stepId,
        stepName: step.label || step.stepId,
        stage: step.stage || 'analysis',
        decision: step.decision || 'proceed',
        confidence: step.confidence || 0,
        answer: step.answer || '',
        skillResults: skillsCalled.map((skill: any) => ({
          skillId: skill.skillId,
          skillName: skill.skillName,
          status: skill.result?.success ? 'completed' : 'failed',
          confidence: skill.confidence || skill.result?.confidence || 0,
          data: skill.result?.outputs || null,
        })),
      };
    });

    const overallConf =
      raw.execution_summary?.quality?.average_confidence ||
      raw.execution_summary?.confidence ||
      0;
    const totalTokens = steps.reduce((sum: number, s: ReportStep) => {
      return (
        sum +
        s.skillResults.reduce((s2: number, sk) => {
          const data = sk.data as any;
          return s2 + (data?.tokensUsed || 0);
        }, 0)
      );
    }, 0);

    let summary = raw.content || '';
    const detailsMatch = summary.match(/^([\s\S]*?)\n\n---\n\n<details>/);
    if (detailsMatch) {
      summary = detailsMatch[1].trim();
    }
    const deepenOptions: Array<{ key: string; label: string; description: string }> = [];
    const deepenMatch = raw.content?.match(
      /<details>\n<summary>📋 想要更深入？[\s\S]*?<\/details>/
    );
    if (deepenMatch) {
      const optionMatches = [...raw.content.matchAll(/-\s*\[(\d+)\]\s*(.+?)(?:\n|$)/g)];
      optionMatches.forEach((m, idx) => {
        deepenOptions.push({
          key: `opt_${idx}`,
          label: m[2].trim(),
          description: '',
        });
      });
    }

    const report: ReportData = {
      taskId: raw.task_id || taskId,
      taskType: raw.intent?.type || taskData?.intent?.type || 'analysis',
      intent: raw.intent?.type || taskData?.intent?.type || 'market_query',
      input: taskData?.message || raw.message || raw.input || raw.task_id || '',
      summary,
      overallConfidence: overallConf * 100,
      totalTokens,
      durationMs: raw.execution_time_ms || 0,
      steps,
      createdAt: raw.created_at || taskData?.created_at || new Date().toISOString(),
      deepeningOptions:
        deepenOptions.length > 0
          ? deepenOptions
          : [
              { key: 'strategy', label: '策略建议', description: '获取具体的交易策略和操作建议' },
              { key: 'scenario', label: '情景推演', description: '模拟不同市场情景下的走势推演' },
              { key: 'onchain', label: '链上数据深入', description: '深入分析链上数据和资金流向' },
            ],
    };

    // 生成 markdown
    const markdown = buildMarkdown(report);

    // 确保 ARTIFACTS_DIR 存在
    await mkdir(ARTIFACTS_DIR, { recursive: true });

    // 文件名: A1_task_${taskId}_${YYYYMMDDHHmmss}.md
    const pad = (n: number) => String(n).padStart(2, '0');
    const now = new Date();
    const ts =
      `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
      `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const filename = `A1_task_${taskId}_${ts}.md`;
    const filePath = join(ARTIFACTS_DIR, filename);
    await writeFile(filePath, markdown, 'utf-8');

    // 更新 index.json：追加 entry
    const dateISO = now.toISOString();
    const newMeta = {
      file: filename,
      title: `${report.intent || '任务报告'} - ${taskId}`,
      date: dateISO,
      type: 'task_report',
      chain_phase: 'A1',
      tags: 'task_report,' + (report.intent || ''),
      department: 'frontend',
      status: 'completed',
      confidence: report.overallConfidence / 100,
    };

    try {
      if (existsSync(INDEX_FILE)) {
        const idxRaw = await readFile(INDEX_FILE, 'utf-8');
        const idxParsed = JSON.parse(idxRaw);
        let artifacts: any[];
        if (Array.isArray(idxParsed)) {
          artifacts = idxParsed;
        } else if (Array.isArray(idxParsed.artifacts)) {
          artifacts = idxParsed.artifacts;
        } else {
          artifacts = [];
        }
        // 去重：相同 file 则替换
        const filtered = artifacts.filter((a) => a?.file !== filename);
        filtered.unshift(newMeta);
        const newIdx = {
          generated_at: dateISO,
          artifacts: filtered,
        };
        await writeFile(INDEX_FILE, JSON.stringify(newIdx, null, 2), 'utf-8');
      } else {
        // 不存在则创建
        const newIdx = {
          generated_at: dateISO,
          artifacts: [newMeta],
        };
        await writeFile(INDEX_FILE, JSON.stringify(newIdx, null, 2), 'utf-8');
      }
    } catch (err) {
      // index 更新失败不阻断主流程
      console.error('更新 index.json 失败（不阻断）:', err);
    }

    return NextResponse.json({
      success: true,
      file: filename,
      path: filePath,
      title: newMeta.title,
      date: dateISO,
      markdown_size: markdown.length,
    });
  } catch (error: any) {
    console.error('生成报告失败:', error);
    return NextResponse.json(
      { success: false, error: error.message || '生成报告失败' },
      { status: 500 }
    );
  }
}
