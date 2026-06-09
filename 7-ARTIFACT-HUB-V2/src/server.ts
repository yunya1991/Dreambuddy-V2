import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import crypto from "node:crypto";
import fs from "node:fs";
import { ChainContentStore } from "./chain/content.js";
import { renderChainIndexHtml } from "./chain/render.js";
import { loadConfig, resolveRepoRoot } from "./config.js";
import { ArtifactStore } from "./artifact-store.js";
import { EventBus } from "./event-bus.js";
import { FeedContentStore } from "./feed/content.js";
import { renderFeedDetailHtml, renderFeedIndexHtml } from "./feed/render.js";
import { readJson, sendJson, methodNotAllowed, notFound } from "./http-utils.js";
import { MetaStore } from "./meta-store.js";
import { RouterEngine } from "./router-engine.js";
import { WorkOrderManager } from "./work-order.js";
import type { Intent, MarketIntel, DistributionStatus, DistributionChannel } from "./types.js";
import { groupByWorkflowType, normalizeWorkflowType } from "./chain-workflow-guard.js";
import { proxyToTrading, checkBridgeHealth } from "./trading-bridge.js";

const srcDir = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(srcDir, "..", "public");

export interface HubServerOptions {
  repoRoot?: string;
  artifactsRoot?: string;
  metaRoot?: string;
}

function parseOptionalInt(value: string | null): number | undefined {
  if (value === null || value.trim() === "") return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? undefined : parsed;
}

export function createHubServer(options: HubServerOptions = {}) {
  const repoRoot = options.repoRoot ?? resolveRepoRoot();
  const config = options.artifactsRoot && options.metaRoot ? null : loadConfig(repoRoot);
  const artifactsRoot = options.artifactsRoot ?? path.join(repoRoot, config!.paths.artifacts_root);
  const metaRoot = options.metaRoot ?? path.join(repoRoot, config!.paths.meta_root);

  const store = new ArtifactStore(artifactsRoot);
  const feedStore = new FeedContentStore(artifactsRoot);
  const chainStore = new ChainContentStore(artifactsRoot);
  const meta = new MetaStore(metaRoot);
  meta.setArtifactStore(store); // Enable board metrics to access artifact count
  const router = new RouterEngine();
  const events = new EventBus();
  const work = new WorkOrderManager(artifactsRoot);

  const stopPollingResults = work.pollResults((result, filePath) => {
    meta.addEvent(
      result.trace_id,
      `e_result_${crypto.randomUUID()}`,
      "result.detected",
      { file: filePath, result },
      Date.now()
    );
    events.publish(result.trace_id, {
      type: "result.detected",
      payload: { file: filePath, result },
      ts: Date.now()
    });
  });

  const server = createServer(async (req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

    const readFeedQuery = (fixedCategory?: string) => ({
      category: fixedCategory ?? url.searchParams.get("category") ?? undefined,
      q: url.searchParams.get("q") ?? undefined,
      department: url.searchParams.get("department") ?? undefined,
      status: url.searchParams.get("status") ?? undefined,
      chainPhase: url.searchParams.get("chainPhase") ?? undefined,
      limit: parseOptionalInt(url.searchParams.get("limit")),
      offset: parseOptionalInt(url.searchParams.get("offset"))
    });

  if (req.method === "GET" && url.pathname === "/health") {
    return sendJson(res, 200, { ok: true, service: "artifact-hub-v2" });
  }

    if (req.method === "GET" && url.pathname === "/feed") {
      const query = readFeedQuery();
      const items = feedStore.listArtifacts(query);
      const html = renderFeedIndexHtml({
        title: "Dream 产物中心",
        items,
        stats: feedStore.getStats(),
        query,
        summary: feedStore.getHomepageSummary()
      });
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (req.method === "GET" && /^\/feed\/[^/]+$/.test(url.pathname)) {
      const category = decodeURIComponent(url.pathname.split("/")[2] ?? "");
      const query = readFeedQuery(category);
      const html = renderFeedIndexHtml({
        title: `Dream 产物中心 / ${category}`,
        items: feedStore.listArtifacts(query),
        stats: feedStore.getStats(),
        query,
        summary: feedStore.getHomepageSummary()
      });
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (req.method === "GET" && /^\/feed\/[^/]+\/[^/]+$/.test(url.pathname)) {
      const [, , rawCategory, rawArtifactId] = url.pathname.split("/");
      const category = decodeURIComponent(rawCategory ?? "");
      const artifactId = decodeURIComponent(rawArtifactId ?? "");
      const detail = feedStore.getArtifactDetail(category, artifactId);
      if (!detail) return notFound(res);
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(renderFeedDetailHtml(detail));
      return;
    }

    if (req.method === "GET" && url.pathname === "/chain") {
      const html = renderChainIndexHtml(
        chainStore.getOverview(),
        undefined,
        url.searchParams.get("artifactId") ?? undefined
      );
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (
      req.method === "GET" &&
      /^\/chain\/[^/]+$/.test(url.pathname) &&
      ["legacy_chain", "trading_v2"].includes(url.pathname.split("/")[2] ?? "")
    ) {
      const workflowType = decodeURIComponent(url.pathname.split("/")[2] ?? "");
      const html = renderChainIndexHtml(
        chainStore.getOverview(),
        workflowType,
        url.searchParams.get("artifactId") ?? undefined
      );
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

  // GET / - 首页重定向到 /board
  if (req.method === "GET" && url.pathname === "/") {
    res.writeHead(302, { Location: "/board" });
    res.end();
    return;
  }

  // GET /board - 董事会总览台 HTML
  if (req.method === "GET" && url.pathname === "/board") {
    const htmlPath = path.join(publicDir, "board", "index.html");
    if (!fs.existsSync(htmlPath)) return notFound(res);
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.writeHead(200);
    fs.createReadStream(htmlPath).pipe(res);
    return;
  }

  // GET /ops - 运维监控台 HTML
  if (req.method === "GET" && url.pathname === "/ops") {
    const htmlPath = path.join(publicDir, "ops", "index.html");
    if (!fs.existsSync(htmlPath)) return notFound(res);
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.writeHead(200);
    fs.createReadStream(htmlPath).pipe(res);
    return;
  }

  if (url.pathname === "/route/decide") {
    if (req.method !== "POST") return methodNotAllowed(res);

    const intent = await readJson<Intent>(req);
    const artifacts = store.getArtifactsIndex();
    const plan = router.decide(intent, artifacts);

    meta.addEvent(plan.trace_id, `e_trace_${crypto.randomUUID()}`, "trace.created", { trace_id: plan.trace_id });
    meta.addEvent(plan.trace_id, `e_route_${crypto.randomUUID()}`, "route.decided", { mode: plan.mode });
    meta.addRouteDecision(plan.trace_id, `d_${crypto.randomUUID()}`, intent, plan, "v0");
    events.publish(plan.trace_id, { type: "route.decided", payload: plan, ts: Date.now() });

    return sendJson(res, 200, plan);
  }

  if (url.pathname === "/route/execute") {
    if (req.method !== "POST") return methodNotAllowed(res);

    const intent = await readJson<Intent>(req);
    const artifacts = store.getArtifactsIndex();
    const plan = router.decide(intent, artifacts);
    const taskId = crypto.randomUUID();

    meta.addEvent(plan.trace_id, `e_trace_${crypto.randomUUID()}`, "trace.created", { trace_id: plan.trace_id });
    meta.addEvent(
      plan.trace_id,
      `e_work_${crypto.randomUUID()}`,
      "work_order.written",
      { task_id: taskId },
      Date.now()
    );
    meta.addRouteDecision(plan.trace_id, `d_${crypto.randomUUID()}`, intent, plan, "v0");

    const taskFilePath = work.writeTask({
      trace_id: plan.trace_id,
      task_id: taskId,
      created_at: new Date().toISOString(),
      intent,
      routing_plan: plan
    });

    events.publish(plan.trace_id, { type: "work_order.written", payload: { task_id: taskId }, ts: Date.now() });

    return sendJson(res, 200, { trace_id: plan.trace_id, task_id: taskId, task_file_path: taskFilePath });
  }

  if (url.pathname === "/events/stream") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const traceId = url.searchParams.get("traceId");
    if (!traceId) return sendJson(res, 400, { error: "missing_traceId" });

    res.statusCode = 200;
    res.setHeader("content-type", "text/event-stream; charset=utf-8");
    res.setHeader("cache-control", "no-cache");
    res.setHeader("connection", "keep-alive");
    res.write(`event: ready\ndata: ${JSON.stringify({ ok: true })}\n\n`);
    events.subscribe(traceId, res);
    return;
  }

  if (url.pathname.startsWith("/traces/")) {
    if (req.method !== "GET") return methodNotAllowed(res);
    const traceId = url.pathname.split("/").filter(Boolean)[1];
    if (!traceId) return notFound(res);
    const decision = meta.getLatestRouteDecision(traceId);
    const ev = meta.listEvents(traceId);
    return sendJson(res, 200, { trace_id: traceId, decision, events: ev });
  }


  if (url.pathname === "/chain/artifacts") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const workflowTypeParam = url.searchParams.get("workflow_type") ?? undefined;
    const allArtifacts = store.getArtifactsIndex();
    const groups = groupByWorkflowType(
      allArtifacts.map(a => ({
        artifact_id: a.id,
        title: a.title,
        department: a.department,
        category: a.id.split("/")[0] ?? "",
        type: a.type,
        chain_phase: a.chain_phase,
        workflow_id: a.workflow_id || "",
        workflow_type: normalizeWorkflowType(a.workflow_type),
        trace_id: "",
        status: a.status,
        relative_path: a.url,
        created_at: a.date,
      }))
    );
    if (workflowTypeParam === "legacy_chain" || workflowTypeParam === "trading_v2") {
      return sendJson(res, 200, {
        workflow_type: workflowTypeParam,
        items: groups[workflowTypeParam],
        total: groups[workflowTypeParam].length,
      });
    }
    return sendJson(res, 200, {
      legacy_chain: groups.legacy_chain,
      trading_v2: groups.trading_v2,
      total: allArtifacts.length,
    });
  }

  if (url.pathname === "/chain/reviews") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const traceIdFilter = url.searchParams.get("trace_id") ?? undefined;
    const reviews = meta.listExecutionReviews(traceIdFilter);
    return sendJson(res, 200, { reviews, total: reviews.length });
  }

  if (url.pathname === "/chain/distributions") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const traceId = url.searchParams.get("trace_id") ?? undefined;
    return sendJson(res, 200, { success: true, data: meta.listDistributions(traceId) });
  }

  if (url.pathname === "/chain/performance") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const workflowId = url.searchParams.get("workflow_id") ?? undefined;
    return sendJson(res, 200, { success: true, data: meta.listPerformance(workflowId) });
  }

  if (url.pathname === "/chain/market-intel") {
    if (req.method === "GET") {
      const symbol = url.searchParams.get("symbol") ?? undefined;
      return sendJson(res, 200, { success: true, data: meta.listMarketIntel(symbol) });
    }
    if (req.method === "POST") {
      const body = await readJson<MarketIntel>(req);
      meta.addMarketIntel(body);
      return sendJson(res, 201, { success: true });
    }
    return methodNotAllowed(res);
  }

  if (url.pathname === "/market/route") {
    if (req.method !== "GET") return methodNotAllowed(res);
    return sendJson(res, 200, { success: true, data: meta.listRouteDecisions(50) });
  }

  if (url.pathname === "/board/approval/summary") {
    if (req.method !== "GET") return methodNotAllowed(res);
    return sendJson(res, 200, { success: true, data: meta.getApprovalSummary() });
  }

  // ============================================
  // Phase 2: Board Dashboard APIs
  // ============================================

  // GET /board/proposals - List all proposals
  if (url.pathname === "/board/proposals") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const status = url.searchParams.get("status") ?? undefined;
    const limit = parseInt(url.searchParams.get("limit") ?? "50");
    const proposals = meta.listBoardProposals(status, limit);
    return sendJson(res, 200, { success: true, data: proposals, total: proposals.length });
  }

  // GET /board/proposals/:id - Get proposal detail with gates
  if (url.pathname.startsWith("/board/proposals/")) {
    if (req.method !== "GET") return methodNotAllowed(res);
    const proposalId = url.pathname.split("/board/proposals/")[1];
    const proposal = meta.getBoardProposal(proposalId);
    if (!proposal) return sendJson(res, 404, { success: false, error: "proposal_not_found" });
    const gates = meta.getProposalGates(proposalId);
    return sendJson(res, 200, { success: true, data: { ...proposal, gates } });
  }

  // GET /board/audit - List audit records
  if (url.pathname === "/board/audit") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const traceId = url.searchParams.get("trace_id") ?? undefined;
    const limit = parseInt(url.searchParams.get("limit") ?? "50");
    const records = meta.listAuditRecords(traceId, limit);
    return sendJson(res, 200, { success: true, data: records, total: records.length });
  }

  // GET /board/metrics - Board dashboard metrics
  if (url.pathname === "/board/metrics") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const metrics = meta.getBoardMetrics();
    return sendJson(res, 200, { success: true, data: metrics });
  }

  // GET /board/decisions - Recent routing decisions
  if (url.pathname === "/board/decisions") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const limit = parseInt(url.searchParams.get("limit") ?? "50");
    const decisions = meta.listRouteDecisions(limit);
    return sendJson(res, 200, { success: true, data: decisions, total: decisions.length });
  }

  // ============================================
  // Phase 2: Ops Queue Monitoring APIs
  // ============================================

  // GET /ops/queues - Queue statistics overview
  if (url.pathname === "/ops/queues") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const stats = work.getQueueStats();
    return sendJson(res, 200, { success: true, data: stats });
  }

  // GET /ops/queues/items - List all queue items
  if (url.pathname === "/ops/queues/items") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const status = url.searchParams.get("status") ?? undefined;
    const department = url.searchParams.get("department") ?? undefined;
    const limit = parseInt(url.searchParams.get("limit") ?? "50");
    let items = work.listQueueItems();
    if (status) items = items.filter(i => i.status === status);
    if (department) items = items.filter(i => i.department === department);
    items = items.slice(0, limit);
    return sendJson(res, 200, { success: true, data: items, total: items.length });
  }

  // GET /ops/queues/tasks/:taskId - Get task detail
  if (url.pathname.startsWith("/ops/queues/tasks/")) {
    if (req.method !== "GET") return methodNotAllowed(res);
    const taskId = url.pathname.split("/ops/queues/tasks/")[1];
    const task = work.getTask(taskId);
    if (!task) return sendJson(res, 404, { success: false, error: "task_not_found" });
    return sendJson(res, 200, { success: true, data: task });
  }

  // ============================================
  // Phase 2: L1/L2/L3 Decision Level APIs
  // ============================================

  // GET /ops/decision-levels - List all decision levels with config
  if (url.pathname === "/ops/decision-levels") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const levels = [
      router.getDecisionLevelConfig("L1"),
      router.getDecisionLevelConfig("L2"),
      router.getDecisionLevelConfig("L3"),
    ];
    return sendJson(res, 200, { success: true, data: levels });
  }

  // POST /ops/classify - Classify intent to decision level
  if (url.pathname === "/ops/classify") {
    if (req.method !== "POST") return methodNotAllowed(res);
    const intent = await readJson<Intent>(req);
    const level = router.classifyDecisionLevel(intent);
    const config = router.getDecisionLevelConfig(level);
    return sendJson(res, 200, { 
      success: true, 
      data: { 
        level,
        label: config.label,
        description: config.description,
        requires_board_approval: config.requires_board_approval,
      } 
    });
  }

  // GET /ops/decision-level-stats - Decision level statistics
  if (url.pathname === "/ops/decision-level-stats") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const decisions = meta.listRouteDecisions(500);
    const stats: Record<string, number> = { L1: 0, L2: 0, L3: 0, unknown: 0 };
    for (const d of decisions) {
      const level = (d.decision_level as string) ?? "unknown";
      stats[level] = (stats[level] ?? 0) + 1;
    }
    return sendJson(res, 200, { success: true, data: stats });
  }

  // ============================================
  // Phase 2: Distribution APIs
  // ============================================

  // /distribution - List (GET) or Create (POST)
  if (url.pathname === "/distribution") {
    if (req.method === "GET") {
      const traceId = url.searchParams.get("trace_id") ?? undefined;
      const distributions = meta.listDistributions(traceId);
      return sendJson(res, 200, { success: true, data: distributions, total: distributions.length });
    }
    if (req.method === "POST") {
      const body = await readJson<{ trace_id?: string; artifact_id?: string; channel?: string; recipient?: string }>(req);
      const d = {
        distribution_id: `dist_${crypto.randomUUID()}`,
        trace_id: body.trace_id ?? "",
        artifact_id: body.artifact_id ?? "",
        channel: (body.channel ?? "internal") as DistributionChannel,
        recipient: body.recipient ?? "",
        status: "pending" as DistributionStatus,
        policy_version: "v0",
        created_at: new Date().toISOString(),
      };
      meta.addDistribution(d);
      return sendJson(res, 201, { success: true, data: d });
    }
    return methodNotAllowed(res);
  }

  // GET /distribution/:id - Get distribution detail
  if (url.pathname.startsWith("/distribution/")) {
    if (req.method !== "GET") return methodNotAllowed(res);
    const distributions = meta.listDistributions();
    const distId = url.pathname.split("/distribution/")[1];
    const dist = distributions.find(d => d.distribution_id === distId);
    if (!dist) return sendJson(res, 404, { success: false, error: "distribution_not_found" });
    return sendJson(res, 200, { success: true, data: dist });
  }

  // ============================================
  // Phase 1: 研究中台 API (/api/artifacts)
  // ============================================
  if (url.pathname === "/api/artifacts" || url.pathname.startsWith("/api/artifacts/")) {
    if (req.method === "GET") {
      // 产物列表
      const category = url.searchParams.get("category") ?? undefined;
      const department = url.searchParams.get("department") ?? undefined;
      const limit = parseInt(url.searchParams.get("limit") ?? "50");
      const offset = parseInt(url.searchParams.get("offset") ?? "0");

      let artifacts = store.getArtifactsIndex();

      // 过滤
      if (category) {
        artifacts = artifacts.filter(a => a.id.startsWith(`${category}/`));
      }
      if (department) {
        artifacts = artifacts.filter(a => a.department === department);
      }

      const total = artifacts.length;
      const items = artifacts.slice(offset, offset + limit);

      return sendJson(res, 200, {
        items,
        total,
        limit,
        offset,
        has_more: offset + limit < total
      });
    }

    // 产物详情
    if (url.pathname.startsWith("/api/artifacts/")) {
      if (req.method === "GET") {
        const artifactId = url.pathname.split("/api/artifacts/")[1];
        const artifact = store.getArtifact(artifactId);

        if (!artifact) {
          return sendJson(res, 404, { error: "artifact_not_found", artifact_id: artifactId });
        }

        return sendJson(res, 200, artifact);
      }
    }

    return methodNotAllowed(res);
  }

  // ============================================
  // Trading Bridge: Hub → 6-TRADING 实时连通
  // ============================================

  // GET /api/trading/health — 6-TRADING bridge 健康检查
  if (url.pathname === "/api/trading/health") {
    if (req.method !== "GET") return methodNotAllowed(res);
    const health = await checkBridgeHealth();
    return sendJson(res, 200, { success: true, data: health });
  }

  // POST /api/trading/mailbox-scan — 接收 mailbox_scanner 实时推送
  if (url.pathname === "/api/trading/mailbox-scan") {
    if (req.method !== "POST") return methodNotAllowed(res);
    const body = await readJson<Record<string, unknown>>(req);
    const scanId = `scan_${crypto.randomUUID()}`;

    // 存储到 MetaStore 作为市场情报
    if (body.screen1 || body.signals) {
      const screen1 = body.screen1 as Record<string, unknown> | undefined;
      meta.addMarketIntel({
        intel_id: scanId,
        trace_id: "",
        department: "trading",
        symbol: (screen1?.inst_id as string) ?? "",
        direction: ((screen1?.direction as string)?.toLowerCase() as "long" | "short" | "neutral") ?? "neutral",
        confidence: Number(screen1?.confidence ?? 0),
        regime: "",
        source: "mailbox_scanner",
        summary: JSON.stringify(body),
        created_at: new Date().toISOString(),
      });
    }

    // 发布事件，订阅者可实时接收
    events.publish("trading:mailbox", {
      type: "trading.mailbox_scan",
      payload: { scan_id: scanId, ...body },
      ts: Date.now(),
    });

    return sendJson(res, 201, {
      success: true,
      scan_id: scanId,
      message: "Trading scan received and stored",
    });
  }

  // /api/trading/* — 代理到 6-TRADING Flask 服务
  if (url.pathname.startsWith("/api/trading/")) {
    const tradingPath = url.pathname.replace("/api/trading", "");
    const queryString = url.search;
    const fullPath = `/api${tradingPath}${queryString}`;

    if (req.method === "GET") {
      try {
        const result = await proxyToTrading(fullPath, "GET");
        return sendJson(res, result.status, result.data);
      } catch (err: unknown) {
        return sendJson(res, 502, {
          success: false,
          error: "trading_bridge_unreachable",
          detail: err instanceof Error ? err.message : String(err),
        });
      }
    }

    if (req.method === "POST") {
      try {
        const body = await readJson<Record<string, unknown>>(req);
        const result = await proxyToTrading(fullPath, "POST", body);
        return sendJson(res, result.status, result.data);
      } catch (err: unknown) {
        return sendJson(res, 502, {
          success: false,
          error: "trading_bridge_unreachable",
          detail: err instanceof Error ? err.message : String(err),
        });
      }
    }

    return methodNotAllowed(res);
  }

    return notFound(res);
  });

  server.on("close", stopPollingResults);
  return server;
}
