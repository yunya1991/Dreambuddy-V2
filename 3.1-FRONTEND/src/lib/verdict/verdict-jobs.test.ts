import { promises as fs } from "fs";
import * as os from "os";
import * as path from "path";
import { assessVerdict } from "./uncertainty-verdict";
import {
  createVerdictJob,
  executeVerdictJob,
  getVerdictJob,
  listVerdictJobs,
  type VerdictJobRequest,
} from "./verdict-jobs";

function request(overrides: Partial<VerdictJobRequest> = {}): VerdictJobRequest {
  return {
    task_id: "task-1",
    trace_id: "trace-1",
    claim: "该接口返回营收字段",
    level: "U3",
    ...overrides,
  };
}

function fakeVerdict(taskId: string) {
  const { verdict } = assessVerdict({
    task_id: taskId,
    trace_id: "trace-1",
    claim: "该接口返回营收字段",
    level: "U1",
    evidence: [
      { ref: "stats:revenue", kind: "statistics", sample_size: 120, replayable: true },
    ],
    confidence: 0.9,
  });
  return verdict;
}

describe("异步裁决 job", () => {
  let root: string;

  beforeEach(async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), "verdict-jobs-"));
  });

  afterEach(async () => {
    await fs.rm(root, { recursive: true, force: true });
  });

  it("创建后为 queued 且可读回", async () => {
    const job = await createVerdictJob(request(), { root });
    expect(job.status).toBe("queued");
    expect(job.attempts).toBe(0);

    const stored = await getVerdictJob(job.job_id, root);
    expect(stored?.job_id).toBe(job.job_id);
    expect(stored?.request.level).toBe("U3");
  });

  it("执行成功 → succeeded，裁决通过 onVerdict 写入", async () => {
    const job = await createVerdictJob(request(), { root });
    const executor = jest.fn(async (input: VerdictJobRequest) => ({
      verdict: fakeVerdict(input.task_id),
      issues: [],
    }));
    const onVerdict = jest.fn(async () => undefined);

    const done = await executeVerdictJob(job.job_id, executor, { root, onVerdict });

    expect(done?.status).toBe("succeeded");
    expect(done?.attempts).toBe(1);
    expect(done?.verdict?.verdict).toBe("supported");
    expect(onVerdict).toHaveBeenCalledTimes(1);
    expect(executor).toHaveBeenCalledTimes(1);
  });

  it("已成功的 job 幂等，不重复执行与写入", async () => {
    const job = await createVerdictJob(request(), { root });
    const executor = jest.fn(async (input: VerdictJobRequest) => ({
      verdict: fakeVerdict(input.task_id),
      issues: [],
    }));
    const onVerdict = jest.fn(async () => undefined);

    await executeVerdictJob(job.job_id, executor, { root, onVerdict });
    const again = await executeVerdictJob(job.job_id, executor, { root, onVerdict });

    expect(again?.status).toBe("succeeded");
    expect(executor).toHaveBeenCalledTimes(1);
    expect(onVerdict).toHaveBeenCalledTimes(1);
  });

  it("执行异常 → failed 并保留错误", async () => {
    const job = await createVerdictJob(request(), { root });
    const done = await executeVerdictJob(
      job.job_id,
      async () => {
        throw new Error("回测数据缺口");
      },
      { root, onVerdict: async () => undefined },
    );

    expect(done?.status).toBe("failed");
    expect(done?.error).toBe("回测数据缺口");
  });

  it("按 task_id 过滤 job 列表", async () => {
    await createVerdictJob(request({ task_id: "task-a" }), { root });
    await createVerdictJob(request({ task_id: "task-b" }), { root });

    const jobs = await listVerdictJobs("task-a", root);
    expect(jobs).toHaveLength(1);
    expect(jobs[0].request.task_id).toBe("task-a");
  });

  it("不存在的 job 返回 null", async () => {
    expect(await getVerdictJob("missing", root)).toBeNull();
    expect(
      await executeVerdictJob("missing", async () => {
        throw new Error("never");
      }, { root }),
    ).toBeNull();
  });
});
