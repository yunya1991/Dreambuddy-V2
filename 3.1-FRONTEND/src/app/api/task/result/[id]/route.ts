import { NextRequest, NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import { join } from 'path';
import { existsSync } from 'fs';

function resolveResultsDir(): string {
  const cwd = process.cwd();
  const candidates = [
    join(cwd, '..', 'dreambuddy', 'artifacts', 'results'),
    join(cwd, 'dreambuddy', 'artifacts', 'results'),
    join(cwd, 'artifacts', 'results'),
  ];
  for (const dir of candidates) {
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

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const taskId = sanitizeId(id);
    if (!taskId) {
      return NextResponse.json(
        { success: false, error: '无效的任务ID' },
        { status: 400 }
      );
    }

    const RESULTS_DIR = resolveResultsDir();
    const resultFile = join(RESULTS_DIR, `result_${taskId}.json`);

    let rawData: string;
    try {
      rawData = await readFile(resultFile, 'utf-8');
    } catch {
      return NextResponse.json(
        { success: false, error: '报告不存在' },
        { status: 404 }
      );
    }

    const raw = JSON.parse(rawData);

    let taskData: any = null;
    try {
      const TASKS_DIR = resolveTasksDir();
      const taskFile = join(TASKS_DIR, `${taskId}.json`);
      const taskContent = await readFile(taskFile, 'utf-8');
      taskData = JSON.parse(taskContent);
    } catch {
      // task file not found is ok
    }

    const plannerSteps = raw.execution_summary?.planner_result?.steps || [];
    const steps = plannerSteps.map((step: any) => {
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

    const overallConf = raw.execution_summary?.quality?.average_confidence || raw.execution_summary?.confidence || 0;
    const totalTokens = steps.reduce((sum: number, s: any) => {
      return sum + s.skillResults.reduce((s2: number, sk: any) => s2 + (sk.data?.tokensUsed || 0), 0);
    }, 0);

    let summary = raw.content || '';
    const detailsMatch = summary.match(/^([\s\S]*?)\n\n---\n\n<details>/);
    if (detailsMatch) {
      summary = detailsMatch[1].trim();
    }
    const deepenMatch = raw.content?.match(/<details>\n<summary>📋 想要更深入？[\s\S]*?<\/details>/);
    const deepenOptions: Array<{ key: string; label: string; description: string }> = [];
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

    const report = {
      taskId: raw.task_id || id,
      taskType: raw.intent?.type || taskData?.intent?.type || 'analysis',
      intent: raw.intent?.type || taskData?.intent?.type || 'market_query',
      input: taskData?.message || raw.message || raw.input || raw.task_id || '',
      summary,
      overallConfidence: overallConf * 100,
      totalTokens,
      durationMs: raw.execution_time_ms || 0,
      steps,
      createdAt: raw.created_at || taskData?.created_at || new Date().toISOString(),
      deepeningOptions: deepenOptions.length > 0 ? deepenOptions : [
        { key: 'strategy', label: '策略建议', description: '获取具体的交易策略和操作建议' },
        { key: 'scenario', label: '情景推演', description: '模拟不同市场情景下的走势推演' },
        { key: 'onchain', label: '链上数据深入', description: '深入分析链上数据和资金流向' },
      ],
    };

    return NextResponse.json({
      success: true,
      data: report,
    });
  } catch (error: any) {
    console.error('加载任务结果失败:', error);
    return NextResponse.json(
      { success: false, error: error.message || '加载失败' },
      { status: 500 }
    );
  }
}
