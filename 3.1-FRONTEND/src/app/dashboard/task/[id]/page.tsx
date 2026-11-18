"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { TaskBoard } from "@/components/features/task-board/TaskBoard";
import { useTaskBoard } from "@/lib/task-board/use-task-board";

export default function TaskBoardPage() {
  const params = useParams<{ id: string }>();
  const taskId = typeof params?.id === "string" ? params.id : "";
  const { snapshot, hydrated, mode, decideGate, busyGateId } =
    useTaskBoard(taskId);

  return (
    <div className="min-h-full">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-2 px-6 pt-5 text-xs text-slate-500">
        <Link href="/dashboard/agent" className="hover:text-slate-300">
          ← 返回工作台
        </Link>
        <span className="text-slate-700">/</span>
        <span>任务看板</span>
      </div>

      {hydrated ? (
        <TaskBoard
          snapshot={snapshot}
          onDecideGate={decideGate}
          busyGateId={busyGateId}
          mode={mode}
        />
      ) : (
        <div className="mx-auto w-full max-w-6xl animate-pulse space-y-3 p-6">
          <div className="h-24 rounded-xl bg-slate-800/60" />
          <div className="h-40 rounded-xl bg-slate-800/60" />
          <div className="h-32 rounded-xl bg-slate-800/60" />
        </div>
      )}
    </div>
  );
}
