import type { AcceptanceRecord } from "@/types/task-board";
import { EmptyHint, SectionCard, VerdictBadge } from "./primitives";

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
}

export function AcceptanceFeed({ records }: { records: AcceptanceRecord[] }) {
  const sorted = [...records].sort((a, b) => b.ts - a.ts);

  return (
    <SectionCard
      title="验收回流"
      testId="task-board-acceptance"
      meta={
        records.length > 0 ? (
          <span className="text-[10px] text-slate-500">最近 {records.length} 条</span>
        ) : undefined
      }
    >
      {sorted.length === 0 ? (
        <EmptyHint>验收结论会回流到对应 KR：绿通过、黄待复核、红驳回。</EmptyHint>
      ) : (
        <ol className="space-y-2">
          {sorted.map((record) => (
            <li
              key={`${record.role}:${record.node_id}:${record.ts}`}
              data-testid="acceptance-row"
              className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <VerdictBadge verdict={record.verdict} />
                <span className="text-xs text-slate-300">
                  {record.role} → {record.node_id}
                </span>
                <span className="ml-auto text-[10px] text-slate-500">
                  {fmtTime(record.ts)}
                </span>
              </div>
              {record.reason && (
                <p className="mt-1 text-[11px] leading-5 text-slate-400">{record.reason}</p>
              )}
              <p className="mt-1 text-[10px] text-slate-500">
                证据 {record.evidence_refs.length > 0 ? record.evidence_refs.join("、") : "—"}
              </p>
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  );
}
