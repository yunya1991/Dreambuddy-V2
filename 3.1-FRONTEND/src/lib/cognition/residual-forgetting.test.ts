import {
  buildForgettingPlan,
  decideForgetting,
  type MemoryRecord,
} from "./residual-forgetting";

const NOW = Date.UTC(2026, 10, 18);
const DAY = 24 * 60 * 60 * 1000;

function record(overrides: Partial<MemoryRecord> & { id: string }): MemoryRecord {
  return {
    subclass: "code_fact",
    verify_state: "verified",
    created_at: NOW - 365 * DAY,
    last_verified_at: NOW - DAY,
    form: "M1",
    ...overrides,
  };
}

describe("残差遗忘调度", () => {
  it("已验证的代码事实不因时间久远被降级", () => {
    const decision = decideForgetting(
      record({ id: "m1", created_at: NOW - 900 * DAY, last_verified_at: NOW }),
      { now: NOW },
    );
    expect(decision.action).toBe("keep");
    expect(decision.reason_code).toBe("verified");
  });

  it("D-policy 即使 degraded 也不自动降级", () => {
    const decision = decideForgetting(
      record({ id: "m2", subclass: "policy", verify_state: "degraded" }),
      { now: NOW },
    );
    expect(decision.action).toBe("keep");
    expect(decision.reason_code).toBe("policy_frozen");
  });

  it("未分型存量按 D-policy 冻结", () => {
    const decision = decideForgetting(record({ id: "m3", subclass: null }), {
      now: NOW,
    });
    expect(decision.action).toBe("keep");
    expect(decision.reason_code).toBe("policy_frozen");
  });

  it("人工 pin 跳过自动治理", () => {
    const decision = decideForgetting(
      record({ id: "m4", pinned: true, verify_state: "degraded" }),
      { now: NOW },
    );
    expect(decision.action).toBe("keep");
    expect(decision.reason_code).toBe("pinned");
  });

  it("degraded → 移出检索索引（可逆），不物理删除", () => {
    const decision = decideForgetting(
      record({ id: "m5", verify_state: "degraded", last_used_at: NOW }),
      { now: NOW, deletion_test_passed: true },
    );
    expect(decision.action).toBe("demote");
    expect(decision.reason_code).toBe("degraded");
    expect(decision.trace).toBeUndefined();
  });

  it("锚点消失 → 事件驱动判 degraded 并降级", () => {
    const decision = decideForgetting(
      record({ id: "m6", anchor_exists: false, verify_state: "verified" }),
      { now: NOW },
    );
    expect(decision.action).toBe("demote");
    expect(decision.reason_code).toBe("degraded");
  });

  it("运行期记忆超宽限期但删除测试集未通过 → 只降级", () => {
    const decision = decideForgetting(
      record({
        id: "m7",
        subclass: "runtime",
        verify_state: "degraded",
        last_used_at: NOW - 30 * DAY,
      }),
      { now: NOW, deletion_test_passed: false },
    );
    expect(decision.action).toBe("demote");
    expect(decision.reason_code).toBe("degraded_runtime");
  });

  it("运行期记忆超宽限期且删除测试集通过 → 降为痕迹池", () => {
    const decision = decideForgetting(
      record({
        id: "m8",
        subclass: "runtime",
        verify_state: "degraded",
        last_used_at: NOW - 30 * DAY,
        summary: "某次数据源异常的处理经验",
      }),
      { now: NOW, deletion_test_passed: true },
    );
    expect(decision.action).toBe("archive_trace");
    expect(decision.reason_code).toBe("degraded_runtime_grace_expired");
    expect(decision.trace?.id).toBe("m8");
    expect(decision.trace?.tags).toContain("runtime");
    expect(decision.trace?.summary).toContain("数据源异常");
  });

  it("stale 非运行期记忆保留，可召回但需带标记", () => {
    const decision = decideForgetting(
      record({ id: "m9", subclass: "tech_decision", verify_state: "stale" }),
      { now: NOW },
    );
    expect(decision.action).toBe("keep");
    expect(decision.reason_code).toBe("stale_kept");
  });

  it("运行期 stale 在宽限期内保留", () => {
    const decision = decideForgetting(
      record({
        id: "m10",
        subclass: "runtime",
        verify_state: "stale",
        last_used_at: NOW - 2 * DAY,
      }),
      { now: NOW },
    );
    expect(decision.action).toBe("keep");
    expect(decision.reason_code).toBe("stale_within_grace");
  });

  it("M1 超过硬上限 → 输出抽象合并候选，不直接删除", () => {
    const records = [
      record({ id: "a", access_count: 10, last_used_at: NOW }),
      record({ id: "b", access_count: 1, last_used_at: NOW - 30 * DAY }),
      record({ id: "c", access_count: 5, last_used_at: NOW }),
    ];
    const plan = buildForgettingPlan(records, { now: NOW, m1_limit: 2 });
    expect(plan.m1_overflow.map((item) => item.id)).toEqual(["b"]);
    expect(plan.m1_overflow[0].reason).toBe("m1_cap_exceeded");
    expect(plan.next).toContain("consolidate_m1");
    expect(plan.counts.keep).toBe(3);
  });

  it("计划统计与下一步提示一致", () => {
    const plan = buildForgettingPlan(
      [
        record({ id: "keep-1" }),
        record({ id: "demote-1", verify_state: "degraded", last_used_at: NOW }),
        record({
          id: "trace-1",
          subclass: "runtime",
          verify_state: "stale",
          last_used_at: NOW - 30 * DAY,
        }),
      ],
      { now: NOW, deletion_test_passed: true },
    );
    expect(plan.counts).toEqual({ keep: 1, demote: 1, archive_trace: 1 });
    expect(plan.next).toContain("recheck_anchor");
  });
});
