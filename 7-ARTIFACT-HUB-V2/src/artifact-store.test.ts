import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { ArtifactStore } from "./artifact-store.js";

test("ArtifactStore reads category index.json", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-hub-"));
  const trading = path.join(root, "trading");
  fs.mkdirSync(trading, { recursive: true });
  fs.writeFileSync(
    path.join(trading, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-15T00:00:00Z",
      artifacts: [{ artifact_id: "trading/x", title: "X", tags: ["a"] }]
    })
  );

  const store = new ArtifactStore(root);
  const idx = store.getArtifactsIndex();
  assert.equal(idx.length, 1);
  assert.equal(idx[0].id, "trading/x");
});

