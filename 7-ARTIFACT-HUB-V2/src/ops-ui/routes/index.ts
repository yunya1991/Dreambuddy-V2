import express from "express";
import type { Request, Response } from "express";
import { renderHealth } from "../views/health.js";
import { renderOpsHtml } from "../html.js";
import { getQueueSnapshot } from "../ops-api.js";
import { listStrategies, readStrategy } from "../strategy-library.js";
import { renderUiMapHtml } from "../ui-map.js";
import { toHealthViewModel } from "../adapters/index.js";
import type { HealthContractV1 } from "../adapters/index.js";

function sendHtml(res: Response, statusCode: number, html: string) {
  res.setHeader("content-type", "text/html; charset=utf-8");
  return res.status(statusCode).send(html);
}

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

type PlannedModuleCard = {
  leftTitle: string;
  leftItems: string[];
  rightTitle: string;
  rightItems: string[];
};

function getPlannedModuleCard(moduleName: string, node: string): PlannedModuleCard {
  const normalizedModule = moduleName.trim().toLowerCase();
  const normalizedNode = node.trim().toLowerCase();
  if (normalizedModule === "feed" || normalizedNode === "feed") {
    return {
      leftTitle: "内容门户结构",
      leftItems: ["/feed", "/feed/[category]", "/feed/[category]/[artifactId]"],
      rightTitle: "预计承接能力",
      rightItems: ["内容浏览", "分类聚合", "上下文阅读"],
    };
  }
  if (normalizedModule === "query layer" || normalizedNode === "query") {
    return {
      leftTitle: "查询对象",
      leftItems: ["ArtifactIndex", "ArtifactContent", "SearchResult"],
      rightTitle: "数据能力",
      rightItems: ["分类映射", "摘要提取", "标签与 phase 聚合"],
    };
  }
  if (normalizedModule === "data fabric" || normalizedNode === "data") {
    return {
      leftTitle: "底层目录",
      leftItems: ["artifacts", "meta", "config"],
      rightTitle: "协议与运行数据",
      rightItems: ["task_*.json", "result_*.json", "archive / registry"],
    };
  }
  return {
    leftTitle: "模块结构",
    leftItems: ["规划中入口"],
    rightTitle: "预计承接能力",
    rightItems: ["后续页面入口承接"],
  };
}

function renderPlannedPage(params: { target: string; label: string; module: string; node: string }): string {
  const target = escapeHtml(params.target);
  const label = escapeHtml(params.label);
  const moduleName = escapeHtml(params.module);
  const node = escapeHtml(params.node);
  const moduleCard = getPlannedModuleCard(params.module, params.node);
  const leftTitle = escapeHtml(moduleCard.leftTitle);
  const rightTitle = escapeHtml(moduleCard.rightTitle);
  const leftItems = moduleCard.leftItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const rightItems = moduleCard.rightItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Coming Soon</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: linear-gradient(180deg, #06101d 0%, #08111f 100%);
        color: #eef5ff;
        font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      }
      .card {
        width: min(720px, calc(100vw - 32px));
        border-radius: 24px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        background: rgba(8, 16, 30, 0.92);
        padding: 28px;
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.42);
      }
      .eyebrow {
        color: #ffe2b3;
        font-size: 12px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      h1 {
        margin: 12px 0 10px;
        font-size: 36px;
      }
      p {
        color: #97a8c8;
        line-height: 1.7;
      }
      code {
        color: #dbeafe;
      }
      .actions {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        margin-top: 20px;
      }
      a {
        color: #8cc4ff;
        text-decoration: none;
      }
      a:hover {
        text-decoration: underline;
      }
      .pill {
        display: inline-flex;
        align-items: center;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255, 191, 95, 0.3);
        background: rgba(255, 191, 95, 0.12);
        color: #ffe2b3;
        font-size: 12px;
      }
      .section {
        margin-top: 18px;
        padding-top: 18px;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
      }
      .section h2 {
        margin: 0 0 10px;
        font-size: 18px;
      }
      .module-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
        margin-top: 12px;
      }
      .module-panel {
        border-radius: 18px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        background: rgba(255, 255, 255, 0.03);
        padding: 14px;
      }
      .module-panel h3 {
        margin: 0 0 10px;
        font-size: 16px;
      }
      ul {
        margin: 0;
        padding-left: 18px;
        color: #97a8c8;
        line-height: 1.7;
      }
      @media (max-width: 520px) {
        .card {
          width: min(720px, calc(100vw - 20px));
          padding: 22px 16px;
          border-radius: 20px;
        }
        h1 {
          font-size: 30px;
        }
        .module-grid {
          grid-template-columns: 1fr;
        }
      }
    </style>
  </head>
  <body>
    <main class="card">
      <div class="eyebrow">Planned Route</div>
      <h1>coming soon</h1>
      <p><span class="pill">Coming Soon</span></p>
      <p>当前入口 <code>${label}</code> 还处于规划阶段，暂未接入真实页面。</p>
      <p>所属模块：<code>${moduleName}</code></p>
      <p>目标路径：<code>${target}</code></p>
      <section class="section">
        <h2>${moduleName} Module Card</h2>
        <div class="module-grid">
          <div class="module-panel">
            <h3>${leftTitle}</h3>
            <ul>
              ${leftItems}
            </ul>
          </div>
          <div class="module-panel">
            <h3>${rightTitle}</h3>
            <ul>
              ${rightItems}
            </ul>
          </div>
        </div>
      </section>
      <section class="section">
        <h2>返回上一个节点</h2>
        <p>可返回到 <code>/ui-map</code> 并自动打开来源节点的 Drawer。</p>
      </section>
      <div class="actions">
        <a href="/ui-map?node=${node}">Back to Previous Node</a>
        <a href="/ui-map">Back to UI Map</a>
        <a href="/">Open Ops Home</a>
      </div>
    </main>
  </body>
</html>`;
}

function readOptionalEnv(name: string): string | null {
  const raw = process.env[name]?.trim();
  if (!raw || raw === "undefined" || raw === "null") {
    return null;
  }

  return raw;
}

function readOptionalEnvUrl(name: string): string | null {
  const raw = readOptionalEnv(name);
  if (!raw) {
    return null;
  }

  try {
    return new URL(raw).toString();
  } catch {
    return null;
  }
}

function resolveHubBaseUrl(): string {
  return readOptionalEnvUrl("HUB_URL") ?? "http://127.0.0.1:3456";
}

function resolveFeedBaseUrl(): string {
  return readOptionalEnvUrl("OPS_UI_FEED_BASE_URL") ?? resolveHubBaseUrl();
}

function resolveUiMapFeedBaseUrl(): string {
  return readOptionalEnv("OPS_UI_FEED_BASE_URL") ?? readOptionalEnv("HUB_URL") ?? "http://127.0.0.1:3456";
}

function resolveGatewayBaseUrl(): string {
  return readOptionalEnvUrl("GATEWAY_URL") ?? "http://127.0.0.1:3000";
}

function resolveOpsAdminToken(): string | null {
  const raw = process.env.OPS_ADMIN_TOKEN?.trim();
  return raw && raw.length > 0 ? raw : null;
}

async function safeFetchJson(url: string): Promise<{ ok: true; status: number; data: unknown } | { ok: false; error: string }> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1500) });
    const text = await res.text();
    try {
      return { ok: true, status: res.status, data: JSON.parse(text) as unknown };
    } catch {
      return { ok: true, status: res.status, data: text };
    }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

type UiMapHubStatus =
  | { kind: "ok"; baseUrl: string }
  | { kind: "invalid"; baseUrl: null }
  | { kind: "unreachable"; baseUrl: string };

async function resolveUiMapHubStatus(feedBaseUrl: string): Promise<UiMapHubStatus> {
  if (!feedBaseUrl) {
    return { kind: "invalid", baseUrl: null };
  }

  let normalizedBaseUrl: string;
  try {
    normalizedBaseUrl = new URL(feedBaseUrl).toString();
  } catch {
    return { kind: "invalid", baseUrl: null };
  }

  const health = await safeFetchJson(new URL("/health", normalizedBaseUrl).toString());
  return health.ok ? { kind: "ok", baseUrl: normalizedBaseUrl } : { kind: "unreachable", baseUrl: normalizedBaseUrl };
}

async function proxyJson(req: Request, res: Response, targetUrl: string) {
  try {
    const upstream = await fetch(targetUrl, {
      method: req.method,
      headers: { "content-type": "application/json; charset=utf-8", accept: "application/json" },
      body: req.method === "POST" ? JSON.stringify(req.body ?? {}) : undefined,
    });
    const text = await upstream.text();
    try {
      return res.status(upstream.status).json(JSON.parse(text) as unknown);
    } catch {
      return res.status(upstream.status).json({ ok: false, error: "invalid_json_from_upstream", raw: text });
    }
  } catch (e) {
    return res.status(502).json({
      ok: false,
      error: "upstream_fetch_failed",
      message: e instanceof Error ? e.message : String(e),
    });
  }
}

function tryParseHealthContract(data: unknown): HealthContractV1 | null {
  if (
    data !== null &&
    typeof data === "object" &&
    "service" in data &&
    "status" in data &&
    "timestamp" in data &&
    "dependencies" in data
  ) {
    return data as HealthContractV1;
  }
  return null;
}

export function buildOpsRouter(): express.Router {
  const router = express.Router();
  const hubBaseUrl = resolveHubBaseUrl();
  const feedBaseUrl = resolveFeedBaseUrl();
  const gatewayBaseUrl = resolveGatewayBaseUrl();

  router.get("/health", (_req: Request, res: Response) => {
    const ts = new Date().toISOString();
    return res.json({
      service: "ops-ui",
      status: "ok",
      timestamp: ts,
      dependencies: { artifact_hub: "unknown", gateway: "unknown", meta_db: "unknown" },
    });
  });

  router.get("/api/ops/queues", (_req: Request, res: Response) => {
    return res.status(200).json(getQueueSnapshot());
  });

  router.get("/api/ops/strategy-library", (_req: Request, res: Response) => {
    return res.status(200).json(listStrategies());
  });

  router.get("/api/ops/strategy-library/file", (req: Request, res: Response) => {
    const id = req.query.id;
    if (typeof id !== "string" || id.trim().length === 0) {
      return res.status(400).json({ ok: false, error: "missing_id" });
    }
    try {
      return res.status(200).json({ ok: true, doc: readStrategy(id) });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      return res.status(message === "strategy_not_found" ? 404 : 400).json({ ok: false, error: message });
    }
  });

  router.get("/api/ops/strategy-stats", async (_req: Request, res: Response) => {
    const token = resolveOpsAdminToken();
    if (!token) return res.status(500).json({ ok: false, error: "missing_ops_admin_token" });
    try {
      const upstream = await fetch(new URL("/api/admin/strategy-stats", gatewayBaseUrl).toString(), {
        headers: { accept: "application/json", "x-admin-token": token },
        signal: AbortSignal.timeout(1500),
      });
      const text = await upstream.text();
      try {
        return res.status(upstream.status).json(JSON.parse(text) as unknown);
      } catch {
        return res.status(upstream.status).json({ ok: false, error: "invalid_json_from_gateway", raw: text });
      }
    } catch (e) {
      return res.status(502).json({
        ok: false,
        error: "gateway_fetch_failed",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  });

  router.get("/api/ops/health", async (_req: Request, res: Response) => {
    const [hub, gateway] = await Promise.all([
      safeFetchJson(new URL("/health", hubBaseUrl).toString()),
      safeFetchJson(new URL("/api/monitor/stats", gatewayBaseUrl).toString()),
    ]);
    const queues = getQueueSnapshot();

    const hubContract = hub.ok ? tryParseHealthContract(hub.data) : null;
    const hubHealthView = hubContract ? toHealthViewModel(hubContract) : null;

    return res.status(200).json({
      ok: hub.ok && gateway.ok,
      generated_at: new Date().toISOString(),
      hub: { base_url: hubBaseUrl, result: hub },
      hub_health: hubHealthView,
      gateway: { base_url: gatewayBaseUrl, result: gateway },
      queues,
    });
  });

  router.post("/api/ops/route/decide", async (req: Request, res: Response) => {
    return proxyJson(req, res, new URL("/route/decide", hubBaseUrl).toString());
  });

  router.post("/api/ops/route/execute", async (req: Request, res: Response) => {
    return proxyJson(req, res, new URL("/route/execute", hubBaseUrl).toString());
  });

  router.get("/api/ops/traces/:traceId", async (req: Request, res: Response) => {
    const traceId = req.params.traceId;
    if (!traceId) return res.status(404).json({ ok: false, error: "missing_trace_id" });
    return proxyJson(req, res, new URL(`/traces/${encodeURIComponent(traceId)}`, hubBaseUrl).toString());
  });

  router.get("/", (_req: Request, res: Response) => {
    return sendHtml(res, 200, renderOpsHtml({ host: "127.0.0.1", port: Number(process.env.OPS_UI_PORT || 3457) }));
  });

  router.get("/ui-map", async (_req: Request, res: Response) => {
    const hubStatus = await resolveUiMapHubStatus(resolveUiMapFeedBaseUrl());
    return sendHtml(
      res,
      200,
      renderUiMapHtml({
        host: "127.0.0.1",
        port: Number(process.env.OPS_UI_PORT || 3457),
        feedBaseUrl: hubStatus.baseUrl ?? "",
        hubStatus
      })
    );
  });

  router.get("/planned", (req: Request, res: Response) => {
    const target = typeof req.query.target === "string" && req.query.target.trim().length > 0 ? req.query.target : "/";
    const label = typeof req.query.label === "string" && req.query.label.trim().length > 0 ? req.query.label : target;
    const moduleName =
      typeof req.query.module === "string" && req.query.module.trim().length > 0 ? req.query.module : "Planned Module";
    const node = typeof req.query.node === "string" && req.query.node.trim().length > 0 ? req.query.node : "feed";
    return sendHtml(res, 200, renderPlannedPage({ target, label, module: moduleName, node }));
  });

  router.get("/health.html", (_req: Request, res: Response) => {
    return sendHtml(res, 200, renderHealth());
  });

  return router;
}
