/**
 * DreamBuddy Wiki 编译层 Cordis plugin — Karpathy LLM Wiki 模式
 *
 * 暴露三个工具：
 *   - wiki_ingest: 将素材编译为结构化 Wiki 页面
 *   - wiki_query:  基于已编译 Wiki 页面进行知识检索
 *   - wiki_lint:   巡检 Wiki 质量（孤立/过时/断链）
 *
 * 通过 IPC 调用 Python server 的 wiki_ingest/wiki_query/wiki_lint 方法。
 * Python server 内部调用 2-KNOWLEDGE/9-RAG-INFRA/evolution/wiki_compiler.py。
 */

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-knowledge-wiki";
const inject = ["tools"];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
});

const CURRENT_SCHEMA_VERSION = "1.0.0";

function apply(ctx, config) {
  const serverPath =
    config.pythonServerPath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";

  const ipcClient = getSharedIPC({ serverPath, executable });

  let startPromise = null;

  async function ensureStarted() {
    if (!startPromise) {
      startPromise = ipcClient.start();
    }
    return startPromise;
  }

  // ---- 工具 1: wiki_ingest ----
  ctx.tools.register(
    defineTool({
      name: "wiki_ingest",
      description:
        "将素材（文本或URL）编译为结构化 Wiki 页面，提取核心结论、实体、概念。" +
        "编译产物自动同步到知识库、RAG 索引和认知记忆系统。",
      parameters: {
        source: {
          type: "string",
          required: true,
          description: "素材内容（文本）或 URL",
        },
        source_type: {
          type: "string",
          description: "素材类型：text | url | auto（默认 auto）",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: {
            status: { type: "string" },
            source_page: { type: "string" },
            entity_count: { type: "number" },
            concept_count: { type: "number" },
            core_conclusion: { type: "string" },
          },
        },
        render: (_args, value) => [
          { type: "text", text: JSON.stringify(value, null, 2) },
        ],
      },
      async execute(args) {
        await ensureStarted();
        const response = await ipcClient.callMethod("wiki_ingest", {
          source: args.source,
          source_type: args.source_type || "auto",
          two_pass: args.two_pass || false,
        }, 90000);  // ingest 长任务用 90s 超时（P1-4）
        if (!response.ok) {
          throw new Error(
            `wiki_ingest 失败: ${JSON.stringify(response.error || response.result)}`
          );
        }
        return response.result;
      },
      presentCall: (args) => ({
        card: "generic",
        title: "Wiki 编译",
        kind: "execute",
        rawInput: args.source.slice(0, 80),
        content: [{ type: "text", text: "编译素材到 Wiki 知识库" }],
      }),
      presentResult: (_args, result) => ({
        card: "generic",
        content: [
          {
            type: "text",
            text:
              `状态: ${result.status} | 实体: ${result.entity_count} | 概念: ${result.concept_count} | ` +
              `页面: ${result.pages?.length || 0} | 耗时: ${result.duration_ms?.toFixed(0)}ms | ` +
              `Token~: ${result.token_estimate}`,
          },
        ],
      }),
    })
  );

  // ---- 工具 1b: wiki_ingest_batch ----
  ctx.tools.register(
    defineTool({
      name: "wiki_ingest_batch",
      description:
        "批量编译多个素材为结构化 Wiki 页面。顺序处理，单个失败不影响其他。",
      parameters: {
        sources: {
          type: "array",
          required: true,
          description: "素材列表（文本或 URL）",
          items: { type: "string" },
        },
        source_type: {
          type: "string",
          description: "素材类型：text | url | auto（默认 auto）",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: {
            status: { type: "string" },
            total: { type: "number" },
            success: { type: "number" },
            failed: { type: "number" },
            results: { type: "array" },
          },
        },
        render: (_args, value) => [
          { type: "text", text: JSON.stringify(value, null, 2) },
        ],
      },
      async execute(args) {
        await ensureStarted();
        // 批量按素材数动态超时：每个素材 90s
        const timeout = Math.min(90000 * (args.sources?.length || 1), 600000);
        const response = await ipcClient.callMethod("wiki_ingest_batch", {
          sources: args.sources,
          source_type: args.source_type || "auto",
        }, timeout);
        if (!response.ok) {
          throw new Error(
            `wiki_ingest_batch 失败: ${JSON.stringify(response.error || response.result)}`
          );
        }
        return response.result;
      },
      presentCall: (args) => ({
        card: "generic",
        title: "Wiki 批量编译",
        kind: "execute",
        rawInput: `${args.sources?.length || 0} 个素材`,
        content: [{ type: "text", text: `批量编译 ${args.sources?.length || 0} 个素材` }],
      }),
      presentResult: (_args, result) => ({
        card: "generic",
        content: [
          {
            type: "text",
            text: `总数: ${result.total} | 成功: ${result.success} | 失败: ${result.failed}`,
          },
        ],
      }),
    })
  );

  // ---- 工具 2: wiki_query ----
  ctx.tools.register(
    defineTool({
      name: "wiki_query",
      description:
        "基于已编译 Wiki 页面进行知识检索（语义+关键词混合检索）。" +
        "高价值查询结果会自动回写为 syntheses 综合分析页，实现知识复利。",
      parameters: {
        question: {
          type: "string",
          required: true,
          description: "查询问题",
        },
        top_k: {
          type: "number",
          description: "返回结果数（默认 5）",
        },
        enable_write_back: {
          type: "boolean",
          description: "是否启用高价值结果回写为 syntheses（默认 true）",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: {
            status: { type: "string" },
            total: { type: "number" },
            results: { type: "array", items: { type: "object", additionalProperties: true } },
            write_back_performed: { type: "boolean" },
            synthesis_page: { type: "string" },
            value_score: { type: "number" },
          },
        },
        render: (_args, value) => [
          { type: "text", text: JSON.stringify(value, null, 2) },
        ],
      },
      async execute(args) {
        await ensureStarted();
        const response = await ipcClient.callMethod("wiki_query", {
          question: args.question,
          top_k: args.top_k || 5,
          enable_write_back: args.enable_write_back !== false,
        });
        if (!response.ok) {
          throw new Error(
            `wiki_query 失败: ${JSON.stringify(response.error || response.result)}`
          );
        }
        return response.result;
      },
      presentCall: (args) => ({
        card: "generic",
        title: "Wiki 检索",
        kind: "execute",
        rawInput: args.question,
        content: [{ type: "text", text: `检索 Wiki: ${args.question}` }],
      }),
      presentResult: (_args, result) => ({
        card: "generic",
        content: [
          {
            type: "text",
            text: `命中 ${result.total} 条结果` +
              (result.write_back_performed
                ? ` | 已回写 syntheses: ${result.synthesis_page} (价值=${result.value_score?.toFixed(2)})`
                : result.value_score > 0
                  ? ` | 未回写 (价值=${result.value_score?.toFixed(2)}<0.6)`
                  : ""),
          },
          ...(result.results || []).slice(0, 3).map((r) => ({
            type: "text",
            text: `  • ${r.source_file} (score=${r.score.toFixed(3)})`,
          })),
        ],
      }),
    })
  );

  // ---- 工具 3: wiki_lint ----
  ctx.tools.register(
    defineTool({
      name: "wiki_lint",
      description:
        "巡检 Wiki 页面质量：检测孤立页面（无入站链接）、过时页面（>90天未更新）、断链（[[wikilink]] 指向不存在的页面）。",
      parameters: {
        check_type: {
          type: "string",
          description: "检查类型：all | orphans | stale | broken_links（默认 all）",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: {
            status: { type: "string" },
            total_pages: { type: "number" },
            orphan_count: { type: "number" },
            stale_count: { type: "number" },
            broken_link_count: { type: "number" },
          },
        },
        render: (_args, value) => [
          { type: "text", text: JSON.stringify(value, null, 2) },
        ],
      },
      async execute(args) {
        await ensureStarted();
        const response = await ipcClient.callMethod("wiki_lint", {
          check_type: args.check_type || "all",
        });
        if (!response.ok) {
          throw new Error(
            `wiki_lint 失败: ${JSON.stringify(response.error || response.result)}`
          );
        }
        return response.result;
      },
      presentCall: () => ({
        card: "generic",
        title: "Wiki 巡检",
        kind: "execute",
        content: [{ type: "text", text: "执行 Wiki 质量巡检" }],
      }),
      presentResult: (_args, result) => ({
        card: "generic",
        content: [
          {
            type: "text",
            text:
              `总页面: ${result.total_pages} | 健康分: ${result.health_score ?? "N/A"} | ` +
              `孤立: ${result.orphan_count} | 过时: ${result.stale_count} | ` +
              `断链: ${result.broken_link_count}`,
          },
        ],
      }),
    })
  );

  // 共享 IPC 进程由 shared-ipc.mjs 在 Node 退出时统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
