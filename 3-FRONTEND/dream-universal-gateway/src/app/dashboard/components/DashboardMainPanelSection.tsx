import type { DashboardMainPanelItemViewModel } from "../dashboard-main-panel-view-model";

export default function DashboardMainPanelSection(props: {
  title: string;
  description: string;
  items: DashboardMainPanelItemViewModel[];
}) {
  return (
    <section className="dashboard-main-section">
      <header className="dashboard-main-section__header">
        <h3>{props.title}</h3>
        <p>{props.description}</p>
      </header>

      <div className="dashboard-main-section__grid">
        {props.items.map((item) => {
          const content = (
            <>
              <span className="dashboard-main-section__label">{item.label}</span>
              <strong className={`dashboard-main-section__value is-${item.tone}`}>{item.value}</strong>
            </>
          );

          return item.href ? (
            <a
              key={`${props.title}-${item.label}`}
              href={item.href}
              className="dashboard-main-section__card"
              target="_blank"
              rel="noreferrer"
            >
              {content}
            </a>
          ) : (
            <article key={`${props.title}-${item.label}`} className="dashboard-main-section__card">
              {content}
            </article>
          );
        })}
      </div>
    </section>
  );
}
