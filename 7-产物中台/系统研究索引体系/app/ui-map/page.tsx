import UIMapClient from "./UIMapClient";
import { getUIMapScenario, type UIMapScenarioId } from "./ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "./ui-map-shell-view-model.ts";
import {
  buildBusinessPrecipitationOverride,
  buildOperationsUIMapOverride,
  buildResearchChainUIMapOverride,
  buildStrategyUIMapOverride,
  buildSystemResearchUIMapOverride,
  buildUserContextUIMapOverride,
  getBusinessDataView,
} from "../../lib/ui-map-real-data.ts";

export const dynamic = "force-dynamic";

export default async function UIMapPage({
  searchParams,
}: {
  searchParams?: { scenario?: string };
}) {
  const scenario = getUIMapScenario(searchParams?.scenario);
  const businessData = await getBusinessDataView();

  const viewModel = buildUIMapShellViewModel(scenario, {
    systemResearch: buildSystemResearchUIMapOverride(),
    researchChain: buildResearchChainUIMapOverride(),
    operations: buildOperationsUIMapOverride(),
    strategy: buildStrategyUIMapOverride(businessData),
    userContext: buildUserContextUIMapOverride(businessData),
    businessPrecipitation: buildBusinessPrecipitationOverride(businessData),
  });

  return <UIMapClient scenarioId={scenario.id as UIMapScenarioId} viewModel={viewModel} />;
}
