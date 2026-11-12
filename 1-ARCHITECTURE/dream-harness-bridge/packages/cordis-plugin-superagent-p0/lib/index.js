/**
 * DreamBuddy Super-agent P0 Cordis plugin
 *
 * 桥接 python-server/server.py (IPC stdio) 的 P0 方法(进程内 superagent_p0.py),
 * 注册 system-prompt/assemble prepend 向 DSH 注入 L1 事件网关,
 * 并向 Worker 暴露 event_gateway / ticket_router / ticket_bridge / ticket_state 四个工具。
 *
 * 硬约束 (DESIGN-DSH-ARCH-UPGRADE v0.2):
 *   HC-1 FAIL-OPEN: IPC 异常 → degraded,不 crash Worker
 *   HC-2 总闸门 enable_dsh_upgrade=false 时静默不注册 (bridge 端也会降级)
 *   H6   只在 superagent profile 启用,web profile 通过 cordis.patch.yml 不加载本插件
 *   ADR-8 独立 profile
 *
 * 协议: 与 cordis-plugin-intent-gateway 同构
 */

import { resolve, dirname } from "node:path";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-superagent-p0";
const inject = ["tools"];  // 依赖 tools 服务 (ADR-1 Worker 工具面注册)

const Config = z.object({
  pythonBridgePath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
  enabled: z.boolean().default(false),           // HC-2 默认关
  enableUpgrade: z.boolean().default(false),     // 总闸门
  tools: z.boolean().default(true),              // 是否向 Worker 注册工具
  hookAssemble: z.boolean().default(true),        // 是否注入 system-prompt/assemble
  role: z.string().default("superagent-p0"),      // 诊断标签
  // ── P0-D2 常驻 Router 循环(默认全关,首版 shadow) ──
  enableRouterLoop: z.boolean().default(false),   // HC-2 默认关
  routerLoopIntervalMs: z.number().default(5000),
  routerLoopStartDelayMs: z.number().default(2000), // 避免启动风暴
  routerLoopShadow: z.boolean().default(true),    // true=只算不写
  routerLoopWorkers: z.any().default({}),         // {role: [worker_id]}
  routerLoopMaxConsecutiveFailures: z.number().default(3),
  // D2 花名册配套: plan 来源(MVP 由调度方写文件,循环每轮读取;空=只对账/唤醒)
  routerLoopPlanPath: z.string().default(""),
});

// Worker 工具面 (ADR-1): 每个工具 = 一次 bridge IPC 调用
// parameters 用 DSH 支持的 JSON Schema 子集 (type/properties/required/additionalProperties/items/enum/const)
const TOOL_DEFS = [
  {
    name: "dreamos_event_gateway_route",
    method: "event_gateway_route",
    description:
      "DreamOS L1 事件网关三分流: 把触发事件按意图路由为 noise / notify / upgrade。用于判断一条外部事件是否值得唤醒 Super-agent。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        trigger: {
          type: "object",
          additionalProperties: true,
          description: "触发事件,如 {source, type, payload}",
        },
        intents: {
          type: "array",
          items: { type: "object", additionalProperties: true },
          description: "候选意图列表;省略则用内置 event_intents 配置",
        },
        shadow: {
          type: "boolean",
          description: "true=只诊断不生效(默认 true)",
        },
      },
      required: ["trigger"],
    },
  },
  {
    name: "ticket_router_dispatch",
    method: "ticket_router_dispatch",
    description:
      "DreamOS 无状态单轮 Router 分派: 根据 plan 与可用 Worker 角色表,返回本轮的 ticket → worker 分配结果。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        plan: {
          type: "object",
          additionalProperties: true,
          description: "执行计划(含 tickets / steps)",
        },
        workers: {
          type: "object",
          additionalProperties: true,
          description: "角色 → worker_id 列表,如 {role: [id,...]}",
        },
        completed_refs: {
          type: "array",
          items: { type: "string" },
          description: "已完成 ticket id 列表",
        },
      },
      required: ["plan"],
    },
  },
  {
    name: "ticket_bridge_translate",
    method: "ticket_bridge_translate",
    description:
      "OKR → Ticket 草案翻译: 把 OKR 节点树转换为可执行的 Ticket 草案列表(受 enable_superagent_bridge 等 flags 控制)。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        okr_nodes: {
          type: "object",
          additionalProperties: true,
          description: "OKR 节点树",
        },
        flags: {
          type: "object",
          additionalProperties: true,
          description: "特性开关,如 {enable_superagent_bridge: true}",
        },
      },
      required: ["okr_nodes"],
    },
  },
  {
    name: "ticket_state_transition",
    method: "ticket_state_transition",
    description:
      "DreamOS Ticket 四态状态机迁移校验: live / paused / waitsForPerson / ended。返回迁移后的 ticket 或合法性判定。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        ticket: {
          type: "object",
          additionalProperties: true,
          description: "ticket 记录(含 ticket_id/state)",
        },
        new_state: {
          type: "string",
          description: "目标状态: live | paused | waitsForPerson | ended",
        },
        current: {
          type: "string",
          description: "简写形式: 当前状态(无 ticket 记录时)",
        },
        action: {
          type: "string",
          description: "简写形式: 目标状态(无 ticket 记录时)",
        },
      },
    },
  },
  {
    name: "dreamos_router_loop_stats",
    method: "router_loop_stats",
    description:
      "读取 DreamOS 常驻 Router 循环的最近 pass 摘要与计数(只读诊断,不触发 pass)。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {},
    },
  },
];

function apply(ctx, config = {}) {
  if (!config.enabled) {
    // HC-2 默认关 — 静默不注册,web profile 不会加载到本插件
    return;
  }

  // D3: P0 方法已并入 python-server/server.py 单进程,默认不再 spawn 独立 bridge
  const serverPath =
    config.pythonBridgePath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";
  const enableUpgrade = !!config.enableUpgrade;

  const ipc = getSharedIPC({
    serverPath,
    executable,
    env: { DSH_ENABLE_UPGRADE: enableUpgrade ? "true" : "false" },
  });

  let startPromise = null;
  async function ensureStarted() {
    if (!startPromise) startPromise = ipc.start();
    return startPromise;
  }

  // ── system-prompt/assemble prepend hook ───────────────────────────
  // waterfall 签名 (assembly, context, next):必须 await next() 并返回组装结果,
  // 否则返回 undefined 会导致上游 `transformed.contexts` 崩溃。
  if (config.hookAssemble) {
    try {
      ctx.on("system-prompt/assemble", async (assembly, _context, next) => {
        try {
          const assembled = await next();
          const sections = Array.isArray(assembled?.sections)
            ? assembled.sections
            : [];
          return {
            ...assembled,
            sections: [
              {
                name: "dreambuddy-superagent-p0",
                text: `[SuperAgent P0] enable_dsh_upgrade=${enableUpgrade} router_loop=${!!config.enableRouterLoop && `shadow=${!!config.routerLoopShadow}`}. Tools: dreamos_event_gateway_route / ticket_router_dispatch / ticket_bridge_translate / ticket_state_transition / dreamos_router_loop_stats`,
              },
              ...sections,
            ],
          };
        } catch (e) {
          // FAIL-OPEN: 不阻断 system prompt 组装
          console.warn(`[SuperAgentP0] assemble hook FAIL-OPEN: ${e.message}`);
          return assembly;
        }
      });
    } catch (e) {
      console.warn(`[SuperAgentP0] assemble hook not available: ${e.message}`);
    }
  }

  // ── 注册 4 个工具到 Worker ────────────────────────────────────────
  // DSH v0.1.5 契约: ctx.tools.register({ name, description, parameters(JSON Schema),
  // output: { schema(JSON Schema), render(args, value) }, execute(args, exec) })
  if (config.tools) {
    for (const def of TOOL_DEFS) {
      try {
        ctx.tools.register({
          name: def.name,
          description: def.description,
          parameters: def.parameters,
          output: {
            schema: { type: "object", additionalProperties: true },
            render: (_args, value) => [
              { type: "text", text: JSON.stringify(value ?? null) },
            ],
          },
          async execute(args) {
            try {
              await ensureStarted();
              const resp = await ipc.callMethod(def.method, args || {});
              // server.py 响应包: { schema_version, message_type, ok, result|error }
              if (resp?.ok) {
                return resp.result ?? { ok: true };
              }
              return {
                ok: false,
                degraded: true,
                reason: resp?.error?.message || "ipc_response_not_ok",
              };
            } catch (e) {
              // HC-1 FAIL-OPEN: IPC 异常降级返回,不击穿 Worker
              return {
                ok: false,
                degraded: true,
                reason: `ipc_error: ${e.message}`,
              };
            }
          },
        });
        console.log(`[SuperAgentP0] tool registered: ${def.name} → ${def.method}`);
      } catch (e) {
        console.warn(
          `[SuperAgentP0] register ${def.name} failed (FAIL-OPEN): ${e.message}`
        );
      }
    }
  }

  // ── P0-D2 常驻 Router 循环(§3.4 单飞/熔断 + §4.3 配置) ────────────
  // 节拍器放在 JS:可 profile 级开关 + ctx.effect 确定性清理;Python 侧保持无状态。
  // HC-2: enableRouterLoop 默认 false;首版默认 shadow 只算不写。
  if (config.enableRouterLoop) {
    const intervalMs = Math.max(500, Number(config.routerLoopIntervalMs) || 5000);
    const startDelayMs = Math.max(0, Number(config.routerLoopStartDelayMs) || 2000);
    const maxFailures = Math.max(
      1,
      Number(config.routerLoopMaxConsecutiveFailures) || 3
    );
    const loopStats = {
      ticks: 0,
      passes: 0,
      skippedOverlap: 0,
      failures: 0,
      consecutiveFailures: 0,
      circuitOpen: false,
      last: null,
    };
    let inFlight = false;
    let circuitUntil = 0;
    let lastErrorLogAt = 0;
    let loopTimer = null;

    // 同类失败日志 60s 限频,避免 tick 级日志风暴
    const logRateLimited = (msg) => {
      const now = Date.now();
      if (now - lastErrorLogAt < 60000) return;
      lastErrorLogAt = now;
      console.warn(`[SuperAgentP0] router loop: ${msg}`);
    };

    // D2: plan 由调度方写文件注入(MVP);读不到/坏 JSON → null(本轮只对账/唤醒)
    const planPath = config.routerLoopPlanPath || "";
    async function readPlan() {
      if (!planPath) return null;
      try {
        const doc = JSON.parse(await readFile(planPath, "utf8"));
        return doc && typeof doc === "object" ? doc : null;
      } catch (e) {
        logRateLimited(`plan read failed (${planPath}): ${e.message}`);
        return null;
      }
    }

    async function routerTick() {
      // 单飞: 上一轮未完成则跳过,不排队(ADR-1: 下一轮用最新快照重算)
      if (inFlight) {
        loopStats.skippedOverlap += 1;
        return;
      }
      if (Date.now() < circuitUntil) return;
      inFlight = true;
      loopStats.ticks += 1;
      try {
        await ensureStarted();
        const resp = await ipc.callMethod("router_pass", {
          roster: config.routerLoopWorkers || {},
          plan: await readPlan(),
          shadow: !!config.routerLoopShadow,
        });
        // server 响应 = { result: { ok, result: summary } }(与既有 P0 方法同构)
        const summary = resp?.result?.result ?? resp?.result ?? null;
        if (!resp?.ok || !summary) {
          throw new Error(resp?.error?.message || "router_pass_not_ok");
        }
        loopStats.passes += 1;
        loopStats.last = {
          pass_id: summary.pass_id,
          degraded: !!summary.degraded,
          shadow: !!summary.shadow,
          assigned: (summary.assignments || []).length,
          committed: summary.committed || 0,
          skipped: (summary.skipped || []).length,
          unassigned: (summary.unassigned || []).length,
          deferred: (summary.deferred || []).length,
          duration_ms: summary.duration_ms,
        };
        if (summary.degraded) {
          loopStats.failures += 1;
          loopStats.consecutiveFailures += 1;
          logRateLimited(`degraded=${summary.reason || summary.error}`);
        } else {
          loopStats.consecutiveFailures = 0;
        }
      } catch (e) {
        loopStats.failures += 1;
        loopStats.consecutiveFailures += 1;
        logRateLimited(`tick failed: ${e.message}`);
      } finally {
        inFlight = false;
        if (loopStats.consecutiveFailures >= maxFailures) {
          // 熔断: 跳过接下来 3 个 interval,一次成功后重新计数
          loopStats.circuitOpen = true;
          circuitUntil = Date.now() + intervalMs * 3;
          loopStats.consecutiveFailures = 0;
          logRateLimited("circuit open");
        }
      }
    }

    if (typeof ctx.effect === "function") {
      ctx.effect(() => {
        const startTimer = setTimeout(() => {
          loopTimer = setInterval(routerTick, intervalMs);
          loopTimer.unref?.();
        }, startDelayMs);
        startTimer.unref?.();
        return () => {
          clearTimeout(startTimer);
          if (loopTimer) {
            clearInterval(loopTimer);
            loopTimer = null;
          }
        };
      });
      console.log(
        `[SuperAgentP0] router loop enabled interval=${intervalMs}ms shadow=${!!config.routerLoopShadow}`
      );
    } else {
      // FAIL-OPEN: 无 effect 则不启动循环,避免无法回收的常驻定时器
      console.warn("[SuperAgentP0] ctx.effect 不可用, router loop 未启动");
    }
  }

  // ── dispose ──────────────────────────────────────────────────────
  // 共享 IPC 进程由 shared-ipc.mjs 在 Node 退出时统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
