import type { DashboardMainPanelViewModel } from "../dashboard-main-panel-view-model";
import DashboardMainPanelSection from "./DashboardMainPanelSection";

export default function DashboardMainPanel(props: { viewModel: DashboardMainPanelViewModel }) {
  const { hero, strategyTrack, intentTrack, systemTrack } = props.viewModel;

  return (
    <section className="dashboard-main-panel">
      <div className="dashboard-main-panel__hero">
        <span className="dashboard-main-panel__eyebrow">{hero.entryLabel}</span>
        <h2>{hero.title}</h2>
        <p>{hero.summary}</p>
      </div>

      <div className="dashboard-main-panel__tracks">
        <DashboardMainPanelSection
          title={strategyTrack.title}
          description="从策略设置进入任务单、执行、结果和索引。"
          items={strategyTrack.items}
        />
        <DashboardMainPanelSection
          title={intentTrack.title}
          description="从用户输入进入识别、路由、中台能力链和记忆回灌。"
          items={intentTrack.items}
        />
        <DashboardMainPanelSection
          title={systemTrack.title}
          description="保留系统策略入口，同时表达与统一主线的承接关系。"
          items={systemTrack.items}
        />
      </div>
    </section>
  );
}
