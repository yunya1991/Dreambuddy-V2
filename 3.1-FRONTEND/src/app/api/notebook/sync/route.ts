// ============================================================
// /api/notebook/sync — 状态同步 (3.1 内存版)
// POST — 返回当前内存状态 (无文件系统写入)
// GET  — 查询状态和目录信息
// ============================================================

import { NextRequest, NextResponse } from 'next/server';
import { loadState, saveState, seedMockData } from '@/lib/notebook/step-controller';
import type { NotebookTask, TaskPhase } from '@/lib/notebook/types';

function taskToMarkdown(task: NotebookTask): string {
  const lines: string[] = [];
  lines.push(`# ${task.title}`);
  lines.push('');
  lines.push(`- 任务 ID: \`${task.id}\``);
  lines.push(`- 会话: \`${task.sessionId}\``);
  lines.push(`- 意图: \`${task.intent}\``);
  lines.push(`- 状态: **${task.phase}**`);
  lines.push(`- 启动时间: ${task.startedAt}`);
  lines.push(`- 最后活跃: ${task.lastActiveAt}`);
  if (task.entities && Object.keys(task.entities).length > 0) {
    lines.push(`- 关联实体: ${JSON.stringify(task.entities)}`);
  }
  lines.push('');
  lines.push('## 原始请求');
  lines.push('');
  lines.push(`> ${task.userInput}`);
  lines.push('');
  lines.push('## 7步记录');
  lines.push('');
  for (const step of task.steps) {
    const statusIcon = step.status === 'done' ? '✅' : step.status === 'active' ? '▶️' : step.status === 'skipped' ? '⏭️' : '⬜';
    lines.push(`### ${statusIcon} Step ${step.number} ${step.name}`);
    if (step.startedAt) lines.push(`- 启动: ${step.startedAt}`);
    if (step.completedAt) lines.push(`- 完成: ${step.completedAt}`);
    if (step.skippedReason) lines.push(`- 原因: ${step.skippedReason}`);
    if (step.output) {
      lines.push('');
      lines.push(step.output);
    }
    if (step.artifacts && step.artifacts.length > 0) {
      lines.push('');
      lines.push('**产物:**');
      for (const a of step.artifacts) {
        lines.push(`- \`${a}\``);
      }
    }
    lines.push('');
  }

  if (task.dzeChain) {
    lines.push('## D-Z-E 思维链');
    lines.push('');
    lines.push(`- 范围: ${task.dzeChain.scope}`);
    lines.push(`- 当前阶段: **${task.dzeChain.currentPhase || '未开始'}**`);
    lines.push('');
    for (const p of task.dzeChain.phases) {
      const icon = p.status === 'done' ? '✅' : p.status === 'active' ? '▶️' : p.status === 'skipped' ? '⏭️' : '⬜';
      lines.push(`### ${icon} ${p.name}`);
      lines.push(`- 方法论: ${p.methodology}`);
      if (p.output) lines.push(`- 产出: ${p.output}`);
      lines.push('');
    }
  }

  return lines.join('\n');
}

export async function POST(_req: NextRequest) {
  try {
    seedMockData();
    const state = loadState();

    // 生成 Markdown 摘要 (内存版: 不写入文件, 只返回内容)
    const markdownSummaries = state.tasks.map((task) => ({
      taskId: task.id,
      title: task.title,
      phase: task.phase,
      markdown: taskToMarkdown(task),
    }));

    return NextResponse.json({
      success: true,
      message: `已生成 ${markdownSummaries.length} 个任务的 Markdown 摘要`,
      data: {
        tasks: state.tasks.length,
        summaries: markdownSummaries.length,
      },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}

export async function GET(_req: NextRequest) {
  seedMockData();
  const state = loadState();
  return NextResponse.json({
    success: true,
    data: {
      storage: 'in-memory',
      counts: {
        todo: state.tasks.filter((t) => t.phase === 'todo').length,
        active: state.tasks.filter((t) => t.phase === 'active').length,
        done: state.tasks.filter((t) => t.phase === 'done').length,
        archive: state.tasks.filter((t) => t.phase === 'archive').length,
      },
      state,
    },
  });
}
