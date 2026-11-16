import { describe, expect, it, vi } from "vitest";
import { createStatsTools, apply } from "../packages/cordis-plugin-stats/lib/index.js";

type Tool = {
  name: string;
  execute: (args?: Record<string, unknown>) => Promise<Record<string, unknown>>;
};

function tool(tools: Tool[], name: string): Tool {
  const found = tools.find((item) => item.name === name);
  if (!found) throw new Error(`missing tool: ${name}`);
  return found;
}

function fakeIPC(result: unknown = { ok: true }) {
  return vi.fn(async () => ({ ok: true, result }));
}

describe("dreambuddy-stats plugin (T1-1)", () => {
  it("注册 stats_list / stats_run / stats_validate / stats_explain 四个工具", () => {
    const tools = createStatsTools({ callMethod: fakeIPC() }) as Tool[];
    expect(tools.map((item) => item.name).sort()).toEqual([
      "stats_explain",
      "stats_list",
      "stats_run",
      "stats_validate",
    ]);
  });

  it("apply() 把四个工具挂到 ctx.tools", () => {
    const registered: Tool[] = [];
    const ctx = { tools: { register: (def: Tool) => registered.push(def) } };
    apply(ctx as never, { pythonServerPath: "/tmp/not-used-server.py" });
    expect(registered.map((item) => item.name).sort()).toEqual([
      "stats_explain",
      "stats_list",
      "stats_run",
      "stats_validate",
    ]);
  });

  it("stats_validate 透传 op=validate", async () => {
    const callMethod = fakeIPC({ ok: true, missing_params: [], unknown_params: [], warnings: [] });
    const tools = createStatsTools({ callMethod }) as Tool[];
    const out = await tool(tools, "stats_validate").execute({
      capability_id: "D-A06",
      payload: { values: [0.01] },
    });
    const [, params] = callMethod.mock.calls[0] as [string, Record<string, unknown>];
    expect(params).toMatchObject({ op: "validate", capability_id: "D-A06" });
    expect(out).toMatchObject({ ok: true });
  });

  it("stats_list 透传 op=list 与过滤参数", async () => {
    const callMethod = fakeIPC({ total: 1, returned: 1, manifest_version: 1, items: [] });
    const tools = createStatsTools({ callMethod }) as Tool[];
    const out = await tool(tools, "stats_list").execute({ domain: "E", q: "corr", limit: 500 });

    expect(callMethod).toHaveBeenCalledTimes(1);
    const [method, params] = callMethod.mock.calls[0] as [string, Record<string, unknown>];
    expect(method).toBe("stats_capability");
    expect(params).toMatchObject({ op: "list", domain: "E", q: "corr", limit: 200 });
    expect(out).toMatchObject({ total: 1, returned: 1 });
  });

  it("缺少 capability_id 由参数 schema 拦下（不进执行体）", async () => {
    const tools = createStatsTools({ callMethod: fakeIPC() }) as Tool[];
    await expect(tool(tools, "stats_run").execute({ payload: { days: 30 } })).rejects.toThrow(
      /capability_id/
    );
  });

  it("stats_run 透传 capability_id 与 payload", async () => {
    const callMethod = fakeIPC({ ok: true, capability_id: "D-A06", result: { status: "ok" } });
    const tools = createStatsTools({ callMethod }) as Tool[];
    const out = await tool(tools, "stats_run").execute({
      capability_id: "D-A06",
      payload: { values: [0.01, -0.02] },
    });

    const [, params] = callMethod.mock.calls[0] as [string, Record<string, unknown>];
    expect(params).toMatchObject({ op: "run", capability_id: "D-A06" });
    expect(params.payload).toEqual({ values: [0.01, -0.02] });
    expect(out).toMatchObject({ ok: true, capability_id: "D-A06" });
  });

  it("后端报错 → degraded（FAIL-OPEN，不把异常抛给 Worker）", async () => {
    const callMethod = vi.fn(async () => {
      throw new Error("ipc boom");
    });
    const tools = createStatsTools({ callMethod }) as Tool[];
    const out = await tool(tools, "stats_run").execute({ capability_id: "D-E01", payload: {} });
    expect(out.ok).toBe(false);
    expect(out.degraded).toBe(true);
    expect(String(out.reason)).toContain("ipc boom");
  });

  it("超时 → degraded", async () => {
    const callMethod = vi.fn(() => new Promise(() => {}));
    const tools = createStatsTools({ callMethod, timeoutMs: 20 }) as Tool[];
    const out = await tool(tools, "stats_list").execute({});
    expect(out).toMatchObject({ ok: false, degraded: true });
    expect(String(out.reason)).toContain("timeout");
  });
});
