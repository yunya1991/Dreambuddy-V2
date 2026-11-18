#!/usr/bin/env node
/**
 * W5 T5.2 机器验收脚本。
 * 用法：node scripts/acceptance-w5.mjs
 * 退出码：0 全通过；非 0 有失败。
 */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cases = [
  "U 级证据：U2 必须有可复放沙箱/回测；U3 至少 2 个独立来源；过期证据剔除",
  "残差准入：四禁入、可重算→M3、R1→M1、R3/R4→M2",
  "提案预注册：必须有冻结预注册、回滚、证据；已实施/直改拒绝",
];

console.log("W5 验收门（机器判定）");
for (const c of cases) console.log(`  - ${c}`);
console.log("");

const npx = process.platform === "win32" ? "npx.cmd" : "npx";
const run = spawnSync(
  npx,
  ["jest", "src/lib/acceptance/w5-acceptance.test.ts", "--runInBand", "--silent"],
  { cwd: root, stdio: "inherit" },
);

if (run.status === 0) {
  console.log("\nW5 ACCEPTANCE: PASS");
  process.exit(0);
}

console.error("\nW5 ACCEPTANCE: FAIL");
process.exit(run.status ?? 1);
