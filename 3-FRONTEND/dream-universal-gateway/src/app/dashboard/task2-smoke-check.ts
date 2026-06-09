import { buildDashboardMainPanelViewModel } from "./dashboard-main-panel-view-model";

const viewModel = buildDashboardMainPanelViewModel(null);

void import("./components/DashboardMainPanel").then((mod) => {
  if (typeof mod.default !== "function") {
    throw new Error("DashboardMainPanel export is missing");
  }

  return viewModel;
});
