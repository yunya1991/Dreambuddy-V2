import { promises as fs } from "fs";
import * as os from "os";
import * as path from "path";
import {
  appendMemoryRecord,
  ingestPendingCandidates,
  listMemoryRecords,
  refreshAnchors,
  type MemoryRecordInput,
} from "./memory-records";

function input(overrides: Partial<MemoryRecordInput> = {}): MemoryRecordInput {
  return {
    content: "回测发现该接口在 2026-11 后新增 revenue 字段",
    subclass: "code_fact",
    anchor: "file:docs/api.md",
    source_anchor: "file:docs/api.md",
    trace_id: "trace-1",
    summary: "接口字段事实",
    ...overrides,
  };
}

describe("残差记忆记录生产端", () => {
  let root: string;
  let file: string;

  beforeEach(async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), "memory-records-"));
    file = path.join(root, "records.jsonl");
  });

  afterEach(async () => {
    await fs.rm(root, { recursive: true, force: true });
  });

  it("准入通过的候选写为 verified 记录", async () => {
    const result = await appendMemoryRecord(input(), { file, now: 1000 });
    expect(result.ok).toBe(true);
    expect(result.record?.verify_state).toBe("verified");
    expect(result.record?.source_anchor).toBe("file:docs/api.md");
    expect(result.record?.form).toBe("M1");

    const records = await listMemoryRecords(file);
    expect(records).toHaveLength(1);
  });

  it("敏感信息拒绝写入", async () => {
    const result = await appendMemoryRecord(
      input({ sensitive: true }),
      { file, now: 1000 },
    );
    expect(result.ok).toBe(false);
    expect(result.admission.code).toBe("sensitive");
    expect(await listMemoryRecords(file)).toEqual([]);
  });

  it("可推导内容按 M3 拒绝写入", async () => {
    const result = await appendMemoryRecord(
      input({ derivable: true }),
      { file, now: 1000 },
    );
    expect(result.ok).toBe(false);
    expect(result.admission.form).toBe("M3");
    expect(await listMemoryRecords(file)).toEqual([]);
  });

  it("同内容指纹重复提交不重复写", async () => {
    const first = await appendMemoryRecord(input(), { file, now: 1000 });
    const second = await appendMemoryRecord(input(), { file, now: 2000 });
    expect(second.duplicated).toBe(true);
    expect(second.record?.id).toBe(first.record?.id);
    expect(await listMemoryRecords(file)).toHaveLength(1);
  });

  it("锚点存在 → anchor_exists=true，单调回写", async () => {
    await appendMemoryRecord(input(), { file, now: 1000 });
    const records = await listMemoryRecords(file);

    const refreshed = await refreshAnchors(records, {
      root,
      file,
      now: 2000,
      exists: async () => true,
    });

    expect(refreshed.changed).toHaveLength(1);
    expect(refreshed.records[0].anchor_exists).toBe(true);
    expect((await listMemoryRecords(file))[0].anchor_exists).toBe(true);
  });

  it("锚点消失 → anchor_exists=false，治理可判 degraded", async () => {
    await appendMemoryRecord(input(), { file, now: 1000 });
    const records = await listMemoryRecords(file);

    const refreshed = await refreshAnchors(records, {
      root,
      file,
      now: 2000,
      exists: async () => false,
    });

    expect(refreshed.records[0].anchor_exists).toBe(false);
    expect(refreshed.records[0].last_verified_at).toBe(1000);
  });

  it("未知锚点格式不参与复核", async () => {
    const records = [
      {
        id: "mem-x",
        subclass: "code_fact" as const,
        source_anchor: "idea:xxx",
        verify_state: "verified" as const,
      },
    ];
    const refreshed = await refreshAnchors(records, {
      root,
      file,
      exists: async () => false,
    });
    expect(refreshed.changed).toEqual([]);
  });
});

describe("settle 暂存候选摄入", () => {
  let root: string;
  let file: string;
  let pending: string;

  beforeEach(async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), "memory-pending-"));
    file = path.join(root, "records.jsonl");
    pending = path.join(root, "pending.jsonl");
  });

  afterEach(async () => {
    await fs.rm(root, { recursive: true, force: true });
  });

  function candidate(overrides: Record<string, unknown> = {}) {
    return JSON.stringify({
      content: "数据源 X 的 metrics 为空",
      subclass: "runtime",
      anchor: "source:X",
      source_anchor: "source:X",
      summary: "数据源的坑",
      trace_id: "trace-9",
      ...overrides,
    });
  }

  it("准入通过才落盘，拒绝与坏行不保留", async () => {
    await fs.writeFile(
      pending,
      [
        candidate(),
        candidate({ content: "敏感内容", sensitive: true }),
        "{bad json",
      ].join("\n") + "\n",
      "utf-8",
    );

    const counts = await ingestPendingCandidates({ pending, file, now: 1000 });

    expect(counts).toEqual({
      scanned: 3,
      admitted: 1,
      duplicated: 0,
      rejected: 1,
      invalid: 1,
    });
    const records = await listMemoryRecords(file);
    expect(records).toHaveLength(1);
    expect(records[0].trace_id).toBe("trace-9");
    expect(await fs.readFile(pending, "utf-8")).toBe("");
  });

  it("重复摄入按内容指纹去重", async () => {
    await fs.writeFile(pending, `${candidate()}\n`, "utf-8");
    const first = await ingestPendingCandidates({ pending, file, now: 1000 });
    expect(first.admitted).toBe(1);

    await fs.writeFile(pending, `${candidate()}\n`, "utf-8");
    const second = await ingestPendingCandidates({ pending, file, now: 2000 });
    expect(second.duplicated).toBe(1);
    expect(await listMemoryRecords(file)).toHaveLength(1);
  });

  it("非法 subclass 丢弃，不写记录", async () => {
    await fs.writeFile(
      pending,
      `${candidate({ subclass: "unknown" })}\n`,
      "utf-8",
    );
    const counts = await ingestPendingCandidates({ pending, file });
    expect(counts.invalid).toBe(1);
    expect(await listMemoryRecords(file)).toEqual([]);
  });
});
