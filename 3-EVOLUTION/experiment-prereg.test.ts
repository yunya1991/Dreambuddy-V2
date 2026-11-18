import assert from "assert";
import {
  type ExperimentPrereg,
  criteriaHash,
  evaluatePrereg,
  freezePrereg,
  isPreregIntact,
  validatePrereg,
} from "./experiment-prereg";

let passed = 0;
let failed = 0;

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`  ok ${name}`);
    passed += 1;
  } catch (e) {
    console.error(`  FAIL ${name}: ${(e as Error).message}`);
    failed += 1;
  }
}

function base(): ExperimentPrereg {
  return {
    prereg_id: "PR-1",
    proposal_id: "PROP-1",
    hypothesis: "样本外夏普高于 1.2",
    metric: "sharpe",
    direction: "higher_is_better",
    baseline_value: 1.0,
    success_threshold: 1.2,
    failure_threshold: 0.9,
    sample: {
      unit: "trade",
      min_size: 100,
      period_start: "2024-01-01",
      period_end: "2025-12-31",
      out_of_sample_ratio: 0.3,
    },
    stopping_rule: "达到 min_size 或样本外耗尽即停止",
    registered_at: "2026-01-01T00:00:00Z",
    locked: false,
  };
}

test("合法预注册无 error", () => {
  const issues = validatePrereg(base());
  assert.strictEqual(issues.filter((i) => i.level === "error").length, 0);
});

test("缺停止规则报错", () => {
  const p = { ...base(), stopping_rule: "" };
  assert.ok(validatePrereg(p).some((i) => i.code === "missing_stopping_rule"));
});

test("阈值方向不一致报错", () => {
  const p = { ...base(), success_threshold: 0.8 };
  assert.ok(validatePrereg(p).some((i) => i.code === "inconsistent_threshold"));
});

test("小样本与低样本外给 warning", () => {
  const p = {
    ...base(),
    sample: { ...base().sample, min_size: 10, out_of_sample_ratio: 0.1 },
  };
  const codes = validatePrereg(p).map((i) => i.code);
  assert.ok(codes.includes("small_sample"));
  assert.ok(codes.includes("low_out_of_sample"));
});

test("冻结后可验证完整", () => {
  const p = freezePrereg(base());
  assert.strictEqual(p.locked, true);
  assert.ok(p.criteria_hash);
  assert.ok(isPreregIntact(p));
});

test("冻结后改阈值被识别为篡改", () => {
  const p = freezePrereg(base());
  const tampered = { ...p, success_threshold: 1.0 };
  assert.strictEqual(isPreregIntact(tampered), false);
  assert.strictEqual(evaluatePrereg(tampered, { value: 1.5, sample_size: 200 }).verdict, "inconclusive");
});

test("未冻结不允许裁决", () => {
  assert.strictEqual(evaluatePrereg(base(), { value: 1.5, sample_size: 200 }).verdict, "inconclusive");
});

test("达到成功阈值 supported", () => {
  const p = freezePrereg(base());
  assert.strictEqual(evaluatePrereg(p, { value: 1.25, sample_size: 200 }).verdict, "supported");
});

test("达到失败阈值 rejected", () => {
  const p = freezePrereg(base());
  assert.strictEqual(evaluatePrereg(p, { value: 0.85, sample_size: 200 }).verdict, "rejected");
});

test("样本不足 inconclusive", () => {
  const p = freezePrereg(base());
  const out = evaluatePrereg(p, { value: 1.5, sample_size: 50 });
  assert.strictEqual(out.verdict, "inconclusive");
  assert.ok(out.reason.includes("sample_size"));
});

test("区间内 inconclusive", () => {
  const p = freezePrereg(base());
  assert.strictEqual(evaluatePrereg(p, { value: 1.1, sample_size: 200 }).verdict, "inconclusive");
});

test("指纹只随判据变化", () => {
  const p = base();
  assert.strictEqual(criteriaHash(p), criteriaHash({ ...p, registered_at: "2030-01-01" }));
  assert.notStrictEqual(criteriaHash(p), criteriaHash({ ...p, metric: "win_rate" }));
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
