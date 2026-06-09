/**
 * Trading Bridge — Hub → 6-TRADING 代理层
 *
 * 将 Hub 的 /api/trading/* 请求转发到 6-TRADING Flask 服务 (默认 127.0.0.1:3847)
 * 使用 Node.js 原生 http/https 模块，零依赖
 *
 * 功能:
 * - 代理 GET/POST 请求到 6-TRADING bridge
 * - 健康检查: GET /api/trading/health
 * - 行情数据: GET /api/trading/market/*
 * - 交易执行: POST /api/trading/trade/*
 * - SKILL 路由: GET/POST /api/trading/skill/*
 * - 意图路由: POST /api/trading/intent/*
 * - 桥接状态: GET /api/trading/bridge/status
 */

import http from "node:http";
import https from "node:https";

const BRIDGE_URL = process.env.TRADING_BRIDGE_URL ?? "http://127.0.0.1:3847";

export interface TradingBridgeConfig {
  bridgeUrl: string;
  timeoutMs: number;
}

const DEFAULT_CONFIG: TradingBridgeConfig = {
  bridgeUrl: BRIDGE_URL,
  timeoutMs: 15000,
};

/**
 * 转发请求到 6-TRADING Flask 服务
 */
export async function proxyToTrading(
  path: string,
  method: string = "GET",
  body?: unknown,
  config: TradingBridgeConfig = DEFAULT_CONFIG
): Promise<{ status: number; data: unknown }> {
  const url = new URL(path, config.bridgeUrl);

  return new Promise((resolve, reject) => {
    const transport = url.protocol === "https:" ? https : http;
    const options: http.RequestOptions = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method,
      headers: {
        "Content-Type": "application/json",
      },
      timeout: config.timeoutMs,
    };

    const req = transport.request(options, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf-8");
        let data: unknown;
        try {
          data = JSON.parse(raw);
        } catch {
          data = { raw };
        }
        resolve({ status: res.statusCode ?? 500, data });
      });
    });

    req.on("error", (err) => reject(err));
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Trading bridge timeout"));
    });

    if (body && method === "POST") {
      req.write(JSON.stringify(body));
    }
    req.end();
  });
}

/**
 * 检查 6-TRADING bridge 是否在线
 */
export async function checkBridgeHealth(
  config: TradingBridgeConfig = DEFAULT_CONFIG
): Promise<{ online: boolean; latencyMs: number; error?: string }> {
  const start = Date.now();
  try {
    const result = await proxyToTrading("/api/health", "GET", undefined, config);
    return {
      online: result.status === 200,
      latencyMs: Date.now() - start,
    };
  } catch (err: unknown) {
    return {
      online: false,
      latencyMs: Date.now() - start,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
