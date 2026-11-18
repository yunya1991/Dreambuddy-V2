import type { TaskSpec } from "@/types/task-board";
import { EmptyHint, SectionCard } from "./primitives";

/** 对外 SPEC 固定六字段：目标 / 范围 / 假设 / 交付 / 验收 / 依赖 */
const REQUIRED_FIELD_COUNT = 6;

export function SpecPanel({ spec }: { spec?: TaskSpec }) {
  const filled = spec
    ? spec.fields.filter((field) => field.value.trim().length > 0).length
    : 0;
  const missing = spec ? Math.max(0, REQUIRED_FIELD_COUNT - filled) : 0;

  return (
    <SectionCard
      title="SPEC 推理框"
      testId="task-board-spec"
      meta={
        spec ? (
          <>
            <span className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
              v{spec.version}
            </span>
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] ${
                spec.status === "confirmed"
                  ? "border-emerald-700/60 bg-emerald-950/40 text-emerald-300"
                  : "border-slate-700 bg-slate-900 text-slate-400"
              }`}
            >
              {spec.status === "confirmed" ? "已确认" : "草稿"}
            </span>
          </>
        ) : (
          <span className="text-[10px] text-slate-500">必现</span>
        )
      }
    >
      {spec ? (
        <div className="space-y-3">
          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {spec.fields.map((field) => (
              <div key={field.key} className="rounded-lg bg-slate-950/40 px-3 py-2">
                <dt className="text-[10px] text-slate-500">{field.label}</dt>
                <dd
                  className={`mt-0.5 text-xs leading-5 ${
                    field.value.trim() ? "text-slate-200" : "text-slate-600"
                  }`}
                >
                  {field.value.trim() || "—"}
                </dd>
              </div>
            ))}
          </dl>
          {missing > 0 && (
            <p className="text-[11px] text-amber-400/90">
              仍有 {missing} 项未填充；看板不会把空字段当成结论。
            </p>
          )}
        </div>
      ) : (
        <EmptyHint>意图判定后，这里按六字段生成 SPEC。</EmptyHint>
      )}
    </SectionCard>
  );
}
