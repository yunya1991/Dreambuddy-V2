import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { listStrategies, readStrategy } from "./strategy-library.js";

function writeText(p: string, body: string) {
  fs.writeFileSync(p, body, "utf-8");
}

test("listStrategies scans strategy md files and reads frontmatter title", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-hub-strategy-library-"));
  const strategyDir = path.join(root, "strategy");
  fs.mkdirSync(strategyDir, { recursive: true });

  writeText(
    path.join(strategyDir, "alpha.md"),
    ["---", "title: Alpha Strategy", "tags: test", "---", "", "# Ignored heading", ""].join("\n")
  );
  writeText(path.join(strategyDir, "beta.md"), ["# Beta Strategy", "", "Body"].join("\n"));
  writeText(path.join(strategyDir, "ignore.txt"), "not markdown");

  const prev = process.env.ARTIFACTS_ROOT;
  process.env.ARTIFACTS_ROOT = root;
  try {
    const out = listStrategies();
    assert.equal(out.items.length, 2);
    const titles = out.items.map((x) => x.title).sort();
    assert.deepEqual(titles, ["Alpha Strategy", "Beta Strategy"]);
    assert.ok(out.items.every((x) => x.id.endsWith(".md")));
  } finally {
    process.env.ARTIFACTS_ROOT = prev;
  }
});

test("readStrategy reads raw markdown content by id", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-hub-strategy-library-"));
  const strategyDir = path.join(root, "strategy");
  fs.mkdirSync(strategyDir, { recursive: true });
  writeText(path.join(strategyDir, "alpha.md"), ["---", "title: Alpha", "---", "", "hello"].join("\n"));

  const prev = process.env.ARTIFACTS_ROOT;
  process.env.ARTIFACTS_ROOT = root;
  try {
    const doc = readStrategy("alpha.md");
    assert.equal(doc.id, "alpha.md");
    assert.equal(doc.frontmatter.title, "Alpha");
    assert.ok(doc.content.includes("hello"));
  } finally {
    process.env.ARTIFACTS_ROOT = prev;
  }
});

test("readStrategy rejects path traversal ids", () => {
  const prev = process.env.ARTIFACTS_ROOT;
  process.env.ARTIFACTS_ROOT = os.tmpdir();
  try {
    assert.throws(() => readStrategy("../secrets.md"), /invalid_strategy_id/);
  } finally {
    process.env.ARTIFACTS_ROOT = prev;
  }
});
