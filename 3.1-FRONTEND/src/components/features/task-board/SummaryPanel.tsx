import type { TaskSummary } from "@/types/task-board";
import { EmptyHint, SectionCard } from "./primitives";

const QUALITY_LABEL: Record<TaskSummary["data_quality"][number]["status"], string> = {
  missing: "缺失",
  partial: "不完整",
  stale: "过期",
};

export function SummaryPanel({ summary }: { summary?: TaskSummary }) {
  return (
    <SectionCard
      title="汇总"
      testId="task-board-summary"
      meta={<span className="text-[10px] text-slate-500">全部 KR 通过后展开</span>}
    >
      {summary ? (
        <div className="space-y-3">
          <p className="text-sm leading-6 text-slate-100">{summary.conclusion}</p>

          {summary.key_points.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-slate-300">
              {summary.key_points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          )}

          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span>置信度</span>
            <span className="font-mono text-slate-200">
              {summary.confidence === undefined
                ? "—"
                : `${Math.round(summary.confidence * 100)}%`}
            </span>
            {summary.confidence === undefined && (
              <span className="text-[10px] text-slate-500">编排侧未给出</span>
            )}
          </div>

          {summary.data_quality.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {summary.data_quality.map((item) => (
                <span
                  key={`${item.item}:${item.status}`}
                  className="rounded-full border border-amber-700/50 bg-amber-950/30 px-2 py-0.5 text-[10px] text-amber-300/90"
                >
                  {item.item} · {QUALITY_LABEL[item.status] ?? item.status}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <EmptyHint>全部 OKR 验收通过后，G 层结论、要点与数据质量在这里汇总。</EmptyHint>
      )}
    </SectionCard>
  );
}
