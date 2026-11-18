#!/usr/bin/env node
/**
 * Agent 工具调用基线评测（P0）。
 *
 * 复用线上同一套 prompt / 工具 / 温度（`chat-prompt.ts` + capability tools + MCP），
 * 直接对 golden set 跑 `generateText`，输出可复核的工具选择与参数指标。
 *
 * 用法（在 3.1-FRONTEND 下）：
 *   npx tsx scripts/agent-tool-eval.ts --dry-run
 *   npx tsx scripts/agent-tool-eval.ts --limit 10
 *   npx tsx scripts/agent-tool-eval.ts --concurrency 3 --no-mcp
 *
 * 说明：
 *  - 不经过 /api/agent/chat，避免 SPEC 确认与会话鉴权干扰；prompt 与工具同源；
 *  - 默认读取 `.env.local` / `.env`（不覆盖已存在的环境变量）；
 *  - 每题失败不影响其他题，summary 里会统计。
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import * as path from "path";
import { generateText, stepCountIs } from "ai";
import type { Tool } from "ai";
import { resolveAgentModel } from "../src/lib/agent/providers";
import { createCapabilityTools } from "../src/lib/agent/capability-tools";
import { getAgentMcpTools } from "../src/lib/agent/mcp-multi-shell";
import {
  filterToolsByProfile,
  resolveToolProfile,
  type ToolProfileSpec,
} from "../src/lib/agent/tool-profiles";
import {
  AGENT_MAX_STEPS,
  AGENT_TEMPERATURE,
  buildChatSystem,
} from "../src/lib/agent/chat-prompt";
import { inspectToolResult } from "../src/lib/agent/tool-telemetry";

const ROOT = path.resolve(__dirname, "..");
const GOLDEN = path.join(ROOT, "evals", "agent-tool", "golden-60.jsonl");
const OUT_ROOT = path.join(ROOT, "evals", "agent-tool", "out");

interface GoldenCase {
  id: string;
  category: string;
  surface?: "workbench" | "trading";
  query: string;
  expect: {
    tools?: string[];
    capability_ids?: string[];
    params?: Record<string, string>;
    match?: "all" | "any";
    no_tool?: boolean;
  };
  forbid?: string[];
  must_have?: string[];
  /** 输入不足时，先澄清再执行也算正确（不强制立即调用工具） */
  allow_clarify?: boolean;
  max_steps?: number;
}

interface CaseResult {
  id: string;
  category: string;
  query: string;
  ok: boolean;
  selection_ok: boolean;
  capability_ok: boolean;
  params_ok: boolean;
  forbidden_hit: boolean;
  must_have_ok: boolean;
  expected_tools: string[];
  actual_tools: string[];
  expected_capabilities: string[];
  actual_capabilities: string[];
  steps: number;
  tool_calls: number;
  tool_errors: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  final_text: string;
  error?: string;
}

function loadEnvFile(file: string): void {
  if (!existsSync(file)) return;
  for (const line of readFileSync(file, "utf-8").split("\n")) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match) continue;
    let value = match[2];
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[match[1]] === undefined) process.env[match[1]] = value;
  }
}

function parseArgs(argv: string[]) {
  const args = {
    limit: 0,
    concurrency: 2,
    noMcp: false,
    dryRun: false,
    outDir: "",
    model: "",
    provider: "",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--limit") args.limit = Number(argv[++i]) || 0;
    else if (arg === "--concurrency") args.concurrency = Math.max(1, Number(argv[++i]) || 1);
    else if (arg === "--no-mcp") args.noMcp = true;
    else if (arg === "--dry-run") args.dryRun = true;
    else if (arg === "--out") args.outDir = argv[++i] ?? "";
    else if (arg === "--model") args.model = argv[++i] ?? "";
    else if (arg === "--provider") args.provider = argv[++i] ?? "";
  }
  return args;
}

function readGolden(): GoldenCase[] {
  const text = readFileSync(GOLDEN, "utf-8");
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      try {
        return JSON.parse(line) as GoldenCase;
      } catch (error) {
        throw new Error(`golden-60.jsonl 第 ${index + 1} 行不是合法 JSON: ${String(error)}`);
      }
    });
}

function asString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function toolInput(call: unknown): Record<string, unknown> {
  const record = (call ?? {}) as Record<string, unknown>;
  const input = record.input ?? record.args;
  return input && typeof input === "object" ? (input as Record<string, unknown>) : {};
}

async function evaluateCase(
  testCase: GoldenCase,
  model: ReturnType<typeof resolveAgentModel>,
  tools: Record<string, Tool>,
  profile: ToolProfileSpec,
): Promise<CaseResult> {
  const startedAt = Date.now();
  const result = await generateText({
    model: model as NonNullable<typeof model>,
    system: buildChatSystem(profile),
    prompt: testCase.query,
    tools,
    temperature: AGENT_TEMPERATURE,
    stopWhen: stepCountIs(testCase.max_steps ?? AGENT_MAX_STEPS),
  });

  const calls = result.steps.flatMap((step) =>
    step.toolCalls.map((call) => ({
      name: call.toolName,
      input: toolInput(call),
    })),
  );
  const actualTools = [...new Set(calls.map((call) => call.name))];
  const actualCapabilities = [
    ...new Set(
      calls
        .filter((call) => call.name === "run_capability")
        .map((call) => asString(call.input.id))
        .filter(Boolean),
    ),
  ];
  const expected = testCase.expect ?? {};
  const expectedTools = expected.tools ?? [];
  const expectedCapabilities = expected.capability_ids ?? [];
  const match = expected.match ?? "all";

  const selectionOk = expected.no_tool
    ? calls.length === 0
    : match === "any"
      ? expectedTools.some((name) => actualTools.includes(name))
      : expectedTools.every((name) => actualTools.includes(name));

  const capabilityOk =
    expectedCapabilities.length === 0
      ? true
      : match === "any"
        ? expectedCapabilities.some((id) => actualCapabilities.includes(id))
        : expectedCapabilities.every((id) => actualCapabilities.includes(id));

  const params = expected.params ?? {};
  const paramsOk =
    Object.keys(params).length === 0 ||
    calls.some((call) => {
      if (call.name !== "run_capability") return false;
      const callParams =
        call.input.params && typeof call.input.params === "object"
          ? (call.input.params as Record<string, unknown>)
          : {};
      return Object.entries(params).every(
        ([key, value]) =>
          String(callParams[key] ?? "").toUpperCase() === String(value).toUpperCase(),
      );
    });

  const finalText = result.text ?? "";
  // 输入不足时，先澄清（不调用业务能力）是正确行为；只查目录不算执行
  const clarifyOk =
    testCase.allow_clarify === true &&
    !calls.some((call) => call.name === "run_capability") &&
    /(请补充|请提供|需要你|告诉我|请告诉我|确认|具体)/.test(finalText);
  const forbiddenHit = (testCase.forbid ?? []).some((pattern) =>
    new RegExp(pattern, "i").test(finalText),
  );
  const mustHaveOk = (testCase.must_have ?? []).every((text) =>
    finalText.includes(text),
  );
  const toolErrors = result.steps.reduce(
    (count, step) =>
      count +
      step.toolResults.filter(
        (item) =>
          !inspectToolResult((item as { output?: unknown }).output ?? item).ok,
      ).length,
    0,
  );

  return {
    id: testCase.id,
    category: testCase.category,
    query: testCase.query,
    ok:
      (selectionOk || clarifyOk) &&
      (capabilityOk || clarifyOk) &&
      (paramsOk || clarifyOk) &&
      !forbiddenHit &&
      mustHaveOk,
    selection_ok: selectionOk || clarifyOk,
    capability_ok: capabilityOk || clarifyOk,
    params_ok: paramsOk || clarifyOk,
    forbidden_hit: forbiddenHit,
    must_have_ok: mustHaveOk,
    expected_tools: expectedTools,
    actual_tools: actualTools,
    expected_capabilities: expectedCapabilities,
    actual_capabilities: actualCapabilities,
    steps: result.steps.length,
    tool_calls: calls.length,
    tool_errors: toolErrors,
    input_tokens: result.usage.inputTokens ?? 0,
    output_tokens: result.usage.outputTokens ?? 0,
    latency_ms: Date.now() - startedAt,
    final_text: finalText.slice(0, 600),
  };
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function buildSummary(results: CaseResult[]) {
  const total = results.length;
  const rate = (predicate: (item: CaseResult) => boolean) =>
    total === 0 ? 0 : results.filter(predicate).length / total;
  const byCategory = new Map<string, CaseResult[]>();
  for (const item of results) {
    const list = byCategory.get(item.category) ?? [];
    list.push(item);
    byCategory.set(item.category, list);
  }
  return {
    total,
    success_rate: rate((item) => item.ok),
    selection_rate: rate((item) => item.selection_ok),
    capability_rate: rate((item) => item.capability_ok),
    params_rate: rate((item) => item.params_ok),
    forbidden_rate: rate((item) => item.forbidden_hit),
    avg_steps: total ? results.reduce((sum, item) => sum + item.steps, 0) / total : 0,
    avg_tool_calls: total ? results.reduce((sum, item) => sum + item.tool_calls, 0) / total : 0,
    tool_error_rate:
      results.reduce((sum, item) => sum + item.tool_calls, 0) === 0
        ? 0
        : results.reduce((sum, item) => sum + item.tool_errors, 0) /
          results.reduce((sum, item) => sum + item.tool_calls, 0),
    avg_input_tokens: total ? results.reduce((sum, item) => sum + item.input_tokens, 0) / total : 0,
    avg_output_tokens: total ? results.reduce((sum, item) => sum + item.output_tokens, 0) / total : 0,
    p95_latency_ms: (() => {
      if (!total) return 0;
      const sorted = results.map((item) => item.latency_ms).sort((a, b) => a - b);
      return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)];
    })(),
    by_category: [...byCategory.entries()].map(([category, items]) => ({
      category,
      n: items.length,
      success_rate: items.filter((item) => item.ok).length / items.length,
    })),
  };
}

async function main() {
  loadEnvFile(path.join(ROOT, ".env.local"));
  loadEnvFile(path.join(ROOT, ".env"));

  const args = parseArgs(process.argv.slice(2));
  const cases = readGolden();
  const selected = args.limit > 0 ? cases.slice(0, args.limit) : cases;

  const provider = args.provider || undefined;
  const model = resolveAgentModel({
    provider,
    model: args.model || undefined,
    baseURL: process.env.AGENT_BASE_URL,
  });

  if (!model) {
    console.error("未配置模型：需要 AGENT_API_KEY / AGENT_BASE_URL（或 --model/--provider）。");
    process.exit(1);
  }

  const capabilityTools = createCapabilityTools();
  let mcpTools: Record<string, Tool> = {};
  if (!args.noMcp) {
    try {
      mcpTools = await getAgentMcpTools();
    } catch (error) {
      console.warn(`[eval] MCP 不可用，退化为仅能力工具: ${String(error)}`);
    }
  }
  const allTools: Record<string, Tool> = { ...capabilityTools, ...mcpTools };

  console.log(
    `[eval] cases=${selected.length}/${cases.length} model=${args.model || process.env.AGENT_MODEL} tools=${Object.keys(allTools).length} dry_run=${args.dryRun}`,
  );

  if (args.dryRun) {
    for (const item of selected) {
      const profile = resolveToolProfile({
        surface: item.surface ?? "workbench",
        entitled: false,
      });
      const tools: Record<string, Tool> = {
        ...capabilityTools,
        ...(filterToolsByProfile(mcpTools, profile) ?? {}),
      };
      console.log(
        `[dry-run] ${item.id} ${item.category} tools=${Object.keys(tools).length} query=${item.query}`,
      );
    }
    return;
  }

  const outDir =
    args.outDir ||
    path.join(
      OUT_ROOT,
      new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14),
    );
  mkdirSync(outDir, { recursive: true });

  const results: CaseResult[] = [];
  let cursor = 0;
  const worker = async () => {
    while (cursor < selected.length) {
      const index = cursor++;
      const item = selected[index];
      const profile = resolveToolProfile({
        surface: item.surface ?? "workbench",
        entitled: false,
      });
      const tools: Record<string, Tool> = {
        ...capabilityTools,
        ...(filterToolsByProfile(mcpTools, profile) ?? {}),
      };
      try {
        const result = await evaluateCase(item, model, tools, profile);
        results.push(result);
        console.log(
          `[${index + 1}/${selected.length}] ${result.id} ${result.ok ? "PASS" : "FAIL"} tools=${result.actual_tools.join(",") || "-"} caps=${result.actual_capabilities.join(",") || "-"}`,
        );
      } catch (error) {
        results.push({
          id: item.id,
          category: item.category,
          query: item.query,
          ok: false,
          selection_ok: false,
          capability_ok: false,
          params_ok: false,
          forbidden_hit: false,
          must_have_ok: false,
          expected_tools: item.expect?.tools ?? [],
          actual_tools: [],
          expected_capabilities: item.expect?.capability_ids ?? [],
          actual_capabilities: [],
          steps: 0,
          tool_calls: 0,
          tool_errors: 0,
          input_tokens: 0,
          output_tokens: 0,
          latency_ms: 0,
          final_text: "",
          error: error instanceof Error ? error.message : String(error),
        });
        console.warn(`[${index + 1}/${selected.length}] ${item.id} ERROR ${String(error)}`);
      }
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(args.concurrency, selected.length) }, () => worker()),
  );

  results.sort((a, b) => a.id.localeCompare(b.id));
  const summary = buildSummary(results);

  writeFileSync(
    path.join(outDir, "runs.jsonl"),
    `${results.map((item) => JSON.stringify(item)).join("\n")}\n`,
    "utf-8",
  );
  writeFileSync(
    path.join(outDir, "summary.json"),
    JSON.stringify({ generated_at: new Date().toISOString(), model: args.model || process.env.AGENT_MODEL, temperature: AGENT_TEMPERATURE, summary, results }, null, 2),
    "utf-8",
  );

  const lines = [
    `# Agent 工具调用基线 ${new Date().toISOString().slice(0, 10)}`,
    "",
    `- 样本：${summary.total} ｜ 模型：${args.model || process.env.AGENT_MODEL} ｜ 温度：${AGENT_TEMPERATURE}`,
    `- 任务成功率：${pct(summary.success_rate)} ｜ 工具选择：${pct(summary.selection_rate)} ｜ 能力命中：${pct(summary.capability_rate)} ｜ 参数正确：${pct(summary.params_rate)}`,
    `- 平均步数：${summary.avg_steps.toFixed(2)} ｜ 平均工具调用：${summary.avg_tool_calls.toFixed(2)} ｜ 工具失败率：${pct(summary.tool_error_rate)}`,
    `- p95 延迟：${summary.p95_latency_ms} ms ｜ 平均 token：${Math.round(summary.avg_input_tokens)} in / ${Math.round(summary.avg_output_tokens)} out`,
    "",
    "> 口径：成功率 = 工具选择 + 能力命中 + 参数 + 护栏；数据源自身失败单独计入「工具失败率」，不重复扣成功率。",
    "",
    "| 类别 | n | 成功率 |",
    "|---|---|---|",
    ...summary.by_category.map(
      (item) => `| ${item.category} | ${item.n} | ${pct(item.success_rate)} |`,
    ),
    "",
    "## 失败样本",
    "",
    ...results
      .filter((item) => !item.ok)
      .map(
        (item) =>
          `- ${item.id}（${item.category}）：期望 tools=${item.expected_tools.join(",") || "-"} caps=${item.expected_capabilities.join(",") || "-"}；实际 tools=${item.actual_tools.join(",") || "-"} caps=${item.actual_capabilities.join(",") || "-"}${item.error ? `；error=${item.error}` : ""}`,
      ),
  ];
  writeFileSync(path.join(outDir, "summary.md"), `${lines.join("\n")}\n`, "utf-8");

  console.log(`\n[eval] 输出目录：${outDir}`);
  console.log(
    `[eval] 成功率 ${pct(summary.success_rate)} ｜ 工具选择 ${pct(summary.selection_rate)} ｜ 能力命中 ${pct(summary.capability_rate)} ｜ 参数 ${pct(summary.params_rate)}`,
  );
}

main().catch((error) => {
  console.error(`[eval] 失败: ${error instanceof Error ? error.stack : String(error)}`);
  process.exit(1);
});
