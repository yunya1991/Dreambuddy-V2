import test from "node:test";
import assert from "node:assert/strict";
import { renderFeedDetailHtml, renderFeedIndexHtml } from "./render.js";

test("renderFeedIndexHtml renders feed list, filters, and detail links", () => {
  const html = renderFeedIndexHtml({
    title: "Feed Content Portal",
    items: [
      {
        id: "trading/a1",
        category: "trading",
        artifactId: "a1",
        title: "Alpha Report",
        department: "trading",
        type: "report",
        status: "completed",
        date: "2026-05-20T10:00:00Z",
        chainPhase: "A3",
        tags: ["macro"],
        excerpt: "Body excerpt",
        url: "/feed/trading/a1"
      }
    ],
    stats: {
      total: 1,
      byDepartment: { trading: 1 },
      byType: { report: 1 },
      byStatus: { completed: 1 },
      byChainPhase: { A3: 1 }
    },
    query: { category: "trading", q: "alpha" },
    summary: {
      departmentEntries: [{ label: "交易部", count: 1, href: "/feed?department=%E4%BA%A4%E6%98%93%E9%83%A8" }],
      stageEntries: [{ label: "A3", count: 1, href: "/feed?chainPhase=A3" }]
    }
  });

  assert.ok(html.includes("Feed Content Portal"));
  assert.ok(html.includes('action="/feed"'));
  assert.ok(html.includes('name="q"'));
  assert.ok(html.includes('href="/feed/trading/a1"'));
  assert.ok(html.includes("Alpha Report"));
  assert.ok(html.includes("Body excerpt"));
});

test("renderFeedIndexHtml includes navigation, filter chips, and pagination shell", () => {
  const html = renderFeedIndexHtml({
    title: "Dream 产物中心",
    items: [
      {
        id: "trading/a1",
        category: "trading",
        artifactId: "a1",
        filename: "a1.md",
        title: "A1 Report",
        department: "trading",
        type: "report",
        status: "completed",
        date: "2026-05-20",
        chainPhase: "A3",
        tags: ["A3"],
        excerpt: "alpha",
        url: "/feed/trading/a1"
      }
    ],
    stats: {
      total: 1,
      byDepartment: { trading: 1 },
      byType: { report: 1 },
      byStatus: { completed: 1 },
      byChainPhase: { A3: 1 }
    },
    query: { q: "", category: "trading", department: "trading", chainPhase: "A3" },
    summary: {
      departmentEntries: [{ label: "交易部", count: 1, href: "/feed?department=%E4%BA%A4%E6%98%93%E9%83%A8" }],
      stageEntries: [{ label: "A3", count: 1, href: "/feed?chainPhase=A3" }]
    }
  });

  assert.match(html, /Dream 产物中心/);
  assert.match(html, /组织架构/);
  assert.match(html, /驾驶舱/);
  assert.match(html, /trading/);
  assert.match(html, /A3/);
  assert.match(html, /上一页/);
  assert.match(html, /下一页/);
});

test("renderFeedIndexHtml shows Chinese department entrances and fixed A0-A9 stage entrances", () => {
  const html = renderFeedIndexHtml({
    title: "Dream 产物中心",
    items: [],
    stats: { total: 0, byDepartment: {}, byType: {}, byStatus: {}, byChainPhase: {} },
    query: {},
    summary: {
      departmentEntries: [
        { label: "交易部", count: 1, href: "/feed?department=%E4%BA%A4%E6%98%93%E9%83%A8" },
        { label: "做梦部", count: 1, href: "/feed?department=%E5%81%9A%E6%A2%A6%E9%83%A8" },
        { label: "治理部", count: 1, href: "/feed?department=%E6%B2%BB%E7%90%86%E9%83%A8" },
        { label: "知识库", count: 1, href: "/feed?department=%E7%9F%A5%E8%AF%86%E5%BA%93" }
      ],
      stageEntries: ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"].map((label) => ({
        label,
        count: label === "A1" ? 1 : 0,
        href: `/feed?chainPhase=${label}`
      }))
    }
  } as any);

  assert.match(html, /交易部/);
  assert.match(html, /做梦部/);
  assert.match(html, /A0/);
  assert.match(html, /A9/);
  assert.doesNotMatch(html, /name="Department"/);
});

test("renderFeedDetailHtml renders markdown content and back link", () => {
  const html = renderFeedDetailHtml({
    id: "trading/a1",
    category: "trading",
    artifactId: "a1",
    title: "Alpha Report",
    department: "trading",
    type: "report",
    status: "completed",
    date: "2026-05-20T10:00:00Z",
    chainPhase: "A3",
    tags: ["macro"],
    url: "/feed/trading/a1",
    rawPath: "/tmp/a1.md",
    content: "# Alpha Report\n\nRendered body"
  });

  assert.ok(html.includes('href="/feed/trading"'));
  assert.ok(html.includes("Alpha Report"));
  assert.ok(html.includes("<h1>Alpha Report</h1>"));
  assert.ok(html.includes("Rendered body"));
});

test("renderFeedDetailHtml includes governance context and chain jump link", () => {
  const html = renderFeedDetailHtml({
    id: "trading/a1",
    category: "trading",
    artifactId: "a1",
    filename: "a1.md",
    title: "A1 Report",
    department: "trading",
    type: "report",
    status: "completed",
    date: "2026-05-20",
    chainPhase: "A3",
    tags: ["A3"],
    excerpt: "alpha",
    url: "/feed/trading/a1",
    content: "# Report",
    rawPath: "/tmp/a1.md",
    governanceContext: {
      workflowId: "wf-1",
      workflowType: "legacy_chain",
      traceId: "trace-1",
      chainPhase: "A3"
    }
  });

  assert.match(html, /trace-1/);
  assert.match(html, /workflow/);
  assert.match(html, /查看链路监控/);
  assert.match(html, /href="\/chain\/legacy_chain\?artifactId=trading%2Fa1"/);
});

test("renderFeedDetailHtml shows fixed Chinese classification fields for P0", () => {
  const html = renderFeedDetailHtml({
    id: "research/intel-report-001",
    category: "research",
    artifactId: "intel-report-001",
    filename: "intel-report-001.md",
    title: "BTC市场情报分析报告",
    department: "research",
    departmentLabel: "知识库",
    type: "report",
    typeLabel: "报告",
    status: "completed",
    date: "2026-05-20",
    chainPhase: "A1",
    tags: ["bitcoin", "market-analysis"],
    excerpt: "alpha",
    url: "/feed/research/intel-report-001",
    content: "# 报告正文\n\n这里是正文。",
    rawPath: "/tmp/intel-report-001.md",
    governanceContext: {
      workflowId: "wf-1",
      workflowType: "trading_v2",
      traceId: "trace-1",
      chainPhase: "A1"
    }
  });

  assert.match(html, /部门/);
  assert.match(html, /知识库/);
  assert.match(html, /阶段/);
  assert.match(html, /A1/);
  assert.match(html, /类型/);
  assert.match(html, /报告/);
  assert.match(html, /标签/);
  assert.match(html, /bitcoin/);
  assert.match(html, /<h2>正文<\/h2>/);
  assert.match(html, /报告正文/);
  assert.match(html, /查看链路监控/);
});
