import type { UIMapShellViewModel } from "./ui-map-shell-view-model.ts";
import UIMapModuleCard from "./UIMapModuleCard";

export default function UIMapShell(props: { viewModel: UIMapShellViewModel }) {
  const { hero, sourceLayer, mainlineLayer, indexFoundation, perspectiveLayer } = props.viewModel;

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
