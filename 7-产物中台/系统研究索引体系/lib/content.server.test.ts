import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

test("content.server facade uses the canonical repository with environment root override", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "legacy-hub-facade-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-21T12:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/facade-001",
          title: "Facade Artifact",
          department: "trading",
          type: "strategy",
          status: "completed",
          date: "2026-05-21T12:00:00Z",
          chain_phase: "A5",
          tags: ["facade"],
          filename: "facade-note.md",
        },
      ],
    }),
  );
  fs.writeFileSync(path.join(tradingDir, "facade-note.md"), "# Facade");

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;
  const mod = await import("./content.server.ts");

  const index = mod.getArtifactsIndex();
  const detail = mod.getArtifactBySlug("trading/facade-001");

  assert.equal(index.length, 1);
  assert.equal(index[0].id, "trading/facade-001");
  assert.equal(index[0].title, "Facade Artifact");
  assert.equal(index[0].detailUrl, "/feed/trading/facade-001");
  assert.equal(index[0].chainPhase, "A5");
  assert.deepEqual(index[0].tags, ["facade"]);
  assert.equal(detail?.canonical.artifactId, "facade-001");

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("content.server facade exposes artifact relations derived from canonical index", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "legacy-hub-relations-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-21T13:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/rel-001",
          title: "Relation Artifact",
          department: "trading",
          type: "strategy",
          status: "completed",
          date: "2026-05-21T13:00:00Z",
          chain_phase: "A4",
          tags: ["relation"],
          filename: "rel.md",
        },
      ],
    }),
  );
  fs.writeFileSync(path.join(tradingDir, "rel.md"), "# Relation");

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;
  const mod = await import("./content.server.ts");
  const relations = mod.getArtifactRelations();
  const grouped = mod.getChainPhaseArtifacts();

  assert.equal(relations.length, 1);
  assert.equal(relations[0].artifactId, "rel-001");
  assert.equal(relations[0].chainHref, "/chain?phase=A4&artifact=rel-001");
  assert.equal(grouped.A4[0].feedHref, "/feed/trading/rel-001");

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});
