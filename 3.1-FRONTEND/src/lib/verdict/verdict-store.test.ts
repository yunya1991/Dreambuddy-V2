import { mkdtemp } from "fs/promises";
import os from "os";
import path from "path";
import { assessVerdict } from "./uncertainty-verdict";
import { appendVerdict, latestVerdict, listVerdicts } from "./verdict-store";

function verdict() {
  return assessVerdict({
    task_id: "task-1",
    trace_id: "trace-1",
    claim: "样本外有效",
    level: "U1",
    evidence: [
      {
        ref: "stats:a",
        kind: "statistics",
        sample_size: 100,
        effect_size: 0.2,
        replayable: true,
      },
    ],
    confidence: 0.8,
    now: 1,
  }).verdict;
}

describe("verdict-store", () => {
  it("append-only：按 task 分文件，可读回最新一条", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "verdicts-"));
    await appendVerdict({ ...verdict(), created_at: 1 }, root);
    await appendVerdict(
      { ...verdict(), verdict_id: "verdict:task-1:U1:second", created_at: 2 },
      root,
    );

    const all = await listVerdicts("task-1", root);
    expect(all).toHaveLength(2);
    expect((await latestVerdict("task-1", root))?.created_at).toBe(2);
    expect(await latestVerdict("other", root)).toBeNull();
  });

  it("拒绝写入非法 verdict", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "verdicts-"));
    await expect(
      appendVerdict(
        { ...verdict(), evidence_refs: [], verdict: "supported" },
        root,
      ),
    ).rejects.toThrow(/校验失败/);
  });
});
