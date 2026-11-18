"use client";

/**
 * 工作流思维导图（工作台右侧）。
 *
 * 与对话输出共用同一份看板快照：对话每推进一步，这里同步点亮。
 * 只展示内在工作流（意图 → SPEC → 派工 → 执行 → 验收 → 汇总），
 * 用方框 + 连接线表达，不照搬内部架构图。
 */

import Link from "next/link";
import {
  GATE_TITLE,
  TASK_STAGE_LABEL,
  TASK_STAGE_ORDER,
  type GateKind,
  type TaskBoardSnapshot,
  type TaskStage,
} from "@/types/task-board";

const STAGE_ORDER = TASK_STAGE_ORDER;

const STATUS_LABEL: Record<TaskBoardSnapshot["status"], string> = {
  pending: "待开始",
  running: "进行中",
  waiting: "待确认",
  done: "已完成",
  degraded: "有风险",
  failed: "失败",
  terminated: "已终止",
};

const STATUS_STYLE: Record<TaskBoardSnapshot["status"], string> = {
  pending: "border-slate-700 text-slate-400",
  running: "border-indigo-700/70 text-indigo-300",
  waiting: "border-amber-700/70 text-amber-300",
  done: "border-emerald-700/70 text-emerald-300",
  degraded: "border-amber-700/70 text-amber-300",
  failed: "border-red-700/70 text-red-300",
  terminated: "border-red-800/70 text-red-400",
};

const AGENT_STATE_LABEL: Record<string, string> = {
  pending: "待启动",
  running: "执行中",
  waiting: "等待",
  done: "完成",
  degraded: "降级",
  failed: "失败",
};

function stageDetail(snapshot: TaskBoardSnapshot, stage: TaskStage): string {
  switch (stage) {
    case "intent":
      return snapshot.intent?.decision || "等待识别";
    case "spec":
      return snapshot.spec
        ? `v${snapshot.spec.version} · ${
            snapshot.spec.status === "confirmed" ? "已确认" : "草稿"
          }`
        : "等待生成";
    case "dispatch":
      return snapshot.krs.length > 0
        ? `${snapshot.krs.length} 个验收项`
        : "等待派工";
    case "execute": {
      if (snapshot.agents.length === 0) return "暂无子代理";
      const running = snapshot.agents.filter(
        (agent) => agent.state === "running",
      ).length;
      return running > 0
        ? `${running} 个执行中 / 共 ${snapshot.agents.length}`
        : `${snapshot.agents.length} 个子代理已收口`;
    }
    case "accept": {
      if (snapshot.krs.length === 0) return "暂无验收记录";
      const passed = snapshot.krs.filter((kr) => kr.verdict === "pass").length;
      return `通过 ${passed} / ${snapshot.krs.length}`;
    }
    case "summary":
      return snapshot.summary?.conclusion
        ? snapshot.summary.conclusion.slice(0, 46)
        : "等待汇总";
  }
}

export function WorkflowMindmap({
  snapshot,
  taskId,
}: {
  snapshot: TaskBoardSnapshot | null;
  taskId: string | null;
}) {
  if (!snapshot || !taskId) {
    return (
      <div className="p-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          工作流
        </h2>
        <p className="mt-3 text-[11px] leading-relaxed text-slate-600">
          发出一条消息后，这里会按「意图 → SPEC → 派工 → 执行 → 验收 → 汇总」
          同步展开，和对话里的输出一起往前走。
        </p>
      </div>
    );
  }

  const currentIndex = Math.max(0, STAGE_ORDER.indexOf(snapshot.stage));
  const waitingGates = snapshot.gates.filter(
    (gate) => gate.required && gate.status === "waiting",
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-800 px-3 py-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          工作流
        </h2>
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] ${
            STATUS_STYLE[snapshot.status]
          }`}
        >
          {STATUS_LABEL[snapshot.status]}
        </span>
        {waitingGates.length > 0 && (
          <span className="rounded-full border border-amber-700/70 bg-amber-950/30 px-2 py-0.5 text-[10px] text-amber-300">
            待审批 {waitingGates.length}
          </span>
        )}
        <Link
          href={`/dashboard/task/${encodeURIComponent(taskId)}`}
          className="ml-auto text-[10px] text-indigo-300 hover:text-indigo-200"
        >
          完整看板 ↗
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <ol className="relative space-y-1.5">
          <span
            className="absolute top-2 bottom-2 left-[7px] w-px bg-slate-800"
            aria-hidden
          />
          {STAGE_ORDER.map((stage, index) => {
            const active = index === currentIndex;
            const done = index < currentIndex;
            return (
              <li key={stage} className="relative pl-6">
                <span
                  className={`absolute top-3 left-0 h-3.5 w-3.5 rounded-full border ${
                    active
                      ? "border-indigo-400 bg-indigo-500/40 ring-2 ring-indigo-500/30"
                      : done
                        ? "border-emerald-600 bg-emerald-500/40"
                        : "border-slate-700 bg-slate-900"
                  }`}
                  aria-hidden
                />
                <div
                  className={`rounded-lg border px-2.5 py-2 ${
                    active
                      ? "border-indigo-700/70 bg-indigo-950/25"
                      : done
                        ? "border-slate-800 bg-slate-900/50"
                        : "border-slate-800/70 bg-slate-950/40"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`text-[11px] font-medium ${
                        active
                          ? "text-indigo-200"
                          : done
                            ? "text-slate-300"
                            : "text-slate-500"
                      }`}
                    >
                      {TASK_STAGE_LABEL[stage]}
                    </span>
                    {active && (
                      <span className="h-1 w-1 animate-pulse rounded-full bg-indigo-400" />
                    )}
                  </div>
                  <p
                    className={`mt-0.5 truncate text-[10px] ${
                      active ? "text-indigo-300/80" : "text-slate-500"
                    }`}
                    title={stageDetail(snapshot, stage)}
                  >
                    {stageDetail(snapshot, stage)}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>

        {snapshot.steps && snapshot.steps.length > 0 && (
          <div className="mt-4">
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              执行步骤
            </h3>
            <div className="mt-1.5 space-y-1">
              {snapshot.steps.map((step) => (
                <div
                  key={step.step_id}
                  className={`rounded-lg border px-2 py-1.5 ${
                    step.verdict === "fail"
                      ? "border-red-800/60 bg-red-950/20"
                      : step.verdict === "pending"
                        ? "border-amber-800/50 bg-amber-950/15"
                        : "border-emerald-800/50 bg-emerald-950/15"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] text-slate-500">
                      {step.index + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[10px] text-slate-200">
                      {step.title}
                    </span>
                    <span
                      className={`shrink-0 text-[9px] ${
                        step.verdict === "fail"
                          ? "text-red-300"
                          : step.verdict === "pending"
                            ? "text-amber-300"
                            : "text-emerald-300"
                      }`}
                    >
                      {step.verdict === "fail"
                        ? "驳回"
                        : step.verdict === "pending"
                          ? "待评审"
                          : "通过"}
                    </span>
                  </div>
                  {step.comment && (
                    <p
                      className="mt-0.5 truncate text-[9px] text-slate-500"
                      title={step.comment}
                    >
                      {step.reviewer ? `${step.reviewer}：` : ""}
                      {step.comment}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {snapshot.agents.length > 0 && (
          <div className="mt-4">
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              子代理
            </h3>
            <div className="mt-1.5 grid grid-cols-2 gap-1.5">
              {snapshot.agents.map((agent) => (
                <div
                  key={agent.role}
                  className={`rounded-lg border px-2 py-1.5 ${
                    agent.state === "done"
                      ? "border-emerald-900/60 bg-emerald-950/20"
                      : agent.state === "running"
                        ? "border-indigo-800/60 bg-indigo-950/20"
                        : agent.state === "failed"
                          ? "border-red-800/60 bg-red-950/20"
                          : "border-slate-800 bg-slate-900/40"
                  }`}
                >
                  <p className="truncate text-[10px] text-slate-300">
                    {agent.label || agent.role}
                  </p>
                  <p className="mt-0.5 text-[9px] text-slate-500">
                    {AGENT_STATE_LABEL[agent.state] ?? agent.state}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {waitingGates.length > 0 && (
          <div className="mt-4">
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              待确认门禁
            </h3>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {waitingGates.map((gate) => (
                <span
                  key={gate.gate_id}
                  className="rounded border border-amber-700/60 bg-amber-950/20 px-1.5 py-0.5 text-[10px] text-amber-300"
                >
                  {GATE_TITLE[gate.kind as GateKind] ?? gate.title}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
