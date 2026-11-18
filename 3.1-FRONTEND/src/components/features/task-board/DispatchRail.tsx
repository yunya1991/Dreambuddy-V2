import type { TaskStage, TaskStatus } from "@/types/task-board";
import { TASK_STAGE_LABEL, TASK_STAGE_ORDER } from "@/types/task-board";

function activeClass(status: TaskStatus): string {
  switch (status) {
    case "failed":
      return "border-red-700/60 bg-red-950/40 text-red-300";
    case "degraded":
      return "border-amber-700/60 bg-amber-950/40 text-amber-300";
    case "waiting":
      return "border-amber-700/60 bg-amber-950/40 text-amber-300";
    case "done":
      return "border-emerald-700/60 bg-emerald-950/40 text-emerald-300";
    default:
      return "border-indigo-700/60 bg-indigo-950/40 text-indigo-300";
  }
}

export function DispatchRail({
  stage,
  status,
}: {
  stage: TaskStage;
  status: TaskStatus;
}) {
  const currentIndex = TASK_STAGE_ORDER.indexOf(stage);
  const allDone = status === "done";

  return (
    <section
      data-testid="task-board-dispatch-rail"
      className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3"
      aria-label="任务进度"
    >
      <ol className="flex items-center gap-1 overflow-x-auto">
        {TASK_STAGE_ORDER.map((item, index) => {
          const done = allDone || index < currentIndex;
          const active = !allDone && index === currentIndex;
          const cls = done
            ? "border-emerald-700/60 bg-emerald-950/40 text-emerald-300"
            : active
              ? activeClass(status)
              : "border-slate-700 text-slate-600";
          return (
            <li key={item} className="flex min-w-0 flex-1 items-center gap-1">
              <span
                data-testid={`stage-${item}`}
                data-state={done ? "done" : active ? "active" : "todo"}
                className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 text-[11px] ${cls}`}
              >
                <span className="font-mono text-[10px] opacity-70">{index + 1}</span>
                {TASK_STAGE_LABEL[item]}
              </span>
              {index < TASK_STAGE_ORDER.length - 1 && (
                <span
                  className={`h-px min-w-2 flex-1 ${
                    done ? "bg-emerald-700/60" : "bg-slate-800"
                  }`}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
