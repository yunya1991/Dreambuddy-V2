import type { ChainOverviewViewModel, ChainWorkflowItem } from "./types.js";

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderWorkflowSection(
  title: string,
  items: ChainWorkflowItem[],
  selectedWorkflowType: string,
  selectedArtifactId?: string
): string {
  if (selectedWorkflowType !== "all" && selectedWorkflowType !== title) {
    return "";
  }

  const cards = items
    .map(
      (item) => `
        <article class="chain-card${isSelectedArtifact(item, selectedArtifactId) ? " selected" : ""}">
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.chainPhase || "unphased")} · ${escapeHtml(item.status)}</p>
          <p>${escapeHtml(item.department)} / ${escapeHtml(item.category)}</p>
          <a href="${escapeHtml(item.feedUrl)}">查看产物</a>
        </article>
      `
    )
    .join("");

  return `
    <section class="workflow-section">
      <header>
        <h2>${escapeHtml(title)}</h2>
        <p>${items.length} items</p>
      </header>
      <div class="workflow-grid">${cards || "<p>暂无记录</p>"}</div>
    </section>
  `;
}

function normalizeSelectedArtifactId(selectedArtifactId?: string): string | undefined {
  if (!selectedArtifactId) return undefined;
  try {
    return decodeURIComponent(selectedArtifactId);
  } catch {
    return selectedArtifactId;
  }
}

function isSelectedArtifact(item: ChainWorkflowItem, selectedArtifactId?: string): boolean {
  const normalized = normalizeSelectedArtifactId(selectedArtifactId);
  if (!normalized) return false;
  const shortId = item.artifactId.split("/").pop() ?? item.artifactId;
  return normalized === item.artifactId || normalized === shortId;
}

function findSelectedArtifact(
  input: ChainOverviewViewModel,
  selectedArtifactId?: string
): ChainWorkflowItem | undefined {
  const normalized = normalizeSelectedArtifactId(selectedArtifactId);
  if (!normalized) return undefined;
  const allItems = [...input.workflowGroups.legacy_chain, ...input.workflowGroups.trading_v2];
  return allItems.find((item) => isSelectedArtifact(item, normalized));
}

function renderCrossLinkContext(selectedItem?: ChainWorkflowItem): string {
  if (!selectedItem) return "";

  return `
    <section class="cross-link-context">
      <h2>交叉链接上下文</h2>
      <p>当前产物: ${escapeHtml(selectedItem.artifactId)}</p>
      <p>所属链路: ${escapeHtml(selectedItem.workflowType)} · ${escapeHtml(selectedItem.chainPhase || "unphased")}</p>
      <p><a href="${escapeHtml(selectedItem.feedUrl)}">返回产物详情</a></p>
    </section>
  `;
}

export function renderChainIndexHtml(
  input: ChainOverviewViewModel,
  selectedWorkflowType?: string,
  selectedArtifactId?: string
): string {
  const workflowType = selectedWorkflowType ?? "all";
  const selectedItem = findSelectedArtifact(input, selectedArtifactId);
  const anomalies = input.anomalies
    .map(
      (item) =>
        `<li>${escapeHtml(item.kind)} · ${escapeHtml(item.artifactId)} · ${escapeHtml(item.workflowType)}</li>`
    )
    .join("");

  return `<!doctype html>
  <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <title>Chain Monitor</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #06111f; color: #f8fafc; }
        main { max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }
        a { color: #93c5fd; text-decoration: none; }
        .top-nav { display: flex; gap: 16px; margin-bottom: 20px; }
        .hero { margin-bottom: 24px; }
        .cross-link-context { border: 1px solid #1d4ed8; border-radius: 16px; padding: 16px; background: rgba(29, 78, 216, 0.14); margin-bottom: 20px; }
        .layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; align-items: start; }
        .workflow-section { margin-bottom: 20px; }
        .workflow-grid { display: grid; gap: 12px; }
        .chain-card { border: 1px solid #1e293b; border-radius: 16px; padding: 16px; background: #0f172a; }
        .chain-card.selected { border-color: #60a5fa; box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.4); }
        .anomaly-panel { border: 1px solid #7f1d1d; border-radius: 16px; padding: 16px; background: rgba(127, 29, 29, 0.18); }
      </style>
    </head>
    <body>
      <main>
        <nav class="top-nav">
          <a href="/feed">产物中心</a>
          <a href="/chain">组织架构</a>
          <a href="/ops">驾驶舱</a>
        </nav>
        <section class="hero">
          <h1>Chain Monitor</h1>
          <p>workflow_type: ${escapeHtml(workflowType)}</p>
        </section>
        ${renderCrossLinkContext(selectedItem)}
        <section class="layout">
          <div>
            ${renderWorkflowSection("legacy_chain", input.workflowGroups.legacy_chain, workflowType, selectedArtifactId)}
            ${renderWorkflowSection("trading_v2", input.workflowGroups.trading_v2, workflowType, selectedArtifactId)}
          </div>
          <aside class="anomaly-panel">
            <h2>异常监控</h2>
            <ul>${anomalies || "<li>暂无异常</li>"}</ul>
          </aside>
        </section>
      </main>
    </body>
  </html>`;
}
