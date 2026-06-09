import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PRODUCT_HUB_ROOT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台";
const REMOVED_WORKSPACE_PATH = [
  "/Users/zhangjiangtao/WorkBuddy",
  ["dreambuddy-v2", "mainline"].join("-"),
].join("/");
const THIS_FILE = fileURLToPath(import.meta.url);

function collectFiles(root) {
  const entries = readdirSync(root);
  const files = [];

  for (const entry of entries) {
    const fullPath = path.join(root, entry);
    const stats = statSync(fullPath);

    if (stats.isDirectory()) {
      files.push(...collectFiles(fullPath));
      continue;
    }

    files.push(fullPath);
  }

  return files;
}

test("product hub files do not reference the removed workspace root", () => {
  const offenders = collectFiles(PRODUCT_HUB_ROOT)
    .filter((filePath) => {
      if (filePath === THIS_FILE) {
        return false;
      }
      const contents = readFileSync(filePath, "utf8");
      return contents.includes(REMOVED_WORKSPACE_PATH);
    })
    .map((filePath) => path.relative(PRODUCT_HUB_ROOT, filePath));

  assert.deepEqual(offenders, []);
});
