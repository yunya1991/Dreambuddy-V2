import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import type { Server } from "node:http";
import { createHubServer } from "../server.js";

function listen(server: Server): Promise<{ baseUrl: string; close: () => Promise<void> }> {
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("failed_to_listen"));
        return;
      }

      resolve({
        baseUrl: `http://127.0.0.1:${address.port}`,
        close: () =>
          new Promise((done, closeReject) => {
            server.close((error) => {
              if (error) {
                closeReject(error);
                return;
              }
              done();
            });
          })
      });
    });
  });
}

test("createHubServer serves /chain and /chain/:workflowType", async () => {
  const artifactsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "chain-routes-artifacts-"));
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "chain-routes-meta-"));
  fs.mkdirSync(path.join(artifactsRoot, "trading"), { recursive: true });
  fs.writeFileSync(
    path.join(artifactsRoot, "trading", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/a1",
          title: "A1",
          workflow_type: "legacy_chain",
          chain_phase: "A3",
          status: "completed"
        }
      ]
    })
  );

  const server = createHubServer({ artifactsRoot, metaRoot });
  const { baseUrl, close } = await listen(server);
  try {
    const overview = await fetch(`${baseUrl}/chain`);
    const legacy = await fetch(`${baseUrl}/chain/legacy_chain`);
    const linked = await fetch(`${baseUrl}/chain/legacy_chain?artifactId=trading%2Fa1`);
    const overviewHtml = await overview.text();
    const legacyHtml = await legacy.text();
    const linkedHtml = await linked.text();

    assert.equal(overview.status, 200);
    assert.equal(legacy.status, 200);
    assert.equal(linked.status, 200);
    assert.match(overviewHtml, /Chain Monitor/);
    assert.match(overviewHtml, /legacy_chain/);
    assert.match(legacyHtml, /legacy_chain/);
    assert.match(linkedHtml, /交叉链接上下文/);
    assert.match(linkedHtml, /href="\/feed\/trading\/a1"/);
  } finally {
    await close();
    fs.rmSync(artifactsRoot, { recursive: true, force: true });
    fs.rmSync(metaRoot, { recursive: true, force: true });
  }
});
