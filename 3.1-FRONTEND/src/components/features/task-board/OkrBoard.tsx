import type { OkrNode, TaskObjective } from "@/types/task-board";
import {
  EmptyHint,
  ProgressBar,
  SectionCard,
  VERIFY_LABEL,
  VerdictBadge,
} from "./primitives";

const MODE_LABEL: Record<TaskObjective["mode"], string> = {
  judge: "判定",
  supervise: "督导",
};

export function OkrBoard({
  objective,
  krs,
}: {
  objective?: TaskObjective;
  krs: OkrNode[];
}) {
  const passed = krs.filter((kr) => kr.verdict === "pass").length;

  return (
    <SectionCard
      title="OKR 验收"
      testId="task-board-okr"
      meta={
        krs.length > 0 ? (
          <span className="text-[10px] text-slate-500">
            通过 {passed}/{krs.length}
          </span>
        ) : undefined
      }
    >
      {objective ? (
        <div className="rounded-lg bg-slate-950/40 px-3 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-slate-100">{objective.title}</p>
            <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-400">
              {MODE_LABEL[objective.mode] ?? objective.mode}
            </span>
            <span className="ml-auto font-mono text-xs text-slate-400">
              {Math.round(objective.progress * 100)}%
            </span>
          </div>
          <div className="mt-2">
            <ProgressBar value={objective.progress} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            <span>
              负责人：<span className="text-slate-300">{objective.owner || "—"}</span>
            </span>
            <span>
              截止：
              <span className="text-slate-300">{objective.deadline || "—"}</span>
            </span>
            <span>
              置信门槛：
              <span className="text-slate-300">
                {Math.round(objective.confidence_threshold * 100)}%
              </span>
            </span>
          </div>
        </div>
      ) : (
        <EmptyHint>目标（O）生成后会显示负责人、模式与置信门槛。</EmptyHint>
      )}

      {krs.length > 0 ? (
        <ul className="mt-3 divide-y divide-slate-800/80">
          {krs.map((kr) => (
            <li
              key={kr.node_id}
              data-testid={`okr-row-${kr.node_id}`}
              className="flex flex-col gap-1 py-2.5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {kr.node_id}
                </span>
                <span className="min-w-0 flex-1 text-xs leading-5 text-slate-200">
                  {kr.criteria}
                </span>
                <VerdictBadge verdict={kr.verdict} />
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
                <span>{VERIFY_LABEL[kr.verify] ?? kr.verify}</span>
                <span>负责人 {kr.owner || "—"}</span>
                <span>证据 {kr.evidence_count > 0 ? kr.evidence_count : "—"}</span>
              </div>
              {kr.reason && (
                <p className="text-[11px] leading-5 text-slate-400">{kr.reason}</p>
              )}
            </li>
          ))}
        </ul>
      ) : (
        objective && <p className="mt-3 text-[11px] text-slate-500">等待领队派工后生成 KR。</p>
      )}
    </SectionCard>
  );
}
