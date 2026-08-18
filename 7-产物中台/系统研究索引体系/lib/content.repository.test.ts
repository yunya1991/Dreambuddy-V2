import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { ContentRepository } from "./content.repository.ts";

test("ContentRepository builds canonical index entries from index.json metadata instead of frontmatter overrides", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "legacy-hub-data-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-21T09:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/eth-breakout-001",
          title: "ETH Breakout Plan",
          department: "trading",
          type: "strategy",
          status: "completed",
          date: "2026-05-21T08:30:00Z",
          chain_phase: "A3",
          tags: ["eth", "breakout"],
          filename: "eth-breakout-custom.md",
        },
      ],
    }),
  );

  fs.writeFileSync(
    path.join(tradingDir, "eth-breakout-custom.md"),
    [
      "---",
      "title: Wrong Frontmatter Title",
      "department: knowledge",
      "type: research",
      "status: rejected",
      "date: 2020-01-01",
      "tags:",
      "  - stale",
      "---",
      "",
      "# ETH Breakout",
      "Canonical content body.",
    ].join("\n"),
  );

  const repo = new ContentRepository(root);
  const index = repo.getArtifactsIndex();

  assert.equal(index.length, 1);
  assert.equal(index[0].artifactId, "eth-breakout-001");
  assert.equal(index[0].title, "ETH Breakout Plan");
  assert.equal(index[0].department, "trading");
  assert.equal(index[0].type, "strategy");
  assert.equal(index[0].status, "completed");
  assert.equal(index[0].chainPhase, "A3");
  assert.deepEqual(index[0].tags, ["eth", "breakout"]);
  assert.equal(index[0].sourceFile, "eth-breakout-custom.md");
  assert.equal(index[0].sourceType, "markdown");

  fs.rmSync(root, { recursive: true, force: true });
});

test("ContentRepository resolves detail content from canonical sourceFile instead of guessing artifactId filenames", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "legacy-hub-detail-"));
  const riskDir = path.join(root, "risk");
  fs.mkdirSync(riskDir, { recursive: true });

  fs.writeFileSync(
    path.join(riskDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-21T10:00:00Z",
      artifacts: [
        {
          artifact_id: "risk/alert-001",
          title: "Risk Alert",
          department: "governance",
          type: "risk_report",
          status: "completed",
          date: "2026-05-21T10:00:00Z",
          chain_phase: "A6",
          tags: ["risk", "alert"],
          filename: "custom-alert-note.md",
        },
      ],
    }),
  );

  fs.writeFileSync(
    path.join(riskDir, "custom-alert-note.md"),
    ["---", "title: Detail Title", "---", "", "Actual detail body."].join("\n"),
  );

  const repo = new ContentRepository(root);
  const detail = repo.getArtifactDetailBySlug("risk/alert-001");

  assert.ok(detail);
  assert.equal(detail?.canonical.sourceFile, "custom-alert-note.md");
  assert.equal(detail?.content.includes("Actual detail body."), true);
  assert.equal(detail?.sourcePath.endsWith("custom-alert-note.md"), true);

  fs.rmSync(root, { recursive: true, force: true });
});

test("ContentRepository returns null when canonical source file is missing", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "legacy-hub-missing-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-21T10:30:00Z",
      artifacts: [
        {
          artifact_id: "trading/missing-001",
          title: "Missing",
          department: "trading",
          type: "strategy",
          status: "completed",
          date: "2026-05-21T10:30:00Z",
          chain_phase: "A5",
          tags: [],
          filename: "not-there.md",
        },
      ],
    }),
  );

  const repo = new ContentRepository(root);
  assert.equal(repo.getArtifactDetailBySlug("trading/missing-001"), null);

  fs.rmSync(root, { recursive: true, force: true });
});

test("ContentRepository refreshes index and detail caches when a markdown source file changes", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "legacy-hub-cache-md-"));
  const researchDir = path.join(root, "research");
  fs.mkdirSync(researchDir, { recursive: true });

  fs.writeFileSync(
    path.join(researchDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-21T11:00:00Z",
      artifacts: [
        {
          artifact_id: "research/alpha-001",
          title: "Alpha Note",
          department: "knowledge",
          type: "research",
          status: "completed",
          date: "2026-05-21T11:00:00Z",
          chain_phase: "A1",
          tags: ["alpha"],
          filename: "alpha-note.md",
        },
      ],
    }),
  );

  const sourcePath = path.join(researchDir, "alpha-note.md");
  fs.writeFileSync(sourcePath, ["---", "title: Alpha", "---", "", "first body"].join("\n"));

  const repo = new ContentRepository(root);
  const firstDetail = repo.getArtifactDetailBySlug("research/alpha-001");
  const secondDetail = repo.getArtifactDetailBySlug("research/alpha-001");

  assert.ok(firstDetail);
  assert.equal(firstDetail?.content.includes("first body"), true);
  assert.equal(firstDetail, secondDetail);

  await new Promise((resolve) => setTimeout(resolve, 20));
  fs.writeFileSync(sourcePath, ["---", "title: Alpha", "---", "", "second body"].join("\n"));

  const refreshedDetail = repo.getArtifactDetailBySlug("research/alpha-001");

  assert.ok(refreshedDetail);
  assert.notEqual(refreshedDetail, firstDetail);
  assert.equal(refreshedDetail?.content.includes("second body"), true);

  fs.rmSync(root, { recursive: true, force: true });
});

test("ContentRepository refreshes canonical index when index.json changes", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "legacy-hub-cache-index-"));
  const governanceDir = path.join(root, "governance");
  fs.mkdirSync(governanceDir, { recursive: true });

  const indexPath = path.join(governanceDir, "index.json");
  fs.writeFileSync(
    indexPath,
    JSON.stringify({
      last_updated: "2026-05-21T11:10:00Z",
      artifacts: [
        {
          artifact_id: "governance/policy-001",
          title: "Policy A",
          department: "governance",
          type: "documentation",
          status: "completed",
          date: "2026-05-21T11:10:00Z",
          chain_phase: "A2",
          tags: ["policy"],
          filename: "policy-a.md",
        },
      ],
    }),
  );
  fs.writeFileSync(path.join(governanceDir, "policy-a.md"), "# Policy A");

  const repo = new ContentRepository(root);
  const firstIndex = repo.getArtifactsIndex();
  const secondIndex = repo.getArtifactsIndex();

  assert.equal(firstIndex[0].title, "Policy A");
  assert.equal(firstIndex, secondIndex);

  await new Promise((resolve) => setTimeout(resolve, 20));
  fs.writeFileSync(
    indexPath,
    JSON.stringify({
      last_updated: "2026-05-21T11:11:00Z",
      artifacts: [
        {
          artifact_id: "governance/policy-001",
          title: "Policy B",
          department: "governance",
          type: "documentation",
          status: "completed",
          date: "2026-05-21T11:11:00Z",
          chain_phase: "A2",
          tags: ["policy"],
          filename: "policy-a.md",
        },
      ],
    }),
  );

  const refreshedIndex = repo.getArtifactsIndex();
  assert.notEqual(refreshedIndex, firstIndex);
  assert.equal(refreshedIndex[0].title, "Policy B");

  fs.rmSync(root, { recursive: true, force: true });
});
