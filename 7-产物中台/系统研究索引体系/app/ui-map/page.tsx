import UIMapClient from "./UIMapClient";
import { getUIMapScenario, type UIMapScenarioId } from "./ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "./ui-map-shell-view-model.ts";

export const dynamic = "force-dynamic";

export default function UIMapPage({
  searchParams,
}: {
  searchParams?: { scenario?: string };
}) {
  const scenario = getUIMapScenario(searchParams?.scenario);
  const viewModel = buildUIMapShellViewModel(scenario);

  return <UIMapClient scenarioId={scenario.id as UIMapScenarioId} viewModel={viewModel} />;
}
