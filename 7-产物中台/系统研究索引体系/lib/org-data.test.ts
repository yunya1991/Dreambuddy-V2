import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const MODULE_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系/lib/org-data.ts";

async function importOrgDataModule() {
  const moduleUrl = `${pathToFileURL(MODULE_PATH).href}?t=${Date.now()}-${Math.random()}`;
  return import(moduleUrl);
}

test("getOrgTreeData falls back to an empty org tree when data files are missing", async () => {
  const originalCwd = process.cwd();
  const tempDir = mkdtempSync(path.join(tmpdir(), "org-data-missing-"));

  process.chdir(tempDir);

  try {
    const { getOrgTreeData } = await importOrgDataModule();
    const data = getOrgTreeData();

    assert.equal(data.company.name, "Dream Product Hub");
    assert.deepEqual(data.company.departments, []);
    assert.equal(data.company.total_nodes, 0);
    assert.deepEqual(data.stats, {
      total_skills: 0,
      in_org_tree: 0,
      utility: 0,
      unclassified: 0,
      has_frontmatter: 0,
      missing_frontmatter: [],
    });
    assert.deepEqual(data.all_skills, {});
  } finally {
    process.chdir(originalCwd);
  }
});

test("getOrgTreeWithStatus also falls back cleanly when org and artifact files are missing", async () => {
  const originalCwd = process.cwd();
  const tempDir = mkdtempSync(path.join(tmpdir(), "org-status-missing-"));

  process.chdir(tempDir);

  try {
    const { getOrgTreeWithStatus } = await importOrgDataModule();
    const data = getOrgTreeWithStatus();

    assert.equal(data.company.name, "Dream Product Hub");
    assert.deepEqual(data.company.departments, []);
    assert.equal(data.company.total_nodes, 0);
    assert.deepEqual(data.stats.missing_frontmatter, []);
  } finally {
    process.chdir(originalCwd);
  }
});
