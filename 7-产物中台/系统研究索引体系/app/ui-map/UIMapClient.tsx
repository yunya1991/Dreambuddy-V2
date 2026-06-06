'use client';

import Link from "next/link";

import type { UIMapScenarioId } from "./ui-map-scenarios.ts";
import type { UIMapShellViewModel } from "./ui-map-shell-view-model.ts";
import UIMapShell from "./UIMapShell";

const SCENARIOS: Array<{ id: UIMapScenarioId; label: string }> = [
  { id: "balanced", label: "平衡场景" },
  { id: "custom-heavy", label: "自定义策略主导" },
  { id: "system-heavy", label: "系统策略主导" },
  { id: "execution-heavy", label: "执行频次主导" },
];

export default function UIMapClient(props: {
  scenarioId: UIMapScenarioId;
  viewModel: UIMapShellViewModel;
}) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2" data-testid="ui-map-scenario-switcher">
        {SCENARIOS.map((scenario) => (
          <Link
            key={scenario.id}
            href={`/ui-map?scenario=${scenario.id}`}
            className={
              scenario.id === props.scenarioId
                ? "rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white"
                : "rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"
            }
          >
            {scenario.label}
          </Link>
        ))}
      </div>
      <UIMapShell viewModel={props.viewModel} />
    </div>
  );
}
