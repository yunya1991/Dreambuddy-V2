// ============================================================================
// M2 单测（SPEC-7 §10 / G2）：文件型配置可写规格表 + trailing_stop 白名单
//           + 快照 / 原子写 / 回读（在临时仓库根上验证，不触碰真实配置）
// ============================================================================

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { AdminError } from "../errors.ts";
import {
  FILE_WRITE_SPECS,
  fileWriteSpec,
  isWritableFileKey,
  planFilePatch,
  planTrailingStopPatch,
  readConfigFile,
  writeConfigAtomic,
} from "./file-config.ts";

function expectAdminError(fn: () => void, code: string, messagePart?: string) {
  assert.throws(fn, (error: unknown) => {
    assert.ok(error instanceof AdminError, "应抛出 AdminError");
    assert.equal(error.code, code);
    if (messagePart) assert.ok(error.message.includes(messagePart), error.message);
    return true;
  });
}

const TRAILING_BASE = {
  version: "1.0",
  mode: "atr_adaptive",
  trigger_cooldown_sec: 300,
  auto_close_after_sec: 1800,
  report: {
    enabled: true,
    output_dir: "artifacts/trailing-stop/reports",
  },
};

// ---------------------------------------------------------------- 规格表

test("可写规格表：monitor 在线生效，trailing_stop 需重启", () => {
  assert.equal(isWritableFileKey("monitor"), true);
  assert.equal(isWritableFileKey("trailing_stop"), true);
  assert.equal(fileWriteSpec("monitor").requiresRestart, false);
  assert.equal(fileWriteSpec("trailing_stop").requiresRestart, true);
  assert.deepEqual(Object.keys(FILE_WRITE_SPECS).sort(), ["monitor", "trailing_stop"]);
});

test("可写规格表：capital_control / capital_allocator / 任意串不可写", () => {
  assert.equal(isWritableFileKey("capital_control"), false);
  assert.equal(isWritableFileKey("capital_allocator"), false);
  assert.equal(isWritableFileKey("../../etc/passwd"), false);
  assert.equal(isWritableFileKey(""), false);
});

// ---------------------------------------------------------------- trailing_stop 白名单

test("trailing_stop 白名单：合法 key 产出 before/after/next 且不就地修改", () => {
  const plan = planFilePatch("trailing_stop", TRAILING_BASE, {
    trigger_cooldown_sec: 120,
    auto_close_after_sec: 600,
    "report.enabled": false,
    "report.output_dir": "artifacts/ts/out",
  });
  assert.deepEqual(plan.before, {
    trigger_cooldown_sec: 300,
    auto_close_after_sec: 1800,
    "report.enabled": true,
    "report.output_dir": "artifacts/trailing-stop/reports",
  });
  assert.deepEqual(plan.after, {
    trigger_cooldown_sec: 120,
    auto_close_after_sec: 600,
    "report.enabled": false,
    "report.output_dir": "artifacts/ts/out",
  });
  const next = plan.next as typeof TRAILING_BASE;
  assert.equal(next.trigger_cooldown_sec, 120);
  assert.equal(next.auto_close_after_sec, 600);
  assert.equal(next.report.enabled, false);
  assert.equal(next.report.output_dir, "artifacts/ts/out");
  assert.equal(TRAILING_BASE.trigger_cooldown_sec, 300);
  assert.equal(TRAILING_BASE.report.enabled, true);
});

test("trailing_stop 白名单：非白名单 key 一律 VALIDATION_FAILED", () => {
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { "algorithm.atr_multiplier": 3 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(() => planTrailingStopPatch(TRAILING_BASE, { mode: "fixed" }), "VALIDATION_FAILED");
  expectAdminError(() => planTrailingStopPatch(TRAILING_BASE, { cache_ttl_sec: 5 }), "VALIDATION_FAILED");
  expectAdminError(() => planTrailingStopPatch(TRAILING_BASE, {}), "VALIDATION_FAILED");
});

test("trailing_stop 白名单：类型 / 范围错误 VALIDATION_FAILED", () => {
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { trigger_cooldown_sec: "300" }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { trigger_cooldown_sec: 1.5 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { trigger_cooldown_sec: -1 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { auto_close_after_sec: 86401 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { "report.enabled": "yes" }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { "report.output_dir": "" }),
    "VALIDATION_FAILED",
  );
});

test("trailing_stop 白名单：report.output_dir 必须是仓库内相对路径", () => {
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { "report.output_dir": "/etc/passwd" }),
    "VALIDATION_FAILED",
    "相对路径",
  );
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { "report.output_dir": "../../etc" }),
    "VALIDATION_FAILED",
    "..",
  );
  expectAdminError(
    () => planTrailingStopPatch(TRAILING_BASE, { "report.output_dir": "a/../../b" }),
    "VALIDATION_FAILED",
    "..",
  );
  const plan = planTrailingStopPatch(TRAILING_BASE, { "report.output_dir": " artifacts/x " });
  assert.equal(plan.after["report.output_dir"], "artifacts/x");
});

test("trailing_stop 白名单：缺少 report 节点直接拒绝", () => {
  expectAdminError(
    () => planTrailingStopPatch({ trigger_cooldown_sec: 300 }, { trigger_cooldown_sec: 60 }),
    "VALIDATION_FAILED",
    "report",
  );
});

// ---------------------------------------------------------------- 快照 / 原子写 / 回读

test("原子写：快照落盘、内容替换、回读一致、无临时文件残留", async () => {
  const tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), "admin-m2-"));
  const configDir = path.join(tmpRoot, "16-调控系统", "config");
  const filePath = path.join(configDir, "trailing_stop.json");
  const original = process.env.DREAMBUDDY_ROOT;
  process.env.DREAMBUDDY_ROOT = tmpRoot;

  try {
    await fs.mkdir(configDir, { recursive: true });
    await fs.writeFile(filePath, `${JSON.stringify(TRAILING_BASE, null, 2)}\n`, "utf8");

    const snapshot = await readConfigFile("trailing_stop");
    const plan = planFilePatch("trailing_stop", snapshot.data, { trigger_cooldown_sec: 60 });
    const backupRel = await writeConfigAtomic("trailing_stop", snapshot, plan.next, plan.after);

    const written = JSON.parse(await fs.readFile(filePath, "utf8")) as typeof TRAILING_BASE;
    assert.equal(written.trigger_cooldown_sec, 60);
    assert.equal(written.auto_close_after_sec, 1800);

    // 快照保留写入前的值
    const backup = JSON.parse(
      await fs.readFile(path.join(tmpRoot, backupRel), "utf8"),
    ) as typeof TRAILING_BASE;
    assert.equal(backup.trigger_cooldown_sec, 300);

    // 原子替换后目录里不应残留 .tmp-* 文件
    const leftovers = (await fs.readdir(configDir)).filter((name) => name.includes(".tmp-"));
    assert.deepEqual(leftovers, []);
  } finally {
    if (original === undefined) delete process.env.DREAMBUDDY_ROOT;
    else process.env.DREAMBUDDY_ROOT = original;
    await fs.rm(tmpRoot, { recursive: true, force: true });
  }
});

test("原子写：回读不一致时报 INTERNAL_ERROR（模拟并发改写）", async () => {
  const tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), "admin-m2-"));
  const configDir = path.join(tmpRoot, "16-调控系统", "config");
  const filePath = path.join(configDir, "trailing_stop.json");
  const original = process.env.DREAMBUDDY_ROOT;
  process.env.DREAMBUDDY_ROOT = tmpRoot;

  try {
    await fs.mkdir(configDir, { recursive: true });
    await fs.writeFile(filePath, `${JSON.stringify(TRAILING_BASE, null, 2)}\n`, "utf8");

    const snapshot = await readConfigFile("trailing_stop");
    const plan = planFilePatch("trailing_stop", snapshot.data, { trigger_cooldown_sec: 60 });
    // 声明期望写入 90，实际写入 60 → 回读校验必须失败
    await expectRejects(
      () => writeConfigAtomic("trailing_stop", snapshot, plan.next, { trigger_cooldown_sec: 90 }),
      "INTERNAL_ERROR",
    );
  } finally {
    if (original === undefined) delete process.env.DREAMBUDDY_ROOT;
    else process.env.DREAMBUDDY_ROOT = original;
    await fs.rm(tmpRoot, { recursive: true, force: true });
  }
});

async function expectRejects(fn: () => Promise<unknown>, code: string) {
  await assert.rejects(fn, (error: unknown) => {
    assert.ok(error instanceof AdminError, "应抛出 AdminError");
    assert.equal(error.code, code);
    return true;
  });
}
