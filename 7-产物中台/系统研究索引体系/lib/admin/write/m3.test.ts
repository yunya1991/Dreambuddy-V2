// ============================================================================
// M3 单测（SPEC-7 §6.4 / §16 / G3）：L2 审批闸门 + param_center 硬下限 + 覆盖文件
// ============================================================================

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { AdminError } from "../errors.ts";
import { ADMIN_FILE_KEYS, ADMIN_L2_FILE_KEYS } from "../constants.ts";
import {
  isAdminFileKey,
  isWritableFileKey,
  planFilePatch,
  readConfigFile,
  writeConfigAtomic,
} from "./file-config.ts";
import { planParamCenterPatch, readParamCenterOverride } from "./param-center.ts";
import { assertApprovalUsableForExecution, isApprovedDecision } from "./governance.ts";

function expectAdminError(fn: () => void, code: string, messagePart?: string) {
  assert.throws(fn, (error: unknown) => {
    assert.ok(error instanceof AdminError, "应抛出 AdminError");
    assert.equal(error.code, code);
    if (messagePart) assert.ok(error.message.includes(messagePart), error.message);
    return true;
  });
}

// ---------------------------------------------------------------- 文件分级

test("param_center 只走 L2：在 ADMIN_FILE_KEYS 中但不在 M2 可写规格表", () => {
  assert.equal(isAdminFileKey("param_center"), true);
  assert.equal(isWritableFileKey("param_center"), false);
  assert.equal(ADMIN_FILE_KEYS.param_center, "16-调控系统/config/param_center_override.json");
  assert.deepEqual([...ADMIN_L2_FILE_KEYS], [
    "capital_control",
    "capital_allocator",
    "trailing_stop",
    "param_center",
  ]);
});

// ---------------------------------------------------------------- 硬下限

test("param_center 下限：合法值通过并产出 before/after/next", () => {
  const plan = planParamCenterPatch({}, {
    sl_floor: 0.05,
    tp_floor: 0.15,
    rr_ratio_target: 2.5,
    atr_mult_range: [3, 5],
  });
  assert.deepEqual(plan.after, {
    sl_floor: 0.05,
    tp_floor: 0.15,
    rr_ratio_target: 2.5,
    atr_mult_range: [3, 5],
  });
  assert.deepEqual(plan.before, {
    sl_floor: null,
    tp_floor: null,
    rr_ratio_target: null,
    atr_mult_range: null,
  });
  assert.equal((plan.next as Record<string, unknown>).sl_floor, 0.05);
});

test("param_center 下限：SL<4% / TP<12% / RR<2 / ATR 越界一律 400", () => {
  expectAdminError(() => planParamCenterPatch({}, { sl_floor: 0.0399 }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { tp_floor: 0.1199 }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { rr_ratio_target: 1.99 }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { atr_mult_range: [1.5, 5] }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { atr_mult_range: [3, 6.5] }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { atr_mult_range: [5, 3] }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { atr_mult_range: [3] }), "VALIDATION_FAILED");
});

test("param_center 白名单：类型错误 / 未知键 / 空 patch 一律 400", () => {
  expectAdminError(() => planParamCenterPatch({}, { sl_floor: "0.05" }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { rr_ratio_target: null }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, { stop_loss: 0.05 }), "VALIDATION_FAILED");
  expectAdminError(() => planParamCenterPatch({}, {}), "VALIDATION_FAILED");
});

// ---------------------------------------------------------------- 审批闸门

const APPROVED = {
  target: "param_center",
  decision: "approved",
  requester: "uid-requester",
  approver: "uid-approver",
};

test("审批闸门：approved + 双人 → 放行并回传发起人/审批人", () => {
  const actors = assertApprovalUsableForExecution(APPROVED, "param_center");
  assert.deepEqual(actors, { requester: "uid-requester", approver: "uid-approver" });
  assert.equal(isApprovedDecision("APPROVED"), true);
  assert.equal(isApprovedDecision("pending"), false);
});

test("审批闸门：缺少审批记录 → 403", () => {
  expectAdminError(() => assertApprovalUsableForExecution(null, "param_center"), "FORBIDDEN_ROLE");
});

test("审批闸门：审批目标不一致 / 未通过 → 422", () => {
  expectAdminError(
    () => assertApprovalUsableForExecution({ ...APPROVED, target: "trailing_stop" }, "param_center"),
    "RULE_BLOCKED",
  );
  expectAdminError(
    () => assertApprovalUsableForExecution({ ...APPROVED, decision: "pending" }, "param_center"),
    "RULE_BLOCKED",
  );
  expectAdminError(
    () => assertApprovalUsableForExecution({ ...APPROVED, decision: "rejected" }, "param_center"),
    "RULE_BLOCKED",
  );
});

test("审批闸门：审批人=发起人 / 缺少审批人 → 403", () => {
  expectAdminError(
    () => assertApprovalUsableForExecution({ ...APPROVED, approver: "uid-requester" }, "param_center"),
    "FORBIDDEN_ROLE",
  );
  expectAdminError(
    () => assertApprovalUsableForExecution({ ...APPROVED, approver: "" }, "param_center"),
    "FORBIDDEN_ROLE",
  );
  expectAdminError(
    () => assertApprovalUsableForExecution({ ...APPROVED, requester: "" }, "param_center"),
    "FORBIDDEN_ROLE",
  );
});

// ---------------------------------------------------------------- 覆盖文件写入

test("覆盖文件：不存在时按空对象处理，首次写入自动创建并快照", async () => {
  const tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), "admin-m3-"));
  const configDir = path.join(tmpRoot, "16-调控系统", "config");
  const filePath = path.join(configDir, "param_center_override.json");
  const original = process.env.DREAMBUDDY_ROOT;
  process.env.DREAMBUDDY_ROOT = tmpRoot;

  try {
    await fs.mkdir(configDir, { recursive: true });

    const snapshot = await readParamCenterOverride();
    assert.equal(snapshot.mtimeMs, 0);
    assert.deepEqual(snapshot.data, {});

    const plan = planParamCenterPatch(snapshot.data, { sl_floor: 0.05 });
    const backupRel = await writeConfigAtomic("param_center", snapshot, plan.next, plan.after);

    const written = JSON.parse(await fs.readFile(filePath, "utf8")) as Record<string, unknown>;
    assert.equal(written.sl_floor, 0.05);

    const reread = await readConfigFile("param_center");
    assert.equal(reread.data.sl_floor, 0.05);

    const leftovers = (await fs.readdir(configDir)).filter((name) => name.includes(".tmp-"));
    assert.deepEqual(leftovers, []);
    const backup = await fs.readFile(path.join(tmpRoot, backupRel), "utf8");
    assert.deepEqual(JSON.parse(backup), {});
  } finally {
    if (original === undefined) delete process.env.DREAMBUDDY_ROOT;
    else process.env.DREAMBUDDY_ROOT = original;
    await fs.rm(tmpRoot, { recursive: true, force: true });
  }
});

test("L2 禁止走 M2 的非审批通道：trailing_stop 可被 L2 提案复用同一白名单", () => {
  const plan = planFilePatch("trailing_stop", { report: { enabled: true } }, {
    trigger_cooldown_sec: 60,
  });
  assert.equal(plan.after.trigger_cooldown_sec, 60);
  expectAdminError(
    () => planFilePatch("trailing_stop", { report: { enabled: true } }, { mode: "fixed" }),
    "VALIDATION_FAILED",
  );
});
