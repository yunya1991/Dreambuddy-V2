// ============================================================
// /api/notebook/sync — 文件系统同步
// POST — 将状态中的任务同步到 0-NOTEBOOK/{0-TODO,1-ACTIVE,2-DONE,3-ARCHIVE}
// GET  — 从 0-NOTEBOOK 目录重新读取状态
// 版本: v1.0 | 日期: 2026-06-15
// ============================================================

import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import {
  NOTEBOOK_DIR,
  TODO_DIR,
  ACTIVE_DIR,
  DONE_DIR,
  ARCHIVE_DIR,
  STATE_FILE,
  loadState,
  saveState,
  ensureDirectories,
} from "@/lib/notebook/step-controller";
import type { NotebookTask, TaskPhase } from "@/lib/notebook/types";

function taskFilename(task: NotebookTask): string {
  const base = task.title.slice(0, 40).replace(/[^a-zA-Z0-9\u4e00-\u9fa5-_]/g, "_");
  return `${task.startedAt.slice(0, 10)}_${base}_${task.id.slice(-6)}.md`;
}

function taskToMarkdown(task: NotebookTask): string {
  const lines: string[] = [];
  lines.push(`# ${task.title}`);
  lines.push("");
  lines.push(`- 任务 ID: \`${task.id}\``);
  lines.push(`- 会话: \`${task.sessionId}\``);
  lines.push(`- 意图: \`${task.intent}\``);
  lines.push(`- 状态: **${task.phase}**`);
  lines.push(`- 启动时间: ${task.startedAt}`);
  lines.push(`- 最后活跃: ${task.lastActiveAt}`);
  if (task.entities && Object.keys(task.entities).length > 0) {
    lines.push(`- 关联实体: ${JSON.stringify(task.entities)}`);
  }
  lines.push("");
  lines.push("## 原始请求");
  lines.push("");
  lines.push(`> ${task.userInput}`);
  lines.push("");
  lines.push("## 7步记录");
  lines.push("");
  for (const step of task.steps) {
    const statusIcon = step.status === "done" ? "✅" : step.status === "active" ? "▶️" : step.status === "skipped" ? "⏭️" : "⬜";
    lines.push(`### ${statusIcon} Step ${step.number} ${step.name}`);
    if (step.startedAt) lines.push(`- 启动: ${step.startedAt}`);
    if (step.completedAt) lines.push(`- 完成: ${step.completedAt}`);
    if (step.skippedReason) lines.push(`- 原因: ${step.skippedReason}`);
    if (step.output) {
      lines.push("");
      lines.push(step.output);
    }
    if (step.artifacts && step.artifacts.length > 0) {
      lines.push("");
      lines.push("**产物:**");
      for (const a of step.artifacts) {
        lines.push(`- \`${a}\``);
      }
    }
    lines.push("");
  }

  if (task.dzeChain) {
    lines.push("## D-Z-E 思维链");
    lines.push("");
    lines.push(`- 范围: ${task.dzeChain.scope}`);
    lines.push(`- 当前阶段: **${task.dzeChain.currentPhase || "未开始"}**`);
    lines.push("");
    for (const p of task.dzeChain.phases) {
      const icon = p.status === "done" ? "✅" : p.status === "active" ? "▶️" : p.status === "skipped" ? "⏭️" : "⬜";
      lines.push(`### ${icon} ${p.name}`);
      lines.push(`- 方法论: ${p.methodology}`);
      if (p.output) lines.push(`- 产出: ${p.output}`);
      lines.push("");
    }
  }

  return lines.join("\n");
}

export async function POST(_req: NextRequest) {
  try {
    ensureDirectories();
    const state = loadState();

    let written = 0;
    for (const task of state.tasks) {
      let targetDir: string;
      if (task.phase === "active") targetDir = ACTIVE_DIR;
      else if (task.phase === "todo") targetDir = TODO_DIR;
      else if (task.phase === "done") targetDir = DONE_DIR;
      else targetDir = ARCHIVE_DIR;

      const mdFile = path.join(targetDir, taskFilename(task));
      fs.writeFileSync(mdFile, taskToMarkdown(task), "utf-8");
      written++;
    }

    return NextResponse.json({
      success: true,
      message: `已同步 ${written} 个任务到 ${NOTEBOOK_DIR}`,
      data: {
        notebookDir: NOTEBOOK_DIR,
        tasks: state.tasks.length,
        written,
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
  ensureDirectories();
  const state = loadState();
  return NextResponse.json({
    success: true,
    data: {
      notebookDir: NOTEBOOK_DIR,
      stateFile: STATE_FILE,
      directories: {
        todo: TODO_DIR,
        active: ACTIVE_DIR,
        done: DONE_DIR,
        archive: ARCHIVE_DIR,
      },
      counts: {
        todo: fs.existsSync(TODO_DIR) ? fs.readdirSync(TODO_DIR).length : 0,
        active: fs.existsSync(ACTIVE_DIR) ? fs.readdirSync(ACTIVE_DIR).length : 0,
        done: fs.existsSync(DONE_DIR) ? fs.readdirSync(DONE_DIR).length : 0,
        archive: fs.existsSync(ARCHIVE_DIR) ? fs.readdirSync(ARCHIVE_DIR).length : 0,
      },
      state,
    },
  });
}
