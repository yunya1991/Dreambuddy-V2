import { marked } from "marked";
import type { FeedDetail, FeedHomepageSummary, FeedListItem, FeedQuery, FeedStats } from "./types.js";

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderStats(stats: FeedStats): string {
  return `<div class="feed-stats"><span>Total ${stats.total}</span></div>`;
}

function buildFeedHref(query: FeedQuery, overrides: Partial<FeedQuery> = {}): string {
  const params = new URLSearchParams();
  const nextQuery: FeedQuery = { ...query, ...overrides };

  if (nextQuery.q) params.set("q", nextQuery.q);
  if (nextQuery.category) params.set("category", nextQuery.category);
  if (nextQuery.department) params.set("department", nextQuery.department);
  if (nextQuery.status) params.set("status", nextQuery.status);
  if (nextQuery.chainPhase) params.set("chainPhase", nextQuery.chainPhase);
  if (typeof nextQuery.limit === "number" && Number.isFinite(nextQuery.limit)) {
    params.set("limit", String(nextQuery.limit));
  }
  if (typeof nextQuery.offset === "number" && Number.isFinite(nextQuery.offset) && nextQuery.offset > 0) {
    params.set("offset", String(nextQuery.offset));
  }

  const serialized = params.toString();
  return serialized ? `/feed?${serialized}` : "/feed";
}

function renderPagination(query: FeedQuery, visibleCount: number, total: number): string {
  const limit = Math.max(1, query.limit ?? Math.max(visibleCount, 20));
  const offset = Math.max(0, query.offset ?? 0);
  const prevOffset = Math.max(0, offset - limit);
  const nextOffset = offset + limit;
  const prevHref = buildFeedHref(query, { offset: prevOffset });
  const nextHref = buildFeedHref(query, { offset: nextOffset });
  const prevClass = offset === 0 ? "page-link disabled" : "page-link";
  const nextClass = nextOffset >= total ? "page-link disabled" : "page-link";

  return `
    <nav class="pagination" aria-label="分页">
      <a class="${prevClass}" href="${escapeHtml(prevHref)}">上一页</a>
      <span class="page-state">Offset ${offset} / Total ${total}</span>
      <a class="${nextClass}" href="${escapeHtml(nextHref)}">下一页</a>
    </nav>
  `;
}

function renderEntryButton(item: { label: string; count: number; href: string }): string {
  return `
    <a class="entry-button" href="${escapeHtml(item.href)}">
      <span class="entry-label">${escapeHtml(item.label)}</span>
      <span class="entry-count">${item.count}</span>
    </a>
  `;
}

function renderCard(item: FeedListItem): string {
  return `
    <article class="feed-card">
      <div class="feed-card-meta">${escapeHtml(item.departmentLabel || item.department)} · ${escapeHtml(item.typeLabel || item.type)} · ${escapeHtml(item.chainPhase || "Unphased")}</div>
      <h2><a href="${escapeHtml(item.url)}">${escapeHtml(item.title)}</a></h2>
      <p>${escapeHtml(item.excerpt || "No excerpt available.")}</p>
    </article>
  `;
}

function buildChainDetailHref(detail: FeedDetail): string {
  const workflowType = detail.governanceContext?.workflowType || "legacy_chain";
  const selectedArtifactId = encodeURIComponent(detail.id);
  return `/chain/${workflowType}?artifactId=${selectedArtifactId}`;
}

export function renderFeedIndexHtml(input: {
  title: string;
  items: FeedListItem[];
  stats: FeedStats;
  query: FeedQuery;
  summary: FeedHomepageSummary;
}): string {
  const cards = input.items.length > 0
    ? input.items.map(renderCard).join("")
    : "<p>暂无相关产物。</p>";

  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>${escapeHtml(input.title)}</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #0b1020; color: #f8fafc; }
      main { max-width: 1080px; margin: 0 auto; padding: 32px 20px 48px; }
      .top-nav { display: flex; gap: 16px; padding: 16px 20px 0; max-width: 1080px; margin: 0 auto; }
      .top-nav a { color: #cbd5f5; }
      .hero { display: grid; gap: 10px; margin-bottom: 20px; }
      .toolbar { border: 1px solid #1e293b; border-radius: 18px; padding: 16px; background: rgba(15, 23, 42, 0.8); margin: 16px 0 24px; }
      .search-form { display: flex; gap: 12px; flex-wrap: wrap; margin: 0; }
      form { display: flex; gap: 12px; flex-wrap: wrap; margin: 0 0 12px; }
      input, select, button { padding: 10px 12px; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
      .feed-card { border: 1px solid #1e293b; border-radius: 16px; padding: 16px; margin-bottom: 12px; background: #111827; }
      .feed-card-meta { color: #94a3b8; font-size: 13px; margin-bottom: 8px; }
      a { color: #93c5fd; text-decoration: none; }
      .feed-stats { color: #94a3b8; margin-top: 8px; }
      .entry-grid { display: grid; gap: 14px; margin: 20px 0 24px; }
      .entry-section { border: 1px solid #1e293b; border-radius: 18px; padding: 18px; background: rgba(15, 23, 42, 0.8); }
      .entry-section h2 { margin: 0 0 14px; font-size: 16px; }
      .entry-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }
      .entry-button { display: grid; gap: 8px; border: 1px solid #334155; border-radius: 14px; padding: 14px; background: #0f172a; }
      .entry-button:hover { border-color: #60a5fa; background: rgba(30, 41, 59, 0.95); }
      .entry-label { color: #e2e8f0; font-weight: 600; }
      .entry-count { color: #94a3b8; font-size: 13px; }
      .advanced-filters { margin-top: 12px; color: #94a3b8; }
      .advanced-filters summary { cursor: pointer; user-select: none; }
      .advanced-form { margin-top: 12px; }
      .pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 20px 0 0; }
      .page-link { display: inline-flex; align-items: center; justify-content: center; min-width: 88px; padding: 10px 12px; border: 1px solid #334155; border-radius: 10px; background: #0f172a; }
      .page-link.disabled { pointer-events: none; opacity: 0.5; }
      .page-state { color: #94a3b8; font-size: 13px; }
    </style>
  </head>
  <body>
    <header class="top-nav">
      <a href="/feed">产物中心</a>
      <a href="/chain">组织架构</a>
      <a href="/ops">驾驶舱</a>
    </header>
    <main>
      <section class="hero">
        <h1>${escapeHtml(input.title)}</h1>
        <p>面向治理链路的中间产物入口，聚合 research / trading / governance 内容并暴露上下文跳转。</p>
        ${renderStats(input.stats)}
      </section>
      <section class="entry-grid">
        <section class="entry-section">
          <h2>部门入口</h2>
          <div class="entry-row">${input.summary.departmentEntries.map(renderEntryButton).join("")}</div>
        </section>
        <section class="entry-section">
          <h2>A 系列</h2>
          <div class="entry-row">${input.summary.stageEntries.map(renderEntryButton).join("")}</div>
        </section>
      </section>
      <section class="toolbar">
        <form class="search-form" method="GET" action="/feed">
          <input type="search" name="q" value="${escapeHtml(input.query.q || "")}" placeholder="搜索产物标题、标签..." />
          <button type="submit">搜索</button>
        </form>
        <details class="advanced-filters">
          <summary>高级筛选</summary>
          <form class="advanced-form" method="GET" action="/feed">
            <input type="search" name="q" value="${escapeHtml(input.query.q || "")}" placeholder="搜索产物标题、标签..." />
            <input type="text" name="category" value="${escapeHtml(input.query.category || "")}" placeholder="类别" />
            <input type="text" name="department" value="${escapeHtml(input.query.department || "")}" placeholder="部门" />
            <input type="text" name="status" value="${escapeHtml(input.query.status || "")}" placeholder="状态" />
            <input type="text" name="chainPhase" value="${escapeHtml(input.query.chainPhase || "")}" placeholder="阶段" />
            <input type="number" name="limit" min="1" value="${escapeHtml(String(input.query.limit ?? ""))}" placeholder="数量" />
            <input type="number" name="offset" min="0" value="${escapeHtml(String(input.query.offset ?? ""))}" placeholder="偏移" />
            <button type="submit">应用</button>
          </form>
        </details>
      </section>
      <section>${cards}</section>
      ${renderPagination(input.query, input.items.length, input.stats.total)}
    </main>
  </body>
</html>`;
}

export function renderFeedDetailHtml(detail: FeedDetail): string {
  const renderedMarkdown = marked.parse(detail.content, { async: false }) as string;
  const chainHref = buildChainDetailHref(detail);
  const departmentLabel = detail.departmentLabel || "未归类";
  const typeLabel = detail.typeLabel || "未知类型";
  const phaseLabel = detail.chainPhase || detail.governanceContext?.chainPhase || "未分阶段";
  const tagLabel = detail.tags.length > 0 ? detail.tags.join(", ") : "无标签";

  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>${escapeHtml(detail.title)}</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #0b1020; color: #f8fafc; }
      main { max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }
      nav { margin-bottom: 20px; }
      a { color: #93c5fd; text-decoration: none; }
      header p { color: #94a3b8; }
      article { line-height: 1.7; }
      article pre, article code { background: #111827; border-radius: 8px; }
      .detail-layout { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 24px; align-items: start; }
      .detail-side { border: 1px solid #1e293b; border-radius: 16px; padding: 16px; background: #111827; }
      .detail-side p { color: #cbd5e1; }
    </style>
  </head>
  <body>
    <main>
      <nav><a href="/feed/${escapeHtml(detail.category)}">返回 ${escapeHtml(detail.category)}</a></nav>
      <header>
        <h1>${escapeHtml(detail.title)}</h1>
        <p>${escapeHtml(departmentLabel)} · ${escapeHtml(typeLabel)} · ${escapeHtml(detail.status)}</p>
      </header>
      <section class="detail-layout">
        <article>
          <h2>正文</h2>
          ${renderedMarkdown}
        </article>
        <aside class="detail-side">
          <h2>分类信息</h2>
          <p><strong>部门</strong>：${escapeHtml(departmentLabel)}</p>
          <p><strong>阶段</strong>：${escapeHtml(phaseLabel)}</p>
          <p><strong>类型</strong>：${escapeHtml(typeLabel)}</p>
          <p><strong>标签</strong>：${escapeHtml(tagLabel)}</p>
          <hr />
          <h2>治理上下文</h2>
          <p>trace_id: ${escapeHtml(detail.governanceContext?.traceId || "none")}</p>
          <p>workflow: ${escapeHtml(detail.governanceContext?.workflowType || "legacy_chain")}</p>
          <p><a href="${escapeHtml(chainHref)}">查看链路监控</a></p>
        </aside>
      </section>
    </main>
  </body>
</html>`;
}
