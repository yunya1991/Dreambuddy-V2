import Link from "next/link";
import type { UIMapShellViewModel } from "./ui-map-shell-view-model.ts";
import UIMapModuleCard from "./UIMapModuleCard";

export default function UIMapShell(props: { viewModel: UIMapShellViewModel }) {
  const { hero, sourceLayer, mainlineLayer, businessPrecipitation, indexFoundation, perspectiveLayer } = props.viewModel;

  return (
    <div className="space-y-8">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-600">独立中台首页</span>
          <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">{hero.dataModeLabel}</span>
        </div>
        <h1 className="mt-4 text-3xl font-bold text-slate-900">{hero.title}</h1>
        <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-600">{hero.subtitle}</p>
      </section>

      <section aria-label="source-layer" className="grid gap-6 lg:grid-cols-2">
        {sourceLayer.map((item) => (
          <UIMapModuleCard key={item.title} title={item.title} description={item.description} bullets={item.bullets} />
        ))}
      </section>

      <section className="rounded-3xl border border-emerald-200 bg-emerald-50 p-8 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-700">统一主线层</p>
        <h2 className="mt-2 text-2xl font-bold text-slate-900">{mainlineLayer.title}</h2>
        <p className="mt-3 text-sm font-medium text-emerald-700">{mainlineLayer.convergenceLabel}</p>
        <p className="mt-4 text-sm leading-7 text-slate-700">{mainlineLayer.chain}</p>
        {mainlineLayer.summaryNote && (
          <p className="mt-4 rounded-xl border border-emerald-200 bg-white/60 p-3 text-xs leading-6 text-emerald-900">
            {mainlineLayer.summaryNote}
          </p>
        )}
      </section>

      {businessPrecipitation.statsCards.length > 0 ? (
        <section className="rounded-3xl border border-amber-200 bg-amber-50 p-8 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">业务数据沉淀层</p>
          <h2 className="mt-2 text-2xl font-bold text-slate-900">{businessPrecipitation.title}</h2>
          <p className="mt-3 text-sm font-medium text-slate-700">{businessPrecipitation.description}</p>
          {businessPrecipitation.aggregatedAt ? (
            <p className="mt-2 text-xs text-slate-500">{businessPrecipitation.aggregatedAt}</p>
          ) : null}

          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {businessPrecipitation.statsCards.map((card) => (
              <div key={card.label} className="rounded-2xl border border-amber-200 bg-white p-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{card.label}</p>
                <p className="mt-2 text-3xl font-bold text-amber-800">{card.value}</p>
                {card.detail && <p className="mt-3 text-xs leading-6 text-slate-600">{card.detail}</p>}
              </div>
            ))}
          </div>

          {businessPrecipitation.cards.length > 0 && (
            <div className="mt-6 grid gap-4 lg:grid-cols-3">
              {businessPrecipitation.cards.map((card) => (
                <div key={card.label} className="rounded-2xl border border-amber-200 bg-white p-4 shadow-sm">
                  <p className="text-sm font-semibold text-amber-800">{card.label}</p>
                  <p className="mt-2 text-xs leading-6 text-slate-700">{card.detail}</p>
                </div>
              ))}
            </div>
          )}

          <div className="mt-8 flex items-center justify-between rounded-2xl border border-slate-900 bg-slate-900 p-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-400">数据中台入口</p>
              <p className="mt-1 text-base font-semibold text-white">业务数据管理系统</p>
              <p className="mt-1 text-xs text-slate-400">用户 · 策略 · 任务 · 执行记录 · 交易数据 的只读视图</p>
            </div>
            <Link
              href="/admin"
              className="inline-flex items-center gap-1.5 rounded-xl bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-900 shadow-sm transition hover:bg-amber-300"
            >
              进入管理系统 →
            </Link>
          </div>
        </section>
      ) : (
        <section className="rounded-3xl border border-dashed border-slate-300 bg-white p-8 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">业务数据沉淀层</p>
          <h2 className="mt-2 text-2xl font-bold text-slate-900">{businessPrecipitation.title}</h2>
          <p className="mt-3 text-sm leading-7 text-slate-500">{businessPrecipitation.description}</p>
          <div className="mt-6">
            <Link
              href="/admin"
              className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
            >
              进入管理系统 →
            </Link>
          </div>
        </section>
      )}

      <section className="grid gap-6 lg:grid-cols-2">
        <UIMapModuleCard
          title={indexFoundation.userContext.title}
          description={`${indexFoundation.userContext.description} 执行频率：${indexFoundation.userContext.executionFrequencies.join(" / ")}`}
          bullets={[indexFoundation.userContext.buildLabel, indexFoundation.userContext.runtimeLabel]}
        />
        <UIMapModuleCard
          title={indexFoundation.systemResearch.title}
          description={indexFoundation.systemResearch.description}
          bullets={indexFoundation.systemResearch.bullets}
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        {perspectiveLayer.map((item) => (
          <UIMapModuleCard
            key={item.title}
            title={item.title}
            description={item.description}
            bullets={item.bullets}
          />
        ))}
      </section>
    </div>
  );
}
