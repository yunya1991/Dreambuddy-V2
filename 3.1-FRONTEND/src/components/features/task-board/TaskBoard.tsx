import type { TaskBoardSnapshot } from "@/types/task-board";
import type { GateDecisionInput } from "@/lib/task-board/use-task-board";
import { AcceptanceFeed } from "./AcceptanceFeed";
import { AgentGrid } from "./AgentGrid";
import { DispatchRail } from "./DispatchRail";
import { GateBar } from "./GateBar";
import { IntentGate } from "./IntentGate";
import { OkrBoard } from "./OkrBoard";
import { SpecPanel } from "./SpecPanel";
import { SummaryPanel } from "./SummaryPanel";
import { TaskBoardHeader } from "./TaskBoardHeader";

/**
 * 对外任务看板：只回答「做什么 / 到哪步 / 谁在做 / 合不合格」，
 * 不出现 SACG、DSH、Mandate 等内部术语。
 */
export function TaskBoard({
  snapshot,
  onDecideGate,
  busyGateId,
  mode = "human",
}: {
  snapshot: TaskBoardSnapshot;
  onDecideGate?: (
    decision: GateDecisionInput,
  ) => Promise<{ ok: boolean; error?: string }>;
  busyGateId?: string | null;
  mode?: "autonomy" | "human";
}) {
  const passed = snapshot.krs.filter((kr) => kr.verdict === "pass").length;
  const title = snapshot.objective?.title || "任务目标待生成";

  return (
    <div className="mx-auto w-full max-w-6xl space-y-3 p-6">
      <TaskBoardHeader
        taskId={snapshot.task_id}
        traceId={
          snapshot.trace_id && snapshot.trace_id !== snapshot.task_id
            ? snapshot.trace_id
            : undefined
        }
        title={title}
        status={snapshot.status}
        stage={snapshot.stage}
        doneCount={passed}
        totalCount={snapshot.krs.length}
        updatedAt={snapshot.updated_at || undefined}
      />

      {snapshot.gates.length > 0 && onDecideGate && (
        <GateBar
          taskId={snapshot.task_id}
          gates={snapshot.gates}
          busyGateId={busyGateId}
          mode={mode}
          onDecide={onDecideGate}
        />
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <IntentGate intent={snapshot.intent} />
        <SpecPanel spec={snapshot.spec} />
      </div>

      <OkrBoard objective={snapshot.objective} krs={snapshot.krs} />

      <DispatchRail stage={snapshot.stage} status={snapshot.status} />

      <AgentGrid agents={snapshot.agents} />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <AcceptanceFeed records={snapshot.acceptance} />
        <SummaryPanel summary={snapshot.summary} />
      </div>
    </div>
  );
}
