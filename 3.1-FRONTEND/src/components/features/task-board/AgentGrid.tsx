import type { AgentRun, AgentState } from "@/types/task-board";
import { EmptyHint, SectionCard } from "./primitives";

const AGENT_STATE_META: Record<AgentState, { label: string; dot: string; text: string }> = {
  pending: { label: "待启动", dot: "bg-slate-500", text: "text-slate-400" },
  running: { label: "执行中", dot: "bg-indigo-400 animate-pulse", text: "text-indigo-300" },
  waiting: { label: "等待中", dot: "bg-amber-400", text: "text-amber-300" },
  done: { label: "完成", dot: "bg-emerald-400", text: "text-emerald-300" },
  degraded: { label: "降级", dot: "bg-amber-400", text: "text-amber-300" },
  failed: { label: "失败", dot: "bg-red-400", text: "text-red-300" },
};

function fmtDuration(ms?: number): string | null {
  if (ms === undefined) return null;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function AgentGrid({ agents }: { agents: AgentRun[] }) {
  return (
    <SectionCard
      title="子代理执行"
      testId="task-board-agents"
      meta={
        agents.length > 0 ? (
          <span className="text-[10px] text-slate-500">{agents.length} 个角色</span>
        ) : undefined
      }
    >
      {agents.length === 0 ? (
        <EmptyHint>派工后，这里显示每个子代理的状态、可用能力与结论。</EmptyHint>
      ) : (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent) => {
            const meta = AGENT_STATE_META[agent.state] ?? AGENT_STATE_META.pending;
            const duration = fmtDuration(agent.duration_ms);
            return (
              <article
                key={agent.role}
                data-testid={`agent-card-${agent.role}`}
                className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2.5"
              >
                <div className="flex items-center gap-2">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dot}`} aria-hidden />
                  <span className="truncate text-xs font-medium text-slate-200">
                    {agent.label || agent.role}
                  </span>
                  <span className={`ml-auto shrink-0 text-[10px] ${meta.text}`}>
                    {meta.label}
                  </span>
                </div>

                {agent.capability_ids.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {agent.capability_ids.map((id) => (
                      <span
                        key={id}
                        className="rounded bg-slate-800 px-1 py-0.5 font-mono text-[10px] text-slate-400"
                      >
                        {id}
                      </span>
                    ))}
                  </div>
                )}

                <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-slate-400">
                  {agent.summary || "暂无结论"}
                </p>

                <div className="mt-1.5 flex items-center gap-3 text-[10px] text-slate-500">
                  <span>证据 {agent.evidence_count > 0 ? agent.evidence_count : "—"}</span>
                  {duration && <span>耗时 {duration}</span>}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}
