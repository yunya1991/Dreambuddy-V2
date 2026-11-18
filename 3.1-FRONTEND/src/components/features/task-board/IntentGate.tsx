import type { IntentDecision } from "@/types/task-board";
import { EmptyHint, SectionCard } from "./primitives";

export function IntentGate({ intent }: { intent?: IntentDecision }) {
  return (
    <SectionCard
      title="意图门"
      testId="task-board-intent"
      meta={
        <span className="text-[10px] text-slate-500">
          脑暴 / 逆向解析 / 外部采集，命中才展开
        </span>
      }
    >
      {intent ? (
        <div className="space-y-3">
          <blockquote className="rounded-lg border-l-2 border-slate-600 bg-slate-950/50 px-3 py-2 text-xs leading-5 text-slate-300">
            {intent.raw_input || "—"}
          </blockquote>

          <div className="flex flex-wrap gap-2">
            {intent.gates.map((gate) => (
              <span
                key={gate.key}
                title={gate.reason}
                data-testid={`intent-gate-${gate.key}`}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${
                  gate.hit
                    ? "border-indigo-700/60 bg-indigo-950/40 text-indigo-300"
                    : "border-slate-700 bg-slate-900 text-slate-400"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    gate.hit ? "bg-indigo-400" : "bg-slate-600"
                  }`}
                  aria-hidden
                />
                {gate.label} · {gate.hit ? "命中" : "跳过"}
              </span>
            ))}
          </div>

          <p className="text-xs leading-5 text-slate-300">
            <span className="text-slate-500">判定：</span>
            {intent.decision || "—"}
          </p>
        </div>
      ) : (
        <EmptyHint>收到任务后，先在这里给出意图判定。</EmptyHint>
      )}
    </SectionCard>
  );
}
